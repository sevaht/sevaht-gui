"""Default fonts for sevaht-gui windows on X11, and a check for a Tk without Xft.

On X11 a Tk built with Xft (every distro's) draws fontconfig fonts -- the ones
installed on the system, antialiased. A Tk built *without* it (notably the one
bundled by python-build-standalone, which is what ``uv`` downloads) can only
use the legacy X core fonts, which a modern desktop hardly has: every request
then falls back to the X server's ``fixed`` and the window looks wrong
whatever font is asked for. Nothing at run time can change that, so
:func:`tk_lacks_xft` lets an application say so (:class:`~sevaht_gui.TkApp`
logs a warning), and the cure is a Python whose Tk has Xft (a distro's).

With Xft, Tk's default fonts follow fontconfig's default sans, which is
usually fine. :func:`apply_default_font` instead picks the first of a list of
preferred families that is installed, for a consistent look across systems,
and leaves Tk alone when none is.
"""

from __future__ import annotations

import logging
import sys
import tkinter as tk
from tkinter import font as tkfont
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

logger = logging.getLogger(__name__)

# What the application's text is drawn in: the first of these that is
# installed (names compare without regard to case).
DEFAULT_FONT_FAMILIES: tuple[str, ...] = (
    "Noto Sans",
    "DejaVu Sans",
    "Liberation Sans",
    "Cantarell",
)

# Tk's named fonts that carry the application's text (not TkFixedFont).
_TEXT_FONTS = (
    "TkDefaultFont",
    "TkTextFont",
    "TkMenuFont",
    "TkHeadingFont",
    "TkCaptionFont",
    "TkSmallCaptionFont",
    "TkIconFont",
    "TkTooltipFont",
)


def choose_family(
    available: Iterable[str], preferred: Sequence[str]
) -> str | None:
    """The first of ``preferred`` that is in ``available`` (as written there)."""
    by_name = {name.casefold(): name for name in available}
    for family in preferred:
        if family.casefold() in by_name:
            return by_name[family.casefold()]
    return None


def _x11(root: tk.Misc) -> bool:
    return str(root.tk.call("tk", "windowingsystem")) == "x11"


def tk_lacks_xft(root: tk.Misc) -> bool:
    """True if this is an X11 Tk that cannot draw fontconfig (Xft) fonts."""
    if not _x11(root):
        return False
    try:
        return str(root.tk.eval("tk::pkgconfig get fontsystem")) != "xft"
    except tk.TclError:
        return False  # cannot tell; assume it is fine


def warn_if_no_xft(root: tk.Misc) -> bool:
    """Log a warning and return True if the Tk cannot draw fontconfig fonts."""
    if not tk_lacks_xft(root):
        return False
    logger.warning(
        "This Python's Tk was built without Xft, so it cannot use the "
        "system's fonts and text will look wrong. Run on a Python whose Tk "
        "has it, such as your distribution's (/usr/bin/python3), instead of "
        "a standalone build such as one downloaded by uv "
        "(e.g. `uv tool install --python /usr/bin/python3 ...`)."
    )
    return True


def apply_default_font(
    root: tk.Misc,
    families: Sequence[str] = DEFAULT_FONT_FAMILIES,
) -> str | None:
    """Use the first installed of ``families`` for Tk's text fonts (X11).

    Sizes and weights are kept; only the family changes. Returns the family
    used, or ``None`` when nothing was changed: not X11 (Windows and macOS
    have their own system fonts), no Xft, none of the families installed.
    """
    if sys.platform in {"win32", "darwin"} or not _x11(root):
        return None
    if tk_lacks_xft(root):
        return None
    family = choose_family(tkfont.families(root), families)
    if family is None:
        return None
    for name in _TEXT_FONTS:
        tkfont.nametofont(name, root=root).configure(family=family)
    return family
