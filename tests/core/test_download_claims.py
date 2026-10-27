"""Who owns an unfinished download's name and partial file (ADR 0019).

A name claim belongs to one task. Another task for the same link and format never takes over the
partial of a task that is paused or still running, a cancel never deletes a partial that another
task owns, and a claim that outlived its partial or its age limit no longer counts. Same
stand-in for yt-dlp as ``test_downloads_keep_user_files``. No Tk, no network.
"""
from __future__ import annotations

import json

from app.services import download_service as ds
from tests.core.test_downloads_keep_user_files import _run, _task, env  # noqa: F401  (env is a fixture)


def _video(folder, **kw):
    return _task(folder, mode="Audio and video", output="mp4", **kw)


def test_a_second_task_does_not_take_a_paused_tasks_partial(env, monkeypatch):   # noqa: F811
    svc, folder, _ = env
    monkeypatch.setenv("FAKE_YTDLP_DIE_PART", "1")
    first = _video(folder)
    assert _run(svc, first)[0] == 1
    first.status, first.paused = "paused", True              # the user paused it; the partial stays
    monkeypatch.delenv("FAKE_YTDLP_DIE_PART")
    second = _video(folder)                                   # same link and format, added again
    rc, _e, _l, saved, _f = _run(svc, second)
    assert rc == 0 and saved == str(folder / "Title A (1).mp4")
    assert (folder / "Title A.mp4.part").read_bytes() == b"first half"
    first.status, first.paused = "waiting", False             # the pause is over: it continues its own file
    rc, _e, _l, saved, _f = _run(svc, first)
    assert rc == 0 and saved == str(folder / "Title A.mp4")
    assert (folder / "Title A.mp4").read_bytes().startswith(b"first half|video:")
    assert (folder / "Title A (1).mp4").exists()


def test_cancel_never_deletes_a_partial_another_task_owns(env, monkeypatch):   # noqa: F811
    svc, folder, _ = env
    monkeypatch.setenv("FAKE_YTDLP_DIE_PART", "1")
    failed = _video(folder)
    _run(svc, failed)
    failed.status = "error"
    adopter = _video(folder)                                  # takes the leftover of the failed task
    _run(svc, adopter)
    adopter.status, adopter.paused = "paused", True
    part = folder / "Title A.mp4.part"
    assert part.exists()
    svc.remove_partial_files(failed)                          # Cancel on the old failed row
    assert part.read_bytes() == b"first half"                 # the paused task's partial survives
    claims = json.loads((ds._claims_path()).read_text(encoding="utf-8"))
    assert any(rec["task"] == ds._task_token(adopter) for rec in claims.values())
    svc.remove_partial_files(adopter)                         # its own cancel does clean up
    assert not part.exists()
