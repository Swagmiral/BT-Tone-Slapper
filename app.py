from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


from tone_slapper import APP_VERSION


def self_test(output: Path) -> None:
    if output.exists():
        raise ValueError(f"refusing to overwrite self-test output: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)

    def checkpoint(step: str, **details) -> None:
        output.write_text(json.dumps({"step": step, **details}, indent=2) + "\n", encoding="utf-8")

    checkpoint("started")
    from bleak import BleakClient
    from bleak.backends.winrt.scanner import BleakScannerWinRT

    checkpoint("bleak-imported")
    from tone_slapper.gui import ToneSlapperWindow, create_application
    from tone_slapper.workflow import ToneSlapperEngine

    checkpoint("application-imported")
    gui_application = create_application([])
    app_window = ToneSlapperWindow()
    app_window.hide()
    gui_application.processEvents()
    gui_size = {
        "requested_width": app_window.sizeHint().width(),
        "requested_height": app_window.sizeHint().height(),
        "theme": gui_application.style().objectName(),
    }
    app_window.destroy()
    gui_application.processEvents()
    checkpoint("gui-constructed", **gui_size)
    engine = ToneSlapperEngine()
    checkpoint("assets-verified")
    cached_oem = engine.cached_oem()
    checkpoint("oem-cache-checked", present=cached_oem is not None)
    ffmpeg_result = subprocess.run(
        [str(engine.ffmpeg), "-version"],
        check=False,
        capture_output=True,
        text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        timeout=15,
    )
    report = {
        "version": APP_VERSION,
        "assets_verified": True,
        "oem_cache_present": cached_oem is not None,
        "oem_container_valid": cached_oem.validation.valid if cached_oem else None,
        "oem_sha256": cached_oem.sha256 if cached_oem else None,
        "oem_packet_count": cached_oem.packet_count if cached_oem else None,
        "ffmpeg_executable": ffmpeg_result.returncode == 0,
        "ffmpeg_version_line": ffmpeg_result.stdout.splitlines()[0] if ffmpeg_result.stdout else None,
        "bleak_import": BleakClient is not None,
        "winrt_backend_import": BleakScannerWinRT is not None,
        "gui_constructed": True,
        "gui_requested_width": gui_size["requested_width"],
        "gui_requested_height": gui_size["requested_height"],
        "gui_theme": gui_size["theme"],
    }
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def run() -> None:
    if len(sys.argv) == 3 and sys.argv[1] == "--self-test":
        self_test(Path(sys.argv[2]))
        return
    if len(sys.argv) == 2 and sys.argv[1].startswith("--self-test="):
        self_test(Path(sys.argv[1].split("=", 1)[1]))
        return
    from tone_slapper.gui import main

    main()


if __name__ == "__main__":
    run()
