"""Guarded, offset-driven HmOtaMgr upload engine."""

from __future__ import annotations

import asyncio
import hashlib
import time
from dataclasses import asdict, dataclass
from typing import Any, Callable, Protocol

from .protocol import (
    DfuStatus,
    TransferSession,
    build_apply,
    build_data,
    build_start,
    parse_status,
)


class UploadTransport(Protocol):
    mtu: int
    disconnected_event: asyncio.Event

    async def subscribe(self, callback: Callable[[Any, bytearray], None]) -> None: ...

    async def unsubscribe(self) -> None: ...

    async def write(self, frame: bytes) -> None: ...


class UploadError(RuntimeError):
    pass


class UploadTimeout(UploadError):
    pass


class UploadDisconnected(UploadError):
    pass


class UploadRejected(UploadError):
    pass


class UploadConnectionError(UploadError):
    pass


@dataclass(frozen=True)
class TransferLogEntry:
    elapsed_seconds: float
    direction: str
    frame_hex: str
    size: int
    status: str | None = None
    value: int | None = None
    note: str | None = None


@dataclass(frozen=True)
class UploadReport:
    state: str
    file_size: int
    sha256: str
    mtu: int
    write_count: int
    notification_count: int
    ignored_notification_count: int
    elapsed_seconds: float
    entries: tuple[TransferLogEntry, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DryRunReport:
    file_size: int
    sha256: str
    mtu: int
    language_index: int
    packet_count: int
    data_packet_count: int
    chunk_size: int
    final_chunk_size: int
    packets: tuple[bytes, ...]

    def to_dict(self, *, include_packets: bool = False) -> dict[str, Any]:
        result = asdict(self)
        if include_packets:
            result["packets"] = [packet.hex(" ") for packet in self.packets]
        else:
            result.pop("packets")
        result["mode"] = "dry-run"
        result["connected"] = False
        result["wrote_device"] = False
        return result


def build_dry_run(file_data: bytes, *, mtu: int = 220, language: int = 1) -> DryRunReport:
    session = TransferSession(file_data, mtu=mtu, language=language)
    packets = [session.start_packet()]
    for offset in range(0, len(file_data), session.chunk_size):
        packets.append(build_data(offset, file_data[offset : offset + session.chunk_size]))
    packets.append(build_apply())
    final_chunk_size = len(file_data) % session.chunk_size or session.chunk_size
    return DryRunReport(
        file_size=len(file_data),
        sha256=hashlib.sha256(file_data).hexdigest(),
        mtu=mtu,
        language_index=language,
        packet_count=len(packets),
        data_packet_count=len(packets) - 2,
        chunk_size=session.chunk_size,
        final_chunk_size=final_chunk_size,
        packets=tuple(packets),
    )


async def _next_notification(
    queue: asyncio.Queue[tuple[Any, bytes]],
    disconnected_event: asyncio.Event,
    timeout: float,
    cancel_event: asyncio.Event | None = None,
) -> tuple[Any, bytes] | None:
    queue_task = asyncio.create_task(queue.get())
    disconnect_task = asyncio.create_task(disconnected_event.wait())
    tasks = {queue_task, disconnect_task}
    cancel_task = None
    if cancel_event is not None:
        cancel_task = asyncio.create_task(cancel_event.wait())
        tasks.add(cancel_task)
    done, pending = await asyncio.wait(
        tasks,
        timeout=timeout,
        return_when=asyncio.FIRST_COMPLETED,
    )
    for task in pending:
        task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)
    if queue_task in done:
        return queue_task.result()
    if disconnect_task in done:
        raise UploadDisconnected(
            "The headphones disconnected during upload. Reconnect them and try again."
        )
    if cancel_task is not None and cancel_task in done:
        return None
    raise UploadTimeout(
        "The headphones stopped responding. Keep them connected and try again."
    )


