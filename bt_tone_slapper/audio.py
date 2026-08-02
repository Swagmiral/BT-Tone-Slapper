from __future__ import annotations

import hashlib
import math
import subprocess
import wave
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from .errors import UserFacingError


SAMPLE_RATE = 16_000
CHANNELS = 1
SAMPLE_WIDTH = 2
MSBC_SAMPLES_PER_FRAME = 120
MSBC_FRAME_SIZE = 57


@dataclass(frozen=True)
class EncodedAudio:
    source: str
    source_sha256: str
    normalized_wav: str
    encoded_msbc: str
    input_samples: int
    padded_samples: int
    padding_samples: int
    frame_count: int
    encoded_size: int
    sample_count_field: int
    duration_seconds: float
    sha256: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _run(command: list[str], progress: Callable[[str], None] | None = None) -> None:
    if progress:
        progress("Running bundled FFmpeg conversion")
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    result = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        creationflags=creation_flags,
    )
    if result.returncode:
        raise UserFacingError(
            "The selected audio file could not be converted. Try another common audio format."
        )


def _pad_wav(source: Path, output: Path) -> tuple[int, int, int]:
    with wave.open(str(source), "rb") as reader:
        if (
            reader.getnchannels() != CHANNELS
            or reader.getframerate() != SAMPLE_RATE
            or reader.getsampwidth() != SAMPLE_WIDTH
            or reader.getcomptype() != "NONE"
        ):
            raise ValueError("FFmpeg did not produce 16 kHz mono signed 16-bit PCM")
        input_samples = reader.getnframes()
        pcm = reader.readframes(input_samples)
    if input_samples <= 0:
        raise UserFacingError(
            "The selected audio file contains no usable sound. Choose another file."
        )
    padding_samples = (-input_samples) % MSBC_SAMPLES_PER_FRAME
    padded_samples = input_samples + padding_samples
    with wave.open(str(output), "wb") as writer:
        writer.setnchannels(CHANNELS)
        writer.setsampwidth(SAMPLE_WIDTH)
        writer.setframerate(SAMPLE_RATE)
        writer.writeframes(pcm + b"\x00" * (padding_samples * SAMPLE_WIDTH))
    return input_samples, padded_samples, padding_samples


def encode_audio(
    source: Path,
    work_dir: Path,
    ffmpeg: Path,
    *,
    progress: Callable[[str], None] | None = None,
) -> EncodedAudio:
    source = source.resolve()
    if not source.is_file():
        raise UserFacingError(
            "An assigned audio file could not be found. Choose it again or reset that prompt to OEM."
        )
    work_dir.mkdir(parents=True, exist_ok=True)
    decoded = work_dir / "decoded.wav"
    normalized = work_dir / "normalized_padded.wav"
    encoded = work_dir / "prompt.msbc"
    for path in (decoded, normalized, encoded):
        if path.exists():
            raise ValueError(f"refusing to overwrite work artifact: {path}")

    _run(
        [
            str(ffmpeg),
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(source),
            "-map_metadata",
            "-1",
            "-vn",
            "-sn",
            "-dn",
            "-ac",
            "1",
            "-ar",
            str(SAMPLE_RATE),
            "-c:a",
            "pcm_s16le",
            str(decoded),
        ],
        progress,
    )
    input_samples, padded_samples, padding_samples = _pad_wav(decoded, normalized)
    _run(
        [
            str(ffmpeg),
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(normalized),
            "-c:a",
            "sbc",
            "-msbc",
            "1",
            "-f",
            "sbc",
            str(encoded),
        ],
        progress,
    )
    payload = encoded.read_bytes()
    frame_count, remainder = divmod(len(payload), MSBC_FRAME_SIZE)
    if remainder or frame_count != padded_samples // MSBC_SAMPLES_PER_FRAME:
        raise ValueError("mSBC encoder returned an unexpected frame count")
    if any(payload[offset] != 0xAD for offset in range(0, len(payload), MSBC_FRAME_SIZE)):
        raise ValueError("mSBC encoder returned an invalid sync byte")
    sample_count_field = math.ceil(padded_samples / 128) * 128
    return EncodedAudio(
        source=str(source),
        source_sha256=sha256_file(source),
        normalized_wav=str(normalized),
        encoded_msbc=str(encoded),
        input_samples=input_samples,
        padded_samples=padded_samples,
        padding_samples=padding_samples,
        frame_count=frame_count,
        encoded_size=len(payload),
        sample_count_field=sample_count_field,
        duration_seconds=padded_samples / SAMPLE_RATE,
        sha256=hashlib.sha256(payload).hexdigest(),
    )
