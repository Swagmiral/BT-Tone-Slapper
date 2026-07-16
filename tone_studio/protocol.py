"""Pure protocol implementation of the captured JBL HmOtaMgr transfer."""

from __future__ import annotations

import enum
import struct
import zlib
from dataclasses import dataclass


FRAME_MAGIC = b"\xaa\xf0"
SERVICE_UUID = "65786365-6c70-6f69-6e74-2e636f6d0000"
NOTIFY_UUID = "65786365-6c70-6f69-6e74-2e636f6d0001"
WRITE_UUID = "65786365-6c70-6f69-6e74-2e636f6d0002"


class Subcommand(enum.IntEnum):
    START = 0
    STATUS = 1
    DATA = 2
    CANCEL = 3
    APPLY = 4


class DfuStatus(enum.IntEnum):
    READY = 1
    TRANSFERRING = 2
    TRANSFERRED = 3
    CANCELLED = 4
    DONE = 5
    ERROR = 255


@dataclass(frozen=True)
class StartCommand:
    ota_type: int
    crc32: int
    file_size: int
    version: tuple[int, int, int]
    breakpoint: int
    language: int


@dataclass(frozen=True)
class DataCommand:
    offset: int
    data: bytes


@dataclass(frozen=True)
class ApplyCommand:
    pass


@dataclass(frozen=True)
class CancelCommand:
    pass


@dataclass(frozen=True)
class StatusNotification:
    status: DfuStatus
    value: int | None


def build_frame(body: bytes) -> bytes:
    if len(body) > 0xFFFF:
        raise ValueError("HmOtaMgr body exceeds 16-bit length")
    return FRAME_MAGIC + struct.pack("<H", len(body)) + body


def parse_frame(frame: bytes) -> bytes:
    if len(frame) < 4 or frame[:2] != FRAME_MAGIC:
        raise ValueError("invalid HmOtaMgr frame magic")
    body_size = struct.unpack_from("<H", frame, 2)[0]
    if body_size != len(frame) - 4:
        raise ValueError("HmOtaMgr body length mismatch")
    return frame[4:]


def build_start(
    file_data: bytes,
    *,
    ota_type: int = 2,
    version: tuple[int, int, int] = (9, 9, 9),
    breakpoint: int = 1,
    language: int = 1,
) -> bytes:
    if any(not 0 <= value <= 0xFF for value in (*version, ota_type, breakpoint, language)):
        raise ValueError("start-command byte value out of range")
    body = bytearray([Subcommand.START, 0x01, ota_type, 0x03])
    body.extend(struct.pack("<I", zlib.crc32(file_data) & 0xFFFFFFFF))
    body.append(0x04)
    body.extend(struct.pack("<I", len(file_data)))
    body.extend((0x05, *version, 0x06, breakpoint, 0x02, language))
    return build_frame(bytes(body))


def build_data(offset: int, data: bytes) -> bytes:
    if not 0 <= offset <= 0xFFFFFFFF:
        raise ValueError("data offset out of range")
    if not data:
        raise ValueError("data packet cannot be empty")
    return build_frame(bytes([Subcommand.DATA]) + struct.pack("<I", offset) + data)


def build_apply() -> bytes:
    return build_frame(bytes([Subcommand.APPLY]))


def build_cancel() -> bytes:
    return build_frame(bytes([Subcommand.CANCEL]))


_START_FIELD_SIZES = {0x01: 1, 0x02: 1, 0x03: 4, 0x04: 4, 0x05: 3, 0x06: 1}


