"""Reusable tkinter widgets."""

from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk


class LabelGrooveFrame(tk.LabelFrame):
    """A ``tk.LabelFrame`` with a groove border and theme-matched background.

    Exposes an :attr:`interior` frame whose bottom padding compensates for the
    label inset, so content appears vertically centered within the border.
    """

    def __init__(self, parent: tk.Widget, *, text: str = "") -> None:
        background = ttk.Style().lookup("TFrame", "background")
        super().__init__(
            parent,
            text=text,
            relief="groove",
            borderwidth=2,
            background=background,
        )
        inset = tkfont.nametofont("TkDefaultFont").metrics("linespace") // 2
        self.interior = ttk.Frame(self)
        self.interior.pack(fill=tk.BOTH, expand=True, pady=(0, inset))
