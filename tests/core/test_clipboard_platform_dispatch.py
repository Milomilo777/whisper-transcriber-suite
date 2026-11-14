"""Exercise the actual clipboard installer/callback without constructing Tk.

Compile only the App clipboard methods and table from source so these checks
cannot import the app's runtime services or start a GUI.
"""
from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import _tkinter
import pytest
import tkinter as tk


@pytest.fixture(autouse=True)
def forbid_tk_interpreter(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Clipboard unit tests must not create a Tk interpreter")

    monkeypatch.setattr(_tkinter, "create", forbidden)


def _app_for(platform):
    path = Path(__file__).resolve().parents[2] / "app" / "app.py"
    module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    app = next(node for node in module.body if isinstance(node, ast.ClassDef) and node.name == "App")
    methods = {"_clipboard_action", "_install_clipboard_keys"}
    body = [
        node for node in app.body
        if (isinstance(node, ast.FunctionDef) and node.name in methods)
        or (isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "_CLIPBOARD_VK"
            for target in node.targets
        ))
    ]
    assert len(body) == 3
    subset = ast.Module(body=[ast.ClassDef(
        name="App", bases=[], keywords=[], body=body, decorator_list=[]
    )], type_ignores=[])
    namespace = {
        "sys": SimpleNamespace(platform=platform),
        "shortcuts": SimpleNamespace(is_mac=lambda: platform == "darwin"),
        "tk": tk,
    }
    exec(compile(ast.fix_missing_locations(subset), str(path), "exec"), namespace)
    return namespace["App"]


def _installed(platform):
    app = _app_for(platform)
    bound = {}
    instance = app()

    def bind_all(sequence, callback, add=None):
        assert sequence == "<Control-KeyPress>" and add == "+"
        bound[sequence] = callback

    instance.bind_all = bind_all
    instance._install_clipboard_keys()
    return bound.get("<Control-KeyPress>")


class _Entry:
    def __init__(self):
        self.text = "selected text"
        self.clipboard = "saved clipboard"
        self.selection = (0, 8)
        self.calls = []

    def select_range(self, start, end):
        self.calls.append("selectall")
        self.selection = (0, len(self.text))

    def icursor(self, end):
        self.calls.append("icursor")

    def event_generate(self, event):
        self.calls.append(event)
        start, end = self.selection
        if event in ("<<Copy>>", "<<Cut>>"):
            self.clipboard = self.text[start:end]
        if event == "<<Cut>>":
            self.text = self.text[:start] + self.text[end:]
        if event == "<<Paste>>":
            self.text = self.text[:start] + self.clipboard + self.text[end:]


@pytest.mark.parametrize("keysym,keycode", [
    ("space", 65), ("F1", 67), ("KP_Add", 86), ("KP_2", 88), ("KP_Down", 88),
])
def test_x11_unrelated_ctrl_keys_leave_entry_and_clipboard_unchanged(keysym, keycode):
    handler = _installed("linux")
    field = _Entry()
    before = (field.text, field.clipboard, field.selection)
    event = SimpleNamespace(keysym=keysym, keycode=keycode, widget=field, state=0x0004)
    result = handler(event) if handler else None
    assert (field.text, field.clipboard, field.selection) == before
    assert field.calls == []
    assert result is None


@pytest.mark.parametrize("platform", ["linux", "freebsd14", "darwin"])
def test_non_windows_preserves_native_bindings(platform):
    assert _installed(platform) is None


@pytest.mark.parametrize("keysym,keycode,expected", [
    ("ر", 86, "<<Paste>>"), ("ذ", 67, "<<Copy>>"),
    ("ط", 88, "<<Cut>>"), ("ش", 65, "selectall"),
    ("Cyrillic_em", 86, "<<Paste>>"), ("Cyrillic_es", 67, "<<Copy>>"),
    ("Cyrillic_che", 88, "<<Cut>>"), ("Cyrillic_ef", 65, "selectall"),
])
@pytest.mark.parametrize("state", [0x0004, 0x0005, 0x000C, 0x000D, 0x40004])
def test_windows_non_latin_shortcuts_remain_active(keysym, keycode, expected, state):
    handler = _installed("win32")
    field = _Entry()
    assert handler is not None
    assert handler(SimpleNamespace(keysym=keysym, keycode=keycode, widget=field, state=state)) == "break"
    assert field.calls == (["selectall", "icursor"] if expected == "selectall" else [expected])


@pytest.mark.parametrize("keysym,keycode", [
    ("Cyrillic_es", 67), ("Cyrillic_em", 86), ("Cyrillic_che", 88), ("Cyrillic_ef", 65),
])
@pytest.mark.parametrize("state", [0x20004, 0x20005, 0x2000C, 0x2000D, 0x60004, 0x6000C])
def test_windows_ctrl_alt_chords_that_produce_no_text_do_not_dispatch(keysym, keycode, state):
    handler = _installed("win32")
    field = _Entry()
    before = (field.text, field.clipboard, field.selection)
    assert handler is not None
    result = handler(SimpleNamespace(keysym=keysym, keycode=keycode, widget=field, state=state, char=""))
    assert (result, field.calls, (field.text, field.clipboard, field.selection)) == (None, [], before)


@pytest.mark.parametrize("keysym,keycode", [
    ("v", 86), ("c", 67), ("x", 88), ("a", 65),
    ("V", 86), ("C", 67), ("X", 88), ("A", 65), ("o", 79), ("ن", 79), ("", 13),
])
def test_windows_native_and_unrelated_shortcuts_are_untouched(keysym, keycode):
    handler = _installed("win32")
    field = _Entry()
    before = (field.text, field.clipboard, field.selection)
    assert handler is not None
    assert handler(SimpleNamespace(keysym=keysym, keycode=keycode, widget=field, state=0x0004)) is None
    assert (field.text, field.clipboard, field.selection) == before
    assert field.calls == []


def test_windows_nontext_ctrl_alt_persian_v_does_not_dispatch():
    handler = _installed("win32")
    field = _Entry()
    before = (field.text, field.clipboard, field.selection)
    assert handler is not None
    assert handler(SimpleNamespace(keysym="\u0631", keycode=86, widget=field, state=0x20004, char="")) is None
    assert field.calls == []
    assert (field.text, field.clipboard, field.selection) == before


@pytest.mark.parametrize("state", ["??", None, object(), 0.0])
def test_windows_noninteger_state_keeps_regular_control_dispatch(state):
    handler = _installed("win32")
    field = _Entry()
    assert handler is not None
    assert handler(SimpleNamespace(keysym="\u0631", keycode=86, widget=field, state=state)) == "break"
    assert field.calls == ["<<Paste>>"]
