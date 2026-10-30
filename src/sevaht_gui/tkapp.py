"""A tkinter application base that owns the main thread (Option A).

tkinter is not thread-safe: every widget call must happen on the one thread
that created the root, and on macOS/Windows that loop is happiest on the main
thread. So :class:`TkApp` runs ``root.mainloop()`` on the thread that
constructed it (the main thread) and runs a cross-platform tray icon -- which
brings its own event loop -- on a *worker* thread instead.

Work originating off the UI thread (e.g. a tray menu callback, fired on the
tray worker thread) must be marshalled back with :meth:`run_on_ui_thread` /
:meth:`call_on_ui_thread`. A periodic poll drains that queue and, as a side
effect, gives the interpreter a chance to run signal handlers while the C-level
mainloop is blocked.
"""

from __future__ import annotations

import contextlib
import logging
import queue
import signal
import tkinter as tk
from threading import Event, Thread, get_ident
from tkinter import ttk
from typing import TYPE_CHECKING, Any

from sevaht_utility.notifications import notify as _notify

from ._x11 import request_activation
from .fonts import DEFAULT_FONT_FAMILIES, apply_default_font, warn_if_no_xft
from .monitors import primary_monitor_bounds as _primary_monitor_bounds
from .theme import DEFAULT_THEME, apply_theme
from .tray import as_renderer, tray_available
from .tray import create_tray_icon as _create_tray_icon

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from PIL import Image

    from .tray import IconSource, TrayIcon

logger = logging.getLogger(__name__)

_DEFAULT_POLL_INTERVAL_MS = 25
_UI_CALL_TIMEOUT_S = 5.0
# Size the window/title-bar icon is rendered at before handing it to Tk; the
# window manager scales it to whatever the title bar / task switcher needs.
_WINDOW_ICON_SIZE = 64
# Width (px) at which the confirm dialog's message wraps, so a long message
# wraps to multiple lines instead of stretching the dialog arbitrarily wide.
_CONFIRM_WRAPLENGTH = 320
# Default quit-confirmation prompt; pass quit_confirm=None to quit immediately.
DEFAULT_QUIT_CONFIRM = "Are you sure you want to quit?"


class WindowPlacement:
    """Remembers a toplevel's on-screen position across hide/recreate cycles.

    Call :meth:`remember` before hiding or destroying a window and :meth:`apply`
    after showing or re-creating it, so it reopens where it was left.
    :attr:`position` is plain ``(x, y)`` data you can store in config and
    restore via the constructor; nothing is persisted automatically.

    :class:`TkApp` uses one of these for its main window; create your own for
    any additional toplevels you want to behave the same way.
    """

    def __init__(self, position: tuple[int, int] | None = None) -> None:
        self.position = position

    def remember(self, window: tk.Tk | tk.Toplevel) -> None:
        """Capture ``window``'s position if it is currently on screen."""
        with contextlib.suppress(tk.TclError):
            if str(window.state()) != "withdrawn":
                self.position = (window.winfo_x(), window.winfo_y())

    def apply(self, window: tk.Tk | tk.Toplevel) -> bool:
        """Move ``window`` to the remembered position; return whether one was set."""
        if self.position is None:
            return False
        with contextlib.suppress(tk.TclError):
            window.geometry(f"+{self.position[0]}+{self.position[1]}")
        return True


