"""The "System" theme: Windows registry back-end, fallbacks, live watching (card C2.75).

The registry and darkdetect are faked, so the file runs on every OS. macOS and Linux keep the
earlier behaviour (darkdetect once, no watching): the last tests pin that.
"""
from __future__ import annotations

import logging
import sys
import tkinter as tk
import types
from types import SimpleNamespace
from typing import Any

import pytest

from app.theme import system_appearance as sa
from app.theme import tokens


# ------------------------------------------------------------------------- fakes

def _fake_winreg(monkeypatch: pytest.MonkeyPatch, value: Any = 0, *, error: Exception | None = None):
    """A winreg whose Personalize key holds ``value`` (or raises ``error`` on open)."""
    class _Key:
        def __enter__(self) -> "_Key":
            return self

        def __exit__(self, *exc: object) -> None:
            return None

    opened: list[tuple[Any, str]] = []

    def open_key(hive: Any, path: str) -> _Key:
        opened.append((hive, path))
        if error is not None:
            raise error
        return _Key()

    def query(_key: _Key, name: str) -> tuple[Any, int]:
        assert name == "AppsUseLightTheme"
        return value, 4

    mod = types.SimpleNamespace(HKEY_CURRENT_USER="HKCU", OpenKey=open_key, QueryValueEx=query)
    monkeypatch.setitem(sys.modules, "winreg", mod)
    return opened


class FakeRoot:
    """Stands in for Tk: records ``after`` calls; the test fires them by hand."""

    def __init__(self) -> None:
        self.pending: dict[str, Any] = {}
        self.cancelled: list[str] = []
        self._n = 0
        self.dead = False

    def after(self, ms: int, fn: Any) -> str:
        if self.dead:
            raise tk.TclError("application has been destroyed")
        self._n += 1
        handle = f"after#{self._n}"
        self.pending[handle] = (ms, fn)
        return handle

    def after_cancel(self, handle: str) -> None:
        self.cancelled.append(handle)
        self.pending.pop(handle, None)

    def fire(self) -> None:
        handle = next(iter(self.pending))
        _ms, fn = self.pending.pop(handle)
        fn()


class FakeBackend:
    def __init__(self, answer: bool | None = None, live: bool = True) -> None:
        self.answer = answer
        self.live = live
        self.subscriptions = 0
        self.cancelled = 0

    def is_dark(self) -> bool | None:
        return self.answer

    def subscribe(self, callback: Any, root: Any) -> Any:
        self.subscriptions += 1

        def cancel() -> None:
            self.cancelled += 1
        return cancel


# --------------------------------------------------------------- Windows registry value

@pytest.mark.parametrize("value, dark", [(0, True), (1, False)])
def test_windows_backend_reads_the_app_mode_value(monkeypatch, value, dark) -> None:
    opened = _fake_winreg(monkeypatch, value)
    assert sa.WindowsBackend().is_dark() is dark
    assert opened == [("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")]


def test_windows_backend_missing_value_means_a_light_windows(monkeypatch) -> None:
    _fake_winreg(monkeypatch, error=FileNotFoundError())
    assert sa.WindowsBackend().is_dark() is False


def test_windows_backend_cannot_read_gives_none_and_logs_once(monkeypatch, caplog) -> None:
    _fake_winreg(monkeypatch, error=PermissionError("denied"))
    backend = sa.WindowsBackend()
    with caplog.at_level(logging.WARNING, logger=sa.logger.name):
        assert backend.is_dark() is None
        assert backend.is_dark() is None
    assert len([r for r in caplog.records if "Windows app theme" in r.getMessage()]) == 1


def test_windows_backend_odd_value_gives_none(monkeypatch) -> None:
    _fake_winreg(monkeypatch, "not-a-number")
    assert sa.WindowsBackend().is_dark() is None


@pytest.mark.skipif(sys.platform != "win32", reason="reads this PC's real registry")
def test_windows_backend_reads_the_real_registry() -> None:
    assert sa.WindowsBackend().is_dark() in (True, False)


# ------------------------------------------------------------------- resolve_theme

@pytest.mark.parametrize("name", ["light", "dark"])
def test_explicit_choices_win_over_the_os(name) -> None:
    other = FakeBackend(answer=(name == "light"))  # the OS says the opposite
    assert sa.resolve_theme(name, other) == name


@pytest.mark.parametrize("name", ["", "Dark", "auto", "solarized"])
def test_an_unknown_choice_is_dark_as_before(name) -> None:
    assert sa.resolve_theme(name, FakeBackend(answer=False)) == "dark"


@pytest.mark.parametrize("answer, expected", [(True, "dark"), (False, "light")])
def test_system_follows_the_os_answer(answer, expected) -> None:
    assert sa.resolve_theme("system", FakeBackend(answer)) == expected


def test_system_with_no_answer_is_the_documented_fallback() -> None:
    assert sa.resolve_theme("system", FakeBackend(None)) == sa.UNKNOWN_FALLBACK == "dark"


