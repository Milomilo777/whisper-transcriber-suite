"""A recording stand-in for the tkinter / ttk widgets a simple dialog uses, with no Tk root.

Tests that must not open a window (this suite runs on machines where a window would disturb the
person at the desk) patch a dialog module's ``tk`` and ``ttk`` names with :data:`fake_tk` and
:data:`fake_ttk`, build the dialog, drive its callbacks and read the texts a person would see with
:meth:`Recorder.visible_texts`. Only the calls the converted dialogs make are modelled; anything
else raises ``AttributeError`` so a test never passes by accident.
"""
from __future__ import annotations

import types
from typing import Any, Callable


class Recorder:
    """Every fake widget and variable created since the last :meth:`reset`, in creation order."""

    def __init__(self) -> None:
        self.widgets: list[FakeWidget] = []
        self.after_calls: list[Callable[[], Any]] = []

    def reset(self) -> None:
        self.widgets.clear()
        self.after_calls.clear()

    def visible_texts(self) -> list[list[str]]:
        """[widget id, text] pairs: window titles and the text of labels and buttons."""
        out: list[list[str]] = []
        for i, w in enumerate(self.widgets):
            if w.destroyed:
                continue
            ident = f"{w.kind}#{i}"
            if w.kind == "Toplevel":
                out.append([ident, w.title_text])
            elif w.kind in ("Label", "Button"):
                var = w.options.get("textvariable")
                text = var.get() if var is not None else str(w.options.get("text", ""))
                out.append([ident, text])
        return out

    def run_after_calls(self, rounds: int = 5) -> None:
        for _round in range(rounds):
            pending, self.after_calls = self.after_calls, []
            if not pending:
                return
            for fn in pending:
                fn()


RECORDER = Recorder()


class FakeVar:
    def __init__(self, master: Any = None, value: str = "") -> None:
        self._value = value

    def get(self) -> str:
        return self._value

    def set(self, value: str) -> None:
        self._value = value


class FakeWidget:
    kind = "Widget"

    def __init__(self, master: Any = None, **options: Any) -> None:
        self.master = master
        self.options: dict[str, Any] = dict(options)
        self.bindings: dict[str, list[Callable[..., Any]]] = {}
        self.states: set[str] = set()
        self.destroyed = False
        self.title_text = ""
        self.content = ""
        self.modified = False
        RECORDER.widgets.append(self)

    # geometry and window manager calls the dialogs make; nothing to record
    def grid(self, *_a: Any, **_k: Any) -> None: ...
    def pack(self, *_a: Any, **_k: Any) -> None: ...
    def columnconfigure(self, *_a: Any, **_k: Any) -> None: ...
    def rowconfigure(self, *_a: Any, **_k: Any) -> None: ...
    def transient(self, *_a: Any) -> None: ...
    def resizable(self, *_a: Any) -> None: ...
    def focus_set(self) -> None: ...

    def winfo_toplevel(self) -> "FakeWidget":
        return self

    def title(self, text: str) -> None:
        self.title_text = text

    def bind(self, sequence: str, func: Callable[..., Any], add: str | None = None) -> None:
        self.bindings.setdefault(sequence, []).append(func)

    def fire(self, sequence: str) -> None:
        for fn in list(self.bindings.get(sequence, [])):
            fn(types.SimpleNamespace(widget=self))

    def after(self, _ms: int, func: Callable[[], Any]) -> None:
        RECORDER.after_calls.append(func)

    def winfo_exists(self) -> bool:
        return not self.destroyed

    def destroy(self) -> None:
        self.destroyed = True

    def configure(self, **options: Any) -> None:
        self.options.update(options)

    config = configure

    def cget(self, name: str) -> Any:
        return self.options.get(name, "")

    def state(self, spec: list[str]) -> None:
        for flag in spec:
            if flag.startswith("!"):
                self.states.discard(flag[1:])
            else:
                self.states.add(flag)

    def instate(self, spec: list[str]) -> bool:
        return all((f[1:] not in self.states) if f.startswith("!") else (f in self.states)
                   for f in spec)

    def invoke(self) -> None:
        cmd = self.options.get("command")
        if cmd is not None:
            cmd()

    # tk.Text
    def get(self, _start: str, _end: str) -> str:
        return self.content

    def insert(self, _index: str, text: str) -> None:
        self.content += text
        self.modified = True

    def edit_modified(self, flag: bool | None = None) -> bool:
        if flag is not None:
            self.modified = flag
        return self.modified


def _kind(name: str) -> type[FakeWidget]:
    return type(name, (FakeWidget,), {"kind": name})


Toplevel = _kind("Toplevel")
Frame = _kind("Frame")
Label = _kind("Label")
Button = _kind("Button")
Text = _kind("Text")

fake_tk = types.SimpleNamespace(
    Toplevel=Toplevel, Text=Text, StringVar=FakeVar, Misc=FakeWidget, TclError=RuntimeError,
)
fake_ttk = types.SimpleNamespace(Frame=Frame, Label=Label, Button=Button)
