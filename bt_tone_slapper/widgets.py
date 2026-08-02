from __future__ import annotations

from collections.abc import Callable
from tkinter import Canvas, Misc, PhotoImage

from .resources import asset_path
from .theme import COLORS


class ProgressButton(Canvas):
    def __init__(
        self,
        master: Misc,
        *,
        text: str,
        command: Callable[[], None],
        height: int = 38,
    ) -> None:
        super().__init__(
            master,
            height=height,
            background=COLORS["surface"],
            highlightthickness=0,
            borderwidth=0,
            cursor="hand2",
        )
        self._default_text = text
        self._text = text
        self._command = command
        self._enabled = True
        self._busy = False
        self._complete = False
        self._hovered = False
        self._progress = 0.0
        self.bind("<Configure>", lambda _: self._draw())
        self.bind("<Enter>", self._enter)
        self.bind("<Leave>", self._leave)
        self.bind("<Button-1>", self._click)

    def _enter(self, _event) -> None:
        self._hovered = True
        self._draw()

    def _leave(self, _event) -> None:
        self._hovered = False
        self._draw()

    def _click(self, _event) -> None:
        if self._enabled and not self._busy and not self._complete:
            self._command()

    def _draw(self) -> None:
        width = max(1, self.winfo_width())
        height = max(1, self.winfo_height())
        if self._complete:
            base = COLORS["success"]
            foreground = "#ffffff"
        elif self._busy:
            base = COLORS["surface_hover"]
            foreground = "#ffffff"
        elif not self._enabled:
            base = "#2a2a2a"
            foreground = COLORS["disabled"]
        elif self._hovered:
            base = COLORS["accent_hover"]
            foreground = "#ffffff"
        else:
            base = COLORS["accent"]
            foreground = "#ffffff"

        self.delete("all")
        self.create_rectangle(0, 0, width, height, fill=base, outline="")
        if self._busy and self._progress > 0:
            fill_width = max(2, round(width * self._progress))
            self.create_rectangle(
                0,
                0,
                fill_width,
                height,
                fill=COLORS["accent"],
                outline="",
            )
        self.create_text(
            width / 2,
            height / 2,
            text=self._text,
            fill=foreground,
            font=("Segoe UI Semibold", 9),
        )
        self.configure(
            cursor="hand2"
            if self._enabled and not self._busy and not self._complete
            else "arrow"
        )

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        self._draw()

    def begin(self, text: str) -> None:
        self._complete = False
        self._busy = True
        self._progress = 0.02
        self._text = text
        self._draw()

    def set_progress(self, fraction: float, text: str) -> None:
        self._complete = False
        self._busy = True
        self._progress = min(1.0, max(0.0, fraction))
        self._text = text
        self._draw()

    def complete(self, text: str = "Success!") -> None:
        self._busy = False
        self._complete = True
        self._progress = 1.0
        self._text = text
        self._draw()

    def reset(self, *, enabled: bool) -> None:
        self._busy = False
        self._complete = False
        self._progress = 0.0
        self._text = self._default_text
        self._enabled = enabled
        self._draw()


class ResetButton(Canvas):
    def __init__(
        self,
        master: Misc,
        *,
        command: Callable[[], None],
    ) -> None:
        super().__init__(
            master,
            background=COLORS["prompt_surface"],
            highlightthickness=0,
            borderwidth=0,
            takefocus=False,
        )
        self._command = command
        self._enabled = True
        self._hovered = False
        self._row_hovered = False
        self._icons = {
            "normal": PhotoImage(file=str(asset_path("icons/material_refresh_accent_18.png"))),
            "hover": PhotoImage(file=str(asset_path("icons/material_refresh_hover_18.png"))),
            "disabled": PhotoImage(file=str(asset_path("icons/material_refresh_disabled_18.png"))),
        }
        self.bind("<Configure>", lambda _: self._draw())
        self.bind("<Enter>", self._enter)
        self.bind("<Leave>", self._leave)
        self.bind("<Button-1>", self._click)

    def _enter(self, _event) -> None:
        self._hovered = True
        self._draw()

    def _leave(self, _event) -> None:
        self._hovered = False
        self._draw()

    def _click(self, _event) -> None:
        if self._enabled:
            self._command()

    def _draw(self) -> None:
        height = max(1, self.winfo_height())
        center_y = height / 2
        if self._enabled:
            icon = self._icons["hover" if self._hovered else "normal"]
            text_color = COLORS["text"] if self._hovered else COLORS["muted"]
        else:
            icon = self._icons["disabled"]
            text_color = COLORS["disabled"]

        self.configure(
            background=(
                COLORS["surface_hover"]
                if self._row_hovered
                else COLORS["prompt_surface"]
            )
        )
        self.delete("all")
        self.create_image(13, center_y, image=icon)
        self.create_text(
            27,
            center_y,
            text="Reset",
            anchor="w",
            fill=text_color,
            font=("Segoe UI Semibold", 8),
        )
        self.configure(cursor="hand2" if self._enabled else "arrow")

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        self._draw()

    def set_row_hover(self, hovered: bool) -> None:
        self._row_hovered = hovered
        self._draw()
