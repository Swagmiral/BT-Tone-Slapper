from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QFont, QFontDatabase, QFontInfo, QGuiApplication
from PySide6.QtWidgets import QWidget

from .resources import asset_path


BODY_FONT_FAMILY = "DM Sans"
EMPHASIS_FONT_FAMILY = "DM Sans"
FALLBACK_FONT_FAMILY = "Segoe UI"
FONT_ASSETS = (
    "fonts/dm-sans/DMSans-Variable.ttf",
)
OPTICAL_SIZE_AXIS = QFont.Tag("opsz")
WEIGHT_AXIS = QFont.Tag("wght")
MIN_OPTICAL_SIZE = 9.0
MAX_OPTICAL_SIZE = 40.0
GRAYSCALE_ANTIALIASING = (
    QFont.StyleStrategy.PreferAntialias
    | QFont.StyleStrategy.NoSubpixelAntialias
)

_registration_attempted = False
_bundled_fonts_loaded = False
_registered_font_ids: tuple[int, ...] = ()


def register_bundled_fonts() -> bool:
    global _registration_attempted
    global _bundled_fonts_loaded
    global _registered_font_ids

    if _registration_attempted:
        return _bundled_fonts_loaded
    if QGuiApplication.instance() is None:
        return False

    _registration_attempted = True
    font_ids: list[int] = []
    for relative_path in FONT_ASSETS:
        path = Path(asset_path(relative_path))
        font_id = QFontDatabase.addApplicationFont(str(path))
        if font_id < 0:
            for registered_id in font_ids:
                QFontDatabase.removeApplicationFont(registered_id)
            return False
        font_ids.append(font_id)

    _registered_font_ids = tuple(font_ids)
    _bundled_fonts_loaded = True
    return True


def body_family() -> str:
    return BODY_FONT_FAMILY if _bundled_fonts_loaded else FALLBACK_FONT_FAMILY


def emphasis_family() -> str:
    return EMPHASIS_FONT_FAMILY if _bundled_fonts_loaded else FALLBACK_FONT_FAMILY


def _configured_font(family: str, size: int, weight: QFont.Weight) -> QFont:
    result = QFont(family, size, weight)
    result.setKerning(True)
    result.setHintingPreference(QFont.HintingPreference.PreferVerticalHinting)
    result.setStyleStrategy(GRAYSCALE_ANTIALIASING)
    if _bundled_fonts_loaded:
        result.setVariableAxis(
            OPTICAL_SIZE_AXIS,
            min(MAX_OPTICAL_SIZE, max(MIN_OPTICAL_SIZE, float(size))),
        )
        result.setVariableAxis(WEIGHT_AXIS, float(int(weight)))
    return result


def body_font(size: int) -> QFont:
    weight = QFont.Weight.Medium if _bundled_fonts_loaded else QFont.Weight.Normal
    return _configured_font(body_family(), size, weight)


def emphasis_font(size: int) -> QFont:
    return _configured_font(
        emphasis_family(),
        size,
        QFont.Weight.Bold,
    )


def heavy_font(size: int) -> QFont:
    return _configured_font(
        emphasis_family(),
        size,
        QFont.Weight.Black,
    )


def apply_variable_font_axes(root: QWidget) -> None:
    if not _bundled_fonts_loaded:
        return
    for widget in (root, *root.findChildren(QWidget)):
        widget.ensurePolished()
        font = widget.font()
        if QFontInfo(font).family() != BODY_FONT_FAMILY:
            continue
        point_size = font.pointSizeF()
        if point_size <= 0:
            continue
        configured = QFont(font)
        configured.setKerning(True)
        configured.setHintingPreference(
            QFont.HintingPreference.PreferVerticalHinting
        )
        configured.setStyleStrategy(GRAYSCALE_ANTIALIASING)
        configured.setVariableAxis(
            OPTICAL_SIZE_AXIS,
            min(MAX_OPTICAL_SIZE, max(MIN_OPTICAL_SIZE, point_size)),
        )
        configured.setVariableAxis(
            WEIGHT_AXIS,
            float(int(font.weight())),
        )
        widget.setFont(configured)
