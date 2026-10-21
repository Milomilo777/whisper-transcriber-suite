"""app.widgets.disclosure.Disclosure: a header that shows/hides a body and remembers it in a config key."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import pytest

from app.widgets.disclosure import CLOSED_MARK, OPEN_MARK, Disclosure


@pytest.fixture
def root():
    try:
        root = tk.Tk()
    except tk.TclError as e:
        pytest.skip(f"Tk unavailable: {e}")
    root.withdraw()
    try:
        yield root
    finally:
        root.destroy()


def _make(root: tk.Tk, config: dict, **kw) -> Disclosure:
    disc = Disclosure(root, "More options", config=config, key="more_open", **kw)
    disc.pack(fill="x")
    ttk.Label(disc.body, text="inside").pack()
    root.update_idletasks()
    return disc


def test_starts_closed_when_the_key_is_missing(root: tk.Tk) -> None:
    config: dict = {}
    disc = _make(root, config)
    assert not disc.is_open
    assert not disc.body.winfo_manager()
    assert disc.header.cget("text") == CLOSED_MARK + "More options"
    assert config == {}  # nothing written until a person toggles it


def test_starts_open_from_the_config(root: tk.Tk) -> None:
    disc = _make(root, {"more_open": True})
    assert disc.is_open
    assert disc.body.winfo_manager() == "pack"
    assert disc.header.cget("text") == OPEN_MARK + "More options"


def test_toggle_shows_the_body_writes_the_key_and_calls_back(root: tk.Tk) -> None:
    config: dict = {}
    calls: list[str] = []
    disc = _make(root, config, on_toggle=lambda: calls.append("saved"))
    disc.toggle()
    assert disc.is_open and disc.body.winfo_manager() == "pack"
    assert config["more_open"] is True
    assert calls == ["saved"]
    disc.toggle()
    assert not disc.is_open and not disc.body.winfo_manager()
    assert config["more_open"] is False
    assert calls == ["saved", "saved"]


def test_set_open_to_the_same_state_does_nothing(root: tk.Tk) -> None:
    config: dict = {}
    calls: list[str] = []
    disc = _make(root, config, on_toggle=lambda: calls.append("saved"))
    disc.set_open(False)
    assert config == {} and calls == []


def test_a_click_and_the_keyboard_toggle_it(root: tk.Tk) -> None:
    config: dict = {}
    disc = _make(root, config)
    assert disc.header.cget("takefocus") in (True, 1, "1")
    disc.header.event_generate("<Button-1>")
    assert disc.is_open
    # Key events reach the focused widget only, and a withdrawn window cannot hold the focus.
    root.deiconify()
    root.geometry("+0+0")
    root.update()
    disc.header.focus_force()
    root.update()
    if root.focus_get() is not disc.header:
        pytest.skip("the window could not take the keyboard focus (another window holds it)")
    disc.header.event_generate("<Return>")
    root.update()
    assert not disc.is_open
    disc.header.event_generate("<space>")
    root.update()
    assert disc.is_open
    assert config["more_open"] is True


def test_a_config_function_writes_into_the_owners_current_dict(root: tk.Tk) -> None:
    # App replaces app_config with a fresh load_config() dict (after the model-folder
    # picker): a toggle must land in the dict the next save writes, not the old one.
    owner = {"cfg": {"more_open": False}}
    disc = Disclosure(root, "More options", config=lambda: owner["cfg"], key="more_open")
    old = owner["cfg"]
    owner["cfg"] = {}
    disc.toggle()
    assert owner["cfg"] == {"more_open": True}
    assert old == {"more_open": False}
