"""tools/linux_gui/x11_hands.py: step validation, placeholders and key chords (no X server needed)."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load():
    spec = importlib.util.spec_from_file_location("x11_hands", ROOT / "tools" / "linux_gui" / "x11_hands.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["x11_hands"] = mod
    spec.loader.exec_module(mod)
    return mod


hands = _load()


def test_the_shipped_first_look_list_is_valid():
    actions = json.loads((ROOT / "tools" / "linux_gui" / "first_look.json").read_text(encoding="utf-8"))
    assert hands.validate(actions) == []


def test_a_key_given_as_a_string_is_refused():
    # The Windows daemon typed "ctrl+a" character by character; this runner refuses the shape.
    assert hands.validate([{"op": "key", "keys": "ctrl+a"}]) != []
    assert hands.validate([{"op": "key", "keys": []}]) != []
    assert hands.validate([{"op": "key", "keys": ["ctrl", "a"]}]) == []


@pytest.mark.parametrize("step", [
    {"op": "click", "x": "10", "y": 20},
    {"op": "wait", "s": 500},
    {"op": "launch", "cmd": []},
    {"op": "type"},
    {"op": "nope"},
    "shot",
])
def test_bad_steps_are_named(step):
    problems = hands.validate([{"op": "shot"}, step])
    assert len(problems) == 1 and problems[0].startswith("step 1")


def test_not_a_list_is_refused():
    assert hands.validate({"op": "shot"}) == ["the actions must be a JSON list"]


def test_placeholders_expand_everywhere_and_unknown_ones_fail():
    env = {"HANDS_PROFILE": "/tmp/p", "HANDS_HOME": "/home/r"}
    got = hands.expand([{"op": "launch", "cmd": ["{{HOME}}/bin/app"], "env": {"P": "{{PROFILE}}/x"}}], env)
    assert got == [{"op": "launch", "cmd": ["/home/r/bin/app"], "env": {"P": "/tmp/p/x"}}]
    assert hands.expand({"text": "price {{ not a name }} $HOME"}, env) == {"text": "price {{ not a name }} $HOME"}
    with pytest.raises(KeyError):
        hands.expand("{{MEDIA}}/a.wav", env)


def test_chords_use_xdotool_names():
    assert hands.chord(["ctrl", "a"]) == "ctrl+a"
    assert hands.chord(["enter"]) == "Return"
    assert hands.chord(["alt", "F4"]) == "alt+F4"
    assert hands.chord(["shift", "tab"]) == "shift+Tab"
