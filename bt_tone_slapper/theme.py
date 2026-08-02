from __future__ import annotations

import ctypes
import sys
from tkinter import Misc, PhotoImage, Tk
from tkinter import ttk


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


def apply_dark_title_bar(root: Misc) -> None:
    if sys.platform != "win32":
        return
    try:
        root.update_idletasks()
        enabled = ctypes.c_int(1)
        hwnd = root.winfo_id()
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


def apply_dark_theme(root: Tk) -> ttk.Style:
    root.configure(background=COLORS["window"])
    root.option_add("*Font", "{Segoe UI} 10")
    root.option_add("*TCombobox*Listbox.background", COLORS["field"])
    root.option_add("*TCombobox*Listbox.foreground", COLORS["text"])
    root.option_add("*TCombobox*Listbox.selectBackground", COLORS["accent"])
    root.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")
    root.option_add("*TCombobox*Listbox.borderWidth", 0)
    root.option_add("*TCombobox*Listbox.highlightThickness", 0)
    root.option_add("*TCombobox*Listbox.relief", "flat")
    root.option_add("*TCombobox*Listbox.selectBorderWidth", 0)
    root.option_add("*TCombobox*Listbox.activestyle", "none")

    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(".", background=COLORS["window"], foreground=COLORS["text"])
    style.configure("TFrame", background=COLORS["window"])
    style.configure("Header.TFrame", background=COLORS["window"])
    style.configure(
        "Card.TFrame",
        background=COLORS["window"],
        bordercolor=COLORS["window"],
        borderwidth=0,
        relief="flat",
    )
    style.configure("CardBody.TFrame", background=COLORS["window"], borderwidth=0)
    style.configure(
        "PromptCard.TFrame",
        background=COLORS["prompt_surface"],
        bordercolor=COLORS["prompt_surface"],
        borderwidth=0,
        relief="flat",
    )
    style.configure(
        "PromptBody.TFrame",
        background=COLORS["prompt_surface"],
        borderwidth=0,
    )
    style.configure(
        "PromptEmpty.TLabel",
        background=COLORS["prompt_surface"],
        foreground=COLORS["muted"],
        font=("Segoe UI", 22, "bold"),
        anchor="center",
        justify="center",
    )
    style.configure(
        "FieldShell.TFrame",
        background=COLORS["field"],
        bordercolor=COLORS["border"],
        borderwidth=1,
        relief="solid",
    )
    style.configure("TLabel", background=COLORS["window"], foreground=COLORS["text"])
    style.configure(
        "Title.TLabel",
        background=COLORS["window"],
        foreground=COLORS["text"],
        font=("Segoe UI Variable Display", 20, "bold"),
    )
    style.configure(
        "Subtitle.TLabel",
        background=COLORS["window"],
        foreground=COLORS["muted"],
        font=("Segoe UI", 9),
    )
    style.configure(
        "Section.TLabel",
        background=COLORS["surface"],
        foreground=COLORS["text"],
        font=("Segoe UI Semibold", 10, "bold"),
    )
    style.configure("Card.TLabel", background=COLORS["surface"], foreground=COLORS["text"])
    style.configure(
        "Muted.Card.TLabel",
        background=COLORS["surface"],
        foreground=COLORS["muted"],
        font=("Segoe UI", 9),
    )
    style.configure(
        "Status.TLabel",
        background=COLORS["surface_hover"],
        foreground=COLORS["text"],
        font=("Segoe UI Semibold", 9),
        padding=(10, 5),
    )
    style.configure(
        "BuildTarget.TLabel",
        background=COLORS["window"],
        foreground=COLORS["text"],
        font=("Segoe UI Semibold", 11),
        padding=(0, 0),
    )
    style.configure(
        "WriteWarning.TLabel",
        background=COLORS["window"],
        foreground=COLORS["accent"],
        font=("Segoe UI Semibold", 10, "bold"),
        padding=(0, 2),
    )

    style.configure(
        "TButton",
        background=COLORS["surface_hover"],
        foreground=COLORS["text"],
        bordercolor=COLORS["border"],
        lightcolor=COLORS["surface_hover"],
        darkcolor=COLORS["surface_hover"],
        borderwidth=1,
        focusthickness=0,
        focuscolor=COLORS["surface_hover"],
        font=("Segoe UI Semibold", 9),
        padding=(13, 8),
        relief="flat",
        shiftrelief=0,
    )
    style.layout(
        "TButton",
        [
            (
                "Button.border",
                {
                    "sticky": "nswe",
                    "border": "1",
                    "children": [
                        (
                            "Button.padding",
                            {
                                "sticky": "nswe",
                                "children": [("Button.label", {"sticky": "nswe"})],
                            },
                        )
                    ],
                },
            )
        ],
    )
    style.map(
        "TButton",
        background=[("pressed", "#121212"), ("active", "#2c2c2c"), ("disabled", "#2a2a2a")],
        foreground=[("disabled", COLORS["disabled"])],
        bordercolor=[("pressed", "#121212"), ("active", "#424242"), ("disabled", "#363636")],
        lightcolor=[("pressed", "#121212"), ("active", "#2c2c2c"), ("disabled", "#2a2a2a")],
        darkcolor=[("pressed", "#121212"), ("active", "#2c2c2c"), ("disabled", "#2a2a2a")],
        relief=[("pressed", "flat"), ("active", "flat")],
    )
    style.configure(
        "Accent.TButton",
        background=COLORS["accent"],
        foreground="#ffffff",
        bordercolor=COLORS["accent"],
        lightcolor=COLORS["accent"],
        darkcolor=COLORS["accent"],
        font=("Segoe UI Semibold", 9),
        padding=(15, 8),
    )
    style.map(
        "Accent.TButton",
        background=[
            ("pressed", COLORS["accent_pressed"]),
            ("active", COLORS["accent_hover"]),
            ("disabled", "#56372f"),
        ],
        foreground=[("disabled", "#9a7770")],
        bordercolor=[
            ("pressed", COLORS["accent_pressed"]),
            ("active", COLORS["accent_hover"]),
            ("disabled", "#56372f"),
        ],
        lightcolor=[
            ("pressed", COLORS["accent_pressed"]),
            ("active", COLORS["accent_hover"]),
            ("disabled", "#56372f"),
        ],
        darkcolor=[
            ("pressed", COLORS["accent_pressed"]),
            ("active", COLORS["accent_hover"]),
            ("disabled", "#56372f"),
        ],
        relief=[("pressed", "flat"), ("active", "flat")],
    )
    style.configure(
        "Danger.TButton",
        background=COLORS["danger"],
        foreground="#ffffff",
        bordercolor=COLORS["danger"],
        lightcolor=COLORS["danger"],
        darkcolor=COLORS["danger"],
    )
    style.map(
        "Danger.TButton",
        background=[("pressed", "#a92f3a"), ("active", COLORS["danger_hover"]), ("disabled", "#4a2a30")],
        foreground=[("disabled", "#8d6c72")],
        bordercolor=[("pressed", "#a92f3a"), ("active", COLORS["danger_hover"]), ("disabled", "#4a2a30")],
        lightcolor=[("pressed", "#a92f3a"), ("active", COLORS["danger_hover"]), ("disabled", "#4a2a30")],
        darkcolor=[("pressed", "#a92f3a"), ("active", COLORS["danger_hover"]), ("disabled", "#4a2a30")],
        relief=[("pressed", "flat"), ("active", "flat")],
    )
    style.configure(
        "Success.TButton",
        background=COLORS["success"],
        foreground="#ffffff",
        bordercolor=COLORS["success"],
        lightcolor=COLORS["success"],
        darkcolor=COLORS["success"],
    )
    style.map(
        "Success.TButton",
        background=[
            ("pressed", COLORS["success_pressed"]),
            ("active", COLORS["success_hover"]),
        ],
        bordercolor=[
            ("pressed", COLORS["success_pressed"]),
            ("active", COLORS["success_hover"]),
        ],
        lightcolor=[
            ("pressed", COLORS["success_pressed"]),
            ("active", COLORS["success_hover"]),
        ],
        darkcolor=[
            ("pressed", COLORS["success_pressed"]),
            ("active", COLORS["success_hover"]),
        ],
        relief=[("pressed", "flat"), ("active", "flat")],
    )
    style.configure(
        "Ghost.TButton",
        background=COLORS["surface"],
        foreground=COLORS["muted"],
        bordercolor=COLORS["border"],
        lightcolor=COLORS["surface"],
        darkcolor=COLORS["surface"],
    )
    style.map(
        "Ghost.TButton",
        background=[("pressed", COLORS["field"]), ("active", COLORS["surface_hover"])],
        foreground=[("active", COLORS["text"]), ("disabled", COLORS["disabled"])],
        bordercolor=[("pressed", COLORS["field"])],
        lightcolor=[("pressed", COLORS["field"]), ("active", COLORS["surface_hover"])],
        darkcolor=[("pressed", COLORS["field"]), ("active", COLORS["surface_hover"])],
        relief=[("pressed", "flat"), ("active", "flat")],
    )
    style.configure(
        "Path.TButton",
        background=COLORS["window"],
        foreground=COLORS["muted"],
        bordercolor=COLORS["window"],
        lightcolor=COLORS["window"],
        darkcolor=COLORS["window"],
        borderwidth=0,
        focusthickness=0,
        focuscolor=COLORS["window"],
        anchor="center",
        padding=(0, 4),
        relief="flat",
    )
    style.map(
        "Path.TButton",
        background=[("active", COLORS["window"]), ("pressed", COLORS["window"]), ("disabled", COLORS["window"])],
        foreground=[("active", COLORS["accent_hover"]), ("disabled", COLORS["disabled"])],
        bordercolor=[("active", COLORS["window"]), ("pressed", COLORS["window"])],
        lightcolor=[("active", COLORS["window"]), ("pressed", COLORS["window"])],
        darkcolor=[("active", COLORS["window"]), ("pressed", COLORS["window"])],
        relief=[("pressed", "flat"), ("active", "flat")],
    )
    style.configure(
        "UtilityLink.TButton",
        background=COLORS["window"],
        foreground="#cccccc",
        bordercolor=COLORS["window"],
        lightcolor=COLORS["window"],
        darkcolor=COLORS["window"],
        borderwidth=0,
        focusthickness=0,
        focuscolor=COLORS["window"],
        font=("Segoe UI Semibold", 10),
        padding=(11, 8),
        relief="flat",
    )
    style.map(
        "UtilityLink.TButton",
        background=[("active", COLORS["window"]), ("pressed", COLORS["window"])],
        foreground=[("active", COLORS["text"])],
        bordercolor=[("active", COLORS["window"]), ("pressed", COLORS["window"])],
        lightcolor=[("active", COLORS["window"]), ("pressed", COLORS["window"])],
        darkcolor=[("active", COLORS["window"]), ("pressed", COLORS["window"])],
        relief=[("pressed", "flat"), ("active", "flat")],
    )
    style.configure(
        "HelpTitle.TLabel",
        background=COLORS["window"],
        foreground=COLORS["text"],
        font=("Segoe UI Variable Display", 16, "bold"),
    )
    style.configure(
        "HelpHeading.TLabel",
        background=COLORS["window"],
        foreground=COLORS["accent_hover"],
        font=("Segoe UI Semibold", 10, "bold"),
    )
    style.configure(
        "HelpBody.TLabel",
        background=COLORS["window"],
        foreground=COLORS["text"],
        font=("Segoe UI", 9),
    )
    style.configure(
        "RecoveryLink.TButton",
        background=COLORS["window"],
        foreground=COLORS["danger_hover"],
        bordercolor=COLORS["window"],
        lightcolor=COLORS["window"],
        darkcolor=COLORS["window"],
        borderwidth=0,
        focusthickness=0,
        focuscolor=COLORS["window"],
        anchor="center",
        padding=(0, 4),
        relief="flat",
    )
    style.map(
        "RecoveryLink.TButton",
        background=[("active", COLORS["window"]), ("pressed", COLORS["window"]), ("disabled", COLORS["window"])],
        foreground=[("active", "#ffffff"), ("disabled", COLORS["disabled"])],
        bordercolor=[("active", COLORS["window"]), ("pressed", COLORS["window"]), ("disabled", COLORS["window"])],
        lightcolor=[("active", COLORS["window"]), ("pressed", COLORS["window"]), ("disabled", COLORS["window"])],
        darkcolor=[("active", COLORS["window"]), ("pressed", COLORS["window"]), ("disabled", COLORS["window"])],
        relief=[("pressed", "flat"), ("active", "flat")],
    )

    style.configure(
        "TEntry",
        fieldbackground=COLORS["field"],
        foreground=COLORS["text"],
        insertcolor=COLORS["text"],
        bordercolor=COLORS["border"],
        lightcolor=COLORS["field"],
        darkcolor=COLORS["field"],
        padding=(9, 8),
    )
    style.map(
        "TEntry",
        bordercolor=[("focus", COLORS["accent"])],
        fieldbackground=[("readonly", COLORS["field"])],
        foreground=[("readonly", COLORS["muted"])],
    )
    style.configure(
        "TCombobox",
        fieldbackground=COLORS["field"],
        background=COLORS["surface_hover"],
        foreground=COLORS["text"],
        arrowcolor=COLORS["muted"],
        bordercolor=COLORS["border"],
        lightcolor=COLORS["field"],
        darkcolor=COLORS["field"],
        padding=(8, 7),
    )
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", COLORS["field"])],
        foreground=[("readonly", COLORS["text"])],
        bordercolor=[("focus", COLORS["accent"])],
        arrowcolor=[("active", COLORS["accent"])],
    )
    style.configure(
        "Minimal.TCombobox",
        fieldbackground=COLORS["field"],
        background=COLORS["field"],
        foreground=COLORS["text"],
        arrowcolor=COLORS["muted"],
        bordercolor=COLORS["field"],
        lightcolor=COLORS["field"],
        darkcolor=COLORS["field"],
        arrowsize=14,
        padding=(8, 7),
        selectbackground=COLORS["field"],
        selectforeground=COLORS["text"],
    )
    style.configure(
        "ComboboxPopdownFrame",
        background=COLORS["field"],
        bordercolor=COLORS["field"],
        lightcolor=COLORS["field"],
        darkcolor=COLORS["field"],
        borderwidth=0,
        relief="flat",
    )
    style.map(
        "Minimal.TCombobox",
        fieldbackground=[("readonly", COLORS["field"])],
        background=[("readonly", COLORS["field"]), ("active", COLORS["field"])],
        foreground=[("readonly", COLORS["text"])],
        bordercolor=[("readonly", COLORS["field"]), ("focus", COLORS["field"])],
        arrowcolor=[("active", COLORS["accent"]), ("readonly", COLORS["muted"])],
        selectbackground=[("readonly", COLORS["field"])],
        selectforeground=[("readonly", COLORS["text"])],
    )
    root._combobox_spacer = PhotoImage(width=7, height=1)
    style.element_create("Minimal.Combobox.spacer", "image", root._combobox_spacer)
    style.layout(
        "Minimal.TCombobox",
        [
            ("Minimal.Combobox.spacer", {"side": "right", "sticky": "ns"}),
            ("Combobox.downarrow", {"side": "right", "sticky": "ns"}),
            (
                "Combobox.field",
                {
                    "sticky": "nswe",
                    "children": [
                        (
                            "Combobox.padding",
                            {
                                "sticky": "nswe",
                                "children": [("Combobox.textarea", {"sticky": "nswe"})],
                            },
                        )
                    ],
                },
            ),
        ],
    )
    style.configure(
        "OEMSource.TLabel",
        background=COLORS["prompt_surface"],
        foreground=COLORS["text"],
        anchor="center",
        padding=(0, 0),
        font=("Segoe UI", 9),
    )
    style.configure(
        "CustomSource.TLabel",
        background=COLORS["prompt_surface"],
        foreground="#ffad98",
        anchor="w",
        padding=(10, 0),
        font=("Segoe UI", 9),
    )
    style.configure(
        "OEMSourceHover.TLabel",
        background=COLORS["surface_hover"],
        foreground=COLORS["text"],
        anchor="center",
        padding=(0, 0),
        font=("Segoe UI", 9),
    )
    style.configure(
        "CustomSourceHover.TLabel",
        background=COLORS["surface_hover"],
        foreground="#ffad98",
        anchor="w",
        padding=(10, 0),
        font=("Segoe UI", 9),
    )
    style.configure(
        "Treeview",
        background=COLORS["field"],
        fieldbackground=COLORS["field"],
        foreground=COLORS["text"],
        bordercolor=COLORS["field"],
        lightcolor=COLORS["field"],
        darkcolor=COLORS["field"],
        borderwidth=0,
        relief="flat",
        focuscolor=COLORS["prompt_surface"],
        focusthickness=0,
        rowheight=30,
        font=("Segoe UI", 9),
    )
    style.configure(
        "Prompt.Treeview",
        background=COLORS["prompt_surface"],
        fieldbackground=COLORS["prompt_surface"],
        foreground=COLORS["text"],
        bordercolor=COLORS["prompt_surface"],
        lightcolor=COLORS["prompt_surface"],
        darkcolor=COLORS["prompt_surface"],
        borderwidth=0,
        relief="flat",
        rowheight=30,
        font=("Segoe UI", 9),
    )
    style.map("Treeview", background=[("selected", COLORS["selection"])], foreground=[("selected", "#ffffff")])
    style.map(
        "Prompt.Treeview",
        background=[("selected", COLORS["selection"])],
        foreground=[("selected", "#ffffff")],
        bordercolor=[("focus", COLORS["prompt_surface"])],
        lightcolor=[("focus", COLORS["prompt_surface"])],
        darkcolor=[("focus", COLORS["prompt_surface"])],
    )
    style.configure(
        "Treeview.Heading",
        background=COLORS["surface_hover"],
        foreground=COLORS["muted"],
        bordercolor=COLORS["border"],
        lightcolor=COLORS["surface_hover"],
        darkcolor=COLORS["surface_hover"],
        font=("Segoe UI Semibold", 9),
        padding=(8, 8),
        relief="flat",
    )
    style.map("Treeview.Heading", background=[("active", "#2a2a2a")])
    style.configure(
        "Vertical.TScrollbar",
        background=COLORS["surface_hover"],
        troughcolor=COLORS["prompt_surface"],
        bordercolor=COLORS["prompt_surface"],
        arrowcolor=COLORS["muted"],
        lightcolor=COLORS["surface_hover"],
        darkcolor=COLORS["surface_hover"],
    )
    style.configure(
        "Accent.Horizontal.TProgressbar",
        background=COLORS["accent"],
        troughcolor=COLORS["field"],
        bordercolor=COLORS["border"],
        lightcolor=COLORS["accent"],
        darkcolor=COLORS["accent"],
    )
    apply_dark_title_bar(root)
    return style
