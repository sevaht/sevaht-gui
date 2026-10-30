# sevaht-gui

Small cross-platform GUI building blocks: a system-tray icon and a tkinter
application base, shared across Sevaht desktop tools.

The most-used pieces are:

- **{class}`sevaht_gui.tkapp.TkApp`** — a tkinter app base that owns the main
  thread, runs a tray icon on a worker thread, and provides themed widgets,
  window centring/placement, quit confirmation, and tray-aware close handling.
- **{func}`sevaht_gui.tray.create_tray_icon`** — a single {class}`~sevaht_gui.tray.TrayIcon`
  interface backed by pystray on Windows and StatusNotifierItem/XEmbed on Linux.
- **{mod}`sevaht_gui.widgets`**, **{mod}`sevaht_gui.theme`**,
  **{mod}`sevaht_gui.monitors`** — reusable widgets, default theming, and
  monitor geometry.

## Installation

```console
$ pip install sevaht-gui
```

Requires Python 3.12 or newer. Supports Linux and Windows (macOS is not
supported).

## Quick start

See {doc}`guide/hello_world` for a complete, minimal tray application.

```{toctree}
:hidden:
:caption: Guides

guide/hello_world
```

```{toctree}
:hidden:
:caption: API reference

reference/tkapp
reference/tray
reference/widgets
reference/theme
reference/fonts
reference/monitors
```
