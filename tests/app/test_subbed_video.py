"""Link -> subtitled video chain (app/services/subbed_video.py and its hooks).

Stage tests stub the download, the transcription and ffmpeg; they check the
order of the stages, what Cancel and a failure at each stage leave on disk,
which files the burn receives and what the history row records.
"""
from __future__ import annotations

import os
import subprocess
import time
from types import SimpleNamespace
from typing import Any

import pytest

from app.services import subbed_video
from app.services.download_service import DownloadService
from app.services.transcription_service import TranscriptionService, output_formats_for
from app.widgets.tabs import download_button_states_for_status
from core import burn_subs


class _App:
    """Just enough App for the chain: log, queue refresh, history, main thread."""

    def __init__(self) -> None:
        self.logs: list[str] = []
        self.history_rows: list[tuple[str, list[str], str]] = []
        self.app_config: dict = {"auto_transcribe_after_download": False}
        self.download_queue: list = []
        self.download_current = None
        self.history = None
        self.enqueued: list[tuple[str, object]] = []
        self.download_service = SimpleNamespace(_finish_history=self._finish_history)

    def _finish_history(self, task, status, paths, *, error=""):
        self.history_rows.append((status, list(paths), error))

    def log(self, msg: str) -> None:
        self.logs.append(msg)

    def refresh_download_queue(self) -> None:
        pass

    def post_to_main(self, fn) -> None:
        fn()

    def enqueue_transcription_from_download(self, path, language, source_download=None):
        self.enqueued.append((path, source_download))

    def update_overall_progress(self) -> None:
        pass

    def show_last_result(self, task) -> None:
        pass

    def note_job_success(self) -> None:
        pass


def _dl(media: str) -> SimpleNamespace:
    return SimpleNamespace(
        status="transcribing", saved_path=media, make_subbed_video=True,
        cancelled=False, process=None, progress=100, burn_progress=0.0,
        burned_path=None, transcription_task=None, history_id=7,
    )


def _tr(*outputs: str, **kw) -> SimpleNamespace:
    base = dict(output_paths=list(outputs), cancelled=False, no_speech=False, status="finished")
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.fixture
def sync_threads(monkeypatch):
    """Run safe_thread bodies inline so the burn stage finishes in the test."""
    import core._threads as threads

    monkeypatch.setattr(threads, "safe_thread", lambda fn, name="": fn())


@pytest.fixture
def media(tmp_path):
    video = tmp_path / "Talk [x].mp4"
    video.write_bytes(b"video")
    return str(video)


def _files(folder) -> set[str]:
    return set(os.listdir(folder))


# -- burn stage --------------------------------------------------------------

def test_burn_gets_the_srt_the_transcription_wrote(tmp_path, media, monkeypatch, sync_threads):
    # A re-run wrote "name (1).srt"; the stale "name.srt" must not be burned.
    stale = tmp_path / "Talk [x].srt"
    stale.write_text("old", encoding="utf-8")
    real = tmp_path / "Talk [x] (1).srt"
    real.write_text("new", encoding="utf-8")
    calls = []
    monkeypatch.setattr(
        burn_subs, "burn",
        lambda v, s, o, **kw: (calls.append((v, s, o)), open(o, "wb").close()),
    )
    app, dl = _App(), _dl(media)

    subbed_video.after_transcription(app, dl, _tr(str(real)), True)

    assert calls == [(media, str(real), str(tmp_path / "Talk [x]-subbed.mp4"))]
    assert dl.status == "finished"
    assert dl.burned_path == str(tmp_path / "Talk [x]-subbed.mp4")
    assert app.history_rows == [("finished", [media, dl.burned_path], "")]


def test_existing_subbed_file_is_never_replaced(tmp_path, media, monkeypatch, sync_threads):
    srt = tmp_path / "Talk [x].srt"
    srt.write_text("x", encoding="utf-8")
    sentinel = tmp_path / "Talk [x]-subbed.mp4"
    sentinel.write_bytes(b"earlier result")
    monkeypatch.setattr(burn_subs, "burn", lambda v, s, o, **kw: open(o, "wb").close())
    app, dl = _App(), _dl(media)

    subbed_video.after_transcription(app, dl, _tr(str(srt)), True)

    assert sentinel.read_bytes() == b"earlier result"
    assert dl.burned_path == str(tmp_path / "Talk [x]-subbed (2).mp4")