def test_a_failing_backend_does_not_stop_startup(caplog) -> None:
    class Broken(FakeBackend):
        def is_dark(self) -> bool | None:
            raise RuntimeError("boom")

    with caplog.at_level(logging.WARNING, logger=sa.logger.name):
        assert sa.resolve_theme("system", Broken()) == "dark"
        assert sa.resolve_theme("system", Broken()) == "dark"
    assert len([r for r in caplog.records if "detection failed" in r.getMessage()]) == 1


def test_windows_system_theme_needs_no_darkdetect(monkeypatch) -> None:
    """The bug: a build without darkdetect always got dark. The registry has no such need."""
    monkeypatch.setitem(sys.modules, "darkdetect", None)  # import fails
    _fake_winreg(monkeypatch, 1)
    assert sa.resolve_theme("system", sa.get_backend("win32")) == "light"


# ------------------------------------------------------------------ backend choice

def test_get_backend_by_platform() -> None:
    assert isinstance(sa.get_backend("win32"), sa.WindowsBackend)
    for other in ("darwin", "linux"):
        backend = sa.get_backend(other)
        assert isinstance(backend, sa.DarkdetectBackend)
        assert backend.live is False


# ------------------------------------------- macOS / Linux: unchanged behaviour (pinned)

@pytest.mark.parametrize("answer, dark", [("Dark", True), ("Light", False), ("dark", True)])
def test_darkdetect_backend_maps_the_package_answer(monkeypatch, answer, dark) -> None:
    monkeypatch.setitem(sys.modules, "darkdetect", SimpleNamespace(theme=lambda: answer))
    assert sa.DarkdetectBackend().is_dark() is dark


def test_darkdetect_backend_no_answer_is_none(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "darkdetect", SimpleNamespace(theme=lambda: None))
    assert sa.DarkdetectBackend().is_dark() is None


def test_missing_darkdetect_falls_back_to_dark_and_says_so(monkeypatch, caplog) -> None:
    monkeypatch.setitem(sys.modules, "darkdetect", None)
    with caplog.at_level(logging.WARNING, logger=sa.logger.name):
        assert sa.resolve_theme("system", sa.get_backend("darwin")) == "dark"
        assert sa.resolve_theme("system", sa.get_backend("linux")) == "dark"
    messages = [r.getMessage() for r in caplog.records]
    assert sum("darkdetect is not installed" in m for m in messages) == 1


def test_darkdetect_that_raises_falls_back_to_dark(monkeypatch) -> None:
    def boom() -> str:
        raise OSError("no portal")

    monkeypatch.setitem(sys.modules, "darkdetect", SimpleNamespace(theme=boom))
    assert sa.resolve_theme("system", sa.DarkdetectBackend()) == "dark"


def test_off_windows_nothing_is_watched() -> None:
    root = FakeRoot()
    watcher = sa.SystemThemeWatcher(root, lambda: None, backend=sa.get_backend("darwin"))
    watcher.start()
    assert not watcher.running
    assert root.pending == {}


# ---------------------------------------------------------- Windows watching (after-poll)

def _watch(monkeypatch, answers: list[bool | None]):
    """A WindowsBackend whose registry answers come from ``answers`` (one per read)."""
    backend = sa.WindowsBackend(poll_ms=500)
    queue = list(answers)
    last: list[bool | None] = [None]

    def is_dark() -> bool | None:
        if queue:
            last[0] = queue.pop(0)
        return last[0]

    monkeypatch.setattr(backend, "is_dark", is_dark)
    return backend


def test_a_change_calls_back_once_and_polling_is_slow(monkeypatch) -> None:
    root, calls = FakeRoot(), []
    backend = _watch(monkeypatch, [False, False, True, True, False])
    cancel = backend.subscribe(lambda: calls.append(1), root)  # reads False
    assert [ms for ms, _fn in root.pending.values()] == [500]  # one timer, not a busy loop
    root.fire()   # False: same
    assert calls == []
    root.fire()   # True: changed
    assert calls == [1]
    root.fire()   # True: same
    assert calls == [1]
    root.fire()   # False: changed back
    assert calls == [1, 1]
    cancel()


def test_an_unreadable_value_is_not_a_change(monkeypatch) -> None:
    root, calls = FakeRoot(), []
    backend = _watch(monkeypatch, [True, None, True])
    backend.subscribe(lambda: calls.append(1), root)
    root.fire()
    root.fire()
    assert calls == []
    assert len(root.pending) == 1  # still watching


def test_cancel_stops_the_timer_and_never_calls_back(monkeypatch) -> None:
    root, calls = FakeRoot(), []
    backend = _watch(monkeypatch, [False, True])
    cancel = backend.subscribe(lambda: calls.append(1), root)
    cancel()
    assert root.pending == {} and len(root.cancelled) == 1
    cancel()  # twice is harmless
    assert calls == []


