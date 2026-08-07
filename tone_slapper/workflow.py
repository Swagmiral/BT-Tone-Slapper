from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
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
    DeviceProfile,
    TUNE_720BT_PROFILE,
    get_device_profile,
    resolve_device_profile,
)
from .errors import UserFacingError
from .oem import (
    OEM_FILENAME as BASE_FILENAME,
    OEM_SHA256 as BASE_SHA256,
    OemImage,
    OemStore,
)
from .resources import asset_path, log_directory, portable_root
from .uploader import UploadError, UploadReport, build_dry_run, run_upload


FFMPEG_SHA256 = "2ce797a0f88d7f067180338fb227f7b1928ea727bd9a4d7a1d022f7c52af71a3"
LZMA_ENCODER_SHA256 = "e2d96d96f7c0eb3c6ac13fdcf8ddd664d7bc18916156ffaff09c285327d93ee0"
LANGUAGE_INDEX = 1

@dataclass(frozen=True)
class BuildResult:
    output: str
    sha256: str
    profile_id: str
    validation: ValidationResult
    replacements: Mapping[int, EncodedAudio]
    dry_run: dict[str, object]


class ToneSlapperEngine:
    def __init__(self, *, base_image: Path | None = None) -> None:
        self.base_image = (
            base_image.resolve()
            if base_image is not None
            else (portable_root() / BASE_FILENAME).resolve()
        )
        self.oem_store = OemStore(self.base_image)
        self.ffmpeg = asset_path("ffmpeg.exe")
        self.lzma_encoder = asset_path("LzmaAlone.exe")
        self._verify_asset(self.ffmpeg, FFMPEG_SHA256, "FFmpeg")
        self._verify_asset(self.lzma_encoder, LZMA_ENCODER_SHA256, "LZMA encoder")

    @staticmethod
    def _verify_asset(path: Path, expected_sha256: str, label: str) -> None:
        actual = sha256_file(path)
        if actual != expected_sha256:
            raise ValueError(f"bundled {label} hash mismatch: {actual}")

    @staticmethod
    def _require_profile(profile_id: str) -> DeviceProfile:
        profile = get_device_profile(profile_id)
        if profile is None:
            raise UserFacingError(
                f"This operation is only supported for {TUNE_720BT_PROFILE.display_name}."
            )
        return profile

    def cached_oem(self) -> OemImage | None:
        return self.oem_store.cached()

    def download_official_oem(self) -> OemImage:
        return self.oem_store.download_from_manufacturer()

    def download_github_oem(self) -> OemImage:
        return self.oem_store.download_from_github()

    def import_manual_oem(self, source: Path) -> OemImage:
        return self.oem_store.import_manual(source)

    def build(
        self,
        assignments: Mapping[int, Path],
        output: Path,
        *,
        profile_id: str = TUNE_720BT_PROFILE.profile_id,
        base_image: Path | None = None,
        expected_base_sha256: str = BASE_SHA256,
        progress: Callable[[str], None] | None = None,
        work_dir: Path | None = None,
    ) -> BuildResult:
        profile = self._require_profile(profile_id)
        prompt_labels = profile.prompt_labels
        selected_base = (base_image or self.base_image).resolve()
        base_bytes, _base_validation = self._load_oem_for_use(
            selected_base,
            expected_base_sha256,
        )
        if output.suffix.lower() != ".bin":
            raise UserFacingError("The output filename must end in .bin.")
        output = output.resolve()
        if output == selected_base:
            raise UserFacingError(
                "Choose another save location. The verified OEM file cannot be overwritten."
            )
        replacements: dict[int, EncodedAudio] = {}
        if not assignments:
            if progress:
                progress("Saving verified OEM container")
            output.write_bytes(base_bytes)
        else:
            if work_dir is None:
                work_context = tempfile.TemporaryDirectory(prefix="tone-slapper-build-")
            else:
                work_dir = work_dir.resolve()
                if not work_dir.is_dir() or any(work_dir.iterdir()):
                    raise ValueError("explicit work directory must exist and be empty")
                work_context = contextlib.nullcontext(str(work_dir))
            with work_context as temporary:
                temporary_path = Path(temporary)
                base_snapshot = temporary_path / BASE_FILENAME
                base_snapshot.write_bytes(base_bytes)
                for index, source in sorted(assignments.items()):
                    if not 0 <= index < len(prompt_labels):
                        raise ValueError(f"invalid prompt index: {index}")
                    if progress:
                        progress(f"Converting prompt {index}: {prompt_labels[index]}")
                    replacements[index] = encode_audio(
                        source,
                        temporary_path / f"prompt_{index:02d}",
                        self.ffmpeg,
                        progress=progress,
                    )
                if progress:
                    progress("Rebuilding and signing integrity fields")
                build_container(
                    base_snapshot,
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
    def scan(
        timeout: float = 8.0,
        on_discovered: Callable[[DiscoveredDevice], None] | None = None,
    ) -> list[DiscoveredDevice]:
        manufacturer = TUNE_720BT_PROFILE.display_name.partition(" ")[0]

        def report_supported(device: DiscoveredDevice) -> None:
            if (
                on_discovered is not None
                and resolve_device_profile(device.name) is not None
            ):
                on_discovered(device)

        scan_options = {
            "timeout": timeout,
            "name_contains": manufacturer,
        }
        if on_discovered is not None:
            scan_options["on_discovered"] = report_supported
        devices = asyncio.run(scan_devices(**scan_options))
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
        oem_image: OemImage,
        *,
        device_profile_id: str,
        progress: Callable[[str], None] | None = None,
    ) -> tuple[UploadReport, Path]:
        self._require_profile(device_profile_id)
        image, validation = self._load_oem_for_use(
            oem_image.path,
            oem_image.sha256,
        )
        return self._upload(
            identifier,
            oem_image.path,
            image,
            "recovery",
            validation,
            device_profile_id,
            progress,
        )

    @staticmethod
    def _load_oem_for_use(
        path: Path,
        expected_sha256: str,
    ) -> tuple[bytes, ValidationResult]:
        try:
            image = path.read_bytes()
        except OSError as error:
            raise UserFacingError(
                "The verified OEM file is no longer available. Download it again."
            ) from error
        actual_sha256 = hashlib.sha256(image).hexdigest()
        if actual_sha256 != expected_sha256 or actual_sha256 != BASE_SHA256:
            raise UserFacingError(
                "The OEM file changed after verification. Download it again before continuing."
            )
        try:
            validation = validate_container_bytes(image, source=path)
        except Exception as error:
            raise UserFacingError(
                "The verified OEM file is no longer a valid prompt container."
            ) from error
        if not validation.valid:
            raise UserFacingError(
                "The verified OEM file is no longer a valid prompt container."
            )
        return image, validation

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
