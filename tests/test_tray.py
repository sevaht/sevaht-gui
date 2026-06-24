"""Tests for the parts of the tray module that need no display or session bus.

Constructing an actual tray icon talks to X11 / the session bus (or the Win32
shell), so those paths are exercised manually rather than in CI; here we only
cover the public surface and the pure atom-name helper.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PIL import Image

import sevaht_gui
from sevaht_gui.tray import _atom_safe_name, as_renderer, create_tray_icon

if TYPE_CHECKING:
    from pathlib import Path


def test_public_exports() -> None:
    assert sevaht_gui.create_tray_icon is create_tray_icon
    assert sevaht_gui.as_renderer is as_renderer
    assert hasattr(sevaht_gui, "TrayIcon")
    assert hasattr(sevaht_gui, "SNIRegistrationError")
    assert hasattr(sevaht_gui, "TkApp")


def test_as_renderer_passes_callables_through() -> None:
    def renderer(size: int) -> Image.Image:
        return Image.new("RGBA", (size, size))

    assert as_renderer(renderer) is renderer


def test_as_renderer_scales_a_static_image() -> None:
    source = Image.new("RGBA", (16, 16), (1, 2, 3, 255))
    render = as_renderer(source)
    out = render(48)
    assert out.size == (48, 48)
    assert out.mode == "RGBA"


def test_as_renderer_loads_a_path(tmp_path: Path) -> None:
    icon_path = tmp_path / "icon.png"
    Image.new("RGBA", (8, 8), (255, 0, 0, 255)).save(icon_path)
    render = as_renderer(icon_path)
    out = render(32)
    assert out.size == (32, 32)
    # Accepts both str and os.PathLike.
    assert as_renderer(str(icon_path))(10).size == (10, 10)


def test_atom_safe_name_uppercases_and_replaces() -> None:
    assert _atom_safe_name("battery-tray") == "BATTERY_TRAY"
    assert _atom_safe_name("gamepad.overlay 2") == "GAMEPAD_OVERLAY_2"


def test_atom_safe_name_strips_separators() -> None:
    assert _atom_safe_name("--edge--") == "EDGE"


def test_atom_safe_name_falls_back_when_empty() -> None:
    assert _atom_safe_name("") == "SEVAHT_GUI"
    assert _atom_safe_name("***") == "SEVAHT_GUI"
