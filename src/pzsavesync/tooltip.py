"""Info-bulle simple pour widgets tk/customtkinter."""
from __future__ import annotations

import tkinter as tk


class Tooltip:
    """Survoler le widget pendant ~400 ms affiche une bulle d'info."""

    def __init__(self, widget, text: str, delay_ms: int = 400, wraplength: int = 320):
        self.widget = widget
        self.text = text
        self.delay = delay_ms
        self.wraplength = wraplength
        self._after_id: str | None = None
        self._tip: tk.Toplevel | None = None
        widget.bind("<Enter>", self._on_enter, add="+")
        widget.bind("<Leave>", self._on_leave, add="+")
        widget.bind("<ButtonPress>", self._on_leave, add="+")

    def _on_enter(self, _event=None):
        self._schedule()

    def _on_leave(self, _event=None):
        self._unschedule()
        self._hide()

    def _schedule(self):
        self._unschedule()
        self._after_id = self.widget.after(self.delay, self._show)

    def _unschedule(self):
        if self._after_id is not None:
            try:
                self.widget.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

    def _show(self):
        if self._tip is not None:
            return
        try:
            x = self.widget.winfo_rootx() + 16
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        except Exception:
            return
        self._tip = tk.Toplevel(self.widget)
        self._tip.wm_overrideredirect(True)
        self._tip.wm_geometry(f"+{x}+{y}")
        self._tip.configure(bg="#1e1e1e")
        label = tk.Label(
            self._tip,
            text=self.text,
            justify="left",
            background="#1e1e1e",
            foreground="#e6e6e6",
            relief="solid",
            borderwidth=1,
            padx=8, pady=6,
            wraplength=self.wraplength,
            font=("Segoe UI", 9),
        )
        label.pack()

    def _hide(self):
        if self._tip is not None:
            try:
                self._tip.destroy()
            except Exception:
                pass
            self._tip = None


def attach(widget, text: str, **kwargs) -> Tooltip:
    return Tooltip(widget, text, **kwargs)
