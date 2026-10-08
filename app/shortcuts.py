"""Platform-aware keyboard shortcuts: one place for the label AND the Tk binding.

Windows and Linux use Ctrl; macOS uses the Command key (shown as the command
symbol in buttons, and as a native right-aligned accelerator in menus). Every
user-visible shortcut hint and its key binding come from here so a label can
never promise a key that is not bound, and the Windows output stays unchanged.

``key`` is a Tk keysym stem: a single letter ("o") or a name ("Return").
"""
from __future__ import annotations

import sys
import tkinter as tk
from typing import Any, Callable

# Built from a code point so no invisible character lives in the source.
_COMMAND_SYMBOL = chr(0x2318)


def is_mac() -> bool:
    """True on macOS (``sys.platform == "darwin"``, Tk windowing system aqua)."""
    return sys.platform == "darwin"


def _key_name(key: str) -> str:
    if len(key) == 1:
        return key.upper()
    if key == "Return" and not is_mac():
        return "Enter"  # the label Windows/Linux users know; Tk's keysym is Return
    return key


def accel_text(key: str, *, plain: bool = False) -> str:
    """The shortcut as shown in text: ``Ctrl+O``, or the command symbol plus O on macOS.

    ``plain`` forces the spelled-out ``Cmd+O`` form on macOS for places where a
    symbol would be unclear.
    """
    name = _key_name(key)
    if is_mac():
        return f"Cmd+{name}" if plain else f"{_COMMAND_SYMBOL}{name}"
    return f"Ctrl+{name}"


def bind_sequences(key: str) -> list[str]:
    """Tk event sequences for the shortcut: ``<Control-o>`` / ``<Command-o>``.

    A single letter gets both cases so Caps Lock does not break it.
    """
    mod = "Command" if is_mac() else "Control"
    if len(key) == 1:
        return [f"<{mod}-{key.lower()}>", f"<{mod}-{key.upper()}>"]
    return [f"<{mod}-{key}>"]


def bind_shortcut(widget: tk.Misc, key: str, func: Callable[[], Any]) -> None:
    """Bind the platform's shortcut for ``key`` on ``widget`` to ``func()``."""
    for seq in bind_sequences(key):
        widget.bind(seq, lambda _e: func())


def menu_item(text: str, key: str, *, gap: int = 0) -> dict[str, Any]:
    """``add_command`` keyword arguments for a menu item with a shortcut.

    Windows/Linux keep the label-with-padding form (``text`` + ``gap`` spaces +
    ``Ctrl+O``). macOS uses Tk's ``accelerator`` option, which Tk draws as the
    native right-aligned command-key hint.
    """
    if is_mac():
        return {"label": text, "accelerator": f"Command-{_key_name(key)}"}
    return {"label": f"{text}{' ' * gap}{accel_text(key)}"}


def quit_label() -> str:
    """``Quit`` on macOS, ``Exit`` elsewhere."""
    return "Quit" if is_mac() else "Exit"
