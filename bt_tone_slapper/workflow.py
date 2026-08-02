from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import shutil
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Mapping

from .audio import EncodedAudio, encode_audio, sha256_file
from .ble_transport import BleakUploadTransport
from .bluetooth import DiscoveredDevice, inspect_device, scan_devices
from .container import (
    ValidationResult,
    build_container,
    validate_container,
    validate_container_bytes,
)
from .device_profiles import (
    TUNE_720BT_PROFILE,
    get_device_profile,
    resolve_device_profile,
)
from .errors import UserFacingError
from .resources import asset_path, log_directory
from .uploader import UploadError, UploadReport, build_dry_run, run_upload


BASE_FILENAME = "English_prompt_v0.0.5.bin"
BASE_SHA256 = "91afbf099c9160fc251cf858c43b4d4df5bd9392cab5a6ab3b51ee0541d0ab9f"
FFMPEG_SHA256 = "2ce797a0f88d7f067180338fb227f7b1928ea727bd9a4d7a1d022f7c52af71a3"
LZMA_ENCODER_SHA256 = "e2d96d96f7c0eb3c6ac13fdcf8ddd664d7bc18916156ffaff09c285327d93ee0"
LANGUAGE_INDEX = 1

PROMPT_LABELS = (
    "Power on",
    "Power off",
    "Connected",
    "Pairing",
    "Battery is low",
    "Mute on",
    "Mute off",
    "Incoming call",
    "Voice prompt off",
    "Voice prompt on",
    "Maximum volume",
)


@dataclass(frozen=True)
class BuildResult:
    output: str
    sha256: str
    profile_id: str
    validation: ValidationResult
    replacements: Mapping[int, EncodedAudio]
    dry_run: dict[str, object]


