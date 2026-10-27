"""finish_task hands a FINISHED job to core.finish_hooks, after it is saved.

Windowless: the app is a plain namespace (same shape as test_star_bar.py).
"""
from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any

import pytest

from app.services.transcription_service import TranscriptionService
from core import finish_hooks


def _task(**over: Any) -> SimpleNamespace:
    base: dict[str, Any] = dict(
        status="running", cancelled=False, end_time=None, start_time=time.time(),
        output_paths=["C:/m/clip.srt", "C:/m/clip.json"], file_path="C:/m/clip.mp4",
        history_id=7, source_download=None, detected_language="de",
        speed_model="large-v3", audio_duration=42.0, word_count=5,
    )
    base.update(over)
    return SimpleNamespace(**base)


def _finish(task: Any, config: dict[str, Any], events: list[str], *, keep_status=False):
    app = SimpleNamespace(
        app_config=config, update_overall_progress=lambda: None,
        show_last_result=lambda t: events.append("card"),
        note_job_success=lambda: None, history=None,
        log=lambda *_a, **_k: None,
    )
    svc = TranscriptionService(app)  # type: ignore[arg-type]
    svc._post_usage_stats = lambda *a, **k: None  # type: ignore[method-assign]
    svc.finish_task({"task": task, "temporary": False}, keep_status=keep_status)


@pytest.fixture()
def calls(monkeypatch: pytest.MonkeyPatch) -> list[tuple[dict, finish_hooks.FinishedJob]]:
    seen: list[tuple[dict, finish_hooks.FinishedJob]] = []
    monkeypatch.setattr(finish_hooks, "deliver_async",
                        lambda cfg, job: seen.append((dict(cfg), job)))
    return seen


def test_a_finished_job_is_delivered_after_the_result_card(calls, monkeypatch) -> None:
    events: list[str] = []
    monkeypatch.setattr(finish_hooks, "deliver_async",
                        lambda cfg, job: events.append("hooks"))
    _finish(_task(), {"obsidian_vault_dir": "C:/vault"}, events)
    assert events == ["card", "hooks"]


def test_the_job_carries_the_facts(calls) -> None:
    _finish(_task(), {"obsidian_vault_dir": "C:/vault"}, [])
    (cfg, job), = calls
    assert cfg["obsidian_vault_dir"] == "C:/vault"
    assert job.title == "clip" and job.source == "C:/m/clip.mp4"
    assert job.status == "finished" and job.language == "de"
    assert job.model == "large-v3" and job.duration == 42.0
    assert job.output_paths == ["C:/m/clip.srt", "C:/m/clip.json"]
    assert job.job_id == "h7"


def test_a_downloaded_source_reports_its_link(calls) -> None:
    dl = SimpleNamespace(url="https://example.com/v", status="done",
                         make_subbed_video=False, transcription_task=None)
    app_cfg = {"finish_webhook_url": "https://example.com/hook"}
    _finish(_task(source_download=dl), app_cfg, [])
    assert calls[0][1].source == "https://example.com/v"


def test_nothing_set_means_nothing_runs(calls) -> None:
    _finish(_task(), {}, [])
    assert calls == []


@pytest.mark.parametrize("task_kw,keep", [
    ({"status": "error"}, True),
    ({"cancelled": True}, False),
    ({"open_when_done": True}, False),
])
def test_unfinished_cancelled_and_sample_jobs_are_not_delivered(calls, task_kw, keep) -> None:
    _finish(_task(**task_kw), {"obsidian_vault_dir": "C:/vault"}, [], keep_status=keep)
    assert calls == []


def test_a_failing_hand_off_cannot_break_the_job(monkeypatch) -> None:
    def boom(cfg, job):
        raise RuntimeError("boom")
    monkeypatch.setattr(finish_hooks, "deliver_async", boom)
    task = _task()
    _finish(task, {"obsidian_vault_dir": "C:/vault"}, [])
    assert task.status == "finished"


def test_the_save_in_advanced_writes_the_settings(monkeypatch) -> None:
    from app.dialogs import advanced as adv
    from tests.core.test_advanced_simplified import _base_cfg, _fake_app, _fake_dialog, _V

    cfg = _base_cfg()
    monkeypatch.setattr(adv, "save_config", lambda _c: None)
    adv.AdvancedDialog._save_and_close(  # type: ignore[arg-type]
        _fake_dialog(
            _fake_app(cfg),
            _obsidian_vault_dir=_V("  D:\\Vault "),
            _finish_webhook_url=_V(" https://example.com/h "),
            _finish_webhook_secret=_V(" dummy-credential-A "),
            _finish_webhook_include_text=_V(True),
        )
    )
    assert cfg["obsidian_vault_dir"] == "D:\\Vault"
    assert cfg["finish_webhook_url"] == "https://example.com/h"
    assert cfg["finish_webhook_secret"] == "dummy-credential-A"
    assert cfg["finish_webhook_include_text"] is True
