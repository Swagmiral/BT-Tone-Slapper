from __future__ import annotations

import ctypes
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QWidget

from .fonts import apply_variable_font_axes, body_font, register_bundled_fonts


COLORS = {
    "window": "#111111",
    "prompt_surface": "#0d0d0d",
    "surface": "#1a1a1a",
    "surface_hover": "#242424",
    "field": "#121212",
    "border": "#303030",
    "text": "#f4f4f4",
    "muted": "#9a9a9a",
    "accent": "#ff5f3a",
    "accent_hover": "#ff7657",
    "accent_pressed": "#e74d2b",
    "danger": "#c63f4b",
    "danger_hover": "#db5360",
    "success": "#2f7d4a",
    "success_hover": "#388f57",
    "success_pressed": "#276b3f",
    "disabled": "#5e5e5e",
    "selection": "#333333",
}


def refresh_style(widget: QWidget) -> None:
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    apply_variable_font_axes(widget)
    widget.update()


def apply_dark_title_bar(widget: QWidget) -> None:
    if sys.platform != "win32":
        return
    try:
        enabled = ctypes.c_int(1)
        hwnd = int(widget.winId())
        for attribute in (20, 19):
            result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd,
                attribute,
                ctypes.byref(enabled),
                ctypes.sizeof(enabled),
            )
            if result == 0:
                break
    except Exception:
        pass