class ToneSlapperEngine:
    def __init__(self) -> None:
        self.base_image = asset_path(BASE_FILENAME)
        self.ffmpeg = asset_path("ffmpeg.exe")
        self.lzma_encoder = asset_path("LzmaAlone.exe")
        self._verify_asset(self.base_image, BASE_SHA256, "OEM recovery image")
        self._verify_asset(self.ffmpeg, FFMPEG_SHA256, "FFmpeg")
        self._verify_asset(self.lzma_encoder, LZMA_ENCODER_SHA256, "LZMA encoder")
        base_validation = validate_container(self.base_image)
        if not base_validation.valid:
            raise ValueError(f"bundled OEM recovery image failed validation: {base_validation.errors}")
        self.recovery_packet_count = build_dry_run(
            self.base_image.read_bytes(), language=LANGUAGE_INDEX
        ).packet_count

    @staticmethod
    def _verify_asset(path: Path, expected_sha256: str, label: str) -> None:
        actual = sha256_file(path)
        if actual != expected_sha256:
            raise ValueError(f"bundled {label} hash mismatch: {actual}")

    @staticmethod
    def _require_profile(profile_id: str) -> None:
        if get_device_profile(profile_id) is None:
            raise UserFacingError(
                f"This operation is only supported for {TUNE_720BT_PROFILE.display_name}."
            )

    def build(
        self,
        assignments: Mapping[int, Path],
        output: Path,
        *,
        profile_id: str = TUNE_720BT_PROFILE.profile_id,
        progress: Callable[[str], None] | None = None,
        work_dir: Path | None = None,
    ) -> BuildResult:
        self._require_profile(profile_id)
        if output.suffix.lower() != ".bin":
            raise UserFacingError("The output filename must end in .bin.")
        output = output.resolve()
        if output == self.base_image.resolve():
            raise UserFacingError(
                "Choose another save location. The bundled OEM recovery file cannot be overwritten."
            )
        replacements: dict[int, EncodedAudio] = {}
        if not assignments:
            if progress:
                progress("Saving verified OEM container")
            shutil.copyfile(self.base_image, output)
        else:
            if work_dir is None:
                work_context = tempfile.TemporaryDirectory(prefix="bt-tone-slapper-build-")
            else:
                work_dir = work_dir.resolve()
                if not work_dir.is_dir() or any(work_dir.iterdir()):
                    raise ValueError("explicit work directory must exist and be empty")
                work_context = contextlib.nullcontext(str(work_dir))
            with work_context as temporary:
                temporary_path = Path(temporary)
                for index, source in sorted(assignments.items()):
                    if not 0 <= index < len(PROMPT_LABELS):
                        raise ValueError(f"invalid prompt index: {index}")
                    if progress:
                        progress(f"Converting prompt {index}: {PROMPT_LABELS[index]}")
                    replacements[index] = encode_audio(
                        source,
                        temporary_path / f"prompt_{index:02d}",
                        self.ffmpeg,
                        progress=progress,
                    )
                if progress:
                    progress("Rebuilding and signing integrity fields")
                build_container(
                    self.base_image,
                    replacements,
                    output,
                    self.lzma_encoder,
                    temporary_path / "lzma",
                )
        validation = validate_container(output)
        if not validation.valid:
            raise UserFacingError(
                "The generated file failed validation and was not loaded. Try building it again."
            )
        dry_run = build_dry_run(output.read_bytes(), language=LANGUAGE_INDEX).to_dict()
        if progress:
            progress("Container validated successfully")
        return BuildResult(
            output=str(output),
            sha256=validation.sha256,
            profile_id=profile_id,
            validation=validation,
            replacements=replacements,
            dry_run=dry_run,
        )

    @staticmethod
    def validate(path: Path) -> ValidationResult:
        return validate_container(path)

    @staticmethod
    def open_existing(
        path: Path,
        *,
        profile_id: str = TUNE_720BT_PROFILE.profile_id,
    ) -> BuildResult:
        ToneSlapperEngine._require_profile(profile_id)
        image = path.read_bytes()
        try:
            validation = validate_container_bytes(image, source=path)
        except Exception as error:
            raise UserFacingError(
                f"This file is not a valid {TUNE_720BT_PROFILE.display_name} prompt container."
            ) from error
        if not validation.valid:
            raise UserFacingError(
                f"This file is not a valid {TUNE_720BT_PROFILE.display_name} prompt container."
            )
        dry_run = build_dry_run(image, language=LANGUAGE_INDEX).to_dict()
        return BuildResult(
            output=str(path),
            sha256=validation.sha256,
            profile_id=profile_id,
            validation=validation,
            replacements={},
            dry_run=dry_run,
        )

    @staticmethod
    def scan(timeout: float = 8.0) -> list[DiscoveredDevice]:
        manufacturer = TUNE_720BT_PROFILE.display_name.partition(" ")[0]
        devices = asyncio.run(scan_devices(timeout=timeout, name_contains=manufacturer))
        return [device for device in devices if resolve_device_profile(device.name) is not None]

    @staticmethod
    def inspect(identifier: str) -> dict[str, object]:
        return asyncio.run(inspect_device(identifier)).to_dict()

    def upload_generated(
        self,
        identifier: str,
        candidate: Path,
        expected_sha256: str,
        *,
        file_profile_id: str,
        device_profile_id: str,
        progress: Callable[[str], None] | None = None,
    ) -> tuple[UploadReport, Path]:
        self._require_profile(file_profile_id)
        self._require_profile(device_profile_id)
        if file_profile_id != device_profile_id:
            raise UserFacingError(
                "The loaded prompt file targets a different headphone model. "
                "Rebuild or open a compatible file before uploading."
            )
        image = candidate.read_bytes()
        try:
            validation = validate_container_bytes(image, source=candidate)
        except Exception as error:
            raise UserFacingError(
                "The loaded file is no longer valid. Open it again or rebuild before uploading."
            ) from error
        if not validation.valid:
            raise UserFacingError(
                "The loaded file is no longer valid. Open it again or rebuild before uploading."
            )
        if validation.sha256 != expected_sha256:
            raise UserFacingError(
                "File changed since it was loaded. Open it again or rebuild before uploading."
            )
        return self._upload(
            identifier,
            candidate,
            image,
            "custom",
            validation,
            device_profile_id,
            progress,
        )

    def restore_oem(
        self,
        identifier: str,
        *,
        device_profile_id: str,
        progress: Callable[[str], None] | None = None,
    ) -> tuple[UploadReport, Path]:
        self._require_profile(device_profile_id)
        image = self.base_image.read_bytes()
        actual_sha256 = hashlib.sha256(image).hexdigest()
        if actual_sha256 != BASE_SHA256:
            raise UserFacingError(
                "The bundled OEM recovery file is damaged. Reinstall or extract a fresh copy of the app."
            )
        try:
            validation = validate_container_bytes(image, source=self.base_image)
        except Exception as error:
            raise UserFacingError(
                "The bundled OEM recovery file is damaged. "
                "Reinstall or extract a fresh copy of the app."
            ) from error
        if not validation.valid:
            raise UserFacingError(
                "The bundled OEM recovery file is damaged. "
                "Reinstall or extract a fresh copy of the app."
            )
        return self._upload(
            identifier,
            self.base_image,
            image,
            "recovery",
            validation,
            device_profile_id,
            progress,
        )

    def _upload(
        self,
        identifier: str,
        image_path: Path,
        image: bytes,
        action: str,
        validation: ValidationResult,
        profile_id: str,
        progress: Callable[[str], None] | None,
    ) -> tuple[UploadReport, Path]:
        total_write_count = build_dry_run(image, language=LANGUAGE_INDEX).packet_count
        if progress:
            progress("Connecting and verifying device GATT service")

        write_counter = 0

        def on_entry(entry) -> None:
            nonlocal write_counter
            if entry.direction == "write":
                write_counter += 1
                if progress and write_counter == total_write_count:
                    progress("Applying image and verifying device response")
                elif progress and (write_counter == 1 or write_counter % 5 == 0):
                    progress(f"Uploading packet {write_counter}")

        async def execute() -> UploadReport:
            async with BleakUploadTransport(identifier) as transport:
                return await run_upload(
                    image,
                    transport,
                    language=LANGUAGE_INDEX,
                    entry_callback=on_entry,
                )

        started = datetime.now().astimezone()
        timestamp = started.strftime("%Y%m%d-%H%M%S-%f")
        log_path = log_directory() / f"{timestamp}-{action}.json"
        if log_path.exists():
            raise UserFacingError(
                "Could not create a unique upload log. Close and reopen the app, then try again."
            )
        common_log = {
            "schema": 1,
            "action": action,
            "started_at": started.isoformat(),
            "device_identifier": identifier,
            "device_profile": profile_id,
            "image": str(image_path),
            "image_sha256": hashlib.sha256(image).hexdigest(),
            "recovery_image_sha256": BASE_SHA256,
            "validation": validation.to_dict(),
        }
        try:
            report = asyncio.run(execute())
        except Exception as error:
            failed_log = {
                **common_log,
                "completed_at": datetime.now().astimezone().isoformat(),
                "result": "failed",
                "error": {"type": type(error).__name__, "message": str(error)},
            }
            log_path.write_text(json.dumps(failed_log, indent=2) + "\n", encoding="utf-8")
            if isinstance(error, UploadError):
                message = str(error)
            else:
                message = "Upload failed. Reconnect the headphones and try again."
            raise UserFacingError(message) from error
        completed_log = {
            **common_log,
            "completed_at": datetime.now().astimezone().isoformat(),
            "result": "complete",
            "report": report.to_dict(),
        }
        log_path.write_text(json.dumps(completed_log, indent=2) + "\n", encoding="utf-8")
        if progress:
            progress(f"Device accepted image with state: {report.state}")
        return report, log_path
