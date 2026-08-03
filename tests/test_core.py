from __future__ import annotations

import hashlib
import asyncio
import struct
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from tkinter import Tk
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from bt_tone_slapper import APP_AUTHOR, APP_NAME, LICENSE_NAME, PROJECT_URL
from bt_tone_slapper.bluetooth import DiscoveredDevice, scan_devices
from bt_tone_slapper.container import build_container, validate_container
from bt_tone_slapper.device_profiles import (
    TUNE_720BT_PROFILE,
    normalize_device_name,
    resolve_device_profile,
)
from bt_tone_slapper.errors import UserFacingError, user_error_message
from bt_tone_slapper.gui import (
    CLOSE_BLOCKED_TEXT,
    DONATE_URL,
    LEGAL_NOTICE_FILES,
    SUPPORTED_AUDIO_FORMATS,
    SUPPORTED_DEVICES,
    ToneSlapperWindow,
    WRITE_WARNING_TEXT,
    load_legal_documents,
)
from bt_tone_slapper.protocol import SERVICE_UUID, WRITE_UUID, NOTIFY_UUID
from bt_tone_slapper.oem import (
    OEM_GITHUB_MANUAL_URL,
    OEM_GITHUB_URL,
    OEM_SERVER_URL,
    OemAcquisitionError,
    OemStore,
)
from bt_tone_slapper.uploader import build_dry_run
from bt_tone_slapper.workflow import BASE_SHA256, ToneSlapperEngine


ROOT = PROJECT_ROOT
OEM_SAMPLE = (
    ROOT
    / "OEM Backups"
    / TUNE_720BT_PROFILE.display_name
    / "English_prompt_v0.0.5.bin"
)
CUSTOM_SOUND_PACK = (
    ROOT
    / "Custom Sound Packs"
    / "JBL"
    / TUNE_720BT_PROFILE.display_name
    / "JBL_prompts_custom.bin"
)


class FakeDownloadResponse:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.status = 200
        self.headers = {"Content-Length": str(len(data))}

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback):
        return False

    def read(self, limit: int = -1) -> bytes:
        return self.data if limit < 0 else self.data[:limit]


def test_engine() -> ToneSlapperEngine:
    return ToneSlapperEngine(base_image=OEM_SAMPLE)


