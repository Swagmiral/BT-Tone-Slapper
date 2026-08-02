from __future__ import annotations

import os
import sys
from pathlib import Path


def bundle_root() -> Path:
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        return Path(frozen_root)
    return Path(__file__).resolve().parents[1]


def asset_path(name: str) -> Path:
    path = bundle_root() / "assets" / name
    if not path.is_file():
        raise FileNotFoundError(f"missing bundled asset: {path}")
    return path


def portable_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def user_data_root() -> Path:
    override = os.environ.get("BT_TONE_SLAPPER_DATA")
    root = Path(override) if override else Path(os.environ.get("LOCALAPPDATA", Path.home())) / "BTToneSlapper"
    root.mkdir(parents=True, exist_ok=True)
    return root


def log_directory() -> Path:
    path = user_data_root() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path
