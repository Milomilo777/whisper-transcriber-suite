"""The macOS back-end of the "System" theme (card C2.73).

Tk's Aqua layer is faked at the module boundary (``tk::unsupported::MacWindowStyle isdark`` and the
``<<LightAqua>>`` / ``<<DarkAqua>>`` virtual events, the two hooks ``tools/mac_native_probe.py``
proved on Tk 8.6.16 / macOS 13), so the file runs on every OS. Windows and Linux behaviour stays
pinned in ``test_system_appearance.py``.
"""
from __future__ import annotations

import logging
import sys
import tkinter as tk
from types import SimpleNamespace
from typing import Any, Callable

import pytest

from app.theme import system_appearance as sa


class FakeTk:
    """The Tcl interpreter of a Tk on macOS: answers the two calls the back-end makes."""

    def __init__(self, owner: "FakeAquaRoot") -> None:
        self._owner = owner

    def call(self, *args: str) -> str:
        if args == ("tk", "windowingsystem"):
            return self._owner.windowing_system
        if args == ("tk::unsupported::MacWindowStyle", "isdark", "."):
            if self._owner.isdark_error is not None:
                raise self._owner.isdark_error
            return self._owner.isdark
        raise tk.TclError(f"unexpected call {args!r}")


class FakeAquaRoot:
    """Stands in for the Tk root: ``bind`` / ``unbind`` / ``after``, fired by hand."""

    def __init__(self, dark: bool = False) -> None:
        self.windowing_system = "aqua"
        self.isdark = "1" if dark else "0"
        self.isdark_error: Exception | None = None
        self.tk = FakeTk(self)
        self.bindings: dict[str, dict[str, Callable[[Any], None]]] = {}
        self.unbound: list[tuple[str, str]] = []
        self.pending: dict[str, tuple[int, Callable[[], None]]] = {}
        self.dead = False
        self._n = 0

    def __str__(self) -> str:
        return "."          # Tk's name for the main window

    # appearance
    def set_dark(self, dark: bool) -> None:
        self.isdark = "1" if dark else "0"

    def send(self, sequence: str) -> None:
        """What Tk does on a flip: run every callback bound to the virtual event."""
        for fn in list(self.bindings.get(sequence, {}).values()):
            fn(SimpleNamespace())

    # tkinter surface
    def bind(self, sequence: str, func: Callable[[Any], None], add: Any = None) -> str:
        self._n += 1
        funcid = f"bind#{self._n}"
        self.bindings.setdefault(sequence, {})[funcid] = func
        return funcid

    def unbind(self, sequence: str, funcid: str | None = None) -> None:
        self.unbound.append((sequence, str(funcid)))
        self.bindings.get(sequence, {}).pop(str(funcid), None)

    def after(self, ms: int, fn: Callable[[], None]) -> str:
        if self.dead:
            raise tk.TclError("application has been destroyed")
        self._n += 1
        handle = f"after#{self._n}"
        self.pending[handle] = (ms, fn)
        return handle

    def after_cancel(self, handle: str) -> None:
        self.pending.pop(handle, None)

    def fire_after(self) -> None:
        handle = next(iter(self.pending))
        _ms, fn = self.pending.pop(handle)
        fn()


def _bound_events(root: FakeAquaRoot) -> set[str]:
    return {seq for seq, funcs in root.bindings.items() if funcs}


# ------------------------------------------------------------------ choosing the back-end

def test_darwin_gets_the_mac_backend_and_it_watches() -> None:
    backend = sa.get_backend("darwin")
    assert isinstance(backend, sa.MacBackend)
    assert backend.live is True


def test_windows_and_linux_keep_their_backends() -> None:
    assert isinstance(sa.get_backend("win32"), sa.WindowsBackend)
    assert isinstance(sa.get_backend("linux"), sa.DarkdetectBackend)
    assert sa.get_backend("linux").live is False


# --------------------------------------------------------------------------- reading it

