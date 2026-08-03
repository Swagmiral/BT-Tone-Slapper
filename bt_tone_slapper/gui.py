from __future__ import annotations

import re
import threading
import time
import traceback
import webbrowser
from pathlib import Path
from typing import Callable
from tkinter import (
    BOTH,
    Canvas,
    LEFT,
    RIGHT,
    X,
    Y,
    StringVar,
    Tk,
    Toplevel,
    PhotoImage,
    Text,
    filedialog,
    font,
    messagebox,
)
from tkinter import ttk

from . import APP_AUTHOR, APP_NAME, APP_VERSION, LICENSE_NAME, PROJECT_URL
from .device_profiles import (
    SUPPORTED_PROFILES,
    TUNE_720BT_PROFILE,
    get_device_profile,
    resolve_device_profile,
)
from .errors import user_error_message
from .oem import OEM_GITHUB_MANUAL_URL, OemImage
from .resources import asset_path, bundled_file_path
from .theme import COLORS, apply_dark_theme, apply_dark_title_bar
from .widgets import ProgressButton, ResetButton
from .workflow import BASE_SHA256, BuildResult, ToneSlapperEngine


AUDIO_TYPES = [
    ("Common audio", "*.wav *.mp3 *.flac *.ogg *.oga *.opus *.m4a *.aac *.wma *.aif *.aiff *.caf"),
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
LEGAL_NOTICE_FILES = (
    ("License", "LICENSE"),
    ("Attribution", "ATTRIBUTION.md"),
    ("Third-party notices", "THIRD_PARTY.md"),
)
WRITE_WARNING_TEXT = "Write in progress — do not power off or disconnect."
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


class ToneSlapperWindow:
    SCAN_TEXT = "Scan for devices"
    BUILD_TEXT = "Build"
    OPEN_TEXT = "Open existing…"
    UPLOAD_TEXT = "Upload"
    BUILD_SUCCESS_MS = 3000
    UPLOAD_FINISH_MS = 6000
    UPLOAD_FINISH_INTERVAL_MS = 50

    def __init__(self, root: Tk) -> None:
        self.root = root
        self.root.title(f"{APP_NAME} {APP_VERSION}")
        self.root.geometry("820x720")
        self.root.minsize(680, 700)
        apply_dark_theme(self.root)
        app_icon = str(asset_path("icons/app_icon.ico"))
        self.root.iconbitmap(app_icon)
        self.root.iconbitmap(default=app_icon)
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
        self._prompt_refresh_job: str | None = None
        self._build_status_job: str | None = None
        self._upload_finish_job: str | None = None
        self._upload_success_latched = False
        self._tip_job: str | None = None
        self._tip_canvas: Canvas | None = None
        self._tip_font = font.Font(
            root=self.root,
            family="Segoe UI Semibold",
            size=10,
        )
        self._hovered_prompt: int | None = None
        self._help_window: Toplevel | None = None
        self._legal_window: Toplevel | None = None
        self._legal_documents = load_legal_documents()
        self._pending_oem_action: Callable[[OemImage], None] | None = None
        self._oem_context: str | None = None
        self._reset_buttons: dict[int, ResetButton] = {}
        self._source_labels: dict[int, ttk.Label] = {}
        self._help_icon = PhotoImage(
            file=str(asset_path("icons/material_help_outline_white_18.png"))
        )
        self._support_icon = PhotoImage(
            file=str(asset_path("icons/material_favorite_white_18.png"))
        )

        self.device_var = StringVar()
        self.target_var = StringVar()
        self.output_var = StringVar(value=self.OPEN_TEXT)
        self._build_layout()
        self.root.protocol("WM_DELETE_WINDOW", self._request_close)
        self.root.bind("<F1>", lambda _event: self.show_help())
        self._refresh_prompt_rows()
        self._update_buttons()

    @staticmethod
    def _card(parent):
        return ttk.Frame(parent, style="Card.TFrame")

    def _build_layout(self) -> None:
        outer = ttk.Frame(self.root, padding=(18, 14))
        outer.pack(fill=BOTH, expand=True)

        content = ttk.Frame(outer)
        content.pack(fill=BOTH, expand=True)

        device_card = self._card(content)
        device_card.pack(fill=X, pady=(0, 8))
        device_row = ttk.Frame(device_card, style="CardBody.TFrame")
        device_row.pack(fill=X, padx=14, pady=12)
        device_selector = ttk.Frame(device_row, style="FieldShell.TFrame")
        device_selector.pack(side=LEFT, fill=X, expand=True, padx=(0, 8))
        self.device_combo = ttk.Combobox(
            device_selector,
            textvariable=self.device_var,
            state="readonly",
            style="Minimal.TCombobox",
            takefocus=False,
        )
        self.device_combo.pack(fill=X, expand=True, padx=1, pady=1)
        self.device_combo.bind("<<ComboboxSelected>>", self._device_selected)
        self.device_combo.bind("<Button-1>", self._clear_device_text_selection, add="+")
        self.device_combo.bind("<FocusIn>", self._clear_device_text_selection, add="+")
        self.scan_button = ttk.Button(
            device_row,
            text=self.SCAN_TEXT,
            width=20,
            command=self.scan,
            takefocus=False,
        )
        self.scan_button.pack(side=LEFT)

        self.target_label = ttk.Label(
            content,
            textvariable=self.target_var,
            style="BuildTarget.TLabel",
        )
        self.prompt_card = ttk.Frame(content, style="PromptCard.TFrame")
        self.prompt_card.pack(fill=BOTH, expand=True, pady=(0, 14))
        self.prompt_table = ttk.Frame(self.prompt_card, style="PromptBody.TFrame")
        self.prompt_table.pack(fill=BOTH, expand=True)
        self.prompt_empty_label = ttk.Label(
            self.prompt_table,
            text="Select a device first",
            style="PromptEmpty.TLabel",
            font=("Segoe UI", 22, "bold"),
            anchor="center",
            justify="center",
        )
        self.prompt_tree = ttk.Treeview(
            self.prompt_table,
            columns=("index", "event", "source", "reset"),
            show="headings",
            height=11,
            selectmode="none",
            style="Prompt.Treeview",
            takefocus=False,
        )
        self.prompt_tree.heading("index", text="INDEX", anchor="center")
        self.prompt_tree.heading("event", text="EVENT", anchor="w")
        self.prompt_tree.heading("source", text="AUDIO SOURCE", anchor="center")
        self.prompt_tree.heading("reset", text="", anchor="center")
        self.prompt_tree.column("index", width=64, anchor="center", stretch=False)
        self.prompt_tree.column("event", width=210, anchor="w", stretch=False)
        self.prompt_tree.column("source", width=300, anchor="center", stretch=True)
        self.prompt_tree.column("reset", width=88, anchor="center", stretch=False)
        self.prompt_tree.tag_configure("custom", foreground="#ffad98")
        self.prompt_tree.tag_configure("hover", background=COLORS["surface_hover"])
        self.prompt_scrollbar = ttk.Scrollbar(
            self.prompt_table,
            orient="vertical",
            command=self.prompt_tree.yview,
        )
        self.prompt_tree.configure(yscrollcommand=self._prompt_scroll_changed)
        self._tree_font = font.Font(root=self.root, family="Segoe UI", size=9)
        self.prompt_tree.bind("<Button-1>", self._prompt_click)
        self.prompt_tree.bind("<Double-1>", self._block_column_resize)
        self.prompt_tree.bind("<Motion>", self._prompt_motion)
        self.prompt_tree.bind("<Leave>", self._prompt_leave)
        self.prompt_tree.bind("<Configure>", self._schedule_prompt_refresh)
        self.prompt_tree.bind("<MouseWheel>", self._prompt_mousewheel)

        action_controls = ttk.Frame(content, style="CardBody.TFrame")
        action_controls.pack(fill=X, padx=14, pady=(0, 12))
        self.validate_button = ttk.Button(
            action_controls,
            textvariable=self.output_var,
            style="Path.TButton",
            command=self.open_existing,
            takefocus=False,
        )
        self.validate_button.pack(fill=X, pady=(0, 6))
        self.validate_button.bind("<Button-1>", self._open_button_pressed, add="+")
        self.build_button = ttk.Button(
            action_controls,
            text=self.BUILD_TEXT,
            command=self.build,
            takefocus=False,
        )
        self.build_button.pack(fill=X)
        self.build_button.bind("<Button-1>", self._build_button_pressed, add="+")
        self.write_warning_label = ttk.Label(
            action_controls,
            text=WRITE_WARNING_TEXT,
            style="WriteWarning.TLabel",
            font=("Segoe UI Semibold", 10, "bold"),
            anchor="center",
            justify="center",
        )
        self.upload_button = ProgressButton(
            action_controls,
            text=self.UPLOAD_TEXT,
            command=self.upload,
        )
        self.upload_button.pack(fill=X, pady=(8, 0))
        self.upload_button.bind("<Button-1>", self._upload_button_pressed, add="+")
        self.recovery_button = ttk.Button(
            action_controls,
            text="Restore OEM English",
            style="RecoveryLink.TButton",
            command=self.restore,
            takefocus=False,
        )
        self.recovery_button.pack(fill=X, pady=(8, 0))
        self.recovery_button.bind("<Button-1>", self._recovery_button_pressed, add="+")

        utility_footer = ttk.Frame(content)
        utility_footer.pack(fill=X, padx=14)
        self.help_button = ttk.Button(
            utility_footer,
            text="Help",
            image=self._help_icon,
            compound=LEFT,
            style="UtilityLink.TButton",
            command=self.show_help,
            takefocus=False,
        )
        self.help_button.pack(side=LEFT)
        self.support_button = ttk.Button(
            utility_footer,
            text="Support development",
            image=self._support_icon,
            compound=LEFT,
            style="UtilityLink.TButton",
            command=self.donate,
            takefocus=False,
        )
        self.support_button.pack(side=RIGHT)

    def show_help(self) -> None:
        if self._help_window is not None and self._help_window.winfo_exists():
            self._help_window.lift()
            return

        dialog = Toplevel(self.root)
        self._help_window = dialog
        dialog.withdraw()
        dialog.title(f"{APP_NAME} - Help")
        dialog.configure(background=COLORS["window"])
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.protocol("WM_DELETE_WINDOW", self._close_help)
        dialog.bind("<Escape>", lambda _event: self._close_help())

        content = ttk.Frame(dialog, padding=(22, 18))
        content.pack(fill=BOTH, expand=True)
        ttk.Label(content, text="How to use BT Tone Slapper", style="HelpTitle.TLabel").pack(
            anchor="w", pady=(0, 14)
        )

        sections = (
            (
                "1. Connect",
                "Connect the headphones to Windows normally.\n"
                f"In this app click Scan for devices, then select the connected "
                f"{TUNE_720BT_PROFILE.display_name} if "
                "multiple supported devices are connected.",
            ),
            (
                "2. Choose sounds",
                "In the list of prompts click a prompt row you want to change and choose "
                "an audio file.\n\n"
                "Use Reset on that row if you want to return it to OEM English.\n\n"
                "Supported audio formats:\n"
                f"{', '.join(SUPPORTED_AUDIO_FORMATS)}.\n"
                "Sample rate, bit depth, and channel count are converted automatically.",
            ),
            (
                "3. Build or open",
                "Click Build and choose where to save the .BIN prompt container. To reuse "
                "a previous .BIN container, click Open existing instead.",
            ),
            (
                "4. Upload",
                "Keep the headphones powered on and connected.\n"
                "Click Upload, review the confirmation, and do not disconnect them until "
                "the upload finishes.",
            ),
            (
                "Recovery",
                "Restore OEM English downloads and verifies the original English prompts "
                "before uploading them. If the manufacturer download fails, the app can "
                "use the pinned copy from the BT Tone Slapper GitHub repository.",
            ),
            (
                "Currently supported devices",
                ", ".join(SUPPORTED_DEVICES),
            ),
            (
                "About and license",
                f"Originally created by {APP_AUTHOR}\n"
                f"Original project: {PROJECT_URL}\n"
                f"License: {LICENSE_NAME}",
            ),
        )
        for heading, body in sections:
            ttk.Label(content, text=heading, style="HelpHeading.TLabel").pack(
                anchor="w", pady=(0, 2)
            )
            ttk.Label(
                content,
                text=body,
                style="HelpBody.TLabel",
                wraplength=510,
                justify=LEFT,
            ).pack(anchor="w", fill=X, pady=(0, 9))

        help_actions = ttk.Frame(content)
        help_actions.pack(fill=X, pady=(4, 0))
        ttk.Button(
            help_actions,
            text="Legal notices",
            style="Accent.TButton",
            command=self.show_legal_notices,
            takefocus=False,
        ).pack(side=LEFT, fill=X, expand=True, padx=(0, 4))
        ttk.Button(
            help_actions,
            text="Close",
            command=self._close_help,
            takefocus=False,
        ).pack(side=RIGHT, fill=X, expand=True, padx=(4, 0))

        dialog.update_idletasks()
        apply_dark_title_bar(dialog)
        width = 560
        height = max(530, dialog.winfo_reqheight())
        x = self.root.winfo_rootx() + max(0, (self.root.winfo_width() - 560) // 2)
        y = self.root.winfo_rooty() + max(0, (self.root.winfo_height() - height) // 2)
        dialog.geometry(f"{width}x{height}+{x}+{y}")
        dialog.deiconify()

    def _close_help(self) -> None:
        if self._help_window is not None and self._help_window.winfo_exists():
            self._help_window.destroy()
        self._help_window = None

    def show_legal_notices(self) -> None:
        if self._legal_window is not None and self._legal_window.winfo_exists():
            self._legal_window.lift()
            return

        dialog = Toplevel(self.root)
        self._legal_window = dialog
        dialog.withdraw()
        dialog.title(f"{APP_NAME} - Legal Notices")
        dialog.configure(background=COLORS["window"])
        dialog.minsize(620, 450)
        dialog.transient(self.root)
        dialog.protocol("WM_DELETE_WINDOW", self._close_legal_notices)
        dialog.bind("<Escape>", lambda _event: self._close_legal_notices())

        content = ttk.Frame(dialog, padding=(22, 18))
        content.pack(fill=BOTH, expand=True)
        ttk.Label(content, text="Legal Notices", style="HelpTitle.TLabel").pack(
            anchor="w",
        )
        ttk.Label(
            content,
            text=(
                f"Copyright (C) 2026 {APP_AUTHOR}\n"
                f"Licensed under {LICENSE_NAME}.\n"
                "This program comes with absolutely no warranty. You may redistribute "
                "and modify it under the terms shown here."
            ),
            style="HelpBody.TLabel",
            wraplength=660,
            justify=LEFT,
        ).pack(anchor="w", fill=X, pady=(8, 2))
        ttk.Button(
            content,
            text=f"Open source repository  ·  {PROJECT_URL}",
            style="UtilityLink.TButton",
            command=self.open_source_repository,
            takefocus=False,
        ).pack(anchor="w", pady=(0, 10))

        document_selector = ttk.Frame(content)
        document_selector.pack(fill=X, pady=(0, 8))
        document_frame = ttk.Frame(content, style="FieldShell.TFrame")
        document_frame.pack(fill=BOTH, expand=True)
        document_text = Text(
            document_frame,
            background=COLORS["field"],
            foreground=COLORS["text"],
            selectbackground=COLORS["selection"],
            selectforeground=COLORS["text"],
            borderwidth=0,
            highlightthickness=0,
            relief="flat",
            wrap="word",
            padx=14,
            pady=12,
            font=("Segoe UI", 9),
            state="disabled",
        )
        document_scrollbar = ttk.Scrollbar(
            document_frame,
            orient="vertical",
            command=document_text.yview,
        )
        document_text.configure(yscrollcommand=document_scrollbar.set)
        document_scrollbar.pack(side=RIGHT, fill=Y)
        document_text.pack(side=LEFT, fill=BOTH, expand=True)

        document_buttons: dict[str, ttk.Button] = {}

        def show_document(title: str) -> None:
            document_text.configure(state="normal")
            document_text.delete("1.0", "end")
            document_text.insert("1.0", self._legal_documents[title])
            document_text.configure(state="disabled")
            document_text.yview_moveto(0)
            for button_title, button in document_buttons.items():
                button.configure(
                    style="Accent.TButton" if button_title == title else "TButton"
                )

        for title, _filename in LEGAL_NOTICE_FILES:
            button = ttk.Button(
                document_selector,
                text=title,
                command=lambda document_title=title: show_document(document_title),
                takefocus=False,
            )
            button.pack(side=LEFT, fill=X, expand=True, padx=(0, 6))
            document_buttons[title] = button

        ttk.Button(
            content,
            text="Close",
            command=self._close_legal_notices,
            takefocus=False,
        ).pack(fill=X, pady=(12, 0))

        self._legal_text = document_text
        self._legal_buttons = document_buttons
        show_document("License")
        dialog.update_idletasks()
        apply_dark_title_bar(dialog)
        width = 720
        height = 600
        x = self.root.winfo_rootx() + max(0, (self.root.winfo_width() - width) // 2)
        y = self.root.winfo_rooty() + max(0, (self.root.winfo_height() - height) // 2)
        dialog.geometry(f"{width}x{height}+{x}+{y}")
        dialog.deiconify()

    def _close_legal_notices(self) -> None:
        if self._legal_window is not None and self._legal_window.winfo_exists():
            self._legal_window.destroy()
        self._legal_window = None

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

    def _request_close(self) -> None:
        if self._close_is_blocked():
            messagebox.showwarning(
                APP_NAME,
                CLOSE_BLOCKED_TEXT,
                parent=self.root,
            )
            return
        self.root.destroy()

    def _set_write_warning_visible(self, visible: bool) -> None:
        if visible:
            if not self.write_warning_label.winfo_manager():
                self.write_warning_label.pack(
                    fill=X,
                    pady=(10, 0),
                    before=self.upload_button,
                )
            return
        if self.write_warning_label.winfo_manager():
            self.write_warning_label.pack_forget()

    def donate(self) -> None:
        try:
            opened = webbrowser.open(DONATE_URL, new=2)
        except Exception:
            opened = False
        if not opened:
            messagebox.showerror(
                APP_NAME,
                f"Could not open the donation page. Visit:\n\n{DONATE_URL}",
            )

    def _build_button_pressed(self, _event=None):
        if not self.busy and self.target_profile_id is None:
            self._show_flying_tip(self.build_button, "select target device")
            return "break"
        return None

    def _open_button_pressed(self, _event=None):
        if not self.busy and self.target_profile_id is None:
            self._show_flying_tip(self.validate_button, "select target device")
            return "break"
        return None

    def _upload_button_pressed(self, _event=None):
        if self.busy:
            return "break"
        if self.last_build is None:
            self._show_flying_tip(self.upload_button, "build or open first")
            return "break"
        if self._device_identifier() is None or self._selected_profile_id() is None:
            self._show_flying_tip(self.upload_button, "select connected device")
            return "break"
        return None

    def _recovery_button_pressed(self, _event=None):
        if self.busy:
            return "break"
        if self._device_identifier() is None or self._selected_profile_id() is None:
            self._show_flying_tip(self.recovery_button, "select connected device")
            return "break"
        return None

    def _show_flying_tip(self, anchor, text: str) -> None:
        self._dismiss_flying_tip()
        self.root.update_idletasks()

        if self._tip_canvas is None:
            self._tip_canvas = Canvas(
                self.root,
                background="#000000",
                borderwidth=0,
                highlightthickness=0,
                relief="flat",
                takefocus=False,
            )
            self._tip_canvas.bind("<Button-1>", lambda _event: "break")

        tip = self._tip_canvas
        width = self._tip_font.measure(text) + 16
        height = self._tip_font.metrics("linespace") + 6
        x = (
            anchor.winfo_rootx()
            - self.root.winfo_rootx()
            + (anchor.winfo_width() - width) // 2
        )
        start_y = anchor.winfo_rooty() - self.root.winfo_rooty() - height + 20
        travel = 30
        frames = 36
        interval_ms = 45

        def blend(start: str, end: str, amount: float) -> str:
            start_rgb = tuple(int(start[index : index + 2], 16) for index in (1, 3, 5))
            end_rgb = tuple(int(end[index : index + 2], 16) for index in (1, 3, 5))
            values = tuple(
                round(start_value + (end_value - start_value) * amount)
                for start_value, end_value in zip(start_rgb, end_rgb)
            )
            return "#{:02x}{:02x}{:02x}".format(*values)

        def animate(frame: int = 0) -> None:
            self._tip_job = None
            if self._tip_canvas is not tip or not tip.winfo_exists():
                return
            progress = frame / frames
            y = start_y - round(travel * progress)
            fade_start = 0.68
            fade_progress = max(0.0, (progress - fade_start) / (1.0 - fade_start))
            background = blend("#000000", COLORS["window"], fade_progress)
            foreground = blend("#ffffff", COLORS["window"], fade_progress)
            tip.configure(background=background)
            tip.delete("all")
            tip.create_text(
                width / 2,
                height / 2,
                text=text,
                fill=foreground,
                font=self._tip_font,
            )
            tip.place(x=x, y=y, width=width, height=height)
            tip.tk.call("raise", tip._w)
            if frame >= frames:
                self._dismiss_flying_tip()
                return
            self._tip_job = self.root.after(interval_ms, animate, frame + 1)

        animate()

    def _dismiss_flying_tip(self) -> None:
        if self._tip_job is not None:
            self.root.after_cancel(self._tip_job)
            self._tip_job = None
        if self._tip_canvas is not None:
            self._tip_canvas.place_forget()
            self._tip_canvas.delete("all")

    def _schedule_prompt_refresh(self, _event=None) -> None:
        if self._prompt_refresh_job is not None:
            self.root.after_cancel(self._prompt_refresh_job)
        self._prompt_refresh_job = self.root.after(60, self._refresh_prompt_rows)

    def _prompt_scroll_changed(self, first: str, last: str) -> None:
        self.prompt_scrollbar.set(first, last)
        self.root.after_idle(self._position_row_controls)

    def _prompt_mousewheel(self, event):
        if len(self.prompt_tree.get_children()) <= 11:
            return "break"
        self.prompt_tree.yview_scroll(-1 if event.delta > 0 else 1, "units")
        return "break"

    def _update_prompt_scrollbar(self) -> None:
        needs_scrollbar = len(self.prompt_tree.get_children()) > 11
        if needs_scrollbar and not self.prompt_scrollbar.winfo_manager():
            self.prompt_scrollbar.pack(side=RIGHT, fill=Y)
        elif not needs_scrollbar and self.prompt_scrollbar.winfo_manager():
            self.prompt_scrollbar.pack_forget()

    def _truncate_path(self, path: Path) -> str:
        text = str(path)
        max_width = max(100, int(self.prompt_tree.column("source", "width")) - 22)
        if self._tree_font.measure(text) <= max_width:
            return text
        for start in range(1, len(text)):
            candidate = "…" + text[start:]
            if self._tree_font.measure(candidate) <= max_width:
                return candidate
        return "…" + path.name[-12:]

    def _refresh_prompt_rows(self) -> None:
        self._prompt_refresh_job = None
        self._hovered_prompt = None
        for button in self._reset_buttons.values():
            button.destroy()
        self._reset_buttons.clear()
        for label in self._source_labels.values():
            label.destroy()
        self._source_labels.clear()
        self.prompt_tree.delete(*self.prompt_tree.get_children())
        prompt_labels = self._prompt_labels()
        if not prompt_labels:
            if self.prompt_tree.winfo_manager():
                self.prompt_tree.pack_forget()
            if self.prompt_scrollbar.winfo_manager():
                self.prompt_scrollbar.pack_forget()
            if not self.prompt_empty_label.winfo_manager():
                self.prompt_empty_label.pack(fill=BOTH, expand=True)
            return
        if self.prompt_empty_label.winfo_manager():
            self.prompt_empty_label.pack_forget()
        if not self.prompt_tree.winfo_manager():
            self.prompt_tree.pack(side=LEFT, fill=BOTH, expand=True)
        for index, label in enumerate(prompt_labels):
            custom = index in self.assignments
            self.prompt_tree.insert(
                "",
                "end",
                iid=str(index),
                values=(f"{index:02d}", label, "", ""),
                tags=("custom",) if custom else (),
            )
        self.prompt_tree.selection_remove(*self.prompt_tree.selection())
        self._update_prompt_scrollbar()
        self.root.after_idle(self._position_row_controls)

    def _source_style(self, index: int) -> str:
        custom = index in self.assignments
        hovered = index == self._hovered_prompt
        return f"{'Custom' if custom else 'OEM'}Source{'Hover' if hovered else ''}.TLabel"

    def _position_row_controls(self) -> None:
        if not self.prompt_tree.winfo_exists() or not self.prompt_tree.winfo_manager():
            return
        for button in self._reset_buttons.values():
            button.destroy()
        self._reset_buttons.clear()
        for label in self._source_labels.values():
            label.destroy()
        self._source_labels.clear()
        for index in range(len(self._prompt_labels())):
            source_bounds = self.prompt_tree.bbox(str(index), "source")
            if not source_bounds:
                continue
            source_x, source_y, source_width, source_height = source_bounds
            source_text = (
                self._truncate_path(self.assignments[index])
                if index in self.assignments
                else "OEM English"
            )
            source_label = ttk.Label(
                self.prompt_tree,
                text=source_text,
                style=self._source_style(index),
                anchor="w" if index in self.assignments else "center",
                cursor="arrow" if self.busy else "hand2",
            )
            source_label.place(
                x=source_x + 1,
                y=source_y + 1,
                width=max(1, source_width - 2),
                height=max(1, source_height - 2),
            )
            source_label.bind(
                "<Button-1>",
                lambda _event, prompt_index=index: self._source_click(prompt_index),
            )
            source_label.bind(
                "<Enter>",
                lambda _event, prompt_index=index: self._set_prompt_hover(prompt_index),
            )
            source_label.bind("<Leave>", lambda _event: self._set_prompt_hover(None))
            source_label.bind("<MouseWheel>", self._prompt_mousewheel)
            self._source_labels[index] = source_label

        for index in sorted(self.assignments):
            bounds = self.prompt_tree.bbox(str(index), "reset")
            if not bounds:
                continue
            x, y, width, height = bounds
            button = ResetButton(
                self.prompt_tree,
                command=lambda prompt_index=index: self._reset_prompt(prompt_index),
            )
            button.place(x=x + 4, y=y + 3, width=max(1, width - 8), height=max(1, height - 6))
            button.set_enabled(not self.busy)
            button.bind(
                "<Enter>",
                lambda _event, prompt_index=index: self._set_prompt_hover(prompt_index),
                add="+",
            )
            button.bind("<Leave>", lambda _event: self._set_prompt_hover(None), add="+")
            button.bind("<MouseWheel>", self._prompt_mousewheel, add="+")
            button.set_row_hover(index == self._hovered_prompt)
            self._reset_buttons[index] = button

    def _source_click(self, index: int):
        if not self.busy and self.target_profile_id is not None:
            self._choose_audio_for(index)
        return "break"

    def _prompt_click(self, event):
        region = self.prompt_tree.identify_region(event.x, event.y)
        if region == "separator":
            return "break"
        if self.busy or region != "cell":
            return "break"
        row = self.prompt_tree.identify_row(event.y)
        column = self.prompt_tree.identify_column(event.x)
        if not row:
            return "break"
        index = int(row)
        if column == "#4":
            if index in self.assignments:
                self._reset_prompt(index)
            else:
                self._choose_audio_for(index)
            return "break"
        if column in {"#1", "#2", "#3"}:
            self._choose_audio_for(index)
            return "break"
        return "break"

    def _block_column_resize(self, event):
        return "break"

    def _prompt_motion(self, event) -> None:
        row = self.prompt_tree.identify_row(event.y)
        column = self.prompt_tree.identify_column(event.x)
        region = self.prompt_tree.identify_region(event.x, event.y)
        hovered = int(row) if not self.busy and region == "cell" and row else None
        self._set_prompt_hover(hovered)
        clickable = (
            not self.busy
            and region == "cell"
            and bool(row)
            and column in {"#1", "#2", "#3", "#4"}
        )
        self.prompt_tree.configure(cursor="hand2" if clickable else "")

    def _prompt_leave(self, _event) -> None:
        self._set_prompt_hover(None)
        self.prompt_tree.configure(cursor="")

    def _set_prompt_hover(self, index: int | None) -> None:
        if index == self._hovered_prompt:
            return
        previous = self._hovered_prompt
        self._hovered_prompt = index
        for prompt_index in (previous, index):
            if prompt_index is None or not self.prompt_tree.exists(str(prompt_index)):
                continue
            tags = []
            if prompt_index in self.assignments:
                tags.append("custom")
            if prompt_index == index:
                tags.append("hover")
            self.prompt_tree.item(str(prompt_index), tags=tuple(tags))
            source_label = self._source_labels.get(prompt_index)
            if source_label is not None:
                source_label.configure(style=self._source_style(prompt_index))
            reset_button = self._reset_buttons.get(prompt_index)
            if reset_button is not None:
                reset_button.set_row_hover(prompt_index == index)

    def _choose_audio_for(self, index: int) -> None:
        prompt_labels = self._prompt_labels()
        if not 0 <= index < len(prompt_labels):
            return
        selected = filedialog.askopenfilename(
            title=f"Audio for {prompt_labels[index]}",
            filetypes=AUDIO_TYPES,
        )
        if selected:
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
            self.build_button.configure(text=self.BUILD_TEXT)
        self.last_build = None
        self.build_dirty = True
        self.output_var.set(self.OPEN_TEXT)
        self._update_buttons()

    def _device_selected(self, _event=None) -> None:
        self._reset_upload_success()
        self._clear_device_text_selection()
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
            self.target_var.set(f"Build target: {profile.display_name}")
            if not self.target_label.winfo_manager():
                self.target_label.pack(
                    fill=X,
                    padx=14,
                    pady=(1, 8),
                    before=self.prompt_card,
                )
            self._refresh_prompt_rows()
            self._invalidate_build()
            return
        self._update_buttons()

    def _prompt_labels(self) -> tuple[str, ...]:
        profile = get_device_profile(self.target_profile_id)
        return profile.prompt_labels if profile is not None else ()

    def _clear_device_text_selection(self, _event=None) -> None:
        self.root.after_idle(self.device_combo.selection_clear)

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
            self.scan_button.configure(text="Scanning…")
        elif operation_name == "build":
            self.build_button.configure(text="Preparing audio…")
        elif operation_name == "open":
            self.output_var.set("Opening and validating…")
        elif operation_name.startswith("oem-"):
            if self._oem_context == "build":
                self.build_button.configure(text="Downloading OEM...")
            else:
                self.upload_button.begin("Downloading OEM...")
        elif operation_name in {"upload", "recovery"}:
            self.upload_button.begin("Verifying headphones…")
        self._set_write_warning_visible(operation_name in {"upload", "recovery"})
        self._update_buttons()

        def worker() -> None:
            try:
                result = operation()
            except Exception as error:
                traceback.print_exc()
                self.root.after(0, lambda error=error: self._finish_error(error))
            else:
                self.root.after(0, lambda: self._finish_success(result, success))

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
        messagebox.showerror(APP_NAME, detail)
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
        self._set_write_warning_visible(False)
        self.scan_button.configure(text=self.SCAN_TEXT)
        self.build_button.configure(text=self.BUILD_TEXT)
        self.output_var.set(self.last_build.output if self.last_build else self.OPEN_TEXT)
        if not preserve_upload_status:
            self.upload_button.reset(enabled=False)
        self._update_buttons()

    def _reset_upload_success(self) -> None:
        if not self._upload_success_latched:
            return
        self._upload_success_latched = False
        self.upload_button.reset(enabled=False)

    def _thread_progress(self, message: str) -> None:
        self.root.after(0, lambda: self._apply_progress(message))

    def _apply_progress(self, message: str) -> None:
        if self.active_operation == "build":
            if message.startswith("Saving verified OEM"):
                self.build_button.configure(text="Saving OEM container...")
            elif message.startswith("Converting prompt"):
                self.build_button.configure(text="Converting audio…")
            elif message.startswith("Rebuilding"):
                self.build_button.configure(text="Building container…")
            elif message.startswith("Container validated"):
                self.build_button.configure(text="Validated")
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
            display = f"{model} | {device.address} | Connected"
            values.append(display)
            self.devices[display] = device.address
            self.device_models[display] = model
        self.device_combo["values"] = values
        self.device_var.set(values[0] if values else "")
        if values:
            self._device_selected()
        if not values:
            messagebox.showinfo(
                APP_NAME,
                f"No connected {TUNE_720BT_PROFILE.display_name} was found.",
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
        result: dict[str, str | None] = {"value": None}
        dialog = Toplevel(self.root)
        dialog.withdraw()
        dialog.title(f"{APP_NAME} - {title}")
        dialog.configure(background=COLORS["window"])
        dialog.resizable(False, False)
        dialog.transient(self.root)

        def close(value: str | None = None) -> None:
            result["value"] = value
            dialog.destroy()

        dialog.protocol("WM_DELETE_WINDOW", close)
        dialog.bind("<Escape>", lambda _event: close())
        content = ttk.Frame(dialog, padding=(22, 18))
        content.pack(fill=BOTH, expand=True)
        ttk.Label(content, text=title, style="HelpTitle.TLabel").pack(
            anchor="w",
            pady=(0, 12),
        )
        ttk.Label(
            content,
            text=message,
            style="HelpBody.TLabel",
            wraplength=500,
            justify=LEFT,
        ).pack(anchor="w", fill=X, pady=(0, 18))
        buttons = ttk.Frame(content)
        buttons.pack(fill=X)
        ttk.Button(
            buttons,
            text="Cancel",
            style="Ghost.TButton",
            command=close,
            takefocus=False,
        ).pack(side=RIGHT)
        ttk.Button(
            buttons,
            text=continue_text,
            style="Accent.TButton",
            command=lambda: close("continue"),
            takefocus=False,
        ).pack(side=RIGHT, padx=(0, 8))

        dialog.update_idletasks()
        apply_dark_title_bar(dialog)
        width = 550
        height = max(230, dialog.winfo_reqheight())
        x = self.root.winfo_rootx() + max(0, (self.root.winfo_width() - width) // 2)
        y = self.root.winfo_rooty() + max(0, (self.root.winfo_height() - height) // 2)
        dialog.geometry(f"{width}x{height}+{x}+{y}")
        dialog.deiconify()
        dialog.grab_set()
        self.root.wait_window(dialog)
        return result["value"]

    def _show_manual_oem_recovery(self, detail: str) -> None:
        selected: dict[str, Path | None] = {"path": None}
        dialog = Toplevel(self.root)
        dialog.withdraw()
        dialog.title(f"{APP_NAME} - Manual OEM recovery")
        dialog.configure(background=COLORS["window"])
        dialog.resizable(False, False)
        dialog.transient(self.root)

        def close() -> None:
            dialog.destroy()

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
                filetypes=[("OEM prompt container", "*.bin"), ("All files", "*.*")],
            )
            if chosen:
                selected["path"] = Path(chosen)
                dialog.destroy()

        dialog.protocol("WM_DELETE_WINDOW", close)
        dialog.bind("<Escape>", lambda _event: close())
        content = ttk.Frame(dialog, padding=(22, 18))
        content.pack(fill=BOTH, expand=True)
        ttk.Label(
            content,
            text="Automatic OEM download failed",
            style="HelpTitle.TLabel",
        ).pack(anchor="w", pady=(0, 12))
        ttk.Label(
            content,
            text=(
                f"{detail}\n\n"
                "Download the OEM file manually from the BT Tone Slapper GitHub "
                "repository, then select the downloaded file."
            ),
            style="HelpBody.TLabel",
            wraplength=520,
            justify=LEFT,
        ).pack(anchor="w", fill=X, pady=(0, 18))
        buttons = ttk.Frame(content)
        buttons.pack(fill=X)
        ttk.Button(
            buttons,
            text="Cancel",
            style="Ghost.TButton",
            command=close,
            takefocus=False,
        ).pack(side=RIGHT)
        ttk.Button(
            buttons,
            text="Select downloaded file",
            style="Accent.TButton",
            command=select_file,
            takefocus=False,
        ).pack(side=RIGHT, padx=(0, 8))
        ttk.Button(
            buttons,
            text="Open GitHub",
            command=open_github,
            takefocus=False,
        ).pack(side=LEFT)

        dialog.update_idletasks()
        apply_dark_title_bar(dialog)
        width = 570
        height = max(250, dialog.winfo_reqheight())
        x = self.root.winfo_rootx() + max(0, (self.root.winfo_width() - width) // 2)
        y = self.root.winfo_rooty() + max(0, (self.root.winfo_height() - height) // 2)
        dialog.geometry(f"{width}x{height}+{x}+{y}")
        dialog.deiconify()
        dialog.grab_set()
        self.root.wait_window(dialog)

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
        self._acquire_oem(
            "build",
            self._build_with_oem,
            always_download=False,
        )

    def _build_with_oem(self, oem_image: OemImage) -> None:
        output = filedialog.asksaveasfilename(
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
        self.output_var.set(result.output)
        self.root.after_idle(self._show_build_success)

    def _show_build_success(self) -> None:
        self.build_button.configure(
            text="Build successful",
            style="Success.TButton",
        )
        self._build_status_job = self.root.after(
            self.BUILD_SUCCESS_MS,
            self._restore_build_text,
        )

    def _restore_build_text(self) -> None:
        self._build_status_job = None
        if self.active_operation != "build":
            self.build_button.configure(text=self.BUILD_TEXT)
            self._update_buttons()

    def open_existing(self) -> None:
        profile_id = self.target_profile_id
        if profile_id is None:
            self._show_flying_tip(self.validate_button, "select target device")
            return
        selected = filedialog.askopenfilename(
            filetypes=[("Tone container", "*.bin"), ("All files", "*.*")]
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
        self.output_var.set(result.output)
        messagebox.showinfo(
            APP_NAME,
            f"Container validated and loaded for upload.\n\n{result.output}\n\nSHA-256:\n{result.sha256}",
        )

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
            )
            return
        candidate = Path(self.last_build.output)
        confirmation = (
            "Write the selected prompt container to the headphones?\n\n"
            f"Device: {identifier}\n"
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
        if not messagebox.askyesno(APP_NAME, confirmation, icon="warning"):
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
            f"Device: {identifier}\n"
            f"Recovery SHA-256: {BASE_SHA256}\n\n"
            "The OEM file will be downloaded and cryptographically verified before writing. "
            "Once writing starts, do not close the app, power off or disconnect the headphones, "
            "disable Bluetooth, or let the PC sleep. Wait until the Upload button reports "
            "Success!\n\n"
            "Interrupting recovery may leave voice prompts unavailable and require another OEM "
            "restore attempt."
        )
        if not messagebox.askyesno(APP_NAME, confirmation, icon="warning"):
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
        self.device_combo.configure(values=tuple(self.devices))
        self.device_var.set("")

    def _update_buttons(self) -> None:
        if self.busy:
            self._set_prompt_hover(None)
        normal_state = "disabled" if self.busy else "normal"
        self.device_combo.configure(state="disabled" if self.busy else "readonly")
        has_listed_devices = bool(self.devices)
        self.scan_button.configure(
            state=normal_state,
            style="TButton" if has_listed_devices else "Accent.TButton",
        )
        build_enabled = not self.busy and self.target_profile_id is not None
        self.build_button.configure(
            state="normal" if build_enabled else "disabled",
            style="Accent.TButton" if build_enabled and self.build_dirty else "TButton",
        )
        open_enabled = not self.busy and self.target_profile_id is not None
        self.validate_button.configure(state="normal" if open_enabled else "disabled")
        selected_profile_id = self._selected_profile_id()
        has_device = (
            self._device_identifier() is not None and selected_profile_id is not None
        )
        loaded_profile_matches = (
            self.last_build is not None
            and self.last_build.profile_id == selected_profile_id
        )
        self.upload_button.set_enabled(
            not self.busy and has_device and loaded_profile_matches
        )
        self.recovery_button.configure(
            state="normal" if not self.busy and has_device else "disabled"
        )
        for button in self._reset_buttons.values():
            button.set_enabled(not self.busy)
        for label in self._source_labels.values():
            label.configure(cursor="arrow" if self.busy else "hand2")


def main() -> None:
    root = Tk()
    try:
        ToneSlapperWindow(root)
    except Exception as error:
        traceback.print_exc()
        messagebox.showerror(APP_NAME, user_error_message("startup", error))
        root.destroy()
        return
    root.mainloop()
