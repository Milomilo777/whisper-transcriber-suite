"""Fixtures shared by every test subdirectory (``tests/core``, ``tests/app``,
``tests/smoke``, ...).

Autouse isolation guard: several tests call the REAL transcriber load
functions (``load_existing_model``, ``_load_whisper_model_self_healing``,
``_load_alt_backend``), which mutate ``core.transcriber`` module globals via
``global`` statements. ``monkeypatch`` cannot undo those (it only reverts
attributes it set itself), so without this guard a test that activates a fake
model or an alternate backend leaks that state into later test files — which
produces order-dependent failures whose set shifts with machine state (for
example whether a bundled Google Cloud key flips the default engine to cloud
STT).

This snapshots + restores (NOT resets) the globals around every test, so a
module-scoped model fixture (e.g. ``tests/smoke/test_v08_real_file_e2e.py``'s
``transcribed_clip``) is preserved within its own module while cross-file
leakage is contained at the source. Lives at the ``tests/`` root (not just
``tests/core/``) so it also covers ``tests/smoke/``, which needed it after
``test_v08_real_file_e2e.py`` moved there 2026-08-15 (see
``docs/DECISIONS.md`` ADR 0008 — that move
was to stop it running concurrently with the rest of the ~700-test hermetic
suite, which was implicated in a real, hard-to-pin-down native crash).
"""
from __future__ import annotations

import gc
import sys
from pathlib import Path

import platformdirs
import pytest

from tests import tk_init_retry as _tk_init_retry

# The real platformdirs functions, captured before any fixture patches them.
# ``tests/test_user_dir_isolation.py`` uses them to learn where the real
# per-user folders are, so it can prove no test path points there.
REAL_PLATFORMDIRS = {
    name: getattr(platformdirs, name)
    for name in (
        "user_config_dir",
        "user_cache_dir",
        "user_log_dir",
        "user_data_dir",
        "user_state_dir",
    )
}


