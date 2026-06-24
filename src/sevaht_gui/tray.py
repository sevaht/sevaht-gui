"""Cross-platform tray-icon abstraction.

The application talks to a single :class:`TrayIcon` interface;
:func:`create_tray_icon` hides which backend implements it:

* Windows -> pystray.
* Linux -> StatusNotifierItem when a usable SNI host is present (KDE/GNOME,
  Wayland, or fluxbox with snixembed), otherwise the self-contained XEmbed
  backend. The Linux wrapper also transparently falls back from SNI to XEmbed
  if SNI registration fails at startup.

The tray exposes a deliberately small, two-action feature model:

* ``on_activate`` -- the default action (left-click, and the default menu item
  on backends that have a menu).
* ``on_quit`` -- the quit action.

Backends that can show a menu (pystray, SNI) offer both actions as menu items
on right-click. The XEmbed backend cannot show a menu, so right-click invokes
``on_quit`` directly. The icon and title/tooltip can be updated at any time, and
desktop notifications can be raised via :meth:`TrayIcon.notify`.
"""

from __future__ import annotations

import logging
import os
import re
import sys
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Callable

    from PIL import Image

    # Draws the icon natively at a requested square pixel size.
    IconRenderer = Callable[[int], Image.Image]
    # What callers may supply as an icon: an already-prepared PIL image, a path
    # to an image file (both static), or a renderer that draws at a given size
    # (dynamic). Static sources are the common case; the renderer is for apps
    # that draw their own icon, e.g. to encode live state in the artwork.
    IconSource = Image.Image | str | os.PathLike[str] | IconRenderer
    # Invoked once the tray event loop is ready, with the TrayIcon as argument.
    SetupCallback = Callable[[object], None]

logger = logging.getLogger(__name__)

# pystray draws from a fixed-size PIL image rather than a renderer; this is the
# square size we render it at and let the OS scale to the tray cell.
_PYSTRAY_ICON_SIZE = 64


class SNIRegistrationError(RuntimeError):
    """Raised when the SNI backend cannot register with a watcher at startup.

    Signals the Linux wrapper to fall back to the XEmbed backend, which needs
    no StatusNotifierItem host. Handled internally by :class:`_LinuxTrayIcon`.
    """


def _atom_safe_name(name: str) -> str:
    """Return ``name`` reduced to characters valid in an X11 atom name."""
    cleaned = re.sub(r"[^A-Za-z0-9]", "_", name).strip("_").upper()
    return cleaned or "SEVAHT_GUI"


def tray_available() -> bool:
    """Return True if a system tray a tray icon can dock into is present.

    Lets callers degrade gracefully (run without a tray icon) when no tray host
    exists -- e.g. a bare X11 session with no panel. On Windows the
    notification area is assumed always present.
    """
    if sys.platform == "win32":
        return True
    from ._tray_sni import sni_watcher_present

    if sni_watcher_present():
        return True

    from ._tray_xembed import xembed_host_present

    return xembed_host_present()


def as_renderer(icon: IconSource) -> IconRenderer:
    """Normalize any :data:`IconSource` to an :data:`IconRenderer`.

    A renderer is returned unchanged. A static source (PIL image or file path)
    is loaded once and wrapped in a renderer that returns it scaled to the
    requested size, so a fixed image works anywhere a renderer is expected.
    """
    if callable(icon):
        return icon

    from PIL import Image

    base = Image.open(icon) if isinstance(icon, (str, os.PathLike)) else icon
    base = base.convert("RGBA")

    def render(size: int) -> Image.Image:
        if base.size == (size, size):
            return base
        return base.resize((size, size), Image.Resampling.LANCZOS)

    return render


class TrayIcon(Protocol):
    """The tray-icon surface the application relies on, regardless of backend."""

    title: str

    def set_icon(self, icon: IconSource) -> None:
        """Replace the icon with any :data:`IconSource` (static or renderer)."""

    def notify(
        self, title: str, message: str, *, icon: str | None = None
    ) -> None:
        """Show a desktop notification.

        ``icon`` (a freedesktop icon name) is used where supported (Linux);
        Windows shows the tray icon's own image.
        """

    def run(self, setup: SetupCallback | None = None) -> None:
        """Run the tray event loop, calling ``setup`` once it is ready."""

    def stop(self) -> None:
        """Stop the tray event loop."""