def test_no_srt_in_outputs_is_an_error_even_if_a_guess_exists(tmp_path, media, monkeypatch, sync_threads):
    (tmp_path / "Talk [x].srt").write_text("guess", encoding="utf-8")
    monkeypatch.setattr(burn_subs, "burn", lambda *a, **k: pytest.fail("burn must not run"))
    app, dl = _App(), _dl(media)

    subbed_video.after_transcription(app, dl, _tr(), True)

    assert dl.status == "error"
    assert "no .srt" in app.history_rows[-1][2]


@pytest.mark.parametrize(
    "tr, status",
    [
        (_tr(status="error"), "error"),
        (_tr(status="cancelled", cancelled=True), "cancelled"),
    ],
)
def test_failed_or_cancelled_transcription_makes_no_video(tmp_path, media, monkeypatch, sync_threads, tr, status):
    monkeypatch.setattr(burn_subs, "burn", lambda *a, **k: pytest.fail("burn must not run"))
    before = _files(tmp_path)
    app, dl = _App(), _dl(media)

    subbed_video.after_transcription(app, dl, tr, False)

    assert dl.status == status
    assert _files(tmp_path) == before
    assert app.history_rows[-1][:2] == (status, [media])


def test_no_speech_makes_no_video(tmp_path, media, monkeypatch, sync_threads):
    srt = tmp_path / "Talk [x].srt"
    srt.write_text("", encoding="utf-8")
    monkeypatch.setattr(burn_subs, "burn", lambda *a, **k: pytest.fail("burn must not run"))
    app, dl = _App(), _dl(media)

    subbed_video.after_transcription(app, dl, _tr(str(srt), no_speech=True), True)

    assert dl.status == "error"


def test_burn_failure_keeps_download_and_transcript(tmp_path, media, monkeypatch, sync_threads):
    srt = tmp_path / "Talk [x].srt"
    srt.write_text("x", encoding="utf-8")

    def boom(*a, **k):
        raise RuntimeError("ffmpeg failed to burn subtitles: disk full")

    monkeypatch.setattr(burn_subs, "burn", boom)
    app, dl = _App(), _dl(media)

    subbed_video.after_transcription(app, dl, _tr(str(srt)), True)

    assert dl.status == "error"
    assert _files(tmp_path) == {"Talk [x].mp4", "Talk [x].srt"}
    assert "disk full" in app.history_rows[-1][2]
    assert any("kept" in m for m in app.logs)


def test_cancel_during_burn(tmp_path, media, monkeypatch, sync_threads):
    srt = tmp_path / "Talk [x].srt"
    srt.write_text("x", encoding="utf-8")
    seen = {}

    def fake_burn(v, s, o, *, progress_cb, cancel_check, on_process, placeholder=None):
        on_process("proc")
        seen["registered"] = dl.process
        progress_cb(30.0)
        seen["status"] = dl.status
        dl.cancelled = True  # the row's Cancel
        dl.status = "cancelled"
        assert cancel_check()
        raise burn_subs.BurnCancelled("cancelled")

    monkeypatch.setattr(burn_subs, "burn", fake_burn)
    app, dl = _App(), _dl(media)

    subbed_video.after_transcription(app, dl, _tr(str(srt)), True)

    # The ffmpeg process sat where App.cancel_download tree-kills it.
    assert seen == {"registered": "proc", "status": "burning"}
    assert dl.process is None
    assert dl.status == "cancelled"
    assert _files(tmp_path) == {"Talk [x].mp4", "Talk [x].srt"}
    assert app.history_rows[-1][:2] == ("cancelled", [media])


def test_missing_download_is_an_error(tmp_path, monkeypatch, sync_threads):
    srt = tmp_path / "a.srt"
    srt.write_text("x", encoding="utf-8")
    monkeypatch.setattr(burn_subs, "burn", lambda *a, **k: pytest.fail("burn must not run"))
    app, dl = _App(), _dl(str(tmp_path / "gone.mp4"))

    subbed_video.after_transcription(app, dl, _tr(str(srt)), True)

    assert dl.status == "error"


