"""The YouTube fallback re-checks the stop state after its updater waits.

``_smtv_youtube_fallback`` passes its stop checks, then waits in
``maybe_update_yt_dlp`` (up to a minute) and ``begin_download``. A Cancel,
a Work offline switch or a superseding run landing in that wait has no
process to kill yet; without a second check the fallback still started a
new yt-dlp download. Same stubs as test_smtv_youtube_fallback.py.
"""
from __future__ import annotations

import queue
import types

import pytest

from app.services import download_service as ds
from app.services.download_service import DownloadService
from core.integrations import smtv as smtv_mod

PAGE = "https://suprememastertv.com/en1/v/123.html"


def _task(tmp_path) -> types.SimpleNamespace:
    chosen = {"kind": "smtv", "mode": "audio", "url": "https://cdn.example/x.mp3"}
    episode = smtv_mod.SmtvEpisode(vid="123", title="Some Episode", page_url=PAGE,
                                   lang_prefix="en", youtube_id="AbCdEf01234")
    return types.SimpleNamespace(
        folder=str(tmp_path), url=PAGE, cancelled=False, paused=False, _run_generation=1,
        format_info={"mode": "Audio", "audio": chosen, "video": None, "output": "mp4",
                     "episode": episode},
    )


def _svc():
    events: queue.Queue = queue.Queue()
    app = types.SimpleNamespace(download_events=events, app_config={},
                                yt_dlp_path=lambda: "yt-dlp", bin_path=lambda: "")
    svc = DownloadService(app)  # type: ignore[arg-type]
    commands: list[list[str]] = []

    def official(task, *, run_generation=None):
        raise RuntimeError("SMTV CDN download truncated: received 10 of 99 bytes")

    def media(task, command):
        commands.append(command)
        return 0, "", "", "x.mp3", True

    svc._run_smtv_task = official  # type: ignore[method-assign]
    svc._run_media_process = media  # type: ignore[method-assign]
    svc.maybe_update_yt_dlp = lambda task: None  # type: ignore[method-assign]
    return svc, events, commands


def _drain(events: queue.Queue) -> list[tuple]:
    out = []
    while not events.empty():
        out.append(events.get_nowait())
    return out


@pytest.mark.parametrize("wait", ["update", "begin_download"])
def test_a_cancel_during_the_wait_starts_no_fallback_process(tmp_path, monkeypatch, wait):
    svc, events, commands = _svc()
    task = _task(tmp_path)

    def _cancel_now(*_a, **_k):
        task.cancelled = True

    if wait == "update":
        svc.maybe_update_yt_dlp = _cancel_now  # type: ignore[method-assign]
    else:
        monkeypatch.setattr(ds.yt_dlp_update, "begin_download", _cancel_now)

    svc._run_smtv_with_fallback(task, 1, object())  # type: ignore[arg-type]

    assert commands == []
    got = _drain(events)
    assert ("done", task, "cancelled") in got  # reported once, like every cancel path
    assert not [g for g in got if g[0] == "error"]


def test_work_offline_during_the_wait_starts_no_fallback_process(tmp_path, monkeypatch):
    svc, events, commands = _svc()
    task = _task(tmp_path)
    monkeypatch.setattr(ds.offline, "is_offline", lambda *_a, **_k: False)

    def _go_offline(_task):
        monkeypatch.setattr(ds.offline, "is_offline", lambda *_a, **_k: True)

    svc.maybe_update_yt_dlp = _go_offline  # type: ignore[method-assign]
    svc._run_smtv_with_fallback(task, 1, object())  # type: ignore[arg-type]

    assert commands == []
    errors = [g for g in _drain(events) if g[0] == "error"]
    assert len(errors) == 1 and "truncated" in errors[0][2]


def test_a_superseding_run_during_the_wait_starts_nothing_and_stays_silent(tmp_path):
    svc, events, commands = _svc()
    task = _task(tmp_path)

    def _resumed(_task):
        task._run_generation = 2

    svc.maybe_update_yt_dlp = _resumed  # type: ignore[method-assign]
    svc._run_smtv_with_fallback(task, 1, object())  # type: ignore[arg-type]

    assert commands == []
    assert [g for g in _drain(events) if g[0] in ("done", "done_full", "error")] == []


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
