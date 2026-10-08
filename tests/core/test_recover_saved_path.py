"""Tests for DownloadService._recover_saved_path (self-healing saved path).

When the path parsed from yt-dlp stdout doesn't exist on disk (a rename, or
a filename character that slips past the utf-8 fix), _finish recovers the
real downloaded file so the size readout + auto-transcribe still work.
"""
from __future__ import annotations

import os
import time
import types

import pytest

from app.services.download_service import DownloadService
from core import burn_subs


@pytest.fixture(autouse=True)
def _fresh_burn_records(monkeypatch):
    monkeypatch.setattr(burn_subs, "_reserved", set())
    monkeypatch.setattr(burn_subs, "_produced", set())


def _svc() -> DownloadService:
    # _recover_saved_path doesn't touch the app object.
    return DownloadService(types.SimpleNamespace())  # type: ignore[arg-type]


def _task(folder: str, started: float) -> object:
    return types.SimpleNamespace(folder=folder, start_time=started)


def test_recovers_newest_media_file(tmp_path):
    started = time.time()
    real = tmp_path / "The Idaho Painter.mp4"
    real.write_bytes(b"video")
    (tmp_path / "The Idaho Painter.vtt").write_bytes(b"subs")   # ignored (not media)
    (tmp_path / "The Idaho Painter.srt").write_bytes(b"subs")   # ignored
    old = tmp_path / "unrelated-old.mp4"
    old.write_bytes(b"old")
    os.utime(old, (started - 10_000, started - 10_000))         # before this download
    got = _svc()._recover_saved_path(_task(str(tmp_path), started - 1), None)
    assert got == str(real)


def test_recovers_when_parsed_path_is_mojibake(tmp_path):
    # The real file carries a U+2019 apostrophe; the broken parser saw a
    # U+FFFD replacement char, so its path doesn't exist. Self-heal finds it.
    real = tmp_path / "Don’t Know About.mp4"
    real.write_bytes(b"v")
    parsed = str(tmp_path / "Don�t Know About.mp4")
    got = _svc()._recover_saved_path(_task(str(tmp_path), 0.0), parsed)
    assert got == str(real)


def test_returns_none_when_no_media(tmp_path):
    (tmp_path / "notes.txt").write_bytes(b"x")
    (tmp_path / "subs.srt").write_bytes(b"x")
    assert _svc()._recover_saved_path(_task(str(tmp_path), 0.0), None) is None


def test_returns_none_when_folder_missing():
    task = _task(os.path.join(os.sep, "nope", "zzz-does-not-exist"), 0.0)
    assert _svc()._recover_saved_path(task, None) is None


# -- other chains' files in the same folder ---------------------------------


def _titled(folder: str, started: float, title: str) -> object:
    return types.SimpleNamespace(folder=folder, start_time=started, title=title)


def test_ignores_another_chains_burn_temp_and_placeholder(tmp_path):
    # Chain A is burning in the folder: hidden ".burn-*" temp + an empty
    # "<title>-subbed.mp4" placeholder, both newer than B's real download.
    started = time.time()
    real = tmp_path / "B video.mp4"
    real.write_bytes(b"x" * 10)
    time.sleep(0.05)
    (tmp_path / ".burn-abc123.mp4").write_bytes(b"y" * 10)
    # A reserved placeholder is skipped even once ffmpeg has written into it.
    placeholder = burn_subs.reserve_output_path(str(tmp_path / "A video-subbed.mp4"))
    with open(placeholder, "wb") as f:
        f.write(b"z" * 10)
    got = _svc()._recover_saved_path(
        _task(str(tmp_path), started - 1), str(tmp_path / "B video MISMATCH.mp4")
    )
    assert got == str(real)


def test_ignores_this_runs_finished_burns_and_zero_byte_files(tmp_path, monkeypatch):
    real = tmp_path / "Talk.mp4"
    real.write_bytes(b"v")
    time.sleep(0.05)
    for name in ("Other-subbed.mp4", "Other-subbed (2).mp4"):
        (tmp_path / name).write_bytes(b"done burn")
        burn_subs._produced.add(burn_subs._output_key(str(tmp_path / name)))
    (tmp_path / "empty.mkv").write_bytes(b"")
    (tmp_path / ".hidden.mp4").write_bytes(b"h")
    assert _svc()._recover_saved_path(_task(str(tmp_path), 0.0), None) == str(real)


def test_a_real_title_that_ends_in_subbed_is_recoverable(tmp_path):
    # Not this app's placeholder or output: excluded by record, never by name.
    real = tmp_path / "Fansub-subbed.mp4"
    real.write_bytes(b"v")
    task = _titled(str(tmp_path), 0.0, "Fansub-subbed")
    assert _svc()._recover_saved_path(task, str(tmp_path / "Fansub-subbed MISMATCH.mp4")) == str(real)


def test_only_foreign_files_means_nothing_recovered(tmp_path):
    (tmp_path / ".burn-abc.mp4").write_bytes(b"y")
    burn_subs.reserve_output_path(str(tmp_path / "A-subbed.mp4"))
    assert _svc()._recover_saved_path(_task(str(tmp_path), 0.0), None) is None


