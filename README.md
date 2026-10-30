# sevaht-gui

Small cross-platform GUI building blocks: a system-tray icon and a tkinter
application base, shared across Sevaht desktop tools.

## Documentation

Full documentation lives in `docs/` and is published to GitHub Pages:
<https://sevaht.github.io/sevaht-gui/>.

### Building the docs locally

```console
$ uv run --group docs sphinx-build -b html docs docs/_build/html
```

Then open `docs/_build/html/index.html`. (Publishing to GitHub Pages requires
enabling Pages with the "GitHub Actions" source in the repository settings.)

## Tray icon

`create_tray_icon` returns a single `TrayIcon` interface backed by the right
implementation for the platform:

- **Windows** — [pystray](https://pypi.org/project/pystray/).
- **Linux** — a `StatusNotifierItem` (D-Bus) item when a usable SNI host is
  present (KDE/GNOME, Wayland, or fluxbox with `snixembed`), falling back to a
  self-contained XEmbed icon on bare X11 window managers with no SNI host.

The feature model is deliberately small: a default **activate** action
(left-click, and the default menu item where a menu is available) and a
**quit** action. Backends that can show a menu (pystray, SNI) offer both on
right-click; the menu-less XEmbed backend maps right-click straight to quit.

The icon is any **`IconSource`** — a prepared `PIL.Image`, a path to an image
file (both static; the common case), or a renderer `Callable[[int], Image]`
for apps that draw their own artwork. The title (the item's name) and the optional
`tooltip` (the text shown on hover, apart from the title) and the icon can be changed
live (`set_icon` accepts any `IconSource`), so an app can reflect state either
by swapping prepared images or by re-rendering.

macOS is intentionally unsupported: a real menu-bar item there needs a single
main-thread Cocoa loop shared with tk (custom PyObjC), which the threaded model
used here cannot provide.

## Fonts on Linux: use a Python whose Tk has Xft

On X11 (and Wayland through XWayland) Tk draws the system's fonts only if it was
built with **Xft**. Every distribution's Python has that. The Python builds that
`uv` downloads (python-build-standalone) do **not**: their Tk was built with
`--disable-xft` and can only use the legacy X core fonts, which a modern
desktop barely has, so every font falls back to the X server's `fixed` and the
window looks wrong whatever font you ask for. Nothing at run time can change
that. `TkApp` logs a warning when it sees such a Tk; on Windows and macOS this
does not apply.

Run on your distribution's Python instead, for example:

```sh
uv tool install --python /usr/bin/python3 <your-app>   # or: pipx install <your-app>
uv python pin /usr/bin/python3                          # in a project
```

or tell uv to only use system interpreters (`python-preference = "only-system"`
in `~/.config/uv/uv.toml`). With Xft, `TkApp` also uses the first installed of
Noto Sans, DejaVu Sans, Liberation Sans and Cantarell for Tk's text fonts
(`font_families=`; `None` keeps Tk's own choice).

## TkApp

`TkApp` owns a `tkinter.Tk` root and runs its `mainloop()` on the main thread,
running the tray icon's own event loop on a worker thread. Work originating off
the UI thread (e.g. tray menu callbacks) is marshalled back with
`run_on_ui_thread` / `call_on_ui_thread`. `show()` / `hide()` and the
`run(start_hidden=...)` flag manage window visibility (all thread-safe), and
`set_window_icon` accepts the same `IconSource` as the tray.

```python
from sevaht_gui import TkApp, create_tray_icon

app = TkApp()
app.root.title("Example")
app.set_window_icon("icon.png")  # static file; or a PIL image / renderer

icon = create_tray_icon(
    "example",
    "Example",
    "icon.png",          # any IconSource: path, PIL image, or renderer
    on_activate=app.show,
    on_quit=app.stop,
)
app.run(icon, start_hidden=True)  # only the tray shows until activated
```

The library manages the tray lifecycle, window visibility, and threading;
choosing and (re)drawing the artwork is left to the application.
