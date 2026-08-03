from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .container import ValidationResult, validate_container_bytes
from .errors import UserFacingError
from .uploader import build_dry_run


OEM_FILENAME = "English_prompt_v0.0.5.bin"
OEM_SIZE = 74205
OEM_SHA256 = "91afbf099c9160fc251cf858c43b4d4df5bd9392cab5a6ab3b51ee0541d0ab9f"
OEM_SERVER_URL = (
    "https://storage.harman.com/MyJBLHeadphones/ota/release/20b4/tone/"
    "English_prompt_v0.0.5.bin"
)
OEM_GITHUB_URL = (
    "https://raw.githubusercontent.com/Tselovanskyi/BT-Tone-Slapper/main/"
    "OEM%20Backups/JBL%20Tune%20720BT/"
    "English_prompt_v0.0.5.bin"
)
OEM_GITHUB_MANUAL_URL = (
    "https://github.com/Tselovanskyi/BT-Tone-Slapper/blob/main/"
    "OEM%20Backups/JBL%20Tune%20720BT/"
    "English_prompt_v0.0.5.bin"
)
MAX_OEM_DOWNLOAD_SIZE = 1024 * 1024
DOWNLOAD_TIMEOUT_SECONDS = 20


class OemAcquisitionError(UserFacingError):
    pass


@dataclass(frozen=True)
class OemImage:
    path: Path
    sha256: str
    validation: ValidationResult
    packet_count: int
    source: str


class OemStore:
    def __init__(self, cache_path: Path) -> None:
        self.cache_path = cache_path.resolve()

    def cached(self) -> OemImage | None:
        if not self.cache_path.is_file():
            return None
        try:
            data = self._read_limited(self.cache_path)
            return self._verify(data, self.cache_path, "local cache")
        except (OSError, OemAcquisitionError):
            return None

    def require_cached(self) -> OemImage:
        image = self.cached()
        if image is None:
            raise OemAcquisitionError(
                "The local OEM file is missing or has changed. Download a verified copy first."
            )
        return image

    def download_from_manufacturer(self) -> OemImage:
        return self._download(OEM_SERVER_URL, "manufacturer")

    def download_from_github(self) -> OemImage:
        return self._download(OEM_GITHUB_URL, "GitHub")

    def import_manual(self, source: Path) -> OemImage:
        try:
            data = self._read_limited(source)
        except OSError as error:
            raise OemAcquisitionError(
                "The selected OEM file could not be read."
            ) from error
        verified = self._verify(data, source, "selected file")
        try:
            return self._save_verified(data, verified, "manual GitHub download")
        except OemAcquisitionError:
            return OemImage(
                path=source.resolve(),
                sha256=verified.sha256,
                validation=verified.validation,
                packet_count=verified.packet_count,
                source="manual GitHub download",
            )

    def _download(self, url: str, source: str) -> OemImage:
        request = Request(
            url,
            headers={
                "Accept": "application/octet-stream",
                "User-Agent": "BT-Tone-Slapper/0.2",
            },
        )
        try:
            with urlopen(request, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response:
                status = getattr(response, "status", 200)
                if status != 200:
                    raise OemAcquisitionError(
                        f"The OEM {source} download returned HTTP {status}."
                    )
                declared_length = response.headers.get("Content-Length")
                if declared_length and int(declared_length) > MAX_OEM_DOWNLOAD_SIZE:
                    raise OemAcquisitionError(
                        f"The OEM file provided by {source} is unexpectedly large."
                    )
                data = response.read(MAX_OEM_DOWNLOAD_SIZE + 1)
        except OemAcquisitionError:
            raise
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as error:
            raise OemAcquisitionError(
                f"The OEM file could not be downloaded from {source}."
            ) from error

        if len(data) > MAX_OEM_DOWNLOAD_SIZE:
            raise OemAcquisitionError(
                f"The OEM file provided by {source} is unexpectedly large."
            )
        verified = self._verify(data, Path(OEM_FILENAME), source)
        return self._save_verified(data, verified, source)

    def _verify(self, data: bytes, source_path: Path, source: str) -> OemImage:
        if len(data) != OEM_SIZE:
            raise OemAcquisitionError(
                f"The OEM file from {source} does not match the verified file size."
            )
        actual_sha256 = hashlib.sha256(data).hexdigest()
        if actual_sha256 != OEM_SHA256:
            raise OemAcquisitionError(
                f"The OEM file from {source} does not match the verified SHA-256."
            )
        try:
            validation = validate_container_bytes(data, source=source_path)
        except Exception as error:
            raise OemAcquisitionError(
                f"The OEM file from {source} is not a valid prompt container."
            ) from error
        if not validation.valid:
            raise OemAcquisitionError(
                f"The OEM file from {source} is not a valid prompt container."
            )
        packet_count = build_dry_run(data, language=1).packet_count
        return OemImage(
            path=source_path,
            sha256=actual_sha256,
            validation=validation,
            packet_count=packet_count,
            source=source,
        )

    def _save_verified(self, data: bytes, verified: OemImage, source: str) -> OemImage:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                prefix=f"{OEM_FILENAME}.",
                suffix=".download",
                dir=self.cache_path.parent,
                delete=False,
            ) as temporary:
                temporary.write(data)
                temporary.flush()
                os.fsync(temporary.fileno())
                temporary_path = Path(temporary.name)
            os.replace(temporary_path, self.cache_path)
            temporary_path = None
        except OSError as error:
            raise OemAcquisitionError(
                "The verified OEM file could not be saved next to the application."
            ) from error
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

        return OemImage(
            path=self.cache_path,
            sha256=verified.sha256,
            validation=verified.validation,
            packet_count=verified.packet_count,
            source=source,
        )

    @staticmethod
    def _read_limited(path: Path) -> bytes:
        with path.open("rb") as source:
            data = source.read(MAX_OEM_DOWNLOAD_SIZE + 1)
        if len(data) > MAX_OEM_DOWNLOAD_SIZE:
            raise OemAcquisitionError("The OEM file is unexpectedly large.")
        return data
