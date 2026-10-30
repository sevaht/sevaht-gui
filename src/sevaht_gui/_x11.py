"""Asking an EWMH window manager to activate a window (X11 only).

Tk's ``focus_force`` is a bare ``XSetInputFocus``: it works on an X server
where clients control the focus, but not where a compositor owns it (XWayland
-- the X11 windows of a Wayland desktop -- or any window manager that guards
against focus stealing), and ``lift`` is only a raise. The standard way for an
X11 application to ask for focus is the EWMH ``_NET_ACTIVE_WINDOW`` client
message to the root window, which is what GTK and Qt send when a window is
presented. The window manager then decides, as it does for any other request.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from Xlib.display import Display

logger = logging.getLogger(__name__)

# The message's "source indication": a normal application, not a pager.
_SOURCE_APPLICATION = 1


def _managed_window(display: Display, window_id: int) -> int:
    """The window the window manager manages, given one inside it.

    Tk puts a toplevel's widget window inside a wrapper window of its own and
    gives the wrapper the properties a window manager reads (WM_CLASS...), so
    that is the window an activation request must name, not ``winfo_id()``.
    It is the nearest enclosing window, this one included, that has them (a
    reparenting window manager's frame, further out, does not).
    """
    import Xlib.X

    wm_class = display.intern_atom("WM_CLASS")
    root = display.screen().root.id
    window = display.create_resource_object("window", window_id)
    while window.id != root:
        if window.get_full_property(wm_class, Xlib.X.AnyPropertyType):
            return int(window.id)
        parent = window.query_tree().parent
        if not parent:
            break
        window = parent
    return window_id


def request_activation(
    window_id: int, activation_token: str | None = None
) -> bool:
    """Send ``_NET_ACTIVE_WINDOW`` for the window holding ``window_id``.

    ``window_id`` is a Tk widget window (``winfo_id()``). With an xdg-activation
    token (what the tray host gave for the user's click), the window's
    ``_NET_STARTUP_ID`` is set to it first, as xdg-activation says an X11
    client presents one: the compositor then knows the user asked. Returns True
    if the message was sent. Needs python-xlib and an X display (both only on
    Linux); on anything else it does nothing and returns False.
    """
    try:
        import Xlib.display
        import Xlib.X
    except ImportError:
        return False
    try:
        display = Xlib.display.Display()
    except Exception:  # noqa: BLE001
        logger.debug("Could not open the X display", exc_info=True)
        return False
    try:
        root = display.screen().root
        managed = _managed_window(display, window_id)
        if activation_token:
            # On this connection, so that it is set before the message
            display.create_resource_object("window", managed).change_property(
                display.intern_atom("_NET_STARTUP_ID"),
                display.intern_atom("UTF8_STRING"),
                8,
                activation_token.encode(),
            )
        message = Xlib.display.event.ClientMessage(
            type=Xlib.X.ClientMessage,
            client_type=display.intern_atom("_NET_ACTIVE_WINDOW"),
            window=managed,
            # source, timestamp, the window that is active (unknown: none)
            data=(32, (_SOURCE_APPLICATION, Xlib.X.CurrentTime, 0, 0, 0)),
        )
        display.send_event(
            root,
            message,
            event_mask=(
                Xlib.X.SubstructureRedirectMask | Xlib.X.SubstructureNotifyMask
            ),
        )
        display.flush()
    except Exception:  # noqa: BLE001
        logger.debug("Could not request activation", exc_info=True)
        return False
    finally:
        display.close()
    return True
