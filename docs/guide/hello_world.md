# Hello world

A complete tray application: a window showing **Hello World!** and a button
that fires a notification, with a tray icon and quit-with-confirmation. Almost
all of the fiddly parts -- the confirmation dialog, the tray menu, hiding to
the tray on close, centring, theming, and the notification fallback -- are
handled by {class}`~sevaht_gui.tkapp.TkApp`, so the app itself stays tiny.

```python
import tkinter as tk
from tkinter import ttk

from PIL import Image

from sevaht_gui import TkApp


def render_icon(size: int) -> Image.Image:
    """Draw the tray/window icon (any PIL image, file path, or renderer works)."""
    return Image.new("RGBA", (size, size), (0, 128, 255, 255))


def main() -> None:
    # quit_confirm gives the tray "Quit" item and the window close button a
    # confirmation dialog for free.
    app = TkApp(quit_confirm="Quit Hello World?")
    app.root.title("Hello World")

    content = ttk.Frame(app.root, padding=24)
    content.pack(fill=tk.BOTH, expand=True)
    ttk.Label(content, text="Hello World!").pack(pady=(0, 12))
    ttk.Button(
        content,
        text="Send a notification",
        command=lambda: app.notify("Hello World", "This is a notification."),
    ).pack()

    # None if there is no system tray; the app then runs window-only and the
    # window close button quits (still with confirmation) instead of hiding.
    tray_icon = app.create_tray_icon("hello-world", "Hello World", render_icon)

    app.run(tray_icon)


if __name__ == "__main__":
    main()
```

## Run it

Save the above as ``hello_world.py`` and run ``python hello_world.py`` (it needs
``sevaht-gui`` and ``Pillow`` installed). The window opens centred; closing it
hides to the tray, and **Quit** -- from the tray's right-click menu or by
closing the window when there is no tray -- asks for confirmation first.

## What `TkApp` handled for you

- **Quit confirmation** -- the dialog is built, centred (flicker-free), and
  shown for you; you only supplied ``quit_confirm``.
- **Tray menu and actions** -- left-click (or *Open*) shows the window,
  *Quit* confirms then exits.
- **Close-to-tray** -- the window's close button hides it while a tray exists,
  and quits otherwise.
- **Centring and placement** -- centred on first show on the primary monitor,
  reopened where it was last moved.
- **Theme** -- a themed look with proper checkbox indicators.
- **Notifications** -- {meth}`~sevaht_gui.tkapp.TkApp.notify` uses the tray when
  present and falls back to a standalone notifier otherwise, so the button
  works with or without a tray.

## Next steps

- Pass a prepared image or a file path instead of a renderer; see
  {func}`~sevaht_gui.tray.as_renderer`.
- Keep the window and tray icons in sync with
  {meth}`~sevaht_gui.tkapp.TkApp.set_app_icon`, or set them independently with
  {meth}`~sevaht_gui.tkapp.TkApp.set_window_icon` /
  {meth}`~sevaht_gui.tkapp.TkApp.set_tray_icon`.
- Persist the window position across runs via
  {class}`~sevaht_gui.tkapp.WindowPlacement` and the
  {attr}`~sevaht_gui.tkapp.TkApp.window_position` property.
```
