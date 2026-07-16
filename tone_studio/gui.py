from __future__ import annotations

import re
import threading
import traceback
import webbrowser
from pathlib import Path
from tkinter import (
    BOTH,
    LEFT,
    RIGHT,
    X,
    Y,
    StringVar,
    Tk,
    Toplevel,
    filedialog,
    font,
    messagebox,
)
from tkinter import ttk

from . import APP_NAME, APP_VERSION
from .device_profiles import (
    SUPPORTED_PROFILES,
    TUNE_720BT_PROFILE,
    resolve_device_profile,
)
from .errors import user_error_message
from .theme import COLORS, apply_dark_theme, apply_dark_title_bar
from .widgets import ProgressButton, ResetButton
from .workflow import BASE_SHA256, PROMPT_LABELS, BuildResult, StudioEngine


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


class StudioWindow:
    SCAN_TEXT = "Scan for devices"
    BUILD_TEXT = "Build"
    OPEN_TEXT = "Open existing…"
    UPLOAD_TEXT = "Upload"
    BUILD_SUCCESS_MS = 3000

    def __init__(self, root: Tk) -> None:
        self.root = root
        self.root.title(f"{APP_NAME} {APP_VERSION}")
        self.root.geometry("820x720")
        self.root.minsize(680, 700)
        apply_dark_theme(self.root)
        self.engine = StudioEngine()
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
        self._hovered_prompt: int | None = None
        self._help_window: Toplevel | None = None
        self._reset_buttons: dict[int, ResetButton] = {}
        self._source_labels: dict[int, ttk.Label] = {}

        self.device_var = StringVar()
        self.target_var = StringVar()
        self.output_var = StringVar(value=self.OPEN_TEXT)
        self._build_layout()
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
        prompt_table = ttk.Frame(self.prompt_card, style="PromptBody.TFrame")
        prompt_table.pack(fill=BOTH, expand=True)
        self.prompt_tree = ttk.Treeview(
            prompt_table,
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
            prompt_table,
            orient="vertical",
            command=self.prompt_tree.yview,
        )
        self.prompt_tree.configure(yscrollcommand=self._prompt_scroll_changed)
        self.prompt_tree.pack(side=LEFT, fill=BOTH, expand=True)
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
        self.build_button = ttk.Button(
            action_controls,
            text=self.BUILD_TEXT,
            command=self.build,
            takefocus=False,
        )
        self.build_button.pack(fill=X)
        self.upload_button = ProgressButton(
            action_controls,
            text=self.UPLOAD_TEXT,
            command=self.upload,
        )
        self.upload_button.pack(fill=X, pady=(8, 0))
        self.recovery_button = ttk.Button(
            action_controls,
            text="Restore OEM English",
            style="RecoveryLink.TButton",
            command=self.restore,
            takefocus=False,
        )
        self.recovery_button.pack(fill=X, pady=(8, 0))

        utility_footer = ttk.Frame(content)
        utility_footer.pack(fill=X, padx=14)
        self.help_button = ttk.Button(
            utility_footer,
            text="Help",
            style="UtilityLink.TButton",
            command=self.show_help,
            takefocus=False,
        )
        self.help_button.pack(side=LEFT)
        self.support_button = ttk.Button(
            utility_footer,
            text="Support development",
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
        ttk.Label(content, text="How to use JBL Tone Studio", style="HelpTitle.TLabel").pack(
            anchor="w", pady=(0, 14)
        )

        sections = (
            (
                "1. Connect",
                "Connect the headphones to Windows normally.\n"
                "In this app click Scan for devices, then select the connected JBL Tune 720BT if "
                "multiple JBL devices are connected.",
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
                "Restore OEM English uploads the bundled original English prompts when a "
                "recovery is needed.",
            ),
            (
                "Currently supported devices",
                ", ".join(SUPPORTED_DEVICES),
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

        ttk.Button(
            content,
            text="Close",
            command=self._close_help,
            takefocus=False,
        ).pack(fill=X, pady=(4, 0))

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
        for index, label in enumerate(PROMPT_LABELS):
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
        if not self.prompt_tree.winfo_exists():
            return
        for button in self._reset_buttons.values():
            button.destroy()
        self._reset_buttons.clear()
        for label in self._source_labels.values():
            label.destroy()
        self._source_labels.clear()
        for index in range(len(PROMPT_LABELS)):
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
        if not self.busy:
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
        selected = filedialog.askopenfilename(
            title=f"Audio for {PROMPT_LABELS[index]}",
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
        if self._build_status_job is not None:
            self.root.after_cancel(self._build_status_job)
            self._build_status_job = None
            self.build_button.configure(text=self.BUILD_TEXT)
        self.last_build = None
        self.build_dirty = True
        self.output_var.set(self.OPEN_TEXT)
        self._update_buttons()

    def _device_selected(self, _event=None) -> None:
        self._clear_device_text_selection()
        display = self.device_var.get()
        model = self.device_models.get(display)
        profile = resolve_device_profile(model)
        if profile is None:
            self._update_buttons()
            return
        if profile.profile_id != self.target_profile_id:
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
            self._invalidate_build()
            return
        self._update_buttons()

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
        elif operation_name in {"upload", "recovery"}:
            self.upload_button.begin("Verifying headphones…")
        self._update_buttons()

        def worker() -> None:
            try:
                result = operation()
            except Exception as error:
                detail = user_error_message(operation_name, error)
                traceback.print_exc()
                self.root.after(0, lambda: self._finish_error(detail))
            else:
                self.root.after(0, lambda: self._finish_success(result, success))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_error(self, detail: str) -> None:
        if self.active_operation in {"upload", "recovery"}:
            self.upload_button.set_progress(1.0, "Upload failed")
        messagebox.showerror(APP_NAME, detail)
        self._reset_operation_ui()

    def _finish_success(self, result, callback) -> None:
        callback(result)
        self._reset_operation_ui()

    def _reset_operation_ui(self) -> None:
        self.busy = False
        self.active_operation = None
        self.active_total_packets = 0
        self.scan_button.configure(text=self.SCAN_TEXT)
        self.build_button.configure(text=self.BUILD_TEXT)
        self.output_var.set(self.last_build.output if self.last_build else self.OPEN_TEXT)
        self.upload_button.reset(enabled=False)
        self._update_buttons()

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
            self.upload_button.set_progress(1.0, "Accepted by headphones")

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
            messagebox.showinfo(APP_NAME, "No connected JBL Tune 720BT was found.")

    def build(self) -> None:
        if self.target_profile_id is None:
            return
        output = filedialog.asksaveasfilename(
            title="Save generated tone container",
            defaultextension=".bin",
            initialfile=(
                "English_prompt_custom.bin"
                if self.assignments
                else "English_prompt_OEM.bin"
            ),
            filetypes=[("JBL tone container", "*.bin")],
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
        selected = filedialog.askopenfilename(
            filetypes=[("JBL tone container", "*.bin"), ("All files", "*.*")]
        )
        if not selected:
            return
        path = Path(selected)
        profile_id = self.target_profile_id or TUNE_720BT_PROFILE.profile_id
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
            "Upload the selected prompt container to the headphones?\n\n"
            f"Device: {identifier}\n"
            f"File: {candidate.name}\n"
            f"SHA-256: {self.last_build.sha256}\n\n"
            "Keep the headphones powered on. The verified OEM English recovery image is bundled."
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
            lambda result: self._upload_complete("Prompt upload", result),
            total_packets=int(self.last_build.dry_run["packet_count"]),
        )

    def restore(self) -> None:
        identifier = self._device_identifier()
        device_profile_id = self._selected_profile_id()
        if not identifier or device_profile_id is None:
            return
        confirmation = (
            "Restore the verified OEM English prompt image?\n\n"
            f"Device: {identifier}\n"
            f"Recovery SHA-256: {BASE_SHA256}\n\n"
            "This performs a physical BLE write. Keep the headphones powered on."
        )
        if not messagebox.askyesno(APP_NAME, confirmation, icon="warning"):
            return
        self._run_background(
            "recovery",
            lambda: self.engine.restore_oem(
                identifier,
                device_profile_id=device_profile_id,
                progress=self._thread_progress,
            ),
            lambda result: self._upload_complete("OEM recovery", result),
            total_packets=self.engine.recovery_packet_count,
        )

    def _upload_complete(self, label: str, result) -> None:
        report, log_path = result
        self.upload_button.set_progress(1.0, "Upload complete")
        messagebox.showinfo(
            APP_NAME,
            f"{label} completed.\n\nDevice state: {report.state}\nWrites: {report.write_count}\nLog: {log_path}",
        )

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
        self.validate_button.configure(state=normal_state)
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
        StudioWindow(root)
    except Exception as error:
        traceback.print_exc()
        messagebox.showerror(APP_NAME, user_error_message("startup", error))
        root.destroy()
        return
    root.mainloop()
