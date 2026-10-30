"""Tests for the font helpers that need no display."""

from __future__ import annotations

import logging
import tkinter as tk
from typing import TYPE_CHECKING

from sevaht_gui import fonts

if TYPE_CHECKING:
    import pytest


class _FakeTk:
    """The bit of a Tcl interpreter fonts.py asks questions of."""

    def __init__(self, windowingsystem: str, fontsystem: str | None) -> None:
        self._windowingsystem = windowingsystem
        self._fontsystem = fontsystem

    def call(self, *args: str) -> str:
        assert args == ("tk", "windowingsystem")
        return self._windowingsystem

    def eval(self, script: str) -> str:
        assert script == "tk::pkgconfig get fontsystem"
        if self._fontsystem is None:
            raise tk.TclError
        return self._fontsystem


class _FakeRoot:
    def __init__(self, windowingsystem: str, fontsystem: str | None) -> None:
        self.tk = _FakeTk(windowingsystem, fontsystem)


def test_choose_family_takes_the_first_preferred_installed() -> None:
    available = ["Cantarell", "dejavu sans", "Foo"]
    assert fonts.choose_family(available, ["Noto Sans", "DejaVu Sans"]) == (
        "dejavu sans"
    )


def test_choose_family_none_when_nothing_matches() -> None:
    assert fonts.choose_family(["Foo"], ["Noto Sans"]) is None
    assert fonts.choose_family([], ["Noto Sans"]) is None


def test_tk_without_xft_on_x11_is_detected() -> None:
    assert fonts.tk_lacks_xft(_FakeRoot("x11", "x11"))  # type: ignore[arg-type]


def test_tk_with_xft_is_fine() -> None:
    assert not fonts.tk_lacks_xft(_FakeRoot("x11", "xft"))  # type: ignore[arg-type]


def test_other_windowing_systems_are_not_checked() -> None:
    assert not fonts.tk_lacks_xft(_FakeRoot("win32", "x11"))  # type: ignore[arg-type]
    assert not fonts.tk_lacks_xft(_FakeRoot("aqua", None))  # type: ignore[arg-type]


def test_an_unanswerable_question_is_assumed_fine() -> None:
    assert not fonts.tk_lacks_xft(_FakeRoot("x11", None))  # type: ignore[arg-type]


def test_warning_names_the_cure(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="sevaht_gui.fonts"):
        assert fonts.warn_if_no_xft(_FakeRoot("x11", "x11"))  # type: ignore[arg-type]
    assert "without Xft" in caplog.text
    assert "/usr/bin/python3" in caplog.text


def test_no_warning_with_xft(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="sevaht_gui.fonts"):
        assert not fonts.warn_if_no_xft(_FakeRoot("x11", "xft"))  # type: ignore[arg-type]
    assert not caplog.text


def test_default_font_is_left_alone_without_xft() -> None:
    root = _FakeRoot("x11", "x11")
    assert fonts.apply_default_font(root) is None  # type: ignore[arg-type]
