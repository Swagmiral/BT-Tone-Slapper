from __future__ import annotations

import hashlib
import lzma
import subprocess
import struct
import tempfile
import zlib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Mapping

from .audio import EncodedAudio, MSBC_FRAME_SIZE, MSBC_SAMPLES_PER_FRAME
from .errors import UserFacingError


OUTER_HEADER_SIZE = 0x34
INNER_HEADER_SIZE = 0x20
BANK_HEADER_SIZE = 0x20
ENTRY_SIZE = 0x10
LAYOUT_BODY_SIZE_OFFSET = 0x88
TONE_MAGIC = bytes.fromhex("43 65 cd ab")
MAIN_MAGIC = bytes.fromhex("17 9a e4 a4")


@dataclass(frozen=True)
class PromptPayload:
    index: int
    encoded: bytes
    sample_count_field: int
    flags: int


@dataclass(frozen=True)
class ValidationResult:
    path: str
    valid: bool
    sha256: str
    file_size: int
    prompt_count: int
    main_unpacked_size: int
    main_capacity: int
    descriptor_crc32: str
    body_crc32: str
    packed_crc32: str
    entries: tuple[dict[str, object], ...]
    errors: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _unpack_stream(data: bytes) -> tuple[bytes, bytes, int]:
    decoder = lzma.LZMADecompressor(format=lzma.FORMAT_ALONE)
    unpacked = decoder.decompress(data)
    if not decoder.eof:
        raise ValueError("truncated LZMA-alone stream")
    consumed = len(data) - len(decoder.unused_data)
    return unpacked, decoder.unused_data, consumed


def _read_source(image: bytes) -> tuple[bytes, bytes, bytes, list[PromptPayload]]:
    if len(image) < OUTER_HEADER_SIZE or not image.startswith(TONE_MAGIC):
        raise ValueError("base image is not a recognized tone container")
    main, remainder, _ = _unpack_stream(image[OUTER_HEADER_SIZE:])
    layout, tail, _ = _unpack_stream(remainder)
    if len(tail) != 4 or len(layout) != 244 or not main.startswith(MAIN_MAGIC):
        raise ValueError("base image has an unexpected stream layout")
    count = main[INNER_HEADER_SIZE]
    prompts = []
    for index in range(count):
        entry = INNER_HEADER_SIZE + BANK_HEADER_SIZE + index * ENTRY_SIZE
        offset, size, sample_count, flags = struct.unpack_from("<IIII", main, entry)
        encoded = main[INNER_HEADER_SIZE + offset : INNER_HEADER_SIZE + offset + size]
        if len(encoded) != size:
            raise ValueError(f"base prompt {index} extends beyond the bank")
        prompts.append(PromptPayload(index, encoded, sample_count, flags))
    return main, layout, tail, prompts


def _pack_known_size(data: bytes, encoder: Path, work_dir: Path, stem: str) -> bytes:
    input_path = work_dir / f"{stem}.bin"
    output_path = work_dir / f"{stem}.lzma"
    input_path.write_bytes(data)
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    result = subprocess.run(
        [str(encoder), "e", "-d15", "-fb32", "-mfbt2", str(input_path), str(output_path)],
        check=False,
        capture_output=True,
        text=True,
        creationflags=creation_flags,
    )
    if result.returncode:
        raise ValueError(f"LZMA encoder failed: {result.stderr.strip()}")
    packed = output_path.read_bytes()
    if packed[:5] != bytes.fromhex("5d00800000"):
        raise ValueError("LZMA encoder returned unexpected properties")
    if struct.unpack_from("<Q", packed, 5)[0] != len(data):
        raise ValueError("LZMA encoder returned an incorrect unpacked size")
    decoded, unused, _ = _unpack_stream(packed)
    if decoded != data or unused:
        raise ValueError("LZMA output failed round-trip validation")
    return packed


