"""Regression: ModelDownloadDialog's retry path must start a *clean*
attempt.

A retry after the not-writable re-pick can arrive right after the user
clicked Cancel (that click raced the ModelDestinationNotWritable out of
ensure_model). ``_start_worker`` must clear the stale cancel_event and
re-enable the Cancel button, otherwise the retry worker sees the old
cancellation, raises DownloadCancelled immediately, and the dialog
closes having silently done nothing — with Cancel still disabled.

Bare-instance test (``__new__`` + stubbed attributes, no Tk root), same
pattern as tests/core/test_fixpack_sw2_viewer.py.
"""
from __future__ import annotations

import threading


class _FakeButton:
    def __init__(self, state: str = "disabled") -> None:
        self.state = state

    def configure(self, *, state: str) -> None:
        self.state = state


def _bare_dialog():
    from app.dialogs.model_download import ModelDownloadDialog

    dlg = ModelDownloadDialog.__new__(ModelDownloadDialog)
    dlg.cancel_event = threading.Event()  # type: ignore[attr-defined]
    dlg.done = True  # type: ignore[attr-defined]
    dlg.success = True  # type: ignore[attr-defined]
    dlg.error = "stale error"  # type: ignore[attr-defined]
    dlg.not_writable_dir = "C:/somewhere"  # type: ignore[attr-defined]
    dlg.cancel_btn = _FakeButton()  # type: ignore[attr-defined]
    return dlg


def test_start_worker_clears_stale_cancel_event(monkeypatch):
    captured: dict = {}

    def _fake_safe_thread(target, *, name=None, **_kw):
        captured["target"] = target
        captured["name"] = name

    monkeypatch.setattr("core._threads.safe_thread", _fake_safe_thread)

    dlg = _bare_dialog()
    dlg.cancel_event.set()

    dlg._start_worker()

    # A fresh attempt must not inherit the previous Cancel click.
    assert not dlg.cancel_event.is_set()
    # Per-attempt state reset (existing behaviour, guarded here).
    assert dlg.done is False
    assert dlg.success is False
    assert dlg.error is None
    assert dlg.not_writable_dir is None
    # The Cancel button a previous cancel() disabled is usable again.
    assert dlg.cancel_btn.state == "normal"
    assert captured["name"] == "model-download-dialog"
    assert captured["target"] == dlg._worker


def test_cancel_event_cleared_even_without_prior_cancel(monkeypatch):
    """Normal second attempt (no Cancel clicked): clearing an already
    clear event is a no-op and nothing else regresses."""
    monkeypatch.setattr("core._threads.safe_thread", lambda *a, **kw: None)

    dlg = _bare_dialog()
    dlg.cancel_event.clear()

    dlg._start_worker()

    assert not dlg.cancel_event.is_set()
    assert dlg.done is False