def apply_dark_theme(application: QApplication) -> None:
    register_bundled_fonts()
    application.setStyle("Fusion")
    application.setFont(body_font(10))

    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(COLORS["window"]))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(COLORS["text"]))
    palette.setColor(QPalette.ColorRole.Base, QColor(COLORS["field"]))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(COLORS["surface"]))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#000000"))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.Text, QColor(COLORS["text"]))
    palette.setColor(QPalette.ColorRole.Button, QColor(COLORS["surface_hover"]))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(COLORS["text"]))
    palette.setColor(QPalette.ColorRole.BrightText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(COLORS["accent"]))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    palette.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.Text,
        QColor(COLORS["disabled"]),
    )
    palette.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.ButtonText,
        QColor(COLORS["disabled"]),
    )
    application.setPalette(palette)
    application.setStyleSheet(
        f"""
        QWidget {{
            background: {COLORS["window"]};
            color: {COLORS["text"]};
            selection-background-color: {COLORS["selection"]};
            selection-color: {COLORS["text"]};
        }}

        QMainWindow, QDialog {{
            background: {COLORS["window"]};
        }}

        QFrame#promptPanel, QWidget#promptPanel {{
            background: {COLORS["prompt_surface"]};
            border-radius: 14px;
        }}

        QLabel#promptEmpty {{
            background: transparent;
            color: {COLORS["text"]};
            font-size: 18pt;
            font-weight: 700;
        }}

        QLabel#helpTitle {{
            font-size: 18pt;
            font-weight: 700;
            color: {COLORS["text"]};
        }}

        QLabel#helpHeading {{
            font-size: 14pt;
            font-weight: 700;
            color: {COLORS["text"]};
        }}

        QLabel#helpBody {{
            font-size: 10pt;
            font-weight: 500;
            color: {COLORS["text"]};
        }}

        QLabel#helpBullet {{
            font-size: 10pt;
            font-weight: 700;
            color: {COLORS["accent_hover"]};
        }}

        QLabel#helpLink {{
            font-size: 10pt;
            font-weight: 500;
            color: {COLORS["accent_hover"]};
        }}

        QPushButton {{
            min-height: 42px;
            border: 0;
            border-radius: 0;
            padding: 0 14px;
            background: {COLORS["surface_hover"]};
            color: {COLORS["text"]};
            font-size: 14pt;
            font-weight: 700;
            outline: none;
        }}

        QPushButton:hover {{
            background: #2c2c2c;
        }}

        QPushButton:pressed {{
            background: #121212;
        }}

        QPushButton:disabled {{
            background: #2a2a2a;
            color: {COLORS["disabled"]};
        }}

        QPushButton[available="false"] {{
            background: #2a2a2a;
            color: {COLORS["disabled"]};
        }}

        QPushButton[available="false"]:hover,
        QPushButton[available="false"]:pressed {{
            background: #2a2a2a;
            color: {COLORS["disabled"]};
        }}

        QPushButton[role="accent"] {{
            background: {COLORS["accent"]};
            color: #ffffff;
        }}

        QPushButton[role="accent"]:hover {{
            background: {COLORS["accent_hover"]};
        }}

        QPushButton[role="accent"]:pressed {{
            background: {COLORS["accent_pressed"]};
        }}

        QPushButton[role="success"] {{
            background: {COLORS["success"]};
            color: #ffffff;
        }}

        QPushButton[role="success"]:hover {{
            background: {COLORS["success_hover"]};
        }}

        QPushButton[role="success"]:pressed {{
            background: {COLORS["success_pressed"]};
        }}

        QPushButton[role="ghost"] {{
            background: {COLORS["surface"]};
            color: {COLORS["muted"]};
        }}

        QPushButton[role="ghost"]:hover {{
            background: {COLORS["surface_hover"]};
            color: {COLORS["text"]};
        }}

        QPushButton[role="path"] {{
            min-height: 42px;
            padding: 0 8px;
            background: transparent;
            color: {COLORS["muted"]};
        }}

        QPushButton[role="path"]:hover {{
            background: transparent;
            color: {COLORS["accent_hover"]};
        }}

        QPushButton[role="path"]:pressed {{
            background: transparent;
            color: {COLORS["accent"]};
        }}

        QPushButton[role="path"][available="false"],
        QPushButton[role="path"][available="false"]:hover,
        QPushButton[role="path"][available="false"]:pressed {{
            background: transparent;
            color: {COLORS["disabled"]};
        }}

        QPushButton[role="openProminent"] {{
            min-height: 42px;
            padding: 0 8px;
            background: transparent;
            color: {COLORS["accent_hover"]};
            font-size: 14pt;
            font-weight: 700;
        }}

        QPushButton[role="openProminent"]:hover {{
            background: transparent;
            color: #ffffff;
        }}

        QPushButton[role="openProminent"]:pressed {{
            background: transparent;
            color: {COLORS["accent"]};
        }}

        QPushButton[role="openProminent"]:disabled {{
            background: transparent;
            color: {COLORS["disabled"]};
        }}

        QFrame#orDividerLine {{
            border: 0;
            background: {COLORS["border"]};
        }}

        QLabel#orDividerLabel {{
            background: transparent;
            color: {COLORS["muted"]};
            font-size: 10pt;
            font-weight: 700;
        }}

        QPushButton[role="clearPackage"] {{
            min-height: 42px;
            padding: 0;
            background: transparent;
            color: {COLORS["muted"]};
            font-size: 18pt;
            font-weight: 500;
        }}

        QPushButton[role="clearPackage"]:hover {{
            background: transparent;
            color: #ffffff;
        }}

        QPushButton[role="clearPackage"]:pressed {{
            background: transparent;
            color: {COLORS["accent"]};
        }}

        QPushButton[role="clearPackage"]:disabled {{
            background: transparent;
            color: {COLORS["disabled"]};
        }}

        QPushButton#buildButton,
        QPushButton#scanButton {{
            border-radius: 8px;
        }}

        QPushButton[role="recovery"] {{
            min-height: 30px;
            padding: 0 8px;
            background: transparent;
            color: {COLORS["danger_hover"]};
            font-size: 10pt;
            font-weight: 700;
        }}

        QPushButton[role="recovery"]:hover {{
            background: transparent;
            color: #ffffff;
        }}

        QPushButton[role="recovery"]:pressed {{
            background: transparent;
            color: {COLORS["danger"]};
        }}

        QPushButton[role="recovery"][available="false"],
        QPushButton[role="recovery"][available="false"]:hover,
        QPushButton[role="recovery"][available="false"]:pressed {{
            background: transparent;
            color: {COLORS["disabled"]};
        }}

        QPushButton[role="link"] {{
            min-height: 38px;
            padding: 0 10px;
            background: transparent;
            color: #cccccc;
            font-size: 10pt;
            font-weight: 700;
            text-align: left;
        }}

        QPushButton[role="link"]:hover {{
            background: transparent;
            color: {COLORS["text"]};
        }}

        QPushButton[role="link"]:pressed {{
            background: transparent;
            color: {COLORS["accent_hover"]};
        }}

        QComboBox {{
            min-height: 42px;
            border: 0;
            border-radius: 8px;
            padding: 0 36px 0 12px;
            background: {COLORS["prompt_surface"]};
            color: {COLORS["text"]};
            font-size: 14pt;
            font-weight: 700;
            outline: none;
        }}

        QComboBox:hover {{
            background: {COLORS["prompt_surface"]};
        }}

        QComboBox:disabled {{
            color: {COLORS["disabled"]};
            background: {COLORS["prompt_surface"]};
        }}

        QComboBox::drop-down {{
            width: 32px;
            border: 0;
            background: transparent;
        }}

        QComboBox::down-arrow {{
            image: none;
            width: 9px;
            height: 6px;
        }}

        QComboBox QAbstractItemView {{
            border: 0;
            outline: 0;
            padding: 0;
            background: {COLORS["field"]};
            color: {COLORS["text"]};
            selection-background-color: {COLORS["accent"]};
            selection-color: #ffffff;
        }}

        QTableWidget {{
            border: 0;
            outline: 0;
            gridline-color: transparent;
            background: transparent;
            alternate-background-color: transparent;
            color: {COLORS["text"]};
            font-size: 10pt;
            font-weight: 500;
        }}

        QTableWidget::item {{
            border: 0;
            padding: 0 10px;
        }}

        QTableWidget::item:selected {{
            background: transparent;
            color: {COLORS["text"]};
        }}

        QTableWidget::item:disabled {{
            color: {COLORS["disabled"]};
        }}

        QScrollArea#helpScroll {{
            border: 0;
            background: transparent;
        }}

        QScrollArea#helpScroll > QWidget > QWidget {{
            background: transparent;
        }}

        QHeaderView {{
            background: transparent;
        }}

        QHeaderView::section {{
            min-height: 38px;
            border: 0;
            padding: 0 10px;
            background: transparent;
            color: {COLORS["text"]};
            font-size: 10pt;
            font-weight: 700;
        }}

        QAbstractScrollArea::corner {{
            background: transparent;
        }}

        QScrollBar:vertical {{
            width: 9px;
            margin: 0;
            border: 0;
            background: transparent;
        }}

        QScrollBar::handle:vertical {{
            min-height: 30px;
            border: 0;
            background: #3a3a3a;
        }}

        QScrollBar::handle:vertical:hover {{
            background: #505050;
        }}

        QScrollBar::add-line:vertical,
        QScrollBar::sub-line:vertical,
        QScrollBar::add-page:vertical,
        QScrollBar::sub-page:vertical {{
            height: 0;
            background: transparent;
        }}

        QPlainTextEdit {{
            border: 0;
            padding: 12px;
            background: {COLORS["field"]};
            color: {COLORS["text"]};
            font-size: 10pt;
            font-weight: 500;
            selection-background-color: {COLORS["selection"]};
        }}

        QMessageBox {{
            background: {COLORS["window"]};
        }}

        QToolTip {{
            border: 0;
            padding: 5px 8px;
            background: #000000;
            color: #ffffff;
        }}
        """
    )
    application.setAttribute(Qt.ApplicationAttribute.AA_DontShowIconsInMenus, True)