def test_prefers_the_file_that_matches_the_title(tmp_path):
    # Chain A's own download finished moments ago and is still in the window:
    # the newest file is the wrong one, the title picks the right one.
    started = time.time()
    mine = tmp_path / "Don’t Know About.mp4"
    mine.write_bytes(b"m")
    other = tmp_path / "Another talk.mp4"
    other.write_bytes(b"o")
    os.utime(mine, (started, started))
    os.utime(other, (started + 3, started + 3))
    task = _titled(str(tmp_path), started - 1, "Don't Know About")
    assert _svc()._recover_saved_path(task, str(tmp_path / "Don�t Know About.mp4")) == str(mine)


def test_ambiguous_candidates_are_refused_not_guessed(tmp_path):
    (tmp_path / "One.mp4").write_bytes(b"1")
    (tmp_path / "Two.mp4").write_bytes(b"2")
    task = _titled(str(tmp_path), 0.0, "Three")
    assert _svc()._recover_saved_path(task, str(tmp_path / "Three.mp4")) is None
    assert _svc()._find_recovered_path(task, str(tmp_path / "Three.mp4")) == (None, True)


def test_finish_fails_a_chain_whose_file_cannot_be_identified(tmp_path):
    app = types.SimpleNamespace(
        app_config={}, download_current=None, logs=[],
        log=lambda m: app.logs.append(m), history=None,
        enqueue_transcription_from_download=lambda *a, **k: app.logs.append("ENQUEUED"),
    )
    svc = DownloadService(app)  # type: ignore[arg-type]
    svc.process_queue = lambda: None  # type: ignore[method-assign]
    (tmp_path / "One.mp4").write_bytes(b"1")
    (tmp_path / "Two.mp4").write_bytes(b"2")
    task = types.SimpleNamespace(
        folder=str(tmp_path), start_time=0.0, title="Three", status="running",
        make_subbed_video=True, cancelled=False, paused=False, end_time=None,
        detected_language="en", history_id=0, caption_only=False, progress=0,
    )
    svc._finish(task, "finished", saved_path=str(tmp_path / "Three.mp4"))  # type: ignore[arg-type]
    assert task.status == "error"
    assert "ENQUEUED" not in app.logs
    assert any("could not be told apart" in m for m in app.logs)
    assert not any("Downloaded" in m for m in app.logs)


def test_ignores_unmerged_yt_dlp_part_files(tmp_path):
    (tmp_path / "Talk.f137.mp4").write_bytes(b"video only")
    (tmp_path / "Talk.f140.m4a").write_bytes(b"audio only")
    (tmp_path / "Talk.temp.mp4").write_bytes(b"merging")
    final = tmp_path / "Talk.mkv"
    final.write_bytes(b"merged")
    assert _svc()._recover_saved_path(_task(str(tmp_path), 0.0), None) == str(final)


def test_an_unidentifiable_chain_file_records_no_output(tmp_path):
    rows = []
    app = types.SimpleNamespace(
        app_config={}, download_current=None, log=lambda m: None,
        history=types.SimpleNamespace(
            finish_download=lambda row, **kw: rows.append((row, kw["status"], kw["output_paths"], kw["error"]))),
        enqueue_transcription_from_download=lambda *a, **k: rows.append("ENQUEUED"),
    )
    svc = DownloadService(app)  # type: ignore[arg-type]
    svc.process_queue = lambda: None  # type: ignore[method-assign]
    (tmp_path / "One.mp4").write_bytes(b"1")
    (tmp_path / "Two.mp4").write_bytes(b"2")
    task = types.SimpleNamespace(
        folder=str(tmp_path), start_time=0.0, title="Three", status="running",
        make_subbed_video=True, cancelled=False, paused=False, end_time=None,
        detected_language="en", history_id=5, caption_only=False, progress=0,
    )
    svc._finish(task, "finished", saved_path=str(tmp_path / "Three.mp4"))  # type: ignore[arg-type]
    assert len(rows) == 1 and rows[0][:3] == (5, "error", [])
    assert "no subtitled video was made" in rows[0][3]
    assert task.status == "error"
    assert not getattr(task, "saved_path", None)


def test_an_unidentifiable_plain_download_is_not_transcribed(tmp_path):
    # Auto-transcribe used to be handed a path that does not exist, after a
    # "Downloaded: Three.mp4 (?)" line.
    rows, logs = [], []
    app = types.SimpleNamespace(
        app_config={"auto_transcribe_after_download": True}, download_current=None,
        log=logs.append,
        history=types.SimpleNamespace(
            finish_download=lambda row, **kw: rows.append((row, kw["status"], kw["output_paths"], kw["error"]))),
        enqueue_transcription_from_download=lambda *a, **k: rows.append("ENQUEUED"),
    )
    svc = DownloadService(app)  # type: ignore[arg-type]
    svc.process_queue = lambda: None  # type: ignore[method-assign]
    (tmp_path / "One.mp4").write_bytes(b"1")
    (tmp_path / "Two.mp4").write_bytes(b"2")
    task = types.SimpleNamespace(
        folder=str(tmp_path), start_time=0.0, title="Three", status="running",
        make_subbed_video=False, cancelled=False, paused=False, end_time=None,
        detected_language="en", history_id=6, caption_only=False, progress=0,
    )
    svc._finish(task, "finished", saved_path=str(tmp_path / "Three.mp4"))  # type: ignore[arg-type]
    assert task.status == "error"
    assert rows == [(6, "error", [], rows[0][3])] and "no subtitled video" not in rows[0][3]
    assert not any("Downloaded" in m for m in logs)
