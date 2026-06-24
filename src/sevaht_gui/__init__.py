"""Small cross-platform GUI building blocks.

Submodules:

* :mod:`sevaht_gui.tray` -- a cross-platform system-tray icon
  (:func:`~sevaht_gui.tray.create_tray_icon`) backed by pystray on Windows and
  StatusNotifierItem/XEmbed on Linux.
* :mod:`sevaht_gui.tkapp` -- :class:`~sevaht_gui.tkapp.TkApp`, a tkinter base
  that owns the main thread and runs a tray icon on a worker thread.
* :mod:`sevaht_gui.theme` -- default ttk theming (clam + checkmark indicator).
* :mod:`sevaht_gui.widgets` -- reusable widgets (e.g. ``LabelGrooveFrame``).
* :mod:`sevaht_gui.monitors` -- monitor geometry
  (:func:`~sevaht_gui.monitors.primary_monitor_bounds`).

:meth:`~sevaht_gui.tkapp.TkApp.notify` shows a desktop notification, using the
tray icon when one exists and falling back to a standalone notifier otherwise,
so notifications work with or without a tray.

Attributes:
    __version__: The installed distribution version.
"""

from __future__ import annotations

import importlib.metadata

from .monitors import primary_monitor_bounds
from .theme import apply_theme
from .tkapp import TkApp, WindowPlacement
from .tray import (
    SNIRegistrationError,
    TrayIcon,
    as_renderer,
    create_tray_icon,
    tray_available,
)
from .widgets import LabelGrooveFrame

__version__ = importlib.metadata.version(__package__)

__all__ = [
    "LabelGrooveFrame",
    "SNIRegistrationError",
    "TkApp",
    "TrayIcon",
    "WindowPlacement",
    "__version__",
    "apply_theme",
    "as_renderer",
    "create_tray_icon",
    "primary_monitor_bounds",
    "tray_available",
]