# -- stage order and hooks -----------------------------------------------------

def _download_task() -> SimpleNamespace:
    return SimpleNamespace(
        url="https://x", folder="/tmp", format_label="mp4", format_info={}, title="T",
        subtitles_enabled=False, subtitle_lang="", detected_language="en",
        process=None, status="running", progress=0, start_time=0.0, end_time=None,
        cancelled=False, paused=False, history_id=0, caption_only=False,
        make_subbed_video=True,
    )


def test_download_hands_off_to_transcription_even_with_auto_transcribe_off():
    app = _App()
    svc = DownloadService(app)  # type: ignore[arg-type]
    task = _download_task()

    svc._finish(task, "finished", saved_path="/tmp/T.mp4")  # type: ignore[arg-type]

    assert app.enqueued == [("/tmp/T.mp4", task)]
    assert task.status == "transcribing"


def test_failed_download_starts_no_later_stage():
    app = _App()
    svc = DownloadService(app)  # type: ignore[arg-type]
    task = _download_task()

    svc._finish(task, "error", saved_path=None)  # type: ignore[arg-type]

    assert app.enqueued == []
    assert task.status == "error"


def test_full_chain_runs_download_then_transcribe_then_burn(tmp_path, media, monkeypatch, sync_threads):
    order: list[str] = []
    app = _App()
    svc_dl = DownloadService(app)  # type: ignore[arg-type]
    dl = _download_task()
    srt = tmp_path / "Talk [x].srt"

    def enqueue(path, language, source_download: Any = None):
        order.append("transcribe-queued")
        source_download.status = "transcribing"
        app.enqueued.append((path, source_download))

    app.enqueue_transcription_from_download = enqueue  # type: ignore[method-assign]

    def fake_burn(v, s, o, **kw):
        order.append("burn")
        assert os.path.isfile(s)
        open(o, "wb").close()

    monkeypatch.setattr(burn_subs, "burn", fake_burn)

    order.append("download")
    svc_dl._finish(dl, "finished", saved_path=media)  # type: ignore[arg-type]
    assert dl.status == "transcribing"
    # The transcription ends: its worker wrote the SRT first.
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nhi\n", encoding="utf-8")
    tr = SimpleNamespace(
        status="running", cancelled=False, end_time=None, start_time=time.time(),
        output_paths=[str(srt)], file_path=media, history_id=0, source_download=dl,
        no_speech=False,
    )
    order.append("transcribed")
    svc_tr = TranscriptionService(app)  # type: ignore[arg-type]
    monkeypatch.setattr(svc_tr, "_post_usage_stats", lambda *a, **k: None)
    svc_tr.finish_task({"task": tr, "temporary": False}, keep_status=False)

    assert order == ["download", "transcribe-queued", "transcribed", "burn"]
    assert dl.status == "finished"
    assert os.path.isfile(str(tmp_path / "Talk [x]-subbed.mp4"))


def test_plain_auto_transcribe_row_still_ends_finished(monkeypatch):
    app = _App()
    dl = _download_task()
    dl.make_subbed_video = False
    dl.status = "transcribing"
    tr = SimpleNamespace(
        status="running", cancelled=False, end_time=None, start_time=time.time(),
        output_paths=[], file_path="a.mp4", history_id=0, source_download=dl,
    )
    svc = TranscriptionService(app)  # type: ignore[arg-type]
    monkeypatch.setattr(svc, "_post_usage_stats", lambda *a, **k: None)
    monkeypatch.setattr(subbed_video, "after_transcription", lambda *a: pytest.fail("no burn"))

    svc.finish_task({"task": tr, "temporary": False}, keep_status=False)

    assert dl.status == "finished"


def test_chained_transcription_always_writes_srt():
    chained = SimpleNamespace(source_download=SimpleNamespace(make_subbed_video=True))
    plain = SimpleNamespace(source_download=None)
    assert output_formats_for(chained, ["txt"]) == ["txt", "srt"]
    assert output_formats_for(chained, ["srt", "json"]) == ["srt", "json"]
    assert output_formats_for(plain, ["txt"]) == ["txt"]


