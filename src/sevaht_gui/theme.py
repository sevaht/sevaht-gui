"""Default ttk theming for sevaht-gui windows.

The ``clam`` theme is a good cross-platform default, but its ``TCheckbutton``
indicator is an ``X`` rather than a checkmark. :func:`apply_theme` selects a
base theme and, by default, swaps in the ``alt`` theme's checkmark indicator so
checkboxes read the way users expect while keeping the rest of the chosen
theme.
"""

from __future__ import annotations

from tkinter import ttk

DEFAULT_THEME = "clam"


def _use_checkmark_indicator(style: ttk.Style) -> None:
    """Relayout ``TCheckbutton`` to use the ``alt`` theme's checkmark glyph."""
    # Borrow alt's indicator element; harmless to re-run, but element_create
    # raises if the element already exists, so ignore that.
    try:
        style.element_create(
            "alt.Checkbutton.indicator", "from", "alt", "Checkbutton.indicator"
        )
    except Exception:  # noqa: BLE001
        return
    style.layout(
        "TCheckbutton",
        [
            (
                "Checkbutton.padding",
                {
                    "sticky": "nswe",
                    "children": [
                        (
                            "alt.Checkbutton.indicator",
                            {"side": "left", "sticky": ""},
                        ),
                        (
                            "Checkbutton.focus",
                            {
                                "side": "left",
                                "sticky": "w",
                                "children": [
                                    ("Checkbutton.label", {"sticky": "nswe"})
                                ],
                            },
                        ),
                    ],
                },
            )
        ],
    )


def apply_theme(
    theme: str = DEFAULT_THEME, *, checkmark_indicator: bool = True
) -> None:
    """Apply ``theme`` to the current Tk interpreter.

    Requires a Tk root to already exist. ``checkmark_indicator`` swaps the
    ``X`` checkbutton indicator for a checkmark (recommended with ``clam``).
    """
    style = ttk.Style()
    style.theme_use(theme)
    if checkmark_indicator:
        _use_checkmark_indicator(style)