def build_container(
    base_path: Path,
    replacements: Mapping[int, EncodedAudio],
    output_path: Path,
    encoder: Path,
    work_dir: Path,
) -> None:
    source_image = base_path.read_bytes()
    source_main, source_layout, _, source_prompts = _read_source(source_image)
    prompts = list(source_prompts)
    for index, replacement in replacements.items():
        if not 0 <= index < len(prompts):
            raise ValueError(f"prompt index is out of range: {index}")
        payload = Path(replacement.encoded_msbc).read_bytes()
        prompts[index] = PromptPayload(index, payload, replacement.sample_count_field, prompts[index].flags)

    count = len(prompts)
    bank_header = bytearray(source_main[INNER_HEADER_SIZE : INNER_HEADER_SIZE + BANK_HEADER_SIZE])
    entries = bytearray()
    encoded_bank = bytearray()
    current_offset = BANK_HEADER_SIZE + count * ENTRY_SIZE
    for prompt in prompts:
        entries.extend(
            struct.pack(
                "<IIII",
                current_offset,
                len(prompt.encoded),
                prompt.sample_count_field,
                prompt.flags,
            )
        )
        encoded_bank.extend(prompt.encoded)
        current_offset += len(prompt.encoded)
        padding = (-current_offset) % 4
        encoded_bank.extend(b"\xff" * padding)
        current_offset += padding
    body = bytes(bank_header + entries + encoded_bank)
    inner_header = bytearray(source_main[:INNER_HEADER_SIZE])
    struct.pack_into("<I", inner_header, 4, len(body))
    struct.pack_into("<I", inner_header, 16, zlib.crc32(body) & 0xFFFFFFFF)
    main = bytes(inner_header) + body

    outer_words = struct.unpack_from("<13I", source_image)
    capacity = outer_words[7] - outer_words[6]
    if capacity <= 0 or len(main) > capacity:
        raise UserFacingError(
            "The replacement audio is too large for this headphone model. "
            "Shorten one or more custom sounds and rebuild."
        )
    layout = bytearray(source_layout)
    struct.pack_into("<I", layout, LAYOUT_BODY_SIZE_OFFSET, len(body))

    work_dir.mkdir(parents=True, exist_ok=True)
    packed_main = _pack_known_size(main, encoder, work_dir, "main")
    packed_layout = _pack_known_size(bytes(layout), encoder, work_dir, "layout")
    outer = bytearray(source_image[:OUTER_HEADER_SIZE])
    struct.pack_into("<I", outer, 0x10, len(main))
    struct.pack_into("<I", outer, 0x14, len(packed_main))
    struct.pack_into("<I", outer, 0x20, len(layout))
    struct.pack_into("<I", outer, 0x24, len(packed_layout))
    descriptor_count = struct.unpack_from("<I", outer, 0x08)[0].bit_count()
    descriptor_crc_offset = 0x10 + descriptor_count * 0x10
    descriptor_crc = zlib.crc32(outer[0x10:descriptor_crc_offset]) & 0xFFFFFFFF
    struct.pack_into("<I", outer, descriptor_crc_offset, descriptor_crc)
    packed_streams = packed_main + packed_layout
    image = bytes(outer) + packed_streams + struct.pack("<I", zlib.crc32(packed_streams) & 0xFFFFFFFF)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_output: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{output_path.name}.",
            suffix=".tmp",
            dir=output_path.parent,
            delete=False,
        ) as handle:
            handle.write(image)
            temporary_output = Path(handle.name)
        temporary_output.replace(output_path)
    finally:
        if temporary_output is not None:
            temporary_output.unlink(missing_ok=True)