@pytest.fixture(autouse=True)
def _isolate_user_dirs(tmp_path_factory, monkeypatch):
    """Point every platformdirs per-user folder at a throwaway directory.

    ``core.config.user_config_dir()`` / ``user_log_dir()`` / ``user_data_dir()`` /
    ``user_cache_dir()`` all resolve through ``platformdirs``. Without this a test
    that does not patch them writes into the developer's real app folders: log
    lines in ``Logs/``, rows in ``history.db``, job folders in ``Cache/`` and even
    a ``save_config()`` call against the real ``config.json``. Each test gets its
    own empty tree; a test that needs a specific path still patches
    ``core.config.user_*_dir`` itself, which takes precedence.
    """
    root = tmp_path_factory.mktemp("userdirs")

    def _fake(kind: str):
        def user_dir(appname=None, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
            return str(Path(root) / kind / str(appname or "app"))

        return user_dir

    for name in REAL_PLATFORMDIRS:
        monkeypatch.setattr(platformdirs, name, _fake(name))
    yield

# core.transcriber module globals that the real load paths mutate in place.
_TRANSCRIBER_GLOBALS = (
    "MODEL",
    "PIPELINE",
    "MODEL_READY",
    "MODEL_ERROR",
    "_ALT_BACKEND",
    "_ALT_BACKEND_NAME",
)


@pytest.fixture(autouse=True)
def _reset_burn_process_state():
    """Forget the subtitle burns of an earlier test.

    core.burn_subs keeps process-wide state: the one-way "the app is closing"
    flag (set by App.on_exit), the reserved and produced output records and
    the list of running burns. A test that closes the app would otherwise
    make every later burn in the same pytest process raise BurnCancelled.
    """
    from core import burn_subs

    def _reset() -> None:
        burn_subs._closing.clear()
        burn_subs._reserved.clear()
        burn_subs._produced.clear()
        burn_subs._active.clear()

    _reset()
    yield
    _reset()


@pytest.fixture(autouse=True)
def _isolate_transcriber_globals():
    """Snapshot core.transcriber module globals; restore them after the test."""
    try:
        import core.transcriber as _t
    except Exception:  # noqa: BLE001 — an import failure here is unrelated
        yield
        return
    sentinel = object()
    saved = {name: getattr(_t, name, sentinel) for name in _TRANSCRIBER_GLOBALS}
    try:
        yield
    finally:
        for name, value in saved.items():
            if value is not sentinel:
                setattr(_t, name, value)


_tk_touched = False
_last_module: object = None


def _mark_tk_touched(cls, attr):
    original = getattr(cls, attr)

    def wrapper(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        global _tk_touched
        _tk_touched = True
        return original(self, *args, **kwargs)

    setattr(cls, attr, wrapper)


try:
    import tkinter as _tkinter

    for _cls, _attr in (
        (_tkinter.Tk, "__init__"),
        (_tkinter.BaseWidget, "_setup"),
        (_tkinter.Variable, "__init__"),
        (_tkinter.Image, "__init__"),
    ):
        _mark_tk_touched(_cls, _attr)
    # Retry the one transient "cannot read init.tcl" start-up fault (see tk_init_retry).
    _tkinter.Tk.__init__ = _tk_init_retry.wrap_init(_tkinter.Tk.__init__)  # type: ignore[method-assign]
except Exception:  # noqa: BLE001 — no Tk on this interpreter
    pass


def pytest_terminal_summary(terminalreporter):  # type: ignore[no-untyped-def]
    """Report how many times tk.Tk() needed the init.tcl retry (never silent)."""
    if _tk_init_retry.retries:
        terminalreporter.write_sep(
            "-", f"tk.Tk() init.tcl retries: {len(_tk_init_retry.retries)}"
        )
        for line in _tk_init_retry.retries:
            terminalreporter.write_line(f"  {line}")


@pytest.fixture(autouse=True)
def _collect_tk_garbage_on_main_thread(request):
    """Free unreachable Tk objects on the main thread after GUI tests.

    Tk objects left behind by a GUI test (widgets, images, variables) sit in
    reference cycles until the cyclic GC runs. If that GC pass happens to
    fire on a worker thread of a later test (e.g. test_fixpack_F's
    HistoryDB reader threads), their __del__ calls into Tcl from the wrong
    thread and Tcl aborts the whole process (exit 134, "Garbage-collecting"
    in the faulthandler dump). Collecting here keeps that on the main thread.
    Only tests that created a Tk object pay for the collection, plus one
    pass at each new test module, which catches module-scoped Tk roots torn
    down after the previous module's last test.
    """
    global _tk_touched, _last_module
    module = getattr(request.node, "module", None)
    if module is not _last_module:
        _last_module = module
        if "tkinter" in sys.modules:
            gc.collect()
    _tk_touched = False
    yield
    if _tk_touched:
        _tk_touched = False
        gc.collect()


@pytest.fixture(autouse=True)
def _no_legacy_app_data_migration(monkeypatch):
    """Keep load_config() from touching the real pre-rebrand profile.

    ``migrate_legacy_app_data`` copies files and MOVES cache folders out of
    the developer's actual ``WhisperProject`` profile; tests that exercise
    it patch ``_legacy_app_dirs`` back to a tmp_path layout themselves.
    """
    try:
        import core.config as _cfg
    except Exception:  # noqa: BLE001
        return
    monkeypatch.setattr(_cfg, "_legacy_app_dirs", lambda: None)


@pytest.fixture(autouse=True)
def _work_offline_off(monkeypatch):
    """Work offline is off in every test unless the test turns it on.

    ``core.offline.is_offline`` otherwise reads the developer's real
    config.json, where the switch may be on. Tests of that file read set the
    in-memory switch back to None themselves. A backstop a test installed is
    removed after it.
    """
    try:
        import core.offline as _offline
    except Exception:  # noqa: BLE001
        yield
        return
    monkeypatch.setattr(_offline, "_override", False)
    # The switch's file cache (stat key) must not leak between tests.
    monkeypatch.setattr(_offline, "_cache_key", None)
    # Tests that run a real entry point (worker.main, gui.main) install the
    # socket backstop; remove it again so it never outlives that test.
    guard_was_installed = _offline.network_guard_installed()
    yield
    if not guard_was_installed:
        _offline.uninstall_network_guard()


@pytest.fixture(autouse=True)
def _reset_install_stop_flag():
    """``App.on_exit`` asks every package install to stop for good (process-wide).

    A test that runs the real exit path must not make the next test's install() cancel.
    """
    yield
    try:
        import core.optional_deps as _od
    except Exception:  # noqa: BLE001 - an import failure here is unrelated
        return
    _od._stop_requested.clear()
