"""Collect the interface texts a Tk widget tree shows, to check a dialog's translation.

``visible_texts(widget)`` walks the tree and returns ``(widget path, text)`` pairs: window titles,
the text (or text variable) of labels, buttons, check and radio buttons, label frames and menu
buttons (tk and ttk), menu entry labels, notebook tab texts and combobox values. The content of
Text and Entry widgets is the person's own input and is left out.

``untranslated(widget)`` keeps the pairs whose letters are not all inside a pseudo-locale marker
``[... ~~~]``: build a dialog with ``app.i18n.set_language("qps-ploc")`` and every text that did
not go through the translation layer shows up here.
"""
from __future__ import annotations

import re
import tkinter as tk

_TEXT_CLASSES = {
    "Label", "Button", "Checkbutton", "Radiobutton", "Labelframe", "Menubutton", "Message",
    "TLabel", "TButton", "TCheckbutton", "TRadiobutton", "TLabelframe", "TMenubutton",
}
# The end of one pseudo-locale segment: "[" + text + " " + "~~~" + "]" (app.i18n.pseudo_translate).
_SEGMENT_END = re.compile(r" ~+\]")
# The shortcut app.shortcuts.menu_item puts after a menu label ("Ctrl+O", "Cmd+O", the command
# symbol): key names, never translated. Only one, only at the very end, right after a space or
# the end of a segment.
_TRAILING_SHORTCUT = re.compile(r"(?<=[\s\]])(?:(?:Ctrl|Cmd)\+|" + chr(0x2318) + r")\S+$")


def unmarked_rest(text: str) -> str:
    """``text`` without its pseudo-locale segments: what did not go through the layer.

    Segments may nest (a translated phrase set into a translated sentence gives
    "[... [phrase ~~] ... ~~~]"), and a placeholder value may hold plain brackets ("[1080p]"):
    an opening "[" is matched by the next segment end " ~]" or plain "]" at its level. A
    trailing menu shortcut is dropped too.
    """
    text = _TRAILING_SHORTCUT.sub("", text.rstrip())
    covered = [False] * len(text)
    openers: list[int] = []
    i = 0
    while i < len(text):
        end = _SEGMENT_END.match(text, i)
        if end and openers:
            start = openers.pop()
            covered[start:end.end()] = [True] * (end.end() - start)
            i = end.end()
            continue
        if text[i] == "[":
            openers.append(i)
        elif text[i] == "]" and openers:
            openers.pop()  # a plain pair of brackets, not a segment
        i += 1
    return "".join(ch for ch, hidden in zip(text, covered) if not hidden)


def is_pseudo_marked(text: str) -> bool:
    """True when every letter of ``text`` sits inside a pseudo-locale segment (nested ones
    included), apart from a trailing menu shortcut such as "Ctrl+O"."""
    return not any(c.isalpha() for c in unmarked_rest(text))


def _text_of(w: tk.Misc) -> str:
    # ttk.Labelframe (and a few other widgets) have -text but no -textvariable.
    var = str(w.cget("textvariable") or "") if "textvariable" in w.keys() else ""
    if var:
        return str(w.getvar(var))
    return str(w.cget("text"))


def _menu_labels(menu: tk.Menu) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    end = menu.index("end")
    if end is None:
        return out
    for i in range(int(end) + 1):
        if menu.type(i) in ("separator", "tearoff"):
            continue
        out.append((f"{menu}#{i}", str(menu.entrycget(i, "label"))))
    return out


def visible_texts(widget: tk.Misc) -> list[tuple[str, str]]:
    """``(widget path, text)`` for every non-empty interface text under ``widget``."""
    out: list[tuple[str, str]] = []

    def visit(w: tk.Misc) -> None:
        if "#" in str(w).rsplit(".", 1)[-1]:
            return  # Tk's internal clones of menus (menubar, tear-off copies)
        cls = w.winfo_class()
        if isinstance(w, (tk.Tk, tk.Toplevel)):
            out.append((str(w), str(w.wm_title())))
        elif cls in _TEXT_CLASSES:
            out.append((str(w), _text_of(w)))
        elif cls == "Menu":
            out.extend(_menu_labels(w))  # type: ignore[arg-type]
        elif cls == "TNotebook":
            for tab in w.tk.splitlist(w.tk.call(str(w), "tabs")):
                out.append((f"{w}:{tab}", str(w.tk.call(str(w), "tab", tab, "-text"))))
        elif cls == "TCombobox":
            for value in w.tk.splitlist(w.cget("values")):
                out.append((f"{w}:values", str(value)))
        for child in w.winfo_children():
            visit(child)

    visit(widget)
    return [(path, text) for path, text in out if text.strip()]


def untranslated(widget: tk.Misc) -> list[tuple[str, str]]:
    """The visible texts that did not go through the pseudo-locale (see the module docstring)."""
    return [(path, text) for path, text in visible_texts(widget) if not is_pseudo_marked(text)]