@pytest.mark.parametrize(("raw", "dark"), [("1", True), ("0", False)])
def test_is_dark_reads_the_tk_answer(raw: str, dark: bool) -> None:
    root = FakeAquaRoot()
    root.isdark = raw
    assert sa.MacBackend(root).is_dark() is dark


def test_is_dark_uses_the_default_root_when_given_none(monkeypatch: pytest.MonkeyPatch) -> None:
    root = FakeAquaRoot(dark=True)
    monkeypatch.setattr(tk, "_default_root", root, raising=False)
    assert sa.MacBackend().is_dark() is True
    assert sa.resolve_theme("system", sa.get_backend("darwin")) == "dark"
    root.set_dark(False)
    assert sa.resolve_theme("system", sa.get_backend("darwin")) == "light"


def _darkdetect_says(monkeypatch: pytest.MonkeyPatch, answer: Any) -> None:
    monkeypatch.setitem(sys.modules, "darkdetect", SimpleNamespace(theme=lambda: answer))


def test_without_a_window_the_earlier_darkdetect_answer_is_used(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tk, "_default_root", None, raising=False)
    _darkdetect_says(monkeypatch, "Dark")
    assert sa.MacBackend().is_dark() is True
    _darkdetect_says(monkeypatch, "Light")
    assert sa.MacBackend().is_dark() is False


def test_without_a_window_or_darkdetect_the_answer_is_unknown_then_dark(
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tk, "_default_root", None, raising=False)
    monkeypatch.setitem(sys.modules, "darkdetect", None)
    assert sa.MacBackend().is_dark() is None
    assert sa.resolve_theme("system", sa.MacBackend()) == sa.UNKNOWN_FALLBACK


def test_a_tk_that_is_not_aqua_is_not_asked(monkeypatch: pytest.MonkeyPatch) -> None:
    root = FakeAquaRoot(dark=True)
    root.windowing_system = "x11"
    _darkdetect_says(monkeypatch, "Light")
    assert sa.MacBackend(root).is_dark() is False  # the darkdetect answer, not Tk's "1"


def test_a_tk_without_the_isdark_command_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    root = FakeAquaRoot(dark=True)
    root.isdark_error = tk.TclError("bad option \"isdark\"")
    _darkdetect_says(monkeypatch, "Dark")
    assert sa.MacBackend(root).is_dark() is True
    monkeypatch.setitem(sys.modules, "darkdetect", None)
    assert sa.MacBackend(root).is_dark() is None


def test_an_odd_isdark_value_is_unknown_not_a_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    root = FakeAquaRoot()
    root.isdark = "maybe"
    monkeypatch.setitem(sys.modules, "darkdetect", None)
    assert sa.MacBackend(root).is_dark() is None


@pytest.mark.parametrize("name", ["light", "dark"])
def test_an_explicit_choice_never_asks_the_system(name: str) -> None:
    class Exploding:
        live = True

        def is_dark(self) -> bool | None:
            raise AssertionError("an explicit choice must not read the system")

        def subscribe(self, callback: Any, root: Any) -> Any:
            raise AssertionError("not watched")

    assert sa.resolve_theme(name, Exploding()) == name


# --------------------------------------------------------------------------- watching it

def _subscribe(root: FakeAquaRoot, calls: list[int]) -> Callable[[], None]:
    return sa.MacBackend(root).subscribe(lambda: calls.append(1), root)


def test_subscribe_binds_the_two_proved_events_and_nothing_else() -> None:
    root = FakeAquaRoot()
    _subscribe(root, [])
    assert _bound_events(root) == {"<<LightAqua>>", "<<DarkAqua>>"}


def test_a_flip_calls_back_once_per_change() -> None:
    root, calls = FakeAquaRoot(dark=False), []
    _subscribe(root, calls)
    root.set_dark(True)
    root.send("<<DarkAqua>>")
    assert len(calls) == 1
    root.send("<<DarkAqua>>")        # Tk sends the event again: nothing changed
    assert len(calls) == 1
    root.set_dark(False)
    root.send("<<LightAqua>>")
    assert len(calls) == 2