def validate_container_bytes(image: bytes, *, source: Path | str = "<memory>") -> ValidationResult:
    errors: list[str] = []
    if len(image) < OUTER_HEADER_SIZE or not image.startswith(TONE_MAGIC):
        raise ValueError("not a recognized JBL tone container")
    words = struct.unpack_from("<13I", image)
    descriptor_count = words[2].bit_count()
    descriptor_crc_offset = 0x10 + descriptor_count * 0x10
    stored_descriptor_crc = struct.unpack_from("<I", image, descriptor_crc_offset)[0]
    descriptor_crc = zlib.crc32(image[0x10:descriptor_crc_offset]) & 0xFFFFFFFF
    if descriptor_count != 2:
        errors.append("descriptor count is not two")
    if descriptor_crc != stored_descriptor_crc:
        errors.append("descriptor CRC32 mismatch")
    main, remainder, packed_main_size = _unpack_stream(image[OUTER_HEADER_SIZE:])
    layout, tail, packed_layout_size = _unpack_stream(remainder)
    if len(tail) != 4:
        errors.append("outer CRC32 suffix is not four bytes")
        stored_packed_crc = 0
    else:
        stored_packed_crc = struct.unpack("<I", tail)[0]
    packed_streams = image[OUTER_HEADER_SIZE : OUTER_HEADER_SIZE + packed_main_size + packed_layout_size]
    packed_crc = zlib.crc32(packed_streams) & 0xFFFFFFFF
    if stored_packed_crc != packed_crc:
        errors.append("packed-stream CRC32 mismatch")
    if words[4] != len(main) or words[5] != packed_main_size:
        errors.append("declared main sizes mismatch")
    if words[8] != len(layout) or words[9] != packed_layout_size or len(layout) != 244:
        errors.append("layout sizes mismatch")
    if not main.startswith(MAIN_MAGIC):
        errors.append("main-stream magic mismatch")
    declared_body_size = struct.unpack_from("<I", main, 4)[0]
    body = main[INNER_HEADER_SIZE:]
    body_crc = zlib.crc32(body) & 0xFFFFFFFF
    if declared_body_size != len(body):
        errors.append("declared body size mismatch")
    if struct.unpack_from("<I", main, 16)[0] != body_crc:
        errors.append("inner body CRC32 mismatch")
    if struct.unpack_from("<I", layout, LAYOUT_BODY_SIZE_OFFSET)[0] != len(body):
        errors.append("layout body-size field mismatch")
    capacity = words[7] - words[6]
    if capacity <= 0 or len(main) > capacity:
        errors.append("main stream exceeds destination capacity")
    count = main[INNER_HEADER_SIZE]
    sample_rate = struct.unpack_from("<I", main, INNER_HEADER_SIZE + 4)[0]
    if count != 11:
        errors.append("prompt count is not eleven")
    if sample_rate != 16_000:
        errors.append("prompt bank sample rate is not 16 kHz")
    entries = []
    previous_end = BANK_HEADER_SIZE + count * ENTRY_SIZE
    for index in range(count):
        entry_offset = INNER_HEADER_SIZE + BANK_HEADER_SIZE + index * ENTRY_SIZE
        offset, size, sample_count, flags = struct.unpack_from("<IIII", main, entry_offset)
        encoded = main[INNER_HEADER_SIZE + offset : INNER_HEADER_SIZE + offset + size]
        frame_count, remainder_size = divmod(size, MSBC_FRAME_SIZE)
        sync_valid = remainder_size == 0 and len(encoded) == size and all(
            encoded[position] == 0xAD for position in range(0, size, MSBC_FRAME_SIZE)
        )
        if offset < previous_end or offset % 4:
            errors.append(f"prompt {index} has an invalid offset")
        if not sync_valid:
            errors.append(f"prompt {index} has invalid mSBC framing")
        if abs(sample_count - frame_count * MSBC_SAMPLES_PER_FRAME) >= MSBC_SAMPLES_PER_FRAME:
            errors.append(f"prompt {index} sample count differs by at least one frame")
        previous_end = offset + size
        entries.append(
            {
                "index": index,
                "offset": offset,
                "encoded_size": size,
                "frame_count": frame_count,
                "sample_count_field": sample_count,
                "duration_seconds": sample_count / sample_rate,
                "flags": f"0x{flags:08x}",
                "msbc_sync_valid": sync_valid,
            }
        )
    return ValidationResult(
        path=str(source),
        valid=not errors,
        sha256=hashlib.sha256(image).hexdigest(),
        file_size=len(image),
        prompt_count=count,
        main_unpacked_size=len(main),
        main_capacity=capacity,
        descriptor_crc32=f"0x{descriptor_crc:08x}",
        body_crc32=f"0x{body_crc:08x}",
        packed_crc32=f"0x{packed_crc:08x}",
        entries=tuple(entries),
        errors=tuple(errors),
    )


def validate_container(path: Path) -> ValidationResult:
    return validate_container_bytes(path.read_bytes(), source=path)
