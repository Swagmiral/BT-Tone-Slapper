from __future__ import annotations

import os
import re
import sys
import threading
import time
import traceback
import webbrowser
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QBrush,
    QCloseEvent,
    QColor,
    QFontMetrics,
    QIcon,
    QKeySequence,
    QResizeEvent,
    QShortcut,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedLayout,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import APP_AUTHOR, APP_NAME, APP_VERSION, LICENSE_NAME, PROJECT_URL
from .device_profiles import (
    SUPPORTED_PROFILES,
    TUNE_720BT_PROFILE,
    get_device_profile,
    resolve_device_profile,
)
from .errors import user_error_message
from .fonts import apply_variable_font_axes, emphasis_font
from .oem import OEM_GITHUB_MANUAL_URL, OemImage
from .resources import asset_path, bundled_file_path
from .theme import (
    COLORS,
    apply_dark_theme,
    apply_dark_title_bar,
    refresh_style,
)
from .widgets import (
    AdaptiveButtonRow,
    FlyingTip,
    MinimalComboBox,
    ProgressButton,
    PromptTable,
    ResetButton,
    RoundedPanel,
)
from .workflow import BASE_SHA256, BuildResult, ToneSlapperEngine


AUDIO_TYPES = [
    (
        "Common audio",
        "*.wav *.mp3 *.flac *.ogg *.oga *.opus *.m4a *.aac *.wma *.aif *.aiff *.caf",
    ),
    ("Wave audio", "*.wav"),
    ("MP3 audio", "*.mp3"),
    ("FLAC audio", "*.flac"),
    ("Ogg/Opus audio", "*.ogg *.oga *.opus"),
    ("MPEG-4/AAC audio", "*.m4a *.aac"),
    ("All files", "*.*"),
]

DONATE_URL = "https://donatello.to/polymernyk"
SUPPORTED_AUDIO_FORMATS = (
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
)
SUPPORTED_DEVICES = tuple(profile.display_name for profile in SUPPORTED_PROFILES)
WINDOWS_FONT_PLATFORM = "windows:fontengine=freetype"
LEGAL_NOTICE_FILES = (
    ("License", "LICENSE"),
    ("Attribution", "ATTRIBUTION.md"),
    ("Third-party notices", "THIRD_PARTY.md"),
)
CLOSE_BLOCKED_TEXT = (
    "A headphone write or OEM restore is still in progress.\n\n"
    "Do not power off or disconnect the headphones, disable Bluetooth, close the app, "
    "or let the PC sleep. Wait until the Upload button reports Success!"
)


def load_legal_documents() -> dict[str, str]:
    return {
        title: bundled_file_path(filename).read_text(encoding="utf-8")
        for title, filename in LEGAL_NOTICE_FILES
    }


def _qt_parent(parent) -> QWidget | None:
    return parent if isinstance(parent, QWidget) else None


