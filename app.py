from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


from bt_tone_slapper import APP_VERSION


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
    from tkinter import Tk

    from bt_tone_slapper.gui import ToneSlapperWindow
    from bt_tone_slapper.uploader import build_dry_run
    from bt_tone_slapper.workflow import ToneSlapperEngine

    checkpoint("application-imported")
    gui_root = Tk()
    gui_root.withdraw()
    app_window = ToneSlapperWindow(gui_root)
    gui_root.update_idletasks()
    gui_size = {
        "requested_width": gui_root.winfo_reqwidth(),
        "requested_height": gui_root.winfo_reqheight(),
        "theme": app_window.root.tk.call("ttk::style", "theme", "use"),
    }
    gui_root.destroy()
    checkpoint("gui-constructed", **gui_size)
    engine = ToneSlapperEngine()
    checkpoint("assets-verified")
    validation = engine.validate(engine.base_image)
    checkpoint("oem-validated", valid=validation.valid)
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
        "oem_container_valid": validation.valid,
        "oem_sha256": validation.sha256,
        "oem_packet_count": build_dry_run(engine.base_image.read_bytes(), language=1).packet_count,
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
    from bt_tone_slapper.gui import main

    main()


if __name__ == "__main__":
    run()