def test_a_failing_callback_does_not_end_the_watch(monkeypatch, caplog) -> None:
    root = FakeRoot()
    backend = _watch(monkeypatch, [False, True])

    def bad() -> None:
        raise RuntimeError("restyle failed")

    backend.subscribe(bad, root)
    with caplog.at_level(logging.ERROR, logger=sa.logger.name):
        root.fire()
    assert len(root.pending) == 1
    assert any("handler failed" in r.getMessage() for r in caplog.records)


def test_a_destroyed_window_ends_the_watch(monkeypatch) -> None:
    root = FakeRoot()
    backend = _watch(monkeypatch, [False, True])
    backend.subscribe(lambda: None, root)
    root.dead = True
    root.fire()
    assert root.pending == {}


def test_subscribe_on_a_dead_window_is_harmless(monkeypatch) -> None:
    root = FakeRoot()
    root.dead = True
    cancel = _watch(monkeypatch, [False]).subscribe(lambda: None, root)
    cancel()


# ------------------------------------------------------------------------- watcher

def test_watcher_starts_once_and_stops_idempotently() -> None:
    backend = FakeBackend()
    watcher = sa.SystemThemeWatcher(FakeRoot(), lambda: None, backend=backend)
    watcher.start()
    watcher.start()
    assert backend.subscriptions == 1 and watcher.running
    watcher.stop()
    watcher.stop()
    assert backend.cancelled == 1 and not watcher.running
    watcher.start()  # can be restarted (theme mode: system again)
    assert backend.subscriptions == 2


def test_watcher_ignores_a_backend_that_cannot_watch() -> None:
    backend = FakeBackend(live=False)
    watcher = sa.SystemThemeWatcher(FakeRoot(), lambda: None, backend=backend)
    watcher.start()
    assert backend.subscriptions == 0 and not watcher.running


# ------------------------------------------------------------------- real Tk (poll)

def test_the_real_tk_after_loop_follows_a_change(monkeypatch) -> None:
    try:
        root = tk.Tk()
    except tk.TclError as exc:  # pragma: no cover - no display
        pytest.skip(f"no Tk display: {exc}")
    root.withdraw()
    try:
        answers = {"now": False}
        backend = sa.WindowsBackend(poll_ms=20)
        monkeypatch.setattr(backend, "is_dark", lambda: answers["now"])
        seen: list[bool] = []
        cancel = backend.subscribe(lambda: seen.append(answers["now"]), root)
        answers["now"] = True
        deadline = 0
        while not seen and deadline < 100:
            root.update()
            root.after(10)
            deadline += 1
        cancel()
        assert seen == [True]
    finally:
        root.destroy()


# --------------------------------------------------------- app wiring (no full App)

def _app_double(mode: str, restyles: list[str], watch: Any = None) -> Any:
    from app import app as app_module

    double = SimpleNamespace(theme_var=SimpleNamespace(get=lambda: mode),
                             _restyle=restyles.append, _system_theme_watch=watch)
    double._on_system_theme_change = lambda: app_module.App._on_system_theme_change(double)
    double._sync = lambda name: app_module.App._sync_system_theme_watch(double, name)
    return double


def test_app_restyles_on_an_os_change_in_system_mode(monkeypatch) -> None:
    from app import app as app_module

    monkeypatch.setattr(app_module.system_appearance, "get_backend", lambda *a, **k: FakeBackend(False))
    monkeypatch.setattr(tokens, "_theme", "dark")
    seen: list[str] = []
    _app_double("system", seen)._on_system_theme_change()
    assert seen == ["system"]


def test_app_does_nothing_when_the_theme_is_already_right(monkeypatch) -> None:
    from app import app as app_module

    monkeypatch.setattr(app_module.system_appearance, "get_backend", lambda *a, **k: FakeBackend(True))
    monkeypatch.setattr(tokens, "_theme", "dark")
    seen: list[str] = []
    _app_double("system", seen)._on_system_theme_change()
    assert seen == []


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_an_explicit_choice_ignores_the_os(monkeypatch, mode) -> None:
    from app import app as app_module

    monkeypatch.setattr(app_module.system_appearance, "get_backend", lambda *a, **k: FakeBackend(True))
    monkeypatch.setattr(tokens, "_theme", "light")
    seen: list[str] = []
    _app_double(mode, seen)._on_system_theme_change()
    assert seen == []


def test_the_watch_runs_only_in_system_mode() -> None:
    backend = FakeBackend()
    watch = sa.SystemThemeWatcher(FakeRoot(), lambda: None, backend=backend)
    double = _app_double("system", [], watch)
    double._sync("system")
    assert watch.running
    double._sync("dark")
    assert not watch.running
    double._sync("system")
    double._sync("light")
    assert backend.subscriptions == 2 and backend.cancelled == 2


def test_app_resolves_system_through_the_os_module(monkeypatch) -> None:
    from app import app as app_module

    monkeypatch.setattr(app_module.system_appearance, "get_backend", lambda *a, **k: FakeBackend(False))
    assert app_module._resolve_theme("system") == "light"
    assert app_module._resolve_theme("dark") == "dark"
    assert app_module._resolve_theme("light") == "light"
    assert app_module._resolve_theme("nonsense") == "dark"
