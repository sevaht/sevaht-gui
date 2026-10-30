"""Tests for the activation request, with python-xlib faked out."""

from __future__ import annotations

import sys
import types
from typing import TYPE_CHECKING

from sevaht_gui import _x11

if TYPE_CHECKING:
    import pytest

ROOT_ID = 1
INNER_ID = 30  # Tk's widget window
WRAPPER_ID = 20  # inside the window manager's frame, with WM_CLASS
FRAME_ID = 10  # a reparenting window manager's frame, under the root


class _FakeWindow:
    def __init__(self, display: _FakeDisplay, window_id: int) -> None:
        self.display = display
        self.id = window_id

    def get_full_property(self, atom: str, _type: int) -> object | None:
        has = self.id in self.display.windows_with_wm_class
        return object() if has and atom == "atom:WM_CLASS" else None

    def change_property(
        self, atom: str, kind: str, fmt: int, data: bytes
    ) -> None:
        self.display.calls.append(("property", self.id, atom, kind, fmt, data))

    def query_tree(self) -> types.SimpleNamespace:
        parent_id = self.display.parents.get(self.id)
        parent = _FakeWindow(self.display, parent_id) if parent_id else None
        return types.SimpleNamespace(parent=parent)


class _FakeDisplay:
    instances: list[_FakeDisplay] = []  # noqa: RUF012

    def __init__(self) -> None:
        self.sent: list[tuple[_FakeWindow, types.SimpleNamespace, int]] = []
        self.calls: list[tuple[object, ...]] = []
        self.closed = False
        self.flushed = False
        self.windows_with_wm_class = {WRAPPER_ID}
        self.parents = {INNER_ID: WRAPPER_ID, WRAPPER_ID: FRAME_ID}
        self.parents[FRAME_ID] = ROOT_ID
        _FakeDisplay.instances.append(self)

    def screen(self) -> types.SimpleNamespace:
        return types.SimpleNamespace(root=_FakeWindow(self, ROOT_ID))

    def create_resource_object(
        self, _kind: str, window_id: int
    ) -> _FakeWindow:
        return _FakeWindow(self, window_id)

    def intern_atom(self, name: str) -> str:
        return f"atom:{name}"

    def send_event(
        self,
        destination: _FakeWindow,
        event: types.SimpleNamespace,
        event_mask: int,
    ) -> None:
        self.sent.append((destination, event, event_mask))
        self.calls.append(("message", event.window))

    def flush(self) -> None:
        self.flushed = True

    def close(self) -> None:
        self.closed = True


def _fake_xlib(monkeypatch: pytest.MonkeyPatch) -> None:
    display_module = types.ModuleType("Xlib.display")
    display_module.Display = _FakeDisplay  # type: ignore[attr-defined]
    display_module.event = types.SimpleNamespace(  # type: ignore[attr-defined]
        ClientMessage=types.SimpleNamespace
    )
    x_module = types.ModuleType("Xlib.X")
    x_module.ClientMessage = 33  # type: ignore[attr-defined]
    x_module.CurrentTime = 0  # type: ignore[attr-defined]
    x_module.AnyPropertyType = 0  # type: ignore[attr-defined]
    x_module.SubstructureRedirectMask = 1 << 20  # type: ignore[attr-defined]
    x_module.SubstructureNotifyMask = 1 << 19  # type: ignore[attr-defined]
    package = types.ModuleType("Xlib")
    package.display = display_module  # type: ignore[attr-defined]
    package.X = x_module  # type: ignore[attr-defined]
    for name, module in (
        ("Xlib", package),
        ("Xlib.display", display_module),
        ("Xlib.X", x_module),
    ):
        monkeypatch.setitem(sys.modules, name, module)
    _FakeDisplay.instances.clear()


def test_request_activation_names_the_managed_window_to_the_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_xlib(monkeypatch)
    assert _x11.request_activation(INNER_ID)
    (display,) = _FakeDisplay.instances
    ((destination, event, mask),) = display.sent
    assert destination.id == ROOT_ID
    assert event.client_type == "atom:_NET_ACTIVE_WINDOW"
    # the wrapper (it has WM_CLASS), not Tk's widget window or the WM's frame
    assert event.window == WRAPPER_ID
    # source: an application; no timestamp; no previously active window
    assert event.data == (32, (1, 0, 0, 0, 0))
    assert mask == (1 << 20) | (1 << 19)
    assert display.flushed
    assert display.closed


def test_a_window_with_wm_class_is_named_as_it_is(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_xlib(monkeypatch)
    assert _x11.request_activation(WRAPPER_ID)
    ((_, event, _),) = _FakeDisplay.instances[0].sent
    assert event.window == WRAPPER_ID


def test_without_wm_class_anywhere_the_given_window_is_named(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_xlib(monkeypatch)
    monkeypatch.setattr(_FakeDisplay, "__init__", _no_wm_class_init)
    assert _x11.request_activation(INNER_ID)
    ((_, event, _),) = _FakeDisplay.instances[0].sent
    assert event.window == INNER_ID


def _no_wm_class_init(self: _FakeDisplay) -> None:
    self.sent = []
    self.calls = []
    self.closed = False
    self.flushed = False
    self.windows_with_wm_class = set()
    self.parents = {INNER_ID: WRAPPER_ID, WRAPPER_ID: FRAME_ID}
    self.parents[FRAME_ID] = ROOT_ID
    _FakeDisplay.instances.append(self)


def test_request_activation_closes_the_display_when_sending_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_xlib(monkeypatch)

    def boom(*_args: object, **_kwargs: object) -> None:
        msg = "broken connection"
        raise OSError(msg)

    monkeypatch.setattr(_FakeDisplay, "send_event", boom)
    assert not _x11.request_activation(INNER_ID)
    assert _FakeDisplay.instances[0].closed


def test_request_activation_is_a_no_op_without_xlib(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "Xlib", None)
    monkeypatch.setitem(sys.modules, "Xlib.display", None)
    assert not _x11.request_activation(INNER_ID)


def test_request_activation_is_false_without_a_display(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_xlib(monkeypatch)

    def no_display(*_args: object) -> None:
        msg = "no display"
        raise OSError(msg)

    monkeypatch.setattr(_FakeDisplay, "__init__", no_display)
    assert not _x11.request_activation(INNER_ID)


def test_a_token_is_set_as_startup_id_before_the_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_xlib(monkeypatch)
    assert _x11.request_activation(INNER_ID, "tok-123")
    (display,) = _FakeDisplay.instances
    assert display.calls == [
        (
            "property",
            WRAPPER_ID,
            "atom:_NET_STARTUP_ID",
            "atom:UTF8_STRING",
            8,
            b"tok-123",
        ),
        ("message", WRAPPER_ID),
    ]


def test_no_token_sets_no_startup_id(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_xlib(monkeypatch)
    assert _x11.request_activation(INNER_ID)
    assert _FakeDisplay.instances[0].calls == [("message", WRAPPER_ID)]