def test_burning_row_offers_cancel_only():
    states = download_button_states_for_status("burning")
    assert [k for k, v in states.items() if v] == ["cancel"]


def test_chain_progress_rises_through_the_stages():
    steps = [("running", p) for p in (0, 50, 100)]
    steps += [("transcribing", p) for p in (0, 30, 100)]
    steps += [("burning", p) for p in (0, 99, 100)]
    steps += [("finished", 100)]
    values = [subbed_video.chain_progress(s, p) for s, p in steps]
    assert values == sorted(values)
    assert values[0] == 0 and values[-1] == 100


# -- form ----------------------------------------------------------------------

class _Var:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


def test_audio_mode_is_refused_before_anything_downloads(tmp_path, monkeypatch):
    import tkinter.messagebox as mb

    warned = []
    monkeypatch.setattr(mb, "showwarning", lambda *a, **k: warned.append(a))
    app = SimpleNamespace(
        download_url_var=_Var("https://example.com/v"),
        download_folder_var=_Var(str(tmp_path)),
        download_mode_var=_Var("Audio"),
        audio_format_var=_Var("m4a"),
        video_format_var=_Var(""),
        output_format_var=_Var("mp3"),
        make_subbed_video_var=_Var(True),
        ensure_online=lambda what: True,
        audio_format_map={"m4a": {}},
        video_format_map={},
        download_queue=[],
    )
    svc = DownloadService(app)  # type: ignore[arg-type]
    monkeypatch.setattr(svc, "_caption_choice", lambda: pytest.fail("no caption offer"))

    svc.enqueue_from_form()

    assert app.download_queue == []
    assert warned and "Audio and video" in warned[0][1]


# -- review fixes ----------------------------------------------------------------

def test_two_chains_of_one_title_get_two_names(tmp_path, media, monkeypatch):
    first = subbed_video.subbed_output_path(media)
    second = subbed_video.subbed_output_path(media)
    assert first != second
    assert os.path.basename(second) == "Talk [x]-subbed (2).mp4"


def test_download_without_picture_ends_before_transcription(tmp_path, media, monkeypatch):
    monkeypatch.setattr(burn_subs, "probe_media", lambda p, timeout=60.0: burn_subs.MediaInfo(5.0, False, "aac"))
    app = _App()
    svc = DownloadService(app)  # type: ignore[arg-type]
    monkeypatch.setattr(svc, "_finish_history", app._finish_history)
    task = _download_task()

    svc._finish(task, "finished", saved_path=media)  # type: ignore[arg-type]

    assert app.enqueued == []
    assert task.status == "error"
    assert app.history_rows == [("error", [media], subbed_video.NO_VIDEO_ERROR)]


def test_row_percent_never_drops_while_streams_download():
    dl = SimpleNamespace(status="running", progress=100, chain_percent=0.0)
    assert subbed_video.rising_chain_progress(dl, 100) == 40.0
    dl.progress = 5  # yt-dlp starts the audio stream at 0 again
    assert subbed_video.rising_chain_progress(dl, 5) == 40.0
    dl.status = "transcribing"
    assert subbed_video.rising_chain_progress(dl, 0) == 40.0
    assert subbed_video.rising_chain_progress(dl, 100) == 85.0
    dl.status = "cancelled"
    assert subbed_video.rising_chain_progress(dl, 0) == 5


def test_cancelling_a_waiting_transcription_releases_the_chain_row(tmp_path, media, monkeypatch, sync_threads):
    from app.app import App

    monkeypatch.setattr(burn_subs, "burn", lambda *a, **k: pytest.fail("no burn"))
    app, dl = _App(), _dl(media)
    tr = _tr(cancelled=True, status="cancelled")
    tr.source_download = dl
    dl.transcription_task = tr

    App._release_waiting_download(app, tr)  # type: ignore[arg-type]

    assert dl.status == "cancelled"
    assert tr.source_download is None and dl.transcription_task is None
    assert app.history_rows[-1][:2] == ("cancelled", [media])


# -- review fixes, second round ----------------------------------------------------

