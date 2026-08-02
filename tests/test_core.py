from __future__ import annotations

import hashlib
import asyncio
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from bt_tone_slapper.bluetooth import DiscoveredDevice, scan_devices
from bt_tone_slapper.container import build_container, validate_container
from bt_tone_slapper.device_profiles import (
    TUNE_720BT_PROFILE,
    normalize_device_name,
    resolve_device_profile,
)
from bt_tone_slapper.errors import UserFacingError, user_error_message
from bt_tone_slapper.gui import (
    DONATE_URL,
    SUPPORTED_AUDIO_FORMATS,
    SUPPORTED_DEVICES,
    ToneSlapperWindow,
)
from bt_tone_slapper.protocol import SERVICE_UUID, WRITE_UUID, NOTIFY_UUID
from bt_tone_slapper.uploader import build_dry_run
from bt_tone_slapper.workflow import BASE_SHA256, PROMPT_LABELS, ToneSlapperEngine


ROOT = PROJECT_ROOT


class CoreTests(unittest.TestCase):
    def test_bundled_assets_and_oem_container(self) -> None:
        engine = ToneSlapperEngine()
        self.assertEqual(hashlib.sha256(engine.base_image.read_bytes()).hexdigest(), BASE_SHA256)
        self.assertTrue(validate_container(engine.base_image).valid)

    def test_oem_packet_plan(self) -> None:
        payload = (ROOT / "assets" / "English_prompt_v0.0.5.bin").read_bytes()
        report = build_dry_run(payload, language=1)
        self.assertEqual(report.packet_count, 372)
        self.assertEqual(report.data_packet_count, 370)
        self.assertEqual(report.chunk_size, 201)

    def test_prompt_map_and_live_uuids(self) -> None:
        self.assertEqual(len(PROMPT_LABELS), 11)
        self.assertEqual(PROMPT_LABELS[10], "Maximum volume")
        self.assertEqual(SERVICE_UUID, "65786365-6c70-6f69-6e74-2e636f6d0000")
        self.assertTrue(NOTIFY_UUID.endswith("0001"))
        self.assertTrue(WRITE_UUID.endswith("0002"))

    def test_open_existing_prepares_upload(self) -> None:
        engine = ToneSlapperEngine()
        result = engine.open_existing(engine.base_image)
        self.assertTrue(result.validation.valid)
        self.assertEqual(result.sha256, BASE_SHA256)
        self.assertEqual(result.dry_run["packet_count"], 372)

    def test_build_overwrites_without_sidecar(self) -> None:
        engine = ToneSlapperEngine()
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "reused_name.bin"
            output.write_bytes(b"previous output")
            build_container(
                engine.base_image,
                {},
                output,
                engine.lzma_encoder,
                root / "work",
            )
            self.assertTrue(validate_container(output).valid)
            self.assertFalse(output.with_suffix(".bin.json").exists())

    def test_build_without_assignments_saves_exact_oem_image(self) -> None:
        engine = ToneSlapperEngine()
        with TemporaryDirectory() as temporary:
            output = Path(temporary) / "English_prompt_OEM.bin"
            result = engine.build({}, output)
            self.assertEqual(output.read_bytes(), engine.base_image.read_bytes())
            self.assertEqual(result.sha256, BASE_SHA256)
            self.assertEqual(result.profile_id, TUNE_720BT_PROFILE.profile_id)
            self.assertEqual(result.replacements, {})
            self.assertEqual(result.dry_run["packet_count"], 372)

    def test_upload_uses_validated_in_memory_snapshot(self) -> None:
        engine = ToneSlapperEngine()
        with TemporaryDirectory() as temporary:
            candidate = Path(temporary) / "candidate.bin"
            expected_image = engine.base_image.read_bytes()
            candidate.write_bytes(expected_image)

            def fake_upload(
                identifier,
                image_path,
                image,
                action,
                validation,
                profile_id,
                progress,
            ):
                candidate.unlink()
                self.assertEqual(identifier, "device-id")
                self.assertEqual(image_path, candidate)
                self.assertEqual(image, expected_image)
                self.assertEqual(action, "custom")
                self.assertEqual(validation.sha256, BASE_SHA256)
                self.assertEqual(profile_id, TUNE_720BT_PROFILE.profile_id)
                self.assertIsNone(progress)
                return "report", Path("session.json")

            with patch.object(engine, "_upload", side_effect=fake_upload):
                result = engine.upload_generated(
                    "device-id",
                    candidate,
                    BASE_SHA256,
                    file_profile_id=TUNE_720BT_PROFILE.profile_id,
                    device_profile_id=TUNE_720BT_PROFILE.profile_id,
                )

            self.assertEqual(result, ("report", Path("session.json")))
            self.assertFalse(candidate.exists())

    def test_upload_changed_file_explains_how_to_continue(self) -> None:
        engine = ToneSlapperEngine()
        with self.assertRaisesRegex(
            ValueError,
            "File changed since it was loaded.*Open it again or rebuild before uploading",
        ):
            engine.upload_generated(
                "device-id",
                engine.base_image,
                "incorrect hash",
                file_profile_id=TUNE_720BT_PROFILE.profile_id,
                device_profile_id=TUNE_720BT_PROFILE.profile_id,
            )

    def test_device_profile_accepts_tune_720bt_name_variations(self) -> None:
        names = (
            "JBL Tune720BT",
            "JBL Tune 720BT",
            "JBL-Tune-720BT",
            "LE_JBL Tune720BT",
            "Headphones (JBL Tune 720BT)",
        )
        for name in names:
            with self.subTest(name=name):
                self.assertEqual(
                    resolve_device_profile(name),
                    TUNE_720BT_PROFILE,
                )
        self.assertEqual(normalize_device_name("JBL Tune 720BT"), "jbltune720bt")
        self.assertIsNone(resolve_device_profile("JBL Tune 770NC"))
        self.assertIsNone(resolve_device_profile("JBL Live 770NC"))

    def test_scan_filters_out_other_connected_jbl_models(self) -> None:
        supported = DiscoveredDevice(
            address="02:00:00:00:00:01",
            name="JBL Tune720BT",
            rssi=-40,
            service_uuids=(),
        )
        unsupported = DiscoveredDevice(
            address="02:00:00:00:00:02",
            name="JBL Tune 770NC",
            rssi=-30,
            service_uuids=(),
        )
        scanner = AsyncMock(return_value=[supported, unsupported])
        with patch("bt_tone_slapper.workflow.scan_devices", scanner):
            results = ToneSlapperEngine.scan(timeout=0)

        self.assertEqual(results, [supported])
        scanner.assert_awaited_once_with(timeout=0, name_contains="JBL")

    def test_completed_upload_removes_stale_device_address(self) -> None:
        class FakeVariable:
            def __init__(self, value: str) -> None:
                self.value = value

            def get(self) -> str:
                return self.value

            def set(self, value: str) -> None:
                self.value = value

        class FakeCombo:
            def __init__(self) -> None:
                self.values = ()

            def configure(self, **options) -> None:
                self.values = options["values"]

        selected = "JBL Tune720BT | 02:00:00:00:00:20 | Connected"
        other = "JBL Tune720BT | 02:00:00:00:00:21 | Connected"
        window = object.__new__(ToneSlapperWindow)
        window.devices = {
            selected: "02:00:00:00:00:20",
            other: "02:00:00:00:00:21",
        }
        window.device_models = {
            selected: "JBL Tune720BT",
            other: "JBL Tune720BT",
        }
        window.device_var = FakeVariable(selected)
        window.device_combo = FakeCombo()

        window._remove_uploaded_device_from_scan()

        self.assertNotIn(selected, window.devices)
        self.assertNotIn(selected, window.device_models)
        self.assertEqual(window.device_combo.values, (other,))
        self.assertEqual(window.device_var.get(), "")

    def test_upload_completion_finishes_then_latches_success(self) -> None:
        class FakeRoot:
            def __init__(self) -> None:
                self.delay = None
                self.callback = None

            def after(self, delay: int, callback) -> str:
                self.delay = delay
                self.callback = callback
                return "finish-job"

        class FakeProgressButton:
            def __init__(self) -> None:
                self.updates = []
                self.completed = False
                self.reset_calls = []

            def set_progress(self, fraction: float, text: str) -> None:
                self.updates.append((fraction, text))

            def complete(self) -> None:
                self.completed = True

            def reset(self, *, enabled: bool) -> None:
                self.reset_calls.append(enabled)

        window = object.__new__(ToneSlapperWindow)
        window.root = FakeRoot()
        window.upload_button = FakeProgressButton()
        window._upload_finish_job = None
        window._upload_success_latched = False
        window._remove_uploaded_device_from_scan = Mock()
        window._reset_operation_ui = Mock()

        with patch("bt_tone_slapper.gui.time.monotonic", side_effect=(100.0, 100.0)):
            window._upload_complete(None)

        self.assertEqual(window.UPLOAD_FINISH_MS, 6000)
        self.assertEqual(window.root.delay, window.UPLOAD_FINISH_INTERVAL_MS)
        self.assertEqual(window._upload_finish_job, "finish-job")
        window._remove_uploaded_device_from_scan.assert_called_once_with()

        with patch("bt_tone_slapper.gui.time.monotonic", return_value=106.0):
            window.root.callback()

        self.assertTrue(window.upload_button.completed)
        self.assertTrue(window._upload_success_latched)
        self.assertEqual(window.upload_button.updates[-1][0], 1.0)
        window._reset_operation_ui.assert_called_once_with(
            preserve_upload_status=True
        )

        window._reset_upload_success()
        self.assertFalse(window._upload_success_latched)
        self.assertEqual(window.upload_button.reset_calls, [False])

    def test_upload_rejects_unsupported_profile_before_ble(self) -> None:
        engine = ToneSlapperEngine()
        with patch.object(engine, "_upload") as upload:
            with self.assertRaisesRegex(
                UserFacingError,
                "only supported for JBL Tune 720BT",
            ):
                engine.upload_generated(
                    "device-id",
                    engine.base_image,
                    BASE_SHA256,
                    file_profile_id=TUNE_720BT_PROFILE.profile_id,
                    device_profile_id="unsupported-profile",
                )
        upload.assert_not_called()

    def test_user_errors_hide_python_and_windows_diagnostics(self) -> None:
        missing = user_error_message(
            "upload",
            FileNotFoundError(2, "No such file or directory", "missing.bin"),
        )
        scan = user_error_message("scan", OSError("[WinError 87] invalid parameter"))
        internal = user_error_message(
            "build",
            ValueError("mSBC encoder returned an unexpected frame count"),
        )
        changed = user_error_message(
            "upload",
            UserFacingError(
                "File changed since it was loaded. Open it again or rebuild before uploading."
            ),
        )

        self.assertEqual(
            missing,
            "The loaded file no longer exists. Open it again or rebuild before uploading.",
        )
        self.assertEqual(
            scan,
            "Device scan failed. Check that Bluetooth is turned on and try again.",
        )
        self.assertEqual(
            internal,
            "Build failed. Check the selected audio files and save location, then try again.",
        )
        self.assertEqual(
            changed,
            "File changed since it was loaded. Open it again or rebuild before uploading.",
        )
        self.assertNotIn("FileNotFoundError", missing)
        self.assertNotIn("WinError", scan)
        self.assertNotIn("mSBC", internal)

    def test_help_formats_and_support_link(self) -> None:
        self.assertEqual(DONATE_URL, "https://donatello.to/polymernyk")
        self.assertEqual(SUPPORTED_DEVICES, ("JBL Tune 720BT",))
        self.assertEqual(
            SUPPORTED_AUDIO_FORMATS,
            (
                "WAV",
                "MP3",
                "FLAC",
                "OGG",
                "OGA",
                "Opus",
                "M4A",
                "AAC",
                "WMA",
                "AIFF",
                "AIF",
                "CAF",
            ),
        )
        window = object.__new__(ToneSlapperWindow)
        with patch("bt_tone_slapper.gui.webbrowser.open", return_value=True) as open_url:
            window.donate()
        open_url.assert_called_once_with(DONATE_URL, new=2)

    def test_scan_merges_remembered_ble_devices(self) -> None:
        class FakeScanner:
            @staticmethod
            async def discover(**_kwargs):
                device = SimpleNamespace(address="02:00:00:00:00:10", name="Other")
                advertisement = SimpleNamespace(
                    local_name=None,
                    rssi=-40,
                    service_uuids=(),
                )
                return {device.address: (device, advertisement)}

        remembered = DiscoveredDevice(
            address="02:00:00:00:00:11",
            name="JBL Tune 720BT",
            rssi=-127,
            service_uuids=(),
            remembered=True,
            last_seen=123,
        )

        async def connected_provider():
            return {"jbltune720bt"}

        results = asyncio.run(
            scan_devices(
                timeout=0,
                name_contains="JBL",
                scanner=FakeScanner,
                cached_provider=lambda: [remembered],
                connected_provider=connected_provider,
            )
        )
        self.assertEqual(results, [remembered])

    def test_live_scan_replaces_remembered_model(self) -> None:
        live_device = SimpleNamespace(
            address="02:00:00:00:00:12",
            name="JBL Tune720BT",
        )
        live_advertisement = SimpleNamespace(
            local_name=None,
            rssi=-69,
            service_uuids=(),
        )

        class FakeScanner:
            @staticmethod
            async def discover(**_kwargs):
                return {live_device.address: (live_device, live_advertisement)}

        remembered = DiscoveredDevice(
            address="02:00:00:00:00:13",
            name="JBL Tune 720BT",
            rssi=-127,
            service_uuids=(),
            remembered=True,
            last_seen=123,
        )

        async def connected_provider():
            return {"jbltune720bt"}

        results = asyncio.run(
            scan_devices(
                timeout=0,
                name_contains="JBL",
                scanner=FakeScanner,
                cached_provider=lambda: [remembered],
                connected_provider=connected_provider,
            )
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].address, live_device.address)
        self.assertFalse(results[0].remembered)

    def test_scan_excludes_disconnected_models(self) -> None:
        class FakeScanner:
            called = False

            @classmethod
            async def discover(cls, **_kwargs):
                cls.called = True
                return {}

        async def connected_provider():
            return set()

        results = asyncio.run(
            scan_devices(
                timeout=0,
                name_contains="JBL Tune",
                scanner=FakeScanner,
                cached_provider=lambda: [],
                connected_provider=connected_provider,
            )
        )
        self.assertEqual(results, [])
        self.assertFalse(FakeScanner.called)


if __name__ == "__main__":
    unittest.main()
