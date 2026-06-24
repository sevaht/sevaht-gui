"""Monitor geometry, multi-monitor aware.

tkinter has no native Wayland backend, so on Wayland it runs under XWayland and
the X11 RandR *extension* is available. This queries RandR through python-xlib
(already a Linux dependency) rather than shelling out to the ``xrandr`` binary,
which may not be installed; it therefore works under both X11 and XWayland.

Falls back to the full Tk screen size, which is correct for single-monitor
setups and for Windows (where Tk reports the primary monitor).
"""

from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import tkinter as tk

logger = logging.getLogger(__name__)


def primary_monitor_bounds(root: tk.Misc) -> tuple[int, int, int, int]:
    """Return the primary monitor's ``(x, y, width, height)`` in pixels.

    ``root`` is any Tk widget, used both to talk to the display and for the
    fallback screen size.
    """
    bounds = _x11_primary_bounds()
    if bounds is not None:
        return bounds
    return (0, 0, root.winfo_screenwidth(), root.winfo_screenheight())


def _x11_primary_bounds() -> tuple[int, int, int, int] | None:
    if sys.platform == "win32":
        return None
    try:
        from Xlib import display as xdisplay
    except ImportError:
        return None

    connection = None
    try:
        connection = xdisplay.Display()
        root = connection.screen().root
        resources = root.xrandr_get_screen_resources()
        timestamp = resources.config_timestamp
        primary = root.xrandr_get_output_primary().output
        # Prefer the primary output; otherwise the first active one.
        outputs = (
            [primary, *resources.outputs] if primary else resources.outputs
        )
        for output in outputs:
            if not output:
                continue
            info = connection.xrandr_get_output_info(output, timestamp)
            if not info.crtc:
                continue
            crtc = connection.xrandr_get_crtc_info(info.crtc, timestamp)
            if crtc.width and crtc.height:
                return (crtc.x, crtc.y, crtc.width, crtc.height)
    except Exception:  # noqa: BLE001
        logger.debug("Could not query RandR for monitor bounds", exc_info=True)
        return None
    finally:
        if connection is not None:
            connection.close()
    return None