@pytest.mark.parametrize(
    "exc",
    [
        PermissionError(13, "Access is denied"),
        OSError(36, "File name too long"),
    ],
)
def test_unwritable_output_folder_ends_the_row_with_a_reason(tmp_path, media, monkeypatch, sync_threads, exc):
    srt = tmp_path / "Talk [x].srt"
    srt.write_text("x", encoding="utf-8")

    def refuse(path):
        raise exc

    monkeypatch.setattr(burn_subs, "reserve_output_path", refuse)
    monkeypatch.setattr(burn_subs, "burn", lambda *a, **k: pytest.fail("burn must not run"))
    app, dl = _App(), _dl(media)

    subbed_video.after_transcription(app, dl, _tr(str(srt)), True)  # must not raise

    assert dl.status == "error"
    status, paths, error = app.history_rows[-1]
    assert status == "error" and paths == [media]
    assert "could not be created" in error and str(exc.args[1]) in error
    # The download and its transcript stay where they were.
    assert _files(tmp_path) == {"Talk [x].mp4", "Talk [x].srt"}


def test_a_failure_before_the_burn_starts_closes_the_row_with_a_reason(tmp_path, media, monkeypatch):
    app, dl = _App(), _dl(media)
    tr = _tr(str(tmp_path / "Talk [x].srt"), source_download=dl, file_path=media,
             end_time=None, start_time=time.time(), history_id=0)
    dl.transcription_task = tr

    def boom(*a, **k):
        raise RuntimeError("disk exploded")

    monkeypatch.setattr(subbed_video, "after_transcription", boom)
    svc = TranscriptionService(app)  # type: ignore[arg-type]
    monkeypatch.setattr(svc, "_post_usage_stats", lambda *a, **k: None)
    tr.status = "running"

    svc.finish_task({"task": tr, "temporary": False}, keep_status=False)

    assert dl.status == "error"
    assert app.history_rows[-1][0] == "error"
    assert "disk exploded" in app.history_rows[-1][2]


def test_a_burn_thread_that_cannot_start_leaves_no_placeholder(tmp_path, media, monkeypatch):
    import core._threads as threads

    srt = tmp_path / "Talk [x].srt"
    srt.write_text("x", encoding="utf-8")

    def no_thread(fn, name=""):
        raise RuntimeError("can't start new thread")

    monkeypatch.setattr(threads, "safe_thread", no_thread)
    app, dl = _App(), _dl(media)

    subbed_video.after_transcription(app, dl, _tr(str(srt)), True)

    assert dl.status == "error"
    assert _files(tmp_path) == {"Talk [x].mp4", "Talk [x].srt"}
    assert "can't start new thread" in app.history_rows[-1][2]


def test_the_burn_receives_its_placeholder_for_exit_cleanup(tmp_path, media, monkeypatch, sync_threads):
    srt = tmp_path / "Talk [x].srt"
    srt.write_text("x", encoding="utf-8")
    seen = {}

    def fake_burn(v, s, o, **kw):
        seen["placeholder"] = kw.get("placeholder")
        open(o, "wb").close()

    monkeypatch.setattr(burn_subs, "burn", fake_burn)
    app, dl = _App(), _dl(media)

    subbed_video.after_transcription(app, dl, _tr(str(srt)), True)

    assert seen["placeholder"] == str(tmp_path / "Talk [x]-subbed.mp4")


def test_the_picture_check_on_the_ui_thread_is_short(monkeypatch, media):
    seen = {}

    def probe(path, timeout=60.0):
        seen["timeout"] = timeout
        return burn_subs.MediaInfo(0.0, None, "")

    monkeypatch.setattr(burn_subs, "probe_media", probe)
    assert subbed_video.has_no_video(media) is False        # unanswered probe: not refused
    assert seen["timeout"] <= 10


def test_probe_media_passes_its_timeout_to_ffprobe(monkeypatch, media):
    seen = {}

    def run(cmd, **kw):
        seen["timeout"] = kw["timeout"]
        raise subprocess.TimeoutExpired(cmd, kw["timeout"])

    monkeypatch.setattr(burn_subs.subprocess, "run", run)
    monkeypatch.setattr(burn_subs, "bundled_binary", lambda name: "ffprobe")

    info = burn_subs.probe_media(media, timeout=3.0)

    assert seen["timeout"] == 3.0
    assert info.has_video is None