def test_an_event_with_an_unreadable_state_is_not_a_change(monkeypatch: pytest.MonkeyPatch) -> None:
    root, calls = FakeAquaRoot(dark=False), []
    _subscribe(root, calls)
    monkeypatch.setitem(sys.modules, "darkdetect", None)
    root.isdark_error = tk.TclError("gone")
    root.send("<<DarkAqua>>")
    assert calls == []


def test_cancel_unbinds_and_a_late_event_does_nothing() -> None:
    root, calls = FakeAquaRoot(dark=False), []
    cancel = _subscribe(root, calls)
    stale = [fn for funcs in root.bindings.values() for fn in funcs.values()]
    cancel()
    cancel()                                            # idempotent
    assert _bound_events(root) == set()
    assert len(root.unbound) == 2
    root.set_dark(True)
    for fn in stale:                                    # an event already in flight
        fn(SimpleNamespace())
    assert calls == []


def test_a_failing_handler_is_retried_on_a_timer_then_dropped(caplog: pytest.LogCaptureFixture) -> None:
    root, attempts = FakeAquaRoot(dark=False), []

    def failing() -> None:
        attempts.append(1)
        raise RuntimeError("restyle broke")

    sa.MacBackend(root).subscribe(failing, root)
    root.set_dark(True)
    with caplog.at_level(logging.DEBUG, logger=sa.logger.name):
        root.send("<<DarkAqua>>")
        assert len(attempts) == 1 and len(root.pending) == 1      # retry scheduled
        root.fire_after()
        root.fire_after()
    assert len(attempts) == sa.MAX_CALLBACK_ATTEMPTS == 3
    assert root.pending == {}                                      # given up on this change
    root.send("<<DarkAqua>>")                                      # same state: not retried again
    assert len(attempts) == 3
    assert "giving up" in caplog.text


def test_a_failed_handler_that_works_on_retry_stops_retrying() -> None:
    root, attempts = FakeAquaRoot(dark=False), []

    def flaky() -> None:
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("once")

    sa.MacBackend(root).subscribe(flaky, root)
    root.set_dark(True)
    root.send("<<DarkAqua>>")
    root.fire_after()
    assert len(attempts) == 2 and root.pending == {}


def test_a_retry_after_the_window_is_gone_is_harmless() -> None:
    root = FakeAquaRoot(dark=False)

    def failing() -> None:
        raise RuntimeError("x")

    sa.MacBackend(root).subscribe(failing, root)
    root.set_dark(True)
    root.dead = True
    root.send("<<DarkAqua>>")        # cannot schedule the retry: no exception escapes


def test_a_cancel_removes_a_pending_retry() -> None:
    root = FakeAquaRoot(dark=False)

    def failing() -> None:
        raise RuntimeError("x")

    cancel = sa.MacBackend(root).subscribe(failing, root)
    root.set_dark(True)
    root.send("<<DarkAqua>>")
    assert len(root.pending) == 1
    cancel()
    assert root.pending == {}


def test_subscribe_on_a_root_that_cannot_bind_is_harmless() -> None:
    class Unbindable(FakeAquaRoot):
        def bind(self, *a: Any, **k: Any) -> str:
            raise tk.TclError("application has been destroyed")

    cancel = sa.MacBackend().subscribe(lambda: None, Unbindable())
    cancel()


def test_the_watcher_runs_the_mac_backend() -> None:
    root, calls = FakeAquaRoot(dark=False), []
    watcher = sa.SystemThemeWatcher(root, lambda: calls.append(1), backend=sa.MacBackend(root))
    watcher.start()
    watcher.start()
    assert watcher.running and _bound_events(root) == {"<<LightAqua>>", "<<DarkAqua>>"}
    root.set_dark(True)
    root.send("<<DarkAqua>>")
    assert calls == [1]
    watcher.stop()
    assert not watcher.running and _bound_events(root) == set()


def test_windows_deliver_is_still_the_windows_backends_own() -> None:
    state: dict[str, Any] = {"pending": None, "attempts": 0, "last": None}
    sa.WindowsBackend._deliver(True, state, lambda: None)
    assert state["last"] is True