class _MessageBoxAdapter:
    @staticmethod
    def showerror(title: str, message: str, *, parent=None) -> None:
        QMessageBox.critical(_qt_parent(parent), title, message)

    @staticmethod
    def showwarning(title: str, message: str, *, parent=None) -> None:
        QMessageBox.warning(_qt_parent(parent), title, message)

    @staticmethod
    def showinfo(title: str, message: str, *, parent=None) -> None:
        QMessageBox.information(_qt_parent(parent), title, message)

    @staticmethod
    def askyesno(
        title: str,
        message: str,
        *,
        icon: str | None = None,
        parent=None,
    ) -> bool:
        _ = icon
        result = QMessageBox.question(
            _qt_parent(parent),
            title,
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return result == QMessageBox.StandardButton.Yes


class _FileDialogAdapter:
    @staticmethod
    def _filters(filetypes) -> str:
        return ";;".join(f"{label} ({patterns})" for label, patterns in filetypes)

    @classmethod
    def askopenfilename(
        cls,
        *,
        title: str = "",
        filetypes=None,
        parent=None,
        **_options,
    ) -> str:
        selected, _filter = QFileDialog.getOpenFileName(
            _qt_parent(parent),
            title,
            "",
            cls._filters(filetypes or [("All files", "*.*")]),
        )
        return selected

    @classmethod
    def asksaveasfilename(
        cls,
        *,
        title: str = "",
        initialfile: str = "",
        defaultextension: str = "",
        filetypes=None,
        parent=None,
        **_options,
    ) -> str:
        selected, _filter = QFileDialog.getSaveFileName(
            _qt_parent(parent),
            title,
            initialfile,
            cls._filters(filetypes or [("All files", "*.*")]),
        )
        if selected and defaultextension and not Path(selected).suffix:
            selected += defaultextension
        return selected


messagebox = _MessageBoxAdapter()
filedialog = _FileDialogAdapter()


class _StringValue:
    def __init__(
        self,
        value: str = "",
        changed: Callable[[str], None] | None = None,
    ) -> None:
        self._value = value
        self._changed = changed

    def get(self) -> str:
        return self._value

    def set(self, value: str) -> None:
        self._value = str(value)
        if self._changed is not None:
            self._changed(self._value)

    def set_callback(self, changed: Callable[[str], None] | None) -> None:
        self._changed = changed


class _WorkerSignals(QObject):
    completed = Signal(object, object)
    failed = Signal(object)
    progress = Signal(str)


class ToneSlapperWindow(QMainWindow):
    SCAN_TEXT = "Scan for devices"
    BUILD_TEXT = "Build"
    OPEN_TEXT = "Open sound pack…"
    UPLOAD_TEXT = "Upload"
    BUILD_SUCCESS_MS = 3000
    UPLOAD_FINISH_MS = 6000
    UPLOAD_FINISH_INTERVAL_MS = 50

    def __init__(self) -> None:
        super().__init__()
        self.root = self
        self.setWindowTitle(f"{APP_NAME} {APP_VERSION}")
        self.resize(820, 736)
        self.setMinimumSize(680, 700)
        self.setWindowIcon(QIcon(str(asset_path("icons/app_icon.ico"))))

        self.engine = ToneSlapperEngine()
        self.assignments: dict[int, Path] = {}
        self.devices: dict[str, str] = {}
        self.device_models: dict[str, str] = {}
        self.target_model: str | None = None
        self.target_profile_id: str | None = None
        self.build_dirty = False
        self.last_build: BuildResult | None = None
        self.busy = False
        self.active_operation: str | None = None
        self.active_total_packets = 0
        self._build_status_job: QTimer | None = None
        self._upload_finish_job: QTimer | None = None
        self._upload_success_latched = False
        self._hovered_prompt: int | None = None
        self._help_window: QDialog | None = None
        self._legal_window: QDialog | None = None
        self._legal_documents = load_legal_documents()
        self._pending_oem_action: Callable[[OemImage], None] | None = None
        self._oem_context: str | None = None
        self._reset_buttons: dict[int, ResetButton] = {}
        self._force_close = False

        self.device_var = _StringValue()
        self.output_var = _StringValue(self.OPEN_TEXT)
        self._signals = _WorkerSignals(self)
        self._signals.completed.connect(self._finish_success)
        self._signals.failed.connect(self._finish_error)
        self._signals.progress.connect(self._apply_progress)

        self._build_layout()
        self.output_var.set_callback(self._refresh_package_text)
        self.output_var.set(self.OPEN_TEXT)
        self._flying_tip = FlyingTip(self.centralWidget())
        self._help_shortcut = QShortcut(QKeySequence("F1"), self)
        self._help_shortcut.activated.connect(self.show_help)
        self._refresh_prompt_rows()
        self._update_buttons()
        apply_variable_font_axes(self)
        QTimer.singleShot(0, lambda: apply_dark_title_bar(self))

    def after(self, delay: int, callback: Callable, *args) -> QTimer:
        timer = QTimer(self)
        timer.setSingleShot(True)

        def invoke() -> None:
            callback(*args)
            timer.deleteLater()

        timer.timeout.connect(invoke)
        timer.start(delay)
        return timer

    def after_idle(self, callback: Callable, *args) -> QTimer:
        return self.after(0, callback, *args)

    @staticmethod
    def after_cancel(timer: QTimer | None) -> None:
        if timer is not None:
            timer.stop()
            timer.deleteLater()

    def destroy(self) -> None:
        self._force_close = True
        self.close()

    def _set_button_style(
        self,
        button: QPushButton,
        *,
        role: str,
        available: bool = True,
    ) -> None:
        button.setProperty("role", role)
        button.setProperty("available", available)
        refresh_style(button)

    def _build_layout(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(18, 4, 18, 10)
        outer.setSpacing(0)

        device_row = QHBoxLayout()
        device_row.setContentsMargins(14, 8, 14, 8)
        device_row.setSpacing(8)
        self.device_combo = MinimalComboBox(central)
        self.device_combo.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.device_combo.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        self.device_combo.currentTextChanged.connect(self._combo_changed)
        device_row.addWidget(self.device_combo, 1)
        self.scan_button = QPushButton(self.SCAN_TEXT, central)
        self.scan_button.setObjectName("scanButton")
        self.scan_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.scan_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.scan_button.setFixedWidth(218)
        self.scan_button.clicked.connect(self.scan)
        device_row.addWidget(self.scan_button)
        outer.addLayout(device_row)
        outer.addSpacing(12)

        self.prompt_card = RoundedPanel(central, corner_radius=14)
        self.prompt_card.setObjectName("promptPanel")
        self.prompt_card.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        self.prompt_stack = QStackedLayout(self.prompt_card)
        self.prompt_stack.setContentsMargins(0, 0, 0, 0)

        self.prompt_empty_label = QLabel("Select a device first", self.prompt_card)
        self.prompt_empty_label.setObjectName("promptEmpty")
        self.prompt_empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.prompt_empty_label.setFont(emphasis_font(18))
        self.prompt_stack.addWidget(self.prompt_empty_label)

        self.prompt_tree = PromptTable(self.prompt_card)
        self.prompt_tree.setColumnCount(4)
        self.prompt_tree.setHorizontalHeaderLabels(
            ("INDEX", "EVENT", "AUDIO SOURCE", "")
        )
        self.prompt_tree.verticalHeader().hide()
        header = self.prompt_tree.horizontalHeader()
        header.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        header.viewport().setAttribute(
            Qt.WidgetAttribute.WA_TranslucentBackground,
            True,
        )
        header.viewport().setAutoFillBackground(False)
        header.setSectionsClickable(False)
        header.setSectionsMovable(False)
        header.setHighlightSections(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.prompt_tree.setColumnWidth(0, 64)
        self.prompt_tree.setColumnWidth(1, 210)
        self.prompt_tree.setColumnWidth(3, 88)
        self.prompt_tree.setWordWrap(False)
        self.prompt_tree.cellClicked.connect(self._prompt_cell_clicked)
        self.prompt_tree.row_hovered.connect(self._prompt_row_hovered)
        self.prompt_stack.addWidget(self.prompt_tree)
        outer.addWidget(self.prompt_card, 1)

        action_controls = QVBoxLayout()
        action_controls.setContentsMargins(14, 0, 14, 8)
        action_controls.setSpacing(0)

        self.workflow_slot = QWidget(central)
        self.workflow_slot.setFixedHeight(42)
        self.workflow_stack = QStackedLayout(self.workflow_slot)
        self.workflow_stack.setContentsMargins(0, 0, 0, 0)

        self.build_button = QPushButton(self.BUILD_TEXT, self.workflow_slot)
        self.build_button.setObjectName("buildButton")
        self.build_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.build_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.build_button.clicked.connect(self._build_button_pressed)
        self.build_button_row = AdaptiveButtonRow(
            self.build_button,
            self.workflow_slot,
        )
        self.workflow_stack.addWidget(self.build_button_row)

        self.open_divider = QWidget(self.workflow_slot)
        divider_layout = QHBoxLayout(self.open_divider)
        divider_layout.setContentsMargins(0, 0, 0, 0)
        divider_layout.setSpacing(10)
        left_line = QFrame(self.open_divider)
        right_line = QFrame(self.open_divider)
        for line in (left_line, right_line):
            line.setObjectName("orDividerLine")
            line.setFixedHeight(1)
        divider_layout.addWidget(left_line, 1)
        self.open_divider_label = QLabel("OR", self.open_divider)
        self.open_divider_label.setObjectName("orDividerLabel")
        self.open_divider_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        divider_layout.addWidget(self.open_divider_label)
        divider_layout.addWidget(right_line, 1)
        self.workflow_stack.addWidget(self.open_divider)

        action_controls.addWidget(self.workflow_slot)
        action_controls.addSpacing(2)

        self.package_row = QWidget(central)
        package_layout = QHBoxLayout(self.package_row)
        package_layout.setContentsMargins(0, 0, 0, 0)
        package_layout.setSpacing(4)

        self.validate_button = QPushButton(self.OPEN_TEXT, self.package_row)
        self.validate_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.validate_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.validate_button.clicked.connect(self._open_button_pressed)
        self._set_button_style(self.validate_button, role="path", available=False)
        package_layout.addWidget(self.validate_button, 1)

        self.clear_package_button = QPushButton("×", self.package_row)
        self.clear_package_button.setAccessibleName("Unload sound pack")
        self.clear_package_button.setToolTip("Unload sound pack")
        self.clear_package_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.clear_package_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_package_button.setFixedWidth(38)
        self.clear_package_button.clicked.connect(self._clear_loaded_package)
        self._set_button_style(self.clear_package_button, role="clearPackage")
        self.clear_package_button.hide()
        package_layout.addWidget(self.clear_package_button)

        self.package_button_row = AdaptiveButtonRow(
            self.package_row,
            central,
        )
        action_controls.addWidget(self.package_button_row)
        action_controls.addSpacing(32)

        self.upload_button = ProgressButton(self.UPLOAD_TEXT, central)
        self.upload_button.clicked.connect(self._upload_button_pressed)
        self.upload_button_row = AdaptiveButtonRow(
            self.upload_button,
            central,
        )
        self.upload_button.progress_mode_changed.connect(
            self.upload_button_row.set_expanded
        )
        action_controls.addWidget(self.upload_button_row)
        action_controls.addSpacing(16)

        self.recovery_button = QPushButton("Restore OEM English", central)
        self.recovery_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.recovery_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.recovery_button.clicked.connect(self._recovery_button_pressed)
        self._set_button_style(
            self.recovery_button,
            role="recovery",
            available=False,
        )
        self.recovery_button.setSizePolicy(
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Fixed,
        )
        self.recovery_button_row = QWidget(central)
        recovery_layout = QHBoxLayout(self.recovery_button_row)
        recovery_layout.setContentsMargins(0, 0, 0, 0)
        recovery_layout.setSpacing(0)
        recovery_layout.addStretch(1)
        recovery_layout.addWidget(self.recovery_button)
        recovery_layout.addStretch(1)
        action_controls.addWidget(self.recovery_button_row)
        outer.addLayout(action_controls)
        outer.addSpacing(32)

        utility_footer = QHBoxLayout()
        utility_footer.setContentsMargins(14, 0, 14, 0)
        utility_footer.setSpacing(8)
        self.help_button = QPushButton("Help", central)
        self.help_button.setIcon(
            QIcon(str(asset_path("icons/material_help_outline_white_18.png")))
        )
        self.help_button.setIconSize(QSize(18, 18))
        self.help_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.help_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.help_button.clicked.connect(self.show_help)
        self._set_button_style(self.help_button, role="link")
        utility_footer.addWidget(self.help_button)
        utility_footer.addStretch(1)
        self.support_button = QPushButton("Support development", central)
        self.support_button.setIcon(
            QIcon(str(asset_path("icons/material_favorite_white_18.png")))
        )
        self.support_button.setIconSize(QSize(18, 18))
        self.support_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.support_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.support_button.clicked.connect(self.donate)
        self._set_button_style(self.support_button, role="link")
        utility_footer.addWidget(self.support_button)
        outer.addLayout(utility_footer)

    def _dialog_button(
        self,
        text: str,
        callback: Callable,
        *,
        role: str = "",
    ) -> QPushButton:
        button = QPushButton(text)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(callback)
        if role:
            self._set_button_style(button, role=role)
        return button

    def _help_label(
        self,
        text: str,
        *,
        object_name: str,
        wrap: bool = False,
    ) -> QLabel:
        label = QLabel(text)
        label.setObjectName(object_name)
        label.setWordWrap(wrap)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        return label

    def show_help(self) -> None:
        if self._help_window is not None:
            self._help_window.raise_()
            self._help_window.activateWindow()
            return

        dialog = QDialog(self)
        self._help_window = dialog
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        dialog.setWindowTitle(f"{APP_NAME} - Help")
        dialog.setWindowIcon(self.windowIcon())
        dialog.setModal(False)
        dialog.setFixedWidth(560)
        screen = dialog.screen() or QApplication.primaryScreen()
        available_height = screen.availableGeometry().height() if screen else 800
        dialog.resize(560, min(820, max(560, available_height - 80)))
        dialog.finished.connect(lambda _result: setattr(self, "_help_window", None))

        content = QVBoxLayout(dialog)
        content.setContentsMargins(22, 18, 22, 18)
        content.setSpacing(0)
        content.addWidget(
            self._help_label(
                "How to use BT Tone Slapper",
                object_name="helpTitle",
            )
        )
        content.addSpacing(14)

        help_scroll = QScrollArea(dialog)
        help_scroll.setObjectName("helpScroll")
        help_scroll.setFrameShape(QFrame.Shape.NoFrame)
        help_scroll.setWidgetResizable(True)
        help_scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        help_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        help_sections = QWidget(help_scroll)
        sections_layout = QVBoxLayout(help_sections)
        sections_layout.setContentsMargins(0, 0, 8, 0)
        sections_layout.setSpacing(0)

        def add_help_item(widget: QWidget) -> None:
            item_layout = QHBoxLayout()
            item_layout.setContentsMargins(14, 0, 8, 0)
            item_layout.setSpacing(6)
            bullet = self._help_label("•", object_name="helpBullet")
            bullet.setAlignment(
                Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter
            )
            bullet.setFixedWidth(10)
            item_layout.addWidget(bullet)
            item_layout.addWidget(widget, 1)
            sections_layout.addLayout(item_layout)
            sections_layout.addSpacing(6)

        def add_help_text(text: str) -> None:
            body_label = self._help_label(
                text,
                object_name="helpBody",
                wrap=True,
            )
            body_label.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Fixed,
            )
            body_label.setMinimumHeight(body_label.heightForWidth(470))
            add_help_item(body_label)

        sections = (
            (
                "1. Connect",
                (
                    "Connect the headphones to your computer normally.",
                    "In this app click Scan for devices, then select the connected "
                    "headphones if multiple supported devices are connected.",
                ),
            ),
            (
                "2. Choose sounds (optional)",
                (
                    "To create a custom sound pack, assign regular audio files to the "
                    "prompts you want to replace.",
                    "In the list of prompts click a prompt row you want to change and "
                    "choose an audio file.",
                    "Use Reset on that row if you want to return it to OEM English.",
                    f"Supported audio formats: {', '.join(SUPPORTED_AUDIO_FORMATS)}.",
                    "Sample rate, bit depth, and channel count are converted automatically.",
                    "Skip this step when using an existing .BIN sound pack.",
                ),
            ),
            (
                "3. Build or open a sound pack",
                (
                    "If you assigned custom audio, click Build and choose where to save "
                    "the complete .BIN sound pack.",
                    "Alternatively, click Open sound pack to load an existing .BIN "
                    "package directly. Opening a sound pack does not require choosing "
                    "sounds or building.",
                ),
            ),
            (
                "4. Upload",
                (
                    "Keep the headphones powered on and connected.",
                    "Click Upload, review the confirmation, and do not disconnect them "
                    "until the upload finishes.",
                ),
            ),
            (
                "Recovery",
                (
                    "Restore OEM English downloads and verifies the original English "
                    "prompts before uploading them.",
                    "If the manufacturer download fails, the app can use the pinned "
                    "copy from the BT Tone Slapper GitHub repository.",
                ),
            ),
            (
                "Currently supported devices",
                tuple(SUPPORTED_DEVICES),
            ),
        )
        for heading, items in sections:
            sections_layout.addWidget(
                self._help_label(heading, object_name="helpHeading")
            )
            sections_layout.addSpacing(4)
            for item in items:
                add_help_text(item)
            sections_layout.addSpacing(8)

        sections_layout.addWidget(
            self._help_label("About and license", object_name="helpHeading")
        )
        sections_layout.addSpacing(4)
        add_help_text(f"Originally created by {APP_AUTHOR}")
        project_link = QLabel(
            (
                f'<a href="{PROJECT_URL}" '
                f'style="color: {COLORS["accent_hover"]}; text-decoration: none;">'
                f"Original project: {PROJECT_URL}</a>"
            ),
            help_sections,
        )
        project_link.setObjectName("helpLink")
        project_link.setTextFormat(Qt.TextFormat.RichText)
        project_link.setTextInteractionFlags(
            Qt.TextInteractionFlag.LinksAccessibleByMouse
        )
        project_link.setOpenExternalLinks(False)
        project_link.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        project_link.setCursor(Qt.CursorShape.PointingHandCursor)
        project_link.setAccessibleName("Open source repository")
        project_link.linkActivated.connect(
            lambda _url: self.open_source_repository()
        )
        self._help_project_link = project_link
        add_help_item(project_link)
        add_help_text(f"License: {LICENSE_NAME}")
        sections_layout.addSpacing(12)

        help_scroll.setWidget(help_sections)
        content.addWidget(help_scroll, 1)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        actions.addWidget(
            self._dialog_button(
                "Legal notices",
                self.show_legal_notices,
                role="accent",
            )
        )
        actions.addWidget(self._dialog_button("Close", dialog.close))
        content.addSpacing(12)
        content.addLayout(actions)

        apply_variable_font_axes(dialog)
        dialog.show()
        QTimer.singleShot(0, lambda: apply_dark_title_bar(dialog))

    def _close_help(self) -> None:
        if self._help_window is not None:
            self._help_window.close()

    def show_legal_notices(self) -> None:
        if self._legal_window is not None:
            self._legal_window.raise_()
            self._legal_window.activateWindow()
            return

        dialog = QDialog(self)
        self._legal_window = dialog
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        dialog.setWindowTitle(f"{APP_NAME} - Legal Notices")
        dialog.setWindowIcon(self.windowIcon())
        dialog.setMinimumSize(620, 450)
        dialog.resize(720, 600)
        dialog.finished.connect(lambda _result: setattr(self, "_legal_window", None))

        content = QVBoxLayout(dialog)
        content.setContentsMargins(22, 18, 22, 18)
        content.setSpacing(0)
        content.addWidget(self._help_label("Legal Notices", object_name="helpTitle"))
        content.addSpacing(8)
        content.addWidget(
            self._help_label(
                f"Copyright (C) 2026 {APP_AUTHOR}\n"
                f"Licensed under {LICENSE_NAME}.\n"
                "This program comes with absolutely no warranty. You may redistribute "
                "and modify it under the terms shown here.",
                object_name="helpBody",
                wrap=True,
            )
        )
        source_button = self._dialog_button(
            f"Open source repository  ·  {PROJECT_URL}",
            self.open_source_repository,
            role="link",
        )
        content.addWidget(source_button, 0, Qt.AlignmentFlag.AlignLeft)
        content.addSpacing(8)

        selector = QHBoxLayout()
        selector.setSpacing(6)
        document_buttons: dict[str, QPushButton] = {}
        for title, _filename in LEGAL_NOTICE_FILES:
            button = self._dialog_button(title, lambda: None)
            selector.addWidget(button)
            document_buttons[title] = button
        content.addLayout(selector)
        content.addSpacing(8)

        document_text = QPlainTextEdit(dialog)
        document_text.setReadOnly(True)
        document_text.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        content.addWidget(document_text, 1)
        content.addSpacing(12)
        content.addWidget(self._dialog_button("Close", dialog.close))

        def show_document(title: str) -> None:
            document_text.setPlainText(self._legal_documents[title])
            document_text.verticalScrollBar().setValue(0)
            for button_title, button in document_buttons.items():
                self._set_button_style(
                    button,
                    role="accent" if button_title == title else "",
                )

        for title, button in document_buttons.items():
            button.clicked.disconnect()
            button.clicked.connect(
                lambda _checked=False, document_title=title: show_document(
                    document_title
                )
            )

        self._legal_text = document_text
        self._legal_buttons = document_buttons
        show_document("License")
        apply_variable_font_axes(dialog)
        dialog.show()
        QTimer.singleShot(0, lambda: apply_dark_title_bar(dialog))

    def _close_legal_notices(self) -> None:
        if self._legal_window is not None:
            self._legal_window.close()

    def open_source_repository(self) -> None:
        try:
            opened = webbrowser.open(PROJECT_URL, new=2)
        except Exception:
            opened = False
        if not opened:
            messagebox.showerror(
                APP_NAME,
                f"Could not open the source repository. Visit:\n\n{PROJECT_URL}",
                parent=self._legal_window or self.root,
            )

    def _close_is_blocked(self) -> bool:
        if self.active_operation in {"upload", "recovery"}:
            return True
        return (
            self.busy
            and self._oem_context == "restore"
            and bool(self.active_operation and self.active_operation.startswith("oem-"))
        )

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._force_close:
            event.accept()
            return
        if self._close_is_blocked():
            messagebox.showwarning(
                APP_NAME,
                CLOSE_BLOCKED_TEXT,
                parent=self,
            )
            event.ignore()
            return
        event.accept()

    def _request_close(self) -> None:
        if self._close_is_blocked():
            messagebox.showwarning(
                APP_NAME,
                CLOSE_BLOCKED_TEXT,
                parent=self.root,
            )
            return
        self.root.destroy()

    def donate(self) -> None:
        try:
            opened = webbrowser.open(DONATE_URL, new=2)
        except Exception:
            opened = False
        if not opened:
            messagebox.showerror(
                APP_NAME,
                f"Could not open the donation page. Visit:\n\n{DONATE_URL}",
                parent=self,
            )

    def _build_button_pressed(self) -> None:
        if self.busy:
            return
        if self.target_profile_id is None:
            self._show_flying_tip(self.build_button, "select target device")
            return
        if not self.assignments:
            self._show_flying_tip(self.build_button, "choose a sound first")
            return
        self.build()

    def _open_button_pressed(self) -> None:
        if self.busy:
            return
        if self.target_profile_id is None:
            self._show_flying_tip(self.validate_button, "select target device")
            return
        self.open_existing()

    def _clear_loaded_package(self) -> None:
        if self.busy or self.last_build is None:
            return
        self._invalidate_build()

    def _upload_button_pressed(self) -> None:
        if self.busy:
            return
        if self.last_build is None:
            self._show_flying_tip(self.upload_button, "build or open first")
            return
        if self._device_identifier() is None or self._selected_profile_id() is None:
            self._show_flying_tip(self.upload_button, "select connected device")
            return
        self.upload()

    def _recovery_button_pressed(self) -> None:
        if self.busy:
            return
        if self._device_identifier() is None or self._selected_profile_id() is None:
            self._show_flying_tip(self.recovery_button, "select connected device")
            return
        self.restore()

    def _show_flying_tip(self, anchor: QWidget, text: str) -> None:
        self._flying_tip.show_for(anchor, text)

    def _dismiss_flying_tip(self) -> None:
        self._flying_tip.dismiss()

    def _truncate_path(self, path: Path) -> str:
        width = max(100, self.prompt_tree.columnWidth(2) - 22)
        metrics = QFontMetrics(self.prompt_tree.font())
        return metrics.elidedText(
            str(path),
            Qt.TextElideMode.ElideLeft,
            width,
        )

    def _refresh_package_text(self, value: str | None = None) -> None:
        text = self.output_var.get() if value is None else value
        loaded_path = (
            str(self.last_build.output)
            if self.last_build is not None
            else None
        )
        if loaded_path is not None and text == loaded_path:
            width = max(100, self.validate_button.width() - 20)
            metrics = QFontMetrics(self.validate_button.font())
            self.validate_button.setText(
                metrics.elidedText(
                    text,
                    Qt.TextElideMode.ElideMiddle,
                    width,
                )
            )
            self.validate_button.setToolTip(text)
            return
        self.validate_button.setText(text)
        self.validate_button.setToolTip("")

    def _prompt_item(
        self,
        text: str,
        alignment: Qt.AlignmentFlag,
    ) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        item.setTextAlignment(alignment)
        item.setFlags(
            Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemNeverHasChildren
        )
        return item

    def _refresh_prompt_rows(self) -> None:
        self._hovered_prompt = None
        self._reset_buttons.clear()
        prompt_labels = self._prompt_labels()
        self.prompt_tree.clearContents()
        self.prompt_tree.setRowCount(0)
        if not prompt_labels:
            self.prompt_stack.setCurrentWidget(self.prompt_empty_label)
            return

        self.prompt_tree.setRowCount(len(prompt_labels))
        self.prompt_stack.setCurrentWidget(self.prompt_tree)
        for index, label in enumerate(prompt_labels):
            self.prompt_tree.setRowHeight(index, 30)
            self.prompt_tree.setItem(
                index,
                0,
                self._prompt_item(
                    f"{index:02d}",
                    Qt.AlignmentFlag.AlignCenter,
                ),
            )
            self.prompt_tree.setItem(
                index,
                1,
                self._prompt_item(
                    label,
                    Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                ),
            )
            source = self.assignments.get(index)
            source_item = self._prompt_item(
                self._truncate_path(source) if source is not None else "OEM English",
                (
                    Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
                    if source is not None
                    else Qt.AlignmentFlag.AlignCenter
                ),
            )
            if source is not None:
                source_item.setToolTip(str(source))
            self.prompt_tree.setItem(index, 2, source_item)
            reset_item = self._prompt_item("", Qt.AlignmentFlag.AlignCenter)
            self.prompt_tree.setItem(index, 3, reset_item)
            if source is not None:
                reset_button = ResetButton(self.prompt_tree)
                reset_button.clicked.connect(
                    lambda _checked=False, prompt_index=index: self._reset_prompt(
                        prompt_index
                    )
                )
                reset_button.hovered.connect(
                    lambda hovered, prompt_index=index: self._set_prompt_hover(
                        prompt_index if hovered else None
                    )
                )
                self.prompt_tree.setCellWidget(index, 3, reset_button)
                self._reset_buttons[index] = reset_button
            self._refresh_prompt_row_style(index)

    def _refresh_source_texts(self) -> None:
        for index, path in self.assignments.items():
            item = self.prompt_tree.item(index, 2)
            if item is not None:
                item.setText(self._truncate_path(path))

    def _prompt_row_hovered(self, row: int) -> None:
        self._set_prompt_hover(row if row >= 0 else None)

    def _prompt_cell_clicked(self, row: int, column: int) -> None:
        if self.busy or self.target_profile_id is None:
            return
        if column == 3 and row in self.assignments:
            self._reset_prompt(row)
            return
        self._choose_audio_for(row)

    def _refresh_prompt_row_style(self, index: int) -> None:
        hovered = not self.busy and index == self._hovered_prompt
        background = (
            QColor(COLORS["surface_hover"])
            if hovered
            else QColor(0, 0, 0, 0)
        )
        for column in range(self.prompt_tree.columnCount()):
            item = self.prompt_tree.item(index, column)
            if item is None:
                continue
            item.setBackground(QBrush(background))
            if self.busy:
                foreground = COLORS["disabled"]
            elif column == 2 and index in self.assignments:
                foreground = "#ffad98"
            else:
                foreground = COLORS["text"]
            item.setForeground(QBrush(QColor(foreground)))
        reset_button = self._reset_buttons.get(index)
        if reset_button is not None:
            reset_button.set_row_hover(hovered)
            reset_button.set_enabled(not self.busy)

    def _set_prompt_hover(self, index: int | None) -> None:
        if self.busy:
            index = None
        if index == self._hovered_prompt:
            return
        previous = self._hovered_prompt
        self._hovered_prompt = index
        for prompt_index in (previous, index):
            if prompt_index is not None and 0 <= prompt_index < self.prompt_tree.rowCount():
                self._refresh_prompt_row_style(prompt_index)

    def _choose_audio_for(self, index: int) -> None:
        prompt_labels = self._prompt_labels()
        if not 0 <= index < len(prompt_labels):
            return
        selected = filedialog.askopenfilename(
            parent=self,
            title=f"Audio for {prompt_labels[index]}",
            filetypes=AUDIO_TYPES,
        )
        if selected:
            if Path(selected).suffix.casefold() == ".bin":
                messagebox.showerror(
                    APP_NAME,
                    "The audio source must be a regular audio file. To open a complete "
                    "sound-pack .BIN file, use Open sound pack below the prompt list.",
                    parent=self,
                )
                return
            self.assignments[index] = Path(selected)
            self._invalidate_build()
            self._refresh_prompt_rows()

    def _reset_prompt(self, index: int) -> None:
        if index in self.assignments:
            del self.assignments[index]
            self._invalidate_build()
            self._refresh_prompt_rows()

    def _invalidate_build(self) -> None:
        self._reset_upload_success()
        if self._build_status_job is not None:
            self.root.after_cancel(self._build_status_job)
            self._build_status_job = None
            self.build_button.setText(self.BUILD_TEXT)
        self.last_build = None
        self.build_dirty = True
        self.output_var.set(self.OPEN_TEXT)
        self._update_buttons()

    def _combo_changed(self, display: str) -> None:
        self.device_var.set(display)
        if display:
            self._device_selected()
        else:
            self._update_buttons()

    def _device_selected(self, _event=None) -> None:
        self._reset_upload_success()
        display = self.device_var.get()
        model = self.device_models.get(display)
        profile = resolve_device_profile(model)
        if profile is None:
            self._update_buttons()
            return
        if profile.profile_id != self.target_profile_id:
            self.assignments.clear()
            self.target_profile_id = profile.profile_id
            self.target_model = profile.display_name
            self._refresh_prompt_rows()
            self._invalidate_build()
            return
        self._update_buttons()

    def _prompt_labels(self) -> tuple[str, ...]:
        profile = get_device_profile(self.target_profile_id)
        return profile.prompt_labels if profile is not None else ()

    def _run_background(
        self,
        operation_name: str,
        operation,
        success,
        *,
        total_packets: int = 0,
    ) -> None:
        if self.busy:
            return
        self._reset_upload_success()
        if operation_name == "build" and self._build_status_job is not None:
            self.root.after_cancel(self._build_status_job)
            self._build_status_job = None
        self.busy = True
        self.active_operation = operation_name
        self.active_total_packets = total_packets
        if operation_name == "scan":
            self.scan_button.setText("Scanning…")
        elif operation_name == "build":
            self.build_button.setText("Preparing audio…")
        elif operation_name == "open":
            self.output_var.set("Opening and validating…")
        elif operation_name.startswith("oem-"):
            if self._oem_context == "build":
                self.build_button.setText("Downloading OEM…")
            else:
                self.upload_button.begin("Downloading OEM…")
        elif operation_name in {"upload", "recovery"}:
            self.upload_button.begin("Verifying headphones…")
        self._update_buttons()

        def worker() -> None:
            try:
                result = operation()
            except Exception as error:
                traceback.print_exc()
                self._signals.failed.emit(error)
            else:
                self._signals.completed.emit(result, success)

        threading.Thread(target=worker, daemon=True).start()

    def _finish_error(self, error: Exception) -> None:
        operation_name = self.active_operation or ""
        detail = user_error_message(operation_name, error)
        if operation_name.startswith("oem-"):
            self._reset_operation_ui()
            if operation_name == "oem-official":
                self.root.after_idle(lambda: self._offer_github_oem(detail))
            else:
                self.root.after_idle(lambda: self._show_manual_oem_recovery(detail))
            return
        if operation_name in {"upload", "recovery"}:
            self.upload_button.set_progress(1.0, "Upload failed")
        messagebox.showerror(APP_NAME, detail, parent=self)
        self._reset_operation_ui()

    def _finish_success(self, result, callback) -> None:
        operation_name = self.active_operation
        callback(result)
        if operation_name in {"upload", "recovery"}:
            return
        self._reset_operation_ui()

    def _reset_operation_ui(self, *, preserve_upload_status: bool = False) -> None:
        self.busy = False
        self.active_operation = None
        self.active_total_packets = 0
        self.scan_button.setText(self.SCAN_TEXT)
        self.build_button.setText(self.BUILD_TEXT)
        self.output_var.set(
            str(self.last_build.output) if self.last_build else self.OPEN_TEXT
        )
        if not preserve_upload_status:
            self.upload_button.reset(enabled=False)
        self._update_buttons()

    def _reset_upload_success(self) -> None:
        if not self._upload_success_latched:
            return
        self._upload_success_latched = False
        self.upload_button.reset(enabled=False)

    def _thread_progress(self, message: str) -> None:
        self._signals.progress.emit(message)

    def _apply_progress(self, message: str) -> None:
        if self.active_operation == "build":
            if message.startswith("Saving verified OEM"):
                self.build_button.setText("Saving OEM container…")
            elif message.startswith("Converting prompt"):
                self.build_button.setText("Converting audio…")
            elif message.startswith("Rebuilding"):
                self.build_button.setText("Building container…")
            elif message.startswith("Container validated"):
                self.build_button.setText("Validated")
            return
        if self.active_operation not in {"upload", "recovery"}:
            return
        if message.startswith("Connecting and verifying"):
            self.upload_button.set_progress(0.03, "Verifying headphones…")
            return
        packet_match = re.match(r"Uploading packet (\d+)$", message)
        if packet_match and self.active_total_packets:
            packet = int(packet_match.group(1))
            fraction = 0.05 + 0.88 * min(1.0, packet / self.active_total_packets)
            verb = "Restoring OEM" if self.active_operation == "recovery" else "Uploading"
            self.upload_button.set_progress(
                fraction,
                f"{verb}  {packet} / {self.active_total_packets}",
            )
        elif message.startswith("Applying image"):
            self.upload_button.set_progress(0.96, "Applying and verifying…")
        elif message.startswith("Device accepted image"):
            self.upload_button.set_progress(0.96, "Finishing…")

    def scan(self) -> None:
        self._run_background("scan", self.engine.scan, self._scan_complete)

    def _scan_complete(self, devices) -> None:
        self.devices.clear()
        self.device_models.clear()
        values = []
        for device in devices:
            model = device.name or "Unknown"
            if resolve_device_profile(model) is None:
                continue
            display = model
            duplicate_number = 2
            while display in self.devices:
                display = f"{model} ({duplicate_number})"
                duplicate_number += 1
            values.append(display)
            self.devices[display] = device.address
            self.device_models[display] = model

        self.device_combo.blockSignals(True)
        self.device_combo.clear()
        self.device_combo.addItems(values)
        self.device_combo.blockSignals(False)
        display = values[0] if values else ""
        self.device_var.set(display)
        if display:
            self.device_combo.setCurrentText(display)
            self._device_selected()
        else:
            self._update_buttons()
            messagebox.showinfo(
                APP_NAME,
                f"No connected {TUNE_720BT_PROFILE.display_name} was found.",
                parent=self,
            )

    def _acquire_oem(
        self,
        context: str,
        ready: Callable[[OemImage], None],
        *,
        always_download: bool,
    ) -> None:
        if self.busy:
            return
        if not always_download:
            cached = self.engine.cached_oem()
            if cached is not None:
                ready(cached)
                return
        self._pending_oem_action = ready
        self._oem_context = context
        self._run_background(
            "oem-official",
            self.engine.download_official_oem,
            self._oem_acquired,
        )

    def _oem_acquired(self, image: OemImage) -> None:
        ready = self._pending_oem_action
        self._pending_oem_action = None
        self._oem_context = None
        if ready is not None:
            self.root.after_idle(lambda: ready(image))

    def _clear_oem_acquisition(self) -> None:
        self._pending_oem_action = None
        self._oem_context = None

    def _offer_github_oem(self, detail: str) -> None:
        choice = self._ask_oem_action(
            "OEM download failed",
            f"{detail}\n\n"
            "Download the pinned OEM recovery file from the BT Tone Slapper "
            "GitHub repository instead?",
            "Download from GitHub",
        )
        if choice != "continue":
            self._clear_oem_acquisition()
            return
        self._run_background(
            "oem-github",
            self.engine.download_github_oem,
            self._oem_acquired,
        )

    def _ask_oem_action(
        self,
        title: str,
        message: str,
        continue_text: str,
    ) -> str | None:
        dialog = QDialog(self)
        dialog.setWindowTitle(f"{APP_NAME} - {title}")
        dialog.setWindowIcon(self.windowIcon())
        dialog.setModal(True)
        dialog.setFixedWidth(550)
        result: dict[str, str | None] = {"value": None}

        content = QVBoxLayout(dialog)
        content.setContentsMargins(22, 18, 22, 18)
        content.setSpacing(0)
        content.addWidget(self._help_label(title, object_name="helpTitle"))
        content.addSpacing(12)
        content.addWidget(
            self._help_label(
                message,
                object_name="helpBody",
                wrap=True,
            )
        )
        content.addSpacing(18)
        buttons = QHBoxLayout()
        buttons.addStretch(1)

        def close(value: str | None = None) -> None:
            result["value"] = value
            dialog.accept() if value else dialog.reject()

        buttons.addWidget(
            self._dialog_button(
                continue_text,
                lambda: close("continue"),
                role="accent",
            )
        )
        buttons.addWidget(
            self._dialog_button(
                "Cancel",
                lambda: close(),
                role="ghost",
            )
        )
        content.addLayout(buttons)
        apply_variable_font_axes(dialog)
        QTimer.singleShot(0, lambda: apply_dark_title_bar(dialog))
        dialog.exec()
        return result["value"]

    def _show_manual_oem_recovery(self, detail: str) -> None:
        selected: dict[str, Path | None] = {"path": None}
        dialog = QDialog(self)
        dialog.setWindowTitle(f"{APP_NAME} - Manual OEM recovery")
        dialog.setWindowIcon(self.windowIcon())
        dialog.setModal(True)
        dialog.setFixedWidth(570)

        def open_github() -> None:
            try:
                opened = webbrowser.open(OEM_GITHUB_MANUAL_URL, new=2)
            except Exception:
                opened = False
            if not opened:
                messagebox.showerror(
                    APP_NAME,
                    f"Could not open GitHub. Visit:\n\n{OEM_GITHUB_MANUAL_URL}",
                    parent=dialog,
                )

        def select_file() -> None:
            chosen = filedialog.askopenfilename(
                parent=dialog,
                title="Select the downloaded OEM file",
                filetypes=[
                    ("OEM prompt container", "*.bin"),
                    ("All files", "*.*"),
                ],
            )
            if chosen:
                selected["path"] = Path(chosen)
                dialog.accept()

        content = QVBoxLayout(dialog)
        content.setContentsMargins(22, 18, 22, 18)
        content.setSpacing(0)
        content.addWidget(
            self._help_label(
                "Automatic OEM download failed",
                object_name="helpTitle",
            )
        )
        content.addSpacing(12)
        content.addWidget(
            self._help_label(
                f"{detail}\n\n"
                "Download the OEM file manually from the BT Tone Slapper GitHub "
                "repository, then select the downloaded file.",
                object_name="helpBody",
                wrap=True,
            )
        )
        content.addSpacing(18)
        buttons = QHBoxLayout()
        buttons.addWidget(self._dialog_button("Open GitHub", open_github))
        buttons.addStretch(1)
        buttons.addWidget(
            self._dialog_button(
                "Select downloaded file",
                select_file,
                role="accent",
            )
        )
        buttons.addWidget(
            self._dialog_button(
                "Cancel",
                dialog.reject,
                role="ghost",
            )
        )
        content.addLayout(buttons)
        apply_variable_font_axes(dialog)
        QTimer.singleShot(0, lambda: apply_dark_title_bar(dialog))
        dialog.exec()

        chosen_path = selected["path"]
        if chosen_path is None:
            self._clear_oem_acquisition()
            return
        self._run_background(
            "oem-manual",
            lambda: self.engine.import_manual_oem(chosen_path),
            self._oem_acquired,
        )

    def build(self) -> None:
        if self.target_profile_id is None:
            self._show_flying_tip(self.build_button, "select target device")
            return
        if not self.assignments:
            self._show_flying_tip(self.build_button, "choose a sound first")
            return
        self._acquire_oem(
            "build",
            self._build_with_oem,
            always_download=False,
        )

    def _build_with_oem(self, oem_image: OemImage) -> None:
        output = filedialog.asksaveasfilename(
            parent=self,
            title="Save generated tone container",
            defaultextension=".bin",
            initialfile=(
                "English_prompt_custom.bin"
                if self.assignments
                else "English_prompt_OEM.bin"
            ),
            filetypes=[("Tone container", "*.bin")],
            confirmoverwrite=True,
        )
        if not output:
            return
        output_path = Path(output)
        assignments = dict(self.assignments)
        self._run_background(
            "build",
            lambda: self.engine.build(
                assignments,
                output_path,
                profile_id=self.target_profile_id,
                base_image=oem_image.path,
                expected_base_sha256=oem_image.sha256,
                progress=self._thread_progress,
            ),
            self._build_complete,
        )

    def _build_complete(self, result: BuildResult) -> None:
        self.last_build = result
        self.build_dirty = False
        self.output_var.set(str(result.output))
        self.root.after_idle(self._show_build_success)

    def _show_build_success(self) -> None:
        self.build_button.setText("Build successful")
        self._set_button_style(self.build_button, role="success")
        self._build_status_job = self.root.after(
            self.BUILD_SUCCESS_MS,
            self._restore_build_text,
        )

    def _restore_build_text(self) -> None:
        self._build_status_job = None
        if self.active_operation != "build":
            self.build_button.setText(self.BUILD_TEXT)
            self._update_buttons()

    def open_existing(self) -> None:
        profile_id = self.target_profile_id
        if profile_id is None:
            self._show_flying_tip(self.validate_button, "select target device")
            return
        selected = filedialog.askopenfilename(
            parent=self,
            filetypes=[
                ("Tone container", "*.bin"),
                ("All files", "*.*"),
            ],
        )
        if not selected:
            return
        path = Path(selected)
        self._invalidate_build()
        self._run_background(
            "open",
            lambda: self.engine.open_existing(path, profile_id=profile_id),
            self._existing_opened,
        )

    def _existing_opened(self, result: BuildResult) -> None:
        self.last_build = result
        self.build_dirty = False
        self.output_var.set(str(result.output))

    def _device_identifier(self) -> str | None:
        return self.devices.get(self.device_var.get())

    def _selected_profile_id(self) -> str | None:
        model = self.device_models.get(self.device_var.get())
        profile = resolve_device_profile(model)
        return profile.profile_id if profile is not None else None

    def upload(self) -> None:
        identifier = self._device_identifier()
        device_profile_id = self._selected_profile_id()
        if not identifier or device_profile_id is None or self.last_build is None:
            return
        if self.last_build.profile_id != device_profile_id:
            messagebox.showerror(
                APP_NAME,
                "The loaded prompt file targets a different headphone model. "
                "Rebuild or open a compatible file before uploading.",
                parent=self,
            )
            return
        candidate = Path(self.last_build.output)
        confirmation = (
            "Write the selected prompt container to the headphones?\n\n"
            f"Device: {self.device_var.get()}\n"
            f"File: {candidate.name}\n"
            f"SHA-256: {self.last_build.sha256}\n\n"
            "This modifies prompt data stored on the headphones. An interrupted or "
            "incompatible write may leave voice prompts unavailable and require OEM recovery.\n\n"
            "Verify the device model and file before continuing. Once writing starts, do not "
            "close the app, power off or disconnect the headphones, disable Bluetooth, or let "
            "the PC sleep. Wait until the Upload button reports Success!\n\n"
            "If the upload fails, reconnect and rescan the headphones, then use Restore OEM "
            "English to write the verified recovery image."
        )
        if not messagebox.askyesno(
            APP_NAME,
            confirmation,
            icon="warning",
            parent=self,
        ):
            return
        expected_hash = self.last_build.sha256
        self._run_background(
            "upload",
            lambda: self.engine.upload_generated(
                identifier,
                candidate,
                expected_hash,
                file_profile_id=self.last_build.profile_id,
                device_profile_id=device_profile_id,
                progress=self._thread_progress,
            ),
            self._upload_complete,
            total_packets=int(self.last_build.dry_run["packet_count"]),
        )

    def restore(self) -> None:
        identifier = self._device_identifier()
        device_profile_id = self._selected_profile_id()
        if not identifier or device_profile_id is None:
            return
        confirmation = (
            "Write the verified OEM English recovery image to the headphones?\n\n"
            f"Device: {self.device_var.get()}\n"
            f"Recovery SHA-256: {BASE_SHA256}\n\n"
            "The OEM file will be downloaded and cryptographically verified before writing. "
            "Once writing starts, do not close the app, power off or disconnect the headphones, "
            "disable Bluetooth, or let the PC sleep. Wait until the Upload button reports "
            "Success!\n\n"
            "Interrupting recovery may leave voice prompts unavailable and require another OEM "
            "restore attempt."
        )
        if not messagebox.askyesno(
            APP_NAME,
            confirmation,
            icon="warning",
            parent=self,
        ):
            return
        self._acquire_oem(
            "restore",
            lambda image: self._restore_with_oem(
                identifier,
                device_profile_id,
                image,
            ),
            always_download=True,
        )

    def _restore_with_oem(
        self,
        identifier: str,
        device_profile_id: str,
        oem_image: OemImage,
    ) -> None:
        self._run_background(
            "recovery",
            lambda: self.engine.restore_oem(
                identifier,
                oem_image,
                device_profile_id=device_profile_id,
                progress=self._thread_progress,
            ),
            self._upload_complete,
            total_packets=oem_image.packet_count,
        )

    def _upload_complete(self, _result) -> None:
        self._remove_uploaded_device_from_scan()
        self.upload_button.set_progress(0.96, "Finishing…")
        started_at = time.monotonic()

        def finish() -> None:
            self._upload_finish_job = None
            elapsed = (time.monotonic() - started_at) * 1000
            progress = min(1.0, elapsed / self.UPLOAD_FINISH_MS)
            fraction = 0.96 + 0.04 * progress
            self.upload_button.set_progress(fraction, "Finishing…")
            if progress >= 1.0:
                self._upload_success_latched = True
                self.upload_button.complete()
                self._reset_operation_ui(preserve_upload_status=True)
                return
            self._upload_finish_job = self.root.after(
                self.UPLOAD_FINISH_INTERVAL_MS,
                finish,
            )

        finish()

    def _remove_uploaded_device_from_scan(self) -> None:
        display = self.device_var.get()
        if not display:
            return
        self.devices.pop(display, None)
        self.device_models.pop(display, None)
        values = tuple(self.devices)
        self.device_combo.blockSignals(True)
        self.device_combo.clear()
        self.device_combo.addItems(values)
        self.device_combo.setCurrentIndex(-1)
        self.device_combo.blockSignals(False)
        self.device_var.set("")
        self._update_buttons()

    def _update_buttons(self) -> None:
        if self.busy:
            self._set_prompt_hover(None)

        self.device_combo.setEnabled(not self.busy)
        self.scan_button.setEnabled(not self.busy)
        self._set_button_style(
            self.scan_button,
            role="" if self.devices else "accent",
        )

        build_available = (
            self.target_profile_id is not None
            and bool(self.assignments)
        )
        self.workflow_slot.setVisible(self.target_profile_id is not None)
        self.workflow_stack.setCurrentWidget(
            self.build_button_row
            if build_available
            else self.open_divider
        )
        self.build_button.setEnabled(not self.busy)
        self.build_button.setProperty("available", build_available)
        self._set_button_style(
            self.build_button,
            role="accent" if build_available and self.build_dirty else "",
            available=build_available,
        )

        open_available = self.target_profile_id is not None
        open_prominent = (
            open_available
            and not self.assignments
            and self.last_build is None
        )
        self.validate_button.setEnabled(not self.busy)
        self._set_button_style(
            self.validate_button,
            role="openProminent" if open_prominent else "path",
            available=open_available,
        )
        self.clear_package_button.setVisible(self.last_build is not None)
        self.clear_package_button.setEnabled(not self.busy)
        self._refresh_package_text()

        selected_profile_id = self._selected_profile_id()
        has_device = (
            self._device_identifier() is not None and selected_profile_id is not None
        )
        loaded_profile_matches = (
            self.last_build is not None
            and self.last_build.profile_id == selected_profile_id
        )
        self.upload_button.set_enabled(not self.busy)
        self.upload_button.set_available(
            has_device and loaded_profile_matches
        )

        self.recovery_button.setEnabled(not self.busy)
        self._set_button_style(
            self.recovery_button,
            role="recovery",
            available=has_device,
        )

        self.prompt_tree.viewport().setCursor(
            Qt.CursorShape.ArrowCursor
            if self.busy
            else Qt.CursorShape.PointingHandCursor
        )
        for index in range(self.prompt_tree.rowCount()):
            self._refresh_prompt_row_style(index)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if hasattr(self, "prompt_tree"):
            QTimer.singleShot(0, self._refresh_source_texts)
        if hasattr(self, "validate_button"):
            QTimer.singleShot(0, self._refresh_package_text)


def create_application(argv: list[str] | None = None) -> QApplication:
    if sys.platform == "win32" and "QT_QPA_PLATFORM" not in os.environ:
        os.environ["QT_QPA_PLATFORM"] = WINDOWS_FONT_PLATFORM
    application = QApplication.instance()
    if application is None:
        application = QApplication(argv if argv is not None else sys.argv)
    application.setApplicationName(APP_NAME)
    application.setApplicationVersion(APP_VERSION)
    apply_dark_theme(application)
    return application


def main() -> int:
    application = create_application()
    try:
        window = ToneSlapperWindow()
    except Exception as error:
        traceback.print_exc()
        messagebox.showerror(APP_NAME, user_error_message("startup", error))
        return 1
    window.show()
    return application.exec()
