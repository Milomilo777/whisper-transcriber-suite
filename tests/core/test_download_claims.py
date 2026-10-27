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


def test_a_claim_without_its_partial_does_not_make_a_later_file_the_jobs_own(env, monkeypatch):   # noqa: F811
    svc, folder, _ = env
    monkeypatch.setenv("FAKE_YTDLP_DIE_PART", "1")
    failed = _video(folder)
    _run(svc, failed)
    failed.status = "error"
    (folder / "Title A.mp4.part").unlink()                    # the partial is gone ...
    mine = folder / "Title A.mp4"
    mine.write_bytes(b"the user's own copy")                  # ... and the user saved a file of that name
    monkeypatch.delenv("FAKE_YTDLP_DIE_PART")
    rc, _e, _l, saved, _f = _run(svc, _video(folder))
    assert rc == 0 and saved == str(folder / "Title A (1).mp4")
    assert mine.read_bytes() == b"the user's own copy"


def test_a_claim_older_than_two_weeks_is_not_honoured(env, monkeypatch):   # noqa: F811
    svc, folder, _ = env
    monkeypatch.setenv("FAKE_YTDLP_DIE_PART", "1")
    _run(svc, _video(folder))
    monkeypatch.delenv("FAKE_YTDLP_DIE_PART")
    path = ds._claims_path()
    claims = json.loads(path.read_text(encoding="utf-8"))
    for rec in claims.values():
        rec["created"] = rec.get("created", 0) - 15 * 86400 if rec.get("created") else 1.0
        rec["session"] = "an-earlier-run"                     # an earlier run of the app wrote it
    path.write_text(json.dumps(claims), encoding="utf-8")
    rc, _e, _l, saved, _f = _run(svc, _video(folder))
    assert rc == 0 and saved == str(folder / "Title A (1).mp4")
    assert (folder / "Title A.mp4.part").read_bytes() == b"first half"


def test_a_fresh_claim_of_an_earlier_app_run_still_resumes(env, monkeypatch):   # noqa: F811
    svc, folder, _ = env
    monkeypatch.setenv("FAKE_YTDLP_DIE_PART", "1")
    _run(svc, _video(folder))
    monkeypatch.delenv("FAKE_YTDLP_DIE_PART")
    path = ds._claims_path()
    claims = json.loads(path.read_text(encoding="utf-8"))
    for rec in claims.values():
        rec["session"] = "an-earlier-run"
    path.write_text(json.dumps(claims), encoding="utf-8")
    rc, _e, _l, saved, _f = _run(svc, _video(folder))
    assert rc == 0 and saved == str(folder / "Title A.mp4")
    assert (folder / "Title A.mp4").read_bytes().startswith(b"first half|video:")


def test_a_claim_that_was_just_updated_survives_the_trim(env, monkeypatch):   # noqa: F811
    import time

    svc, folder, _ = env
    monkeypatch.setenv("FAKE_YTDLP_DIE_PART", "1")
    task = _video(folder)
    _run(svc, task)
    path = ds._claims_path()
    claims = json.loads(path.read_text(encoding="utf-8"))
    (stem,) = claims
    filler = {"key": "other", "task": "t", "session": "s", "created": time.time(), "files": []}
    claims.update({f"filler-{i}": dict(filler) for i in range(200)})   # the real entry is the oldest
    path.write_text(json.dumps(claims), encoding="utf-8")
    _run(svc, task)                                                    # the paused task is resumed (and dies again)
    kept = json.loads(path.read_text(encoding="utf-8"))
    assert stem in kept and len(kept) == 200
    assert "filler-0" not in kept                                      # the oldest unrelated entry went instead


def _fake_yt_dlp_for_every_phase(monkeypatch):
    """The caption and plan phases start ``yt-dlp`` by name: run the stand-in instead."""
    import subprocess
    import sys

    from tests.core.test_downloads_keep_user_files import FAKE

    real = subprocess.Popen

    def popen(cmd, *args, **kwargs):
        if cmd and cmd[0] == "yt-dlp":
            cmd = [sys.executable, str(FAKE), *cmd[1:]]
        return real(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", popen)


def test_captions_of_a_numbered_video_carry_its_number(env, monkeypatch):   # noqa: F811
    svc, folder, _ = env
    _fake_yt_dlp_for_every_phase(monkeypatch)
    (folder / "Title A.mp4").write_bytes(b"an older download")
    (folder / "Title A.fr.vtt").write_bytes(b"the older download's captions")
    task = _video(folder)
    task.subtitles_enabled, task.subtitle_lang = True, "fr"
    assert svc._subtitle_phase(task) is False
    rc, _e, _l, saved, _f = _run(svc, task)
    assert rc == 0 and saved == str(folder / "Title A (1).mp4")
    assert (folder / "Title A (1).fr.vtt").read_text(encoding="utf-8").startswith("WEBVTT")
    assert (folder / "Title A.fr.vtt").read_bytes() == b"the older download's captions"   # not reused


def test_the_caption_number_skips_names_an_older_caption_file_uses(env, monkeypatch):   # noqa: F811
    svc, folder, _ = env
    _fake_yt_dlp_for_every_phase(monkeypatch)
    (folder / "Title A.mp4").write_bytes(b"an older download")
    (folder / "Title A (1).fr.vtt").write_bytes(b"captions of a deleted video")
    task = _video(folder)
    task.subtitles_enabled, task.subtitle_lang = True, "fr"
    svc._subtitle_phase(task)
    rc, _e, _l, saved, _f = _run(svc, task)
    assert rc == 0 and saved == str(folder / "Title A (2).mp4")
    assert (folder / "Title A (2).fr.vtt").exists()
    assert (folder / "Title A (1).fr.vtt").read_bytes() == b"captions of a deleted video"


def test_captions_of_a_free_name_stay_plain(env, monkeypatch):   # noqa: F811
    svc, folder, _ = env
    _fake_yt_dlp_for_every_phase(monkeypatch)
    task = _video(folder)
    task.subtitles_enabled, task.subtitle_lang = True, "fr"
    svc._subtitle_phase(task)
    rc, _e, _l, saved, _f = _run(svc, task)
    assert rc == 0 and saved == str(folder / "Title A.mp4")
    assert (folder / "Title A.fr.vtt").exists()