class CoreTests(unittest.TestCase):
    def test_prompt_list_waits_for_device_target(self) -> None:
        root = Tk()
        root.withdraw()
        try:
            window = ToneSlapperWindow(root)
            root.update_idletasks()

            self.assertTrue(root.protocol("WM_DELETE_WINDOW"))
            self.assertEqual(window.prompt_empty_label.cget("text"), "Select a device first")
            self.assertEqual(str(window.prompt_empty_label.cget("anchor")), "center")
            self.assertEqual(str(window.prompt_empty_label.cget("justify")), "center")
            prompt_empty_font = str(window.prompt_empty_label.cget("font"))
            self.assertIn("22", prompt_empty_font)
            self.assertIn("bold", prompt_empty_font)
            self.assertGreaterEqual(window.prompt_empty_label.winfo_reqheight(), 40)
            self.assertTrue(window.prompt_empty_label.winfo_manager())
            self.assertFalse(window.write_warning_label.winfo_manager())
            self.assertEqual(window.write_warning_label.cget("text"), WRITE_WARNING_TEXT)
            window._set_write_warning_visible(True)
            root.update_idletasks()
            self.assertTrue(window.write_warning_label.winfo_manager())
            window._set_write_warning_visible(False)
            self.assertFalse(window.write_warning_label.winfo_manager())
            self.assertFalse(window.prompt_tree.winfo_manager())
            self.assertEqual(window.prompt_tree.get_children(), ())
            self.assertEqual(str(window.validate_button.cget("state")), "disabled")
            with patch("bt_tone_slapper.gui.filedialog.askopenfilename") as choose:
                window._choose_audio_for(0)
            choose.assert_not_called()

            window.target_profile_id = TUNE_720BT_PROFILE.profile_id
            window._refresh_prompt_rows()
            root.update_idletasks()

            self.assertFalse(window.prompt_empty_label.winfo_manager())
            self.assertTrue(window.prompt_tree.winfo_manager())
            self.assertEqual(len(window.prompt_tree.get_children()), 11)
            self.assertEqual(
                window.prompt_tree.item("10", "values")[1],
                "Maximum volume",
            )
        finally:
            root.destroy()

    def test_close_is_blocked_during_upload_and_oem_restore(self) -> None:
        protected_states = (
            ("upload", True, None),
            ("recovery", True, None),
            ("oem-official", True, "restore"),
        )
        for active_operation, busy, oem_context in protected_states:
            with self.subTest(
                active_operation=active_operation,
                oem_context=oem_context,
            ):
                window = object.__new__(ToneSlapperWindow)
                window.root = Mock()
                window.active_operation = active_operation
                window.busy = busy
                window._oem_context = oem_context

                with patch("bt_tone_slapper.gui.messagebox.showwarning") as warning:
                    window._request_close()

                warning.assert_called_once_with(
                    APP_NAME,
                    CLOSE_BLOCKED_TEXT,
                    parent=window.root,
                )
                window.root.destroy.assert_not_called()

    def test_close_remains_available_outside_write_operations(self) -> None:
        window = object.__new__(ToneSlapperWindow)
        window.root = Mock()
        window.active_operation = "build"
        window.busy = True
        window._oem_context = "build"

        with patch("bt_tone_slapper.gui.messagebox.showwarning") as warning:
            window._request_close()

        warning.assert_not_called()
        window.root.destroy.assert_called_once_with()

    def test_write_confirmations_explain_risk_and_recovery(self) -> None:
        window = object.__new__(ToneSlapperWindow)
        window._device_identifier = Mock(return_value="connected-device")
        window._selected_profile_id = Mock(
            return_value=TUNE_720BT_PROFILE.profile_id
        )
        window.last_build = SimpleNamespace(
            output=str(OEM_SAMPLE),
            profile_id=TUNE_720BT_PROFILE.profile_id,
            sha256=BASE_SHA256,
            dry_run={"packet_count": 1},
        )
        window._run_background = Mock()
        window._acquire_oem = Mock()

        with patch(
            "bt_tone_slapper.gui.messagebox.askyesno",
            return_value=False,
        ) as confirm:
            window.upload()
        upload_warning = confirm.call_args.args[1]
        self.assertIn("interrupted or incompatible write", upload_warning)
        self.assertIn("do not close the app", upload_warning)
        self.assertIn("Restore OEM English", upload_warning)
        window._run_background.assert_not_called()

        with patch(
            "bt_tone_slapper.gui.messagebox.askyesno",
            return_value=False,
        ) as confirm:
            window.restore()
        restore_warning = confirm.call_args.args[1]
        self.assertIn("cryptographically verified", restore_warning)
        self.assertIn("do not close the app", restore_warning)
        self.assertIn("another OEM restore attempt", restore_warning)
        window._acquire_oem.assert_not_called()

    def test_runtime_assets_and_oem_fixture(self) -> None:
        engine = test_engine()
        self.assertEqual(hashlib.sha256(engine.base_image.read_bytes()).hexdigest(), BASE_SHA256)
        self.assertTrue(validate_container(engine.base_image).valid)
        icon_png = ROOT / "assets" / "source" / "app_icon.png"
        icon_ico = ROOT / "assets" / "icons" / "app_icon.ico"
        self.assertTrue(icon_png.is_file())
        icon_data = icon_ico.read_bytes()
        reserved, image_type, image_count = struct.unpack_from("<HHH", icon_data)
        self.assertEqual((reserved, image_type, image_count), (0, 1, 9))
        icon_sizes = {
            (
                icon_data[6 + index * 16] or 256,
                icon_data[7 + index * 16] or 256,
            )
            for index in range(image_count)
        }
        self.assertEqual(
            icon_sizes,
            {
                (16, 16),
                (20, 20),
                (24, 24),
                (32, 32),
                (40, 40),
                (48, 48),
                (64, 64),
                (128, 128),
                (256, 256),
            },
        )

    def test_oem_packet_plan(self) -> None:
        payload = OEM_SAMPLE.read_bytes()
        report = build_dry_run(payload, language=1)
        self.assertEqual(report.packet_count, 372)
        self.assertEqual(report.data_packet_count, 370)
        self.assertEqual(report.chunk_size, 201)

    def test_repository_custom_sound_pack(self) -> None:
        result = test_engine().open_existing(
            CUSTOM_SOUND_PACK,
            profile_id=TUNE_720BT_PROFILE.profile_id,
        )
        self.assertTrue(result.validation.valid)
        self.assertEqual(
            result.sha256,
            "d745198f6a9b5041b63b4a6a18f73e05df18265bdf7505706bfb3036f49f2831",
        )
        self.assertEqual(result.validation.file_size, 88740)
        self.assertEqual(result.dry_run["packet_count"], 444)
        self.assertEqual(result.dry_run["data_packet_count"], 442)

    def test_official_oem_download_replaces_invalid_cache(self) -> None:
        payload = OEM_SAMPLE.read_bytes()
        with TemporaryDirectory() as temporary:
            cache = Path(temporary) / OEM_SAMPLE.name
            cache.write_bytes(b"invalid cache")
            store = OemStore(cache)
            with patch(
                "bt_tone_slapper.oem.urlopen",
                return_value=FakeDownloadResponse(payload),
            ) as downloader:
                image = store.download_from_manufacturer()

            self.assertEqual(cache.read_bytes(), payload)
            self.assertEqual(image.sha256, BASE_SHA256)
            self.assertEqual(image.packet_count, 372)
            request = downloader.call_args.args[0]
            self.assertEqual(request.full_url, OEM_SERVER_URL)

    def test_changed_official_oem_is_rejected_without_replacing_cache(self) -> None:
        payload = OEM_SAMPLE.read_bytes()
        changed = bytearray(payload)
        changed[-1] ^= 0x01
        with TemporaryDirectory() as temporary:
            cache = Path(temporary) / OEM_SAMPLE.name
            cache.write_bytes(payload)
            store = OemStore(cache)
            with patch(
                "bt_tone_slapper.oem.urlopen",
                return_value=FakeDownloadResponse(bytes(changed)),
            ):
                with self.assertRaisesRegex(
                    OemAcquisitionError,
                    "does not match the verified SHA-256",
                ):
                    store.download_from_manufacturer()

            self.assertEqual(cache.read_bytes(), payload)

    def test_github_oem_fallback_is_also_pinned(self) -> None:
        payload = OEM_SAMPLE.read_bytes()
        with TemporaryDirectory() as temporary:
            cache = Path(temporary) / OEM_SAMPLE.name
            store = OemStore(cache)
            with patch(
                "bt_tone_slapper.oem.urlopen",
                return_value=FakeDownloadResponse(payload),
            ) as downloader:
                image = store.download_from_github()

            self.assertEqual(image.path, cache.resolve())
            self.assertEqual(cache.read_bytes(), payload)
            request = downloader.call_args.args[0]
            self.assertEqual(request.full_url, OEM_GITHUB_URL)

    def test_restore_oem_always_starts_with_manufacturer_download(self) -> None:
        window = object.__new__(ToneSlapperWindow)
        window.busy = False
        window.engine = Mock()
        window.engine.cached_oem = Mock()
        window.engine.download_official_oem = Mock()
        window._run_background = Mock()
        window._pending_oem_action = None
        window._oem_context = None
        ready = Mock()

        window._acquire_oem("restore", ready, always_download=True)

        window.engine.cached_oem.assert_not_called()
        self.assertIs(window._pending_oem_action, ready)
        self.assertEqual(window._oem_context, "restore")
        operation_name, operation, success = window._run_background.call_args.args
        self.assertEqual(operation_name, "oem-official")
        self.assertIs(operation, window.engine.download_official_oem)
        self.assertEqual(success.__func__, ToneSlapperWindow._oem_acquired)

    def test_prompt_map_and_live_uuids(self) -> None:
        self.assertEqual(len(TUNE_720BT_PROFILE.prompt_labels), 11)
        self.assertEqual(TUNE_720BT_PROFILE.prompt_labels[10], "Maximum volume")
        self.assertEqual(SERVICE_UUID, "65786365-6c70-6f69-6e74-2e636f6d0000")
        self.assertTrue(NOTIFY_UUID.endswith("0001"))
        self.assertTrue(WRITE_UUID.endswith("0002"))

    def test_open_existing_prepares_upload(self) -> None:
        engine = test_engine()
        result = engine.open_existing(engine.base_image)
        self.assertTrue(result.validation.valid)
        self.assertEqual(result.sha256, BASE_SHA256)
        self.assertEqual(result.dry_run["packet_count"], 372)

    def test_build_overwrites_without_sidecar(self) -> None:
        engine = test_engine()
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
        engine = test_engine()
        with TemporaryDirectory() as temporary:
            output = Path(temporary) / "English_prompt_OEM.bin"
            result = engine.build({}, output)
            self.assertEqual(output.read_bytes(), engine.base_image.read_bytes())
            self.assertEqual(result.sha256, BASE_SHA256)
            self.assertEqual(result.profile_id, TUNE_720BT_PROFILE.profile_id)
            self.assertEqual(result.replacements, {})
            self.assertEqual(result.dry_run["packet_count"], 372)

    def test_upload_uses_validated_in_memory_snapshot(self) -> None:
        engine = test_engine()
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
        engine = test_engine()
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
        engine = test_engine()
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
        self.assertEqual(APP_AUTHOR, "Yaroslav Tselovanskyi")
        self.assertEqual(PROJECT_URL, "https://github.com/Tselovanskyi/BT-Tone-Slapper")
        self.assertTrue(
            OEM_GITHUB_URL.startswith(
                "https://raw.githubusercontent.com/Tselovanskyi/BT-Tone-Slapper/"
            )
        )
        self.assertTrue(
            OEM_GITHUB_MANUAL_URL.startswith(
                "https://github.com/Tselovanskyi/BT-Tone-Slapper/"
            )
        )
        self.assertEqual(
            LICENSE_NAME,
            "GNU GPLv3 with Section 7 attribution terms",
        )
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
        window.root = Mock()
        window._legal_window = Mock()
        with patch("bt_tone_slapper.gui.webbrowser.open", return_value=True) as open_url:
            window.open_source_repository()
        open_url.assert_called_once_with(PROJECT_URL, new=2)

    def test_project_license_and_attribution_notices(self) -> None:
        license_text = (PROJECT_ROOT / "LICENSE").read_text(encoding="utf-8")
        attribution_text = (PROJECT_ROOT / "ATTRIBUTION.md").read_text(encoding="utf-8")
        third_party_text = (PROJECT_ROOT / "THIRD_PARTY.md").read_text(encoding="utf-8")
        readme_text = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
        notice = (
            "BT Tone Slapper was originally created by "
            "Yaroslav Tselovanskyi."
        )
        self.assertIn("GNU GENERAL PUBLIC LICENSE", license_text)
        self.assertIn("Version 3, 29 June 2007", license_text)
        self.assertIn(notice, attribution_text)
        self.assertIn(notice, readme_text)
        self.assertIn(PROJECT_URL, attribution_text)
        self.assertIn(
            "No account username or handle is required",
            attribution_text,
        )
        self.assertEqual(
            LEGAL_NOTICE_FILES,
            (
                ("License", "LICENSE"),
                ("Attribution", "ATTRIBUTION.md"),
                ("Third-party notices", "THIRD_PARTY.md"),
            ),
        )
        self.assertEqual(
            load_legal_documents(),
            {
                "License": license_text,
                "Attribution": attribution_text,
                "Third-party notices": third_party_text,
            },
        )
        build_script = (PROJECT_ROOT / "build_portable.ps1").read_text(encoding="utf-8")
        for filename in ("LICENSE", "ATTRIBUTION.md", "THIRD_PARTY.md"):
            self.assertIn(f'--add-data "$Root\\{filename};."', build_script)

    def test_legal_notices_window_displays_all_documents(self) -> None:
        root = Tk()
        root.withdraw()
        try:
            window = ToneSlapperWindow(root)
            window.show_legal_notices()
            root.update_idletasks()

            self.assertIsNotNone(window._legal_window)
            self.assertEqual(
                window._legal_window.title(),
                f"{APP_NAME} - Legal Notices",
            )
            self.assertIn(
                "GNU GENERAL PUBLIC LICENSE",
                window._legal_text.get("1.0", "end-1c"),
            )

            window._legal_buttons["Attribution"].invoke()
            self.assertIn(
                f"Originally created by {APP_AUTHOR}",
                window._legal_text.get("1.0", "end-1c"),
            )
            window._legal_buttons["Third-party notices"].invoke()
            third_party_text = window._legal_text.get("1.0", "end-1c")
            self.assertIn("FFmpeg", third_party_text)
            self.assertIn("Material Symbols", third_party_text)
            self.assertEqual(
                str(window._legal_text.cget("state")),
                "disabled",
            )
        finally:
            root.destroy()

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
