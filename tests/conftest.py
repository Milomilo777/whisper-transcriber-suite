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
STT). See ``docs/history/TEST_ISOLATION_FOLLOWUP.md``.

This snapshots + restores (NOT resets) the globals around every test, so a
module-scoped model fixture (e.g. ``tests/smoke/test_v08_real_file_e2e.py``'s
``transcribed_clip``) is preserved within its own module while cross-file
leakage is contained at the source. Lives at the ``tests/`` root (not just
``tests/core/``) so it also covers ``tests/smoke/``, which needed it after
``test_v08_real_file_e2e.py`` moved there 2026-08-15 (see
``docs/DECISIONS.md`` ADR 0008 / ``docs/SESSION_HANDOFF_NEXT.md`` — that move
was to stop it running concurrently with the rest of the ~700-test hermetic
suite, which was implicated in a real, hard-to-pin-down native crash).
"""
from __future__ import annotations

import pytest

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