async def run_upload(
    file_data: bytes,
    transport: UploadTransport,
    *,
    packet_timeout: float = 10.0,
    total_timeout: float = 600.0,
    language: int = 1,
    cancel_event: asyncio.Event | None = None,
    entry_callback: Callable[[TransferLogEntry], None] | None = None,
) -> UploadReport:
    if packet_timeout <= 0 or total_timeout <= 0:
        raise ValueError("upload timeouts must be positive")
    session = TransferSession(file_data, mtu=transport.mtu, language=language)
    notification_queue: asyncio.Queue[tuple[Any, bytes]] = asyncio.Queue()
    entries: list[TransferLogEntry] = []
    notification_count = 0
    ignored_count = 0
    write_count = 0
    cancelling = False
    started_at = time.monotonic()
    deadline = started_at + total_timeout

    def record(direction: str, frame: bytes, **details: Any) -> None:
        entry = TransferLogEntry(
            elapsed_seconds=round(time.monotonic() - started_at, 6),
            direction=direction,
            frame_hex=frame.hex(" "),
            size=len(frame),
            **details,
        )
        entries.append(entry)
        if entry_callback is not None:
            entry_callback(entry)

    def on_notification(sender: Any, data: bytearray) -> None:
        notification_queue.put_nowait((sender, bytes(data)))

    async def send(frame: bytes) -> None:
        nonlocal write_count
        if transport.disconnected_event.is_set():
            raise UploadDisconnected(
                "The headphones disconnected during upload. Reconnect them and try again."
            )
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise UploadTimeout(
                "The headphones stopped responding. Keep them connected and try again."
            )
        try:
            await asyncio.wait_for(
                transport.write(frame),
                timeout=min(packet_timeout, remaining),
            )
        except TimeoutError as error:
            raise UploadTimeout(
                "The headphones stopped responding. Keep them connected and try again."
            ) from error
        write_count += 1
        record("write", frame)

    subscribed = False
    try:
        try:
            await asyncio.wait_for(transport.subscribe(on_notification), timeout=packet_timeout)
        except TimeoutError as error:
            raise UploadTimeout(
                "Could not start the upload. Reconnect the headphones and try again."
            ) from error
        subscribed = True
        await send(session.start_packet())
        while session.state not in {"done", "cancelled", "error"}:
            if cancel_event is not None and cancel_event.is_set() and not cancelling:
                cancelling = True
                await send(session.cancel_packet())

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise UploadTimeout(
                    "The headphones stopped responding. Keep them connected and try again."
                )
            received = await _next_notification(
                notification_queue,
                transport.disconnected_event,
                min(packet_timeout, remaining),
                None if cancelling else cancel_event,
            )
            if received is None:
                continue
            sender, frame = received
            notification_count += 1
            try:
                status = parse_status(frame)
            except ValueError as error:
                ignored_count += 1
                record("notify", frame, note=f"ignored non-HmOtaMgr notification: {error}")
                continue

            record(
                "notify",
                frame,
                status=status.status.name,
                value=status.value,
                note=f"sender={getattr(sender, 'uuid', sender)}",
            )
            if cancelling and status.status not in {
                DfuStatus.CANCELLED,
                DfuStatus.ERROR,
                DfuStatus.DONE,
            }:
                continue

            action = session.handle_notification(frame)
            if status.status == DfuStatus.ERROR:
                raise UploadRejected(
                    "The headphones rejected the prompt file. Restore the OEM prompts before trying again."
                )
            if action is not None:
                await send(action)

        if session.state != "done":
            raise UploadRejected(
                "The headphones did not complete the upload. Reconnect them and try again."
            )
    finally:
        if subscribed:
            await asyncio.wait_for(transport.unsubscribe(), timeout=packet_timeout)

    return UploadReport(
        state=session.state,
        file_size=len(file_data),
        sha256=hashlib.sha256(file_data).hexdigest(),
        mtu=transport.mtu,
        write_count=write_count,
        notification_count=notification_count,
        ignored_notification_count=ignored_count,
        elapsed_seconds=round(time.monotonic() - started_at, 6),
        entries=tuple(entries),
    )
