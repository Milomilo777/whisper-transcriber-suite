"""If sending the cancel's ``done`` itself fails, the worker falls back to ``error``."""
from __future__ import annotations

from core import worker
from tests.core.test_worker_cancel_error import _run


def test_failing_done_after_cancel_falls_back_to_error(monkeypatch, capsys):
    def boom(task):
        raise ValueError("speed labels broke")

    monkeypatch.setattr(worker, "_speed_fields", boom)

    def fake(task, progress_cb, log_cb, language_cb=None):
        task.cancelled = True
        raise RuntimeError("ffmpeg was stopped")

    events = _run(monkeypatch, capsys, fake)
    errs = [e for e in events if e["event"] == "error"]
    assert len(errs) == 1 and "ffmpeg was stopped" in errs[0]["message"]