class TkApp:
    """Owns a :class:`tkinter.Tk` root and runs its loop on the main thread.

    Construct this on the main thread, build your widgets on ``self.root``, then
    call :meth:`run` (optionally passing a tray icon to run alongside it).

    Sensible defaults (each overridable via the constructor / method args):

    * a ttk theme with proper checkbox indicators;
    * on X11, text in the first installed of ``font_families`` (Noto Sans,
      DejaVu Sans...; ``None`` leaves Tk's fonts alone), and a logged warning
      when this Python's Tk has no Xft and so cannot use the system's fonts
      at all (see :mod:`sevaht_gui.fonts`);
    * the window is centered on the primary monitor the first time it is shown
      (``center_on_show``), then re-opens where it was last positioned;
    * :meth:`quit` asks for confirmation (``quit_confirm``);
    * :meth:`create_tray_icon` also sets the window's title-bar icon to match
      the tray icon (``window_icon``);
    * once a tray icon exists, the window-close button hides the window (the
      tray houses it); with no tray it quits instead;
    * :meth:`notify` shows a desktop notification via the tray when present and
      a standalone notifier otherwise (so it works with or without a tray).

    To persist the window position across runs, read :attr:`window_position`
    when saving config and pass it back as ``window_position`` next launch; the
    library never writes it to disk itself.
    """

    def __init__(  # noqa: PLR0913
        self,
        *,
        theme: str | None = DEFAULT_THEME,
        font_families: Sequence[str] | None = DEFAULT_FONT_FAMILIES,
        checkmark_indicator: bool = True,
        quit_confirm: str | None = DEFAULT_QUIT_CONFIRM,
        quit_confirm_title: str = "Quit",
        center_on_show: bool = True,
        window_position: tuple[int, int] | None = None,
        poll_interval_ms: int = _DEFAULT_POLL_INTERVAL_MS,
    ) -> None:
        self.root = tk.Tk()
        # A Tk with no Xft cannot use the system's fonts: say so once
        warn_if_no_xft(self.root)
        if font_families is not None:
            apply_default_font(self.root, font_families)
        if theme is not None:
            apply_theme(theme, checkmark_indicator=checkmark_indicator)
        self._poll_interval_ms = poll_interval_ms
        self._center_on_show = center_on_show
        # Remembers the main window's position; restored on show, captured on
        # hide (seeded from window_position to persist across runs).
        self._placement = WindowPlacement(window_position)
        self._ui_thread_id = get_ident()
        self._queue: queue.SimpleQueue[Any] = queue.SimpleQueue()
        self._closed = Event()
        self._poll_after_id: str | None = None
        # Retains the current window-icon image so Tk does not garbage-collect
        # it out from under the toplevel.
        self._icon_photo: Any = None
        # Windows kept in sync with set_window_icon (the root plus any tracked
        # toplevels, e.g. the confirm dialog), so a live icon change updates
        # them all.
        self._icon_targets: list[tk.Tk | tk.Toplevel] = [self.root]
        self._tray: TrayIcon | None = None
        # The tray host's xdg-activation token of the click that is about to
        # show the window (set from the tray's thread, used by show()).
        self._activation_token: str | None = None
        # Name used for the standalone notification fallback; captured from
        # create_tray_icon so app.notify works even when no tray is created.
        self._app_name: str | None = None
        self._quit_confirm = quit_confirm
        self._quit_confirm_title = quit_confirm_title
        # Closing the window hides it if a tray houses it, else quits.
        self.root.protocol("WM_DELETE_WINDOW", self._on_window_close)

    @property
    def has_tray(self) -> bool:
        """True if a tray icon was successfully created via this app."""
        return self._tray is not None

    @property
    def window_position(self) -> tuple[int, int] | None:
        """The window's ``(x, y)`` -- current if on screen, else last known.

        Save this in your config and pass it back as ``window_position`` to
        re-open the window where it was left between runs.
        """
        if str(self.root.state()) != "withdrawn":
            with contextlib.suppress(tk.TclError):
                return (self.root.winfo_x(), self.root.winfo_y())
        return self._placement.position

    def _place_window(self) -> None:
        # Restore the remembered position, else center on first appearance.
        if not self._placement.apply(self.root) and self._center_on_show:
            self.center_window(self.root)

    # -- thread marshalling ----------------------------------------------

    def _on_ui_thread(self) -> bool:
        return get_ident() == self._ui_thread_id

    def run_on_ui_thread(self, callback: Callable[[], object]) -> None:
        """Schedule ``callback`` to run on the UI thread (fire and forget)."""
        if self._closed.is_set():
            return
        if self._on_ui_thread():
            callback()
            return
        self._queue.put((callback, None, None))

    def call_on_ui_thread(
        self,
        callback: Callable[[], object],
        *,
        timeout: float = _UI_CALL_TIMEOUT_S,
    ) -> object:
        """Run ``callback`` on the UI thread and return its result.

        Returns ``None`` if the app is shutting down or the call times out.
        """
        if self._closed.is_set():
            return None
        if self._on_ui_thread():
            return callback()
        done = Event()
        result: list[object] = []
        self._queue.put((callback, done, result))
        done.wait(timeout=timeout)
        return result[0] if result else None

    def _poll_queue(self) -> None:
        while True:
            try:
                callback, done, result = self._queue.get_nowait()
            except queue.Empty:
                break
            try:
                value = callback()
                if result is not None:
                    result.append(value)
            except Exception:  # noqa: BLE001
                # A queued UI callback may raise anything; one bad callback
                # must not tear down the Tk event loop, so swallow and log it.
                logger.debug("Error in UI callback", exc_info=True)
            finally:
                if done is not None:
                    done.set()
        if not self._closed.is_set():
            self._poll_after_id = self.root.after(
                self._poll_interval_ms, self._poll_queue
            )

    # -- window icon ------------------------------------------------------

    def set_window_icon(self, icon: IconSource) -> None:
        """Set (or replace) the window/title-bar icon from any IconSource.

        Accepts a prepared PIL image, an image file path, or a renderer; call
        it again to change the icon (e.g. to reflect state).
        """
        image = as_renderer(icon)(_WINDOW_ICON_SIZE)
        self.run_on_ui_thread(lambda: self._apply_window_icon(image))

    def set_tray_icon(self, icon: IconSource) -> None:
        """Set (or replace) the tray icon's image, if a tray icon exists."""
        if self._tray is not None:
            self._tray.set_icon(icon)

    def set_app_icon(self, icon: IconSource) -> None:
        """Set both the window icon and the tray icon (if any) at once.

        A convenience for keeping them in sync. To control them independently
        -- or use different images -- call :meth:`set_window_icon` and
        :meth:`set_tray_icon` separately instead.
        """
        self.set_window_icon(icon)
        self.set_tray_icon(icon)

    def _apply_window_icon(self, image: Image.Image) -> None:
        from PIL import ImageTk

        photo: Any = ImageTk.PhotoImage(image)
        self._icon_photo = photo
        for window in self._icon_targets:
            with contextlib.suppress(tk.TclError):
                # default=True on the root also seeds future toplevels.
                window.iconphoto(window is self.root, photo)

    def track_window_icon(self, window: tk.Tk | tk.Toplevel) -> None:
        """Keep ``window``'s title-bar icon in sync with :meth:`set_window_icon`.

        Applies the current icon immediately and updates it whenever the icon
        changes, until ``window`` is destroyed. Useful for dialogs/toplevels
        that should mirror the main window's (possibly state-dependent) icon.
        """
        self._icon_targets.append(window)
        if self._icon_photo is not None:
            with contextlib.suppress(tk.TclError):
                window.iconphoto(False, self._icon_photo)

        def _untrack(event: tk.Event[tk.Misc]) -> None:
            if event.widget is window and window in self._icon_targets:
                self._icon_targets.remove(window)

        window.bind("<Destroy>", _untrack, add="+")

    # -- tray + quit ------------------------------------------------------

    def create_tray_icon(  # noqa: PLR0913
        self,
        name: str,
        title: str,
        icon: IconSource,
        *,
        on_activate: Callable[[], None] | None = None,
        on_quit: Callable[[], None] | None = None,
        activate_label: str = "Open",
        quit_label: str = "Quit",
        window_icon: bool = True,
        tooltip: str | None = None,
    ) -> TrayIcon | None:
        """Create a tray icon bound to this app, or ``None`` if no tray exists.

        When no system tray is available the app keeps working without one (the
        window close button then quits instead of hiding). ``on_activate``
        defaults to :meth:`show` and ``on_quit`` to :meth:`quit`. ``window_icon``
        (default) also sets the window's title-bar icon to ``icon`` so the two
        match; pass ``False`` to manage the window icon separately. ``tooltip``
        is what shows on hover when it should differ from ``title`` (the
        name); change it later through the icon's ``tooltip``. Pass the
        result to :meth:`run`.
        """
        self._app_name = name
        if window_icon:
            self.set_window_icon(icon)
        if not tray_available():
            logger.info(
                "No system tray available; continuing without a tray icon"
            )
            self._tray = None
            return None
        self._tray = _create_tray_icon(
            name,
            title,
            icon,
            on_activate=on_activate if on_activate is not None else self.show,
            on_quit=on_quit if on_quit is not None else self.quit,
            activate_label=activate_label,
            quit_label=quit_label,
            tooltip=tooltip,
            on_activation_token=self._set_activation_token,
        )
        return self._tray

    def notify(
        self, title: str, message: str, *, icon: str | None = None
    ) -> None:
        """Show a desktop notification.

        Uses the tray icon's native notification when a tray exists; otherwise
        falls back to a standalone notifier (notify-send/dbus-send/console) so
        notifications still work without a tray -- callers need not handle that
        case themselves. ``icon`` is a freedesktop icon name where supported.
        """
        if self._tray is not None:
            self._tray.notify(title, message, icon=icon)
        else:
            _notify(title, message, app_name=self._app_name, icon=icon)

    def quit(self) -> None:
        """Request quit -- confirm if configured, then stop. Thread-safe."""
        self.run_on_ui_thread(self._quit)

    def _quit(self) -> None:
        if self._quit_confirm is not None and not self.confirm(
            self._quit_confirm, title=self._quit_confirm_title
        ):
            return
        self._shutdown()

    def confirm(self, message: str, *, title: str = "Confirm") -> bool:
        """Show a modal Yes/No dialog; return True if confirmed. Thread-safe."""
        return bool(
            self.call_on_ui_thread(lambda: self._confirm(message, title))
        )

    def _confirm(self, message: str, title: str) -> bool:
        result = tk.BooleanVar(master=self.root, value=False)
        dialog = tk.Toplevel(self.root)
        dialog.title(title)
        dialog.resizable(False, False)
        if str(self.root.state()) != "withdrawn":
            dialog.transient(self.root)
        # Mirror the (possibly state-dependent) window icon, live while open.
        self.track_window_icon(dialog)

        frame = ttk.Frame(dialog, padding=20)
        frame.pack()
        ttk.Label(frame, text=message, wraplength=_CONFIRM_WRAPLENGTH).pack(
            pady=(0, 10)
        )
        buttons = ttk.Frame(frame)
        buttons.pack()

        def answer(value: bool) -> None:
            result.set(value)
            dialog.destroy()

        ttk.Button(buttons, text="Yes", command=lambda: answer(True)).pack(
            side=tk.LEFT, padx=5
        )
        ttk.Button(buttons, text="No", command=lambda: answer(False)).pack(
            side=tk.LEFT, padx=5
        )
        dialog.protocol("WM_DELETE_WINDOW", lambda: answer(False))

        self.center_window(dialog)
        dialog.grab_set()
        dialog.focus_set()
        dialog.wait_window()
        return bool(result.get())

    def primary_monitor_bounds(self) -> tuple[int, int, int, int]:
        """Return the primary monitor's (x, y, width, height).

        Queries X11 RandR via python-xlib (works under X11 and XWayland) and
        falls back to the full Tk screen size off-X11.
        """
        return _primary_monitor_bounds(self.root)

    def center_window(self, window: tk.Tk | tk.Toplevel) -> None:
        """Center ``window`` on the main window (if visible) else the primary
        monitor. Works for the root or any toplevel (e.g. your own dialogs).

        The window is positioned while withdrawn and its prior shown/hidden
        state is restored, so it never flashes at the window manager's default
        location first -- ``update_idletasks`` would otherwise map a visible (or
        just-created) window before the geometry is applied. This makes the
        flicker impossible to reintroduce at the call site.
        """
        show_after = str(window.state()) != "withdrawn"
        with contextlib.suppress(tk.TclError):
            window.withdraw()
            window.update_idletasks()
            width = window.winfo_reqwidth()
            height = window.winfo_reqheight()
            # Center on the main window if it is visible, else the primary
            # monitor (correct on multi-monitor X11, not the full virtual span).
            if (
                window is not self.root
                and str(self.root.state()) != "withdrawn"
            ):
                base_x = self.root.winfo_x()
                base_y = self.root.winfo_y()
                base_w = self.root.winfo_width()
                base_h = self.root.winfo_height()
            else:
                base_x, base_y, base_w, base_h = self.primary_monitor_bounds()
            window.geometry(
                f"+{base_x + max(0, (base_w - width) // 2)}"
                f"+{base_y + max(0, (base_h - height) // 2)}"
            )
            if show_after:
                window.deiconify()

    def _on_window_close(self) -> None:
        # The tray houses the window, so closing just hides it; with no tray,
        # closing means quit (with confirmation if configured).
        if self._tray is not None:
            self.hide()
        else:
            self.quit()

    # -- lifecycle --------------------------------------------------------

    def run(
        self,
        tray_icon: TrayIcon | None = None,
        *,
        tray_setup: Callable[[], None] | None = None,
        start_hidden: bool = False,
        handle_signals: bool = True,
    ) -> None:
        """Run the UI loop on the current (main) thread until :meth:`stop`.

        If ``tray_icon`` is given, its event loop runs on a worker thread for
        the lifetime of the app and is stopped when the UI loop exits.

        ``tray_setup`` is passed through to ``tray_icon.run(setup=...)`` and is
        therefore invoked **on the tray's own thread**, once the tray's event
        loop is running. Use it for tray work that cannot happen before the loop
        starts -- e.g. setting the initial icon image on Windows, where the
        HICON cannot be updated until pystray's loop is live. UI work triggered
        from here must still be marshalled with :meth:`run_on_ui_thread`.

        If ``start_hidden`` is true the window starts withdrawn (only the tray
        icon is visible); call :meth:`show` to reveal it. It is ignored when
        there is no ``tray_icon``, since then nothing could restore the window.
        """
        hidden = start_hidden and tray_icon is not None
        if start_hidden and tray_icon is None:
            logger.info(
                "Ignoring start_hidden: no tray icon to restore the window"
            )
        if hidden:
            with contextlib.suppress(tk.TclError):
                self.root.withdraw()
        elif str(self.root.state()) == "withdrawn":
            # The app is managing visibility itself (e.g. it reveals the window
            # via tray_setup); just pre-position it for when it does.
            self._place_window()
        else:
            # Shown at startup: position it while hidden, then reveal, so it
            # never flashes at the window manager's default location first
            # (placement calls update_idletasks, which can map the window).
            with contextlib.suppress(tk.TclError):
                self.root.withdraw()
            self._show()
        handlers = self._install_signal_handlers() if handle_signals else []
        tray_thread: Thread | None = None
        if tray_icon is not None:
            tray_thread = Thread(
                target=lambda: self._run_tray_loop(tray_icon, tray_setup),
                name="sevaht-gui-tray",
                daemon=True,
            )
            tray_thread.start()
        self._poll_queue()
        try:
            self.root.mainloop()
        finally:
            self._closed.set()
            if tray_icon is not None:
                with contextlib.suppress(Exception):
                    tray_icon.stop()
                if tray_thread is not None:
                    tray_thread.join(timeout=2.0)
            with contextlib.suppress(tk.TclError):
                self.root.destroy()
            self._restore_signal_handlers(handlers)

    @staticmethod
    def _run_tray_loop(
        tray_icon: TrayIcon, tray_setup: Callable[[], None] | None
    ) -> None:
        # The tray backend invokes its setup callback with the tray icon, on
        # its own thread, once the loop is running; adapt our zero-arg
        # ``tray_setup``.
        if tray_setup is None:
            tray_icon.run()
        else:
            tray_icon.run(lambda _icon: tray_setup())

    def _set_activation_token(self, token: str) -> None:
        self._activation_token = token

    def show(self) -> None:
        """Show and raise the main window. Safe to call from any thread."""
        self.run_on_ui_thread(self._show)

    def _show(self) -> None:
        # Place the window only when revealing it from hidden, so a window the
        # user moved while open is not yanked back.
        if str(self.root.state()) == "withdrawn":
            self._place_window()
        with contextlib.suppress(tk.TclError):
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
            # What the above cannot do on its own where a compositor or a
            # window manager guards the focus (XWayland, fluxland...): ask
            # it, as GTK and Qt do when they present a window
            token, self._activation_token = self._activation_token, None
            if str(self.root.tk.call("tk", "windowingsystem")) == "x11":
                request_activation(self.root.winfo_id(), token)

    def hide(self) -> None:
        """Hide (withdraw) the main window. Safe to call from any thread."""
        self.run_on_ui_thread(self._hide)

    def _hide(self) -> None:
        # Remember where it was so the next show reopens in the same place.
        self._placement.remember(self.root)
        with contextlib.suppress(tk.TclError):
            self.root.withdraw()

    def stop(self) -> None:
        """Stop the UI loop. Safe to call from any thread."""
        self.run_on_ui_thread(self._shutdown)

    def _shutdown(self) -> None:
        if self._closed.is_set():
            return
        # Capture the position now (the root is destroyed after the loop exits),
        # so window_position is still readable for saving config post-run().
        self._placement.remember(self.root)
        self._closed.set()
        if self._poll_after_id is not None:
            with contextlib.suppress(tk.TclError):
                self.root.after_cancel(self._poll_after_id)
        with contextlib.suppress(tk.TclError):
            self.root.quit()

    def _install_signal_handlers(self) -> list[tuple[int, Any]]:
        handlers: list[tuple[int, Any]] = []

        def handle_signal(_signum: int, _frame: object | None) -> None:
            self.stop()

        for sig in (signal.SIGINT, signal.SIGTERM):
            with contextlib.suppress(ValueError, OSError):
                handlers.append((sig, signal.signal(sig, handle_signal)))
        return handlers

    @staticmethod
    def _restore_signal_handlers(handlers: list[tuple[int, Any]]) -> None:
        for signum, previous in handlers:
            with contextlib.suppress(ValueError, OSError):
                signal.signal(signum, previous)