def parse_command(frame: bytes) -> StartCommand | DataCommand | ApplyCommand | CancelCommand:
    body = parse_frame(frame)
    if not body:
        raise ValueError("empty HmOtaMgr body")
    subcommand = body[0]
    if subcommand == Subcommand.START:
        fields: dict[int, bytes] = {}
        position = 1
        while position < len(body):
            tag = body[position]
            position += 1
            size = _START_FIELD_SIZES.get(tag)
            if size is None or position + size > len(body):
                raise ValueError("invalid start-command field")
            if tag in fields:
                raise ValueError("duplicate start-command field")
            fields[tag] = body[position : position + size]
            position += size
        if set(fields) != set(_START_FIELD_SIZES):
            raise ValueError("incomplete start command")
        return StartCommand(
            ota_type=fields[0x01][0],
            crc32=struct.unpack("<I", fields[0x03])[0],
            file_size=struct.unpack("<I", fields[0x04])[0],
            version=tuple(fields[0x05]),
            breakpoint=fields[0x06][0],
            language=fields[0x02][0],
        )
    if subcommand == Subcommand.DATA:
        if len(body) < 6:
            raise ValueError("truncated data command")
        return DataCommand(struct.unpack_from("<I", body, 1)[0], body[5:])
    if subcommand == Subcommand.APPLY and len(body) == 1:
        return ApplyCommand()
    if subcommand == Subcommand.CANCEL and len(body) == 1:
        return CancelCommand()
    raise ValueError(f"unsupported command body: {body.hex()}")


def parse_status(frame: bytes) -> StatusNotification:
    body = parse_frame(frame)
    if len(body) not in (2, 6) or body[0] != Subcommand.STATUS:
        raise ValueError("invalid status notification")
    try:
        status = DfuStatus(body[1])
    except ValueError as error:
        raise ValueError(f"unknown DFU status {body[1]}") from error
    value = struct.unpack_from("<I", body, 2)[0] if len(body) == 6 else None
    if status in (DfuStatus.READY, DfuStatus.TRANSFERRING, DfuStatus.ERROR) and value is None:
        raise ValueError("status requires a 32-bit value")
    return StatusNotification(status, value)


def chunk_size_for_mtu(mtu: int) -> int:
    chunk_size = mtu - 19
    if chunk_size <= 0:
        raise ValueError("ATT MTU is too small for HmOtaMgr")
    return chunk_size


class TransferSession:
    """Offset-driven transfer state matching the captured JBL app behavior."""

    def __init__(
        self,
        file_data: bytes,
        *,
        mtu: int = 220,
        ota_type: int = 2,
        version: tuple[int, int, int] = (9, 9, 9),
        breakpoint: int = 1,
        language: int = 1,
    ) -> None:
        if not file_data:
            raise ValueError("transfer file cannot be empty")
        self.file_data = bytes(file_data)
        self.chunk_size = chunk_size_for_mtu(mtu)
        self.ota_type = ota_type
        self.version = version
        self.breakpoint = breakpoint
        self.language = language
        self.state = "idle"
        self._served_offsets: set[int] = set()

    def start_packet(self) -> bytes:
        if self.state != "idle":
            raise RuntimeError("transfer already started")
        self.state = "starting"
        return build_start(
            self.file_data,
            ota_type=self.ota_type,
            version=self.version,
            breakpoint=self.breakpoint,
            language=self.language,
        )

    def cancel_packet(self) -> bytes:
        self.state = "cancelling"
        return build_cancel()

    def handle_notification(self, frame: bytes) -> bytes | None:
        notification = parse_status(frame)
        if notification.status in (DfuStatus.READY, DfuStatus.TRANSFERRING):
            offset = notification.value
            assert offset is not None
            if not 0 <= offset < len(self.file_data):
                raise ValueError(f"device requested invalid file offset {offset}")
            self.state = "transferring"
            if offset in self._served_offsets:
                return None
            self._served_offsets.add(offset)
            data = self.file_data[offset : offset + self.chunk_size]
            return build_data(offset, data)
        if notification.status == DfuStatus.TRANSFERRED:
            self.state = "applying"
            return build_apply()
        if notification.status == DfuStatus.DONE:
            self.state = "done"
            return None
        if notification.status == DfuStatus.CANCELLED:
            self.state = "cancelled"
            return None
        if notification.status == DfuStatus.ERROR:
            self.state = "error"
            return None
        raise ValueError(f"unhandled status {notification.status}")