class _PystrayIcon:
    """Adapt :class:`pystray.Icon` to :class:`TrayIcon` (Windows)."""

    def __init__(  # noqa: PLR0913
        self,
        name: str,
        title: str,
        icon: IconSource,
        *,
        on_activate: Callable[[], None] | None,
        on_quit: Callable[[], None] | None,
        activate_label: str,
        quit_label: str,
    ) -> None:
        import pystray

        items = []
        if on_activate is not None:
            items.append(
                pystray.MenuItem(
                    activate_label, lambda _i, _it: on_activate(), default=True
                )
            )
        if on_quit is not None:
            items.append(
                pystray.MenuItem(quit_label, lambda _i, _it: on_quit())
            )
        self._icon = pystray.Icon(
            name,
            icon=as_renderer(icon)(_PYSTRAY_ICON_SIZE),
            title=title,
            menu=pystray.Menu(*items),
        )

    def set_icon(self, icon: IconSource) -> None:
        self._icon.icon = as_renderer(icon)(_PYSTRAY_ICON_SIZE)

    def notify(
        self,
        title: str,
        message: str,
        *,
        icon: str | None = None,  # noqa: ARG002
    ) -> None:
        # pystray shows the tray icon's image; it has no icon-name parameter.
        self._icon.notify(message, title)

    @property
    def title(self) -> str:
        return str(self._icon.title)

    @title.setter
    def title(self, value: str) -> None:
        self._icon.title = value

    def run(self, setup: SetupCallback | None = None) -> None:
        def _setup(icon: object) -> None:
            # pystray icons start hidden; show ours once the loop is live (also
            # the only point at which the Windows HICON can be set/updated).
            self._icon.visible = True
            if setup is not None:
                setup(icon)

        self._icon.run(setup=_setup)

    def stop(self) -> None:
        self._icon.stop()


class _LinuxTrayIcon:
    """The Linux tray: StatusNotifierItem with a transparent XEmbed fallback.

    Tracks the current title/renderer so that, if SNI registration fails and we
    rebuild on the XEmbed backend, the rebuilt icon reflects the latest state.
    """

    def __init__(  # noqa: PLR0913
        self,
        name: str,
        title: str,
        icon: IconSource,
        *,
        on_activate: Callable[[], None] | None,
        on_quit: Callable[[], None] | None,
        activate_label: str,
        quit_label: str,
    ) -> None:
        self._name = name
        self._title = title
        # Normalize once up front: a file source is then read a single time,
        # even if we later rebuild on the XEmbed backend after an SNI failure.
        self._render_icon = as_renderer(icon)
        self._on_activate = on_activate
        self._on_quit = on_quit
        self._activate_label = activate_label
        self._quit_label = quit_label
        self._backend: TrayIcon = self._make_backend()

    def _make_backend(self, *, force_xembed: bool = False) -> TrayIcon:
        if not force_xembed:
            from ._tray_sni import SNITrayIcon, sni_watcher_present

            if sni_watcher_present():
                return SNITrayIcon(
                    self._name,
                    self._title,
                    self._render_icon,
                    on_activate=self._on_activate,
                    on_secondary=self._on_activate,
                    on_quit=self._on_quit,
                    activate_label=self._activate_label,
                    quit_label=self._quit_label,
                )

        from ._tray_xembed import XEmbedTrayIcon

        return XEmbedTrayIcon(
            self._name,
            self._title,
            self._render_icon,
            on_activate=self._on_activate,
            on_quit=self._on_quit,
        )

    def set_icon(self, icon: IconSource) -> None:
        self._render_icon = as_renderer(icon)
        self._backend.set_icon(self._render_icon)

    def notify(
        self, title: str, message: str, *, icon: str | None = None
    ) -> None:
        self._backend.notify(title, message, icon=icon)

    @property
    def title(self) -> str:
        return self._backend.title

    @title.setter
    def title(self, value: str) -> None:
        self._title = value
        self._backend.title = value

    def run(self, setup: SetupCallback | None = None) -> None:
        try:
            self._backend.run(setup)
        except SNIRegistrationError:
            logger.warning(
                "StatusNotifierItem registration failed; "
                "falling back to the XEmbed tray icon"
            )
            self._backend = self._make_backend(force_xembed=True)
            self._backend.run(setup)

    def stop(self) -> None:
        self._backend.stop()


def create_tray_icon(  # noqa: PLR0913
    name: str,
    title: str,
    icon: IconSource,
    *,
    on_activate: Callable[[], None] | None = None,
    on_quit: Callable[[], None] | None = None,
    activate_label: str = "Open",
    quit_label: str = "Quit",
) -> TrayIcon:
    """Create the platform-appropriate tray icon behind :class:`TrayIcon`.

    ``name`` is a machine-friendly identifier (used for the SNI item id and the
    XEmbed window class); ``title`` is the human-readable tooltip. ``icon`` is
    any :data:`IconSource` -- a prepared PIL image, an image file path, or a
    renderer; swap it later with :meth:`TrayIcon.set_icon` to reflect state.
    ``on_activate`` is the default action (left-click / default menu item) and
    ``on_quit`` is the quit action; either may be omitted. ``activate_label`` /
    ``quit_label`` are the menu labels used by backends that show a menu.
    """
    if sys.platform == "win32":
        return _PystrayIcon(
            name,
            title,
            icon,
            on_activate=on_activate,
            on_quit=on_quit,
            activate_label=activate_label,
            quit_label=quit_label,
        )
    return _LinuxTrayIcon(
        name,
        title,
        icon,
        on_activate=on_activate,
        on_quit=on_quit,
        activate_label=activate_label,
        quit_label=quit_label,
    )
