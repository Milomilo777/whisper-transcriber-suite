"""Tests for the "use captions instead" caption-only download shortcut.

When a video already has captions in the target language, the Download
Videos tab offers a dedicated "Use captions instead" button (built in
app.widgets.tabs.build_download_tab, shown/hidden by
App.update_caption_shortcut_state) that fetches only those captions and
converts them to the configured output formats -- skipping the media
download and the auto-transcribe queue entirely.

Covers:
  * DownloadService.enqueue_caption_only_from_form -- validation guards and
    the task it builds.
  * DownloadService._run_caption_only_task -- the actual fetch+convert run,
    including the rolling-auto-caption dedup pass (only for "auto", never
    for "manual") and graceful handling of no-captions / cancel / an
    unconvertible requested format.
  * DownloadService._finish -- a caption-only task must never trigger
    auto-transcribe-after-download, even when that preference is on.
"""
from __future__ import annotations

import types
import tkinter.messagebox  # noqa: F401  -- ensures tkinter.messagebox is a bound attribute to monkeypatch
from queue import Queue

from app.domain.tasks import VideoDownloadTask
from app.services.download_service import DownloadService

ROLLING_VTT = (
    "WEBVTT\n"
    "\n"
    "00:00:00.000 --> 00:00:04.000\n"
    "Hello everyone welcome to the show\n"
    "\n"
    "00:00:03.500 --> 00:00:07.000\n"
    "to the show today we will talk\n"
    "\n"
    "00:00:06.500 --> 00:00:10.000\n"
    "today we will talk about testing\n"
)

NO_SUBS_LINE = "[info] There are no subtitles for the requested languages"


# --- shared fakes -------------------------------------------------------


class _FakeProcess:
    def __init__(self, lines: list[str], returncode: int = 0):
        self.stdout = iter(lines)
        self._returncode = returncode

    def wait(self) -> int:
        return self._returncode


def _popen_factory(monkeypatch, lines: list[str], returncode: int = 0):
    calls: list[list[str]] = []

    def _popen(command, **_):  # noqa: ANN001, ANN003
        calls.append(command)
        return _FakeProcess(lines, returncode)

    monkeypatch.setattr("app.services.download_service.subprocess.Popen", _popen)
    return calls


def _svc(app: types.SimpleNamespace) -> DownloadService:
    """DownloadService.__new__ + manual .app assignment, bypassing
    __init__'s ``app: App`` type -- the stub here is a SimpleNamespace, not
    a real App, matching the convention in test_download_format_lookup_error.py.
    """
    svc = DownloadService.__new__(DownloadService)
    svc.app = app  # type: ignore[attr-defined]
    return svc


def _app(*, output_formats=None, auto_transcribe=False) -> types.SimpleNamespace:
    """A bare stub carrying exactly what _run_caption_only_task / _finish
    touch. A plain SimpleNamespace, NOT App.__new__(App): a real App
    subclasses tkinter.Misc, whose __getattr__ forwards any attribute this
    stub doesn't set to self.tk -- which doesn't exist on an unconstructed
    instance either, recursing until RecursionError. SimpleNamespace has no
    such fallback, so a missing attribute just raises a plain, immediate
    AttributeError (or returns getattr()'s default) like any normal object.
    """
    return types.SimpleNamespace(
        app_config={
            "output_formats": output_formats if output_formats is not None else ["srt", "txt"],
            "auto_transcribe_after_download": auto_transcribe,
        },
        entry_file=__file__,
        download_events=Queue(),
        history=None,
        download_current=None,
        log=lambda *a, **k: None,
        yt_dlp_path=lambda: "yt-dlp",
        bin_path=lambda: "",
    )


def _task(tmp_path, *, subtitle_lang="en", detected_language="en", caption_kind="auto") -> VideoDownloadTask:
    return VideoDownloadTask(
        url="https://www.youtube.com/watch?v=abc123",
        folder=str(tmp_path),
        format_label="Captions only (English)",
        format_info={"mode": "Captions", "audio": None, "video": None, "output": ""},
        title="Sample video (captions only)",
        subtitles_enabled=True,
        subtitle_lang=subtitle_lang,
        detected_language=detected_language,
        caption_only=True,
        caption_kind=caption_kind,
    )


def _drain(app: types.SimpleNamespace) -> list[tuple]:
    events = []
    while not app.download_events.empty():
        events.append(app.download_events.get_nowait())
    return events


# --- _run_caption_only_task: success + dedup ----------------------------


def test_auto_captions_are_deduplicated_and_converted(monkeypatch, tmp_path):
    caption_path = tmp_path / "video.en.vtt"
    caption_path.write_text(ROLLING_VTT, encoding="utf-8")
    _popen_factory(
        monkeypatch,
        [f"Writing video subtitles to: {caption_path}"],
    )
    app = _app(output_formats=["srt", "txt"])
    task = _task(tmp_path, caption_kind="auto")

    _svc(app)._run_caption_only_task(task)

    events = _drain(app)
    kinds = [e[0] for e in events]
    assert "error" not in kinds
    assert "done_full" in kinds

    txt_path = tmp_path / "video.en.txt"
    assert txt_path.exists()
    body = txt_path.read_text(encoding="utf-8")
    # The rolling overlap ("to the show", "today we will talk") must appear
    # exactly once each, not duplicated.
    assert body.count("to the show") == 1
    assert body.count("today we will talk") == 1
    assert "about testing" in body


def test_manual_captions_are_not_deduplicated(monkeypatch, tmp_path):
    # Same rolling-shaped content, but flagged "manual" -- a real manual
    # track would never look like this, but the dedup pass must still be
    # skipped so a manual track is never altered.
    caption_path = tmp_path / "video.en.vtt"
    caption_path.write_text(ROLLING_VTT, encoding="utf-8")
    _popen_factory(monkeypatch, [f"Writing video subtitles to: {caption_path}"])
    app = _app(output_formats=["txt"])
    task = _task(tmp_path, caption_kind="manual")

    _svc(app)._run_caption_only_task(task)

    txt_path = tmp_path / "video.en.txt"
    body = txt_path.read_text(encoding="utf-8")
    # Untouched: the overlapping phrase appears twice, once per raw cue.
    assert body.count("to the show") == 2


def test_unsupported_output_format_is_skipped_not_fatal(monkeypatch, tmp_path):
    caption_path = tmp_path / "video.en.vtt"
    caption_path.write_text(ROLLING_VTT, encoding="utf-8")
    _popen_factory(monkeypatch, [f"Writing video subtitles to: {caption_path}"])
    app = _app(output_formats=["srt", "docx"])  # docx: not offered by convert_file
    task = _task(tmp_path)

    _svc(app)._run_caption_only_task(task)

    events = _drain(app)
    assert any(e[0] == "done_full" for e in events)
    assert (tmp_path / "video.en.srt").exists()
    assert any(
        e[0] == "log" and "docx" in str(e[2]) and "skip" in str(e[2]).lower()
        for e in events
    )


# --- _run_caption_only_task: failure paths -------------------------------


def test_no_captions_available_posts_error_not_done(monkeypatch, tmp_path):
    _popen_factory(monkeypatch, [NO_SUBS_LINE])
    app = _app()
    task = _task(tmp_path)

    _svc(app)._run_caption_only_task(task)

    events = _drain(app)
    kinds = [e[0] for e in events]
    assert "done_full" not in kinds
    assert "error" in kinds


def test_no_resolvable_language_never_calls_popen(monkeypatch, tmp_path):
    calls = _popen_factory(monkeypatch, [])
    app = _app()
    task = _task(tmp_path, subtitle_lang="", detected_language="")

    _svc(app)._run_caption_only_task(task)

    assert calls == []
    events = _drain(app)
    assert any(e[0] == "error" for e in events)


def test_cancelled_removes_partial_file_and_posts_done_cancelled(monkeypatch, tmp_path):
    caption_path = tmp_path / "video.en.vtt"
    caption_path.write_text(ROLLING_VTT, encoding="utf-8")
    _popen_factory(monkeypatch, [f"Writing video subtitles to: {caption_path}"])
    app = _app()
    task = _task(tmp_path)
    task.cancelled = True

    _svc(app)._run_caption_only_task(task)

    assert not caption_path.exists()
    events = _drain(app)
    assert ("done", task, "cancelled") in events
    assert not any(e[0] == "done_full" for e in events)


# --- _finish: caption-only must never trigger auto-transcribe -----------


def test_finish_does_not_auto_transcribe_caption_only_task(monkeypatch, tmp_path):
    app = _app(auto_transcribe=True)
    app.download_queue = []
    called: list = []
    app.enqueue_transcription_from_download = lambda *a, **k: called.append((a, k))

    saved = tmp_path / "video.en.srt"
    saved.write_text("1\n00:00:00,000 --> 00:00:01,000\nHi\n", encoding="utf-8")
    task = _task(tmp_path)

    svc = _svc(app)
    svc._finish(task, "finished", saved_path=str(saved))

    assert called == []
    assert task.status == "finished"


def test_finish_still_auto_transcribes_normal_media_task(monkeypatch, tmp_path):
    # Control: a normal (non caption-only) finished download DOES still
    # trigger auto-transcribe when the preference is on -- proves the
    # caption_only guard is scoped correctly, not a blanket regression.
    app = _app(auto_transcribe=True)
    app.download_queue = []
    called: list = []
    app.enqueue_transcription_from_download = lambda *a, **k: called.append((a, k))

    saved = tmp_path / "video.mp4"
    saved.write_bytes(b"0")
    task = VideoDownloadTask(
        url="https://www.youtube.com/watch?v=abc123",
        folder=str(tmp_path),
        format_label="Audio and video -> mp4",
        format_info={
            "mode": "Audio and video", "output": "mp4",
            "audio": {"kind": "best_audio"}, "video": {"kind": "best_video"},
        },
    )

    svc = _svc(app)
    svc._finish(task, "finished", saved_path=str(saved))

    assert len(called) == 1


# --- enqueue_caption_only_from_form: validation + task built ------------


class _Var:
    def __init__(self, value: str = "") -> None:
        self._v = value

    def get(self) -> str:
        return self._v

    def set(self, v) -> None:  # noqa: ANN001
        self._v = v


def _form_app(
    tmp_path, *, url="https://www.youtube.com/watch?v=abc123", folder=None,
    subtitle_lang="Automatic", caption_langs=None, current_language="en",
    smtv_episode=None,
) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        download_url_var=_Var(url),
        download_folder_var=_Var(folder if folder is not None else str(tmp_path)),
        subtitle_lang_var=_Var(subtitle_lang),
        current_video_caption_langs=caption_langs if caption_langs is not None else {"en": "auto"},
        current_video_language=current_language,
        current_video_title="Sample video",
        _smtv_episode=smtv_episode,
        app_config={},
        download_queue=[],
        refresh_download_queue=lambda: None,
    )


def _svc_with_warnings(app, monkeypatch):
    warnings: list[tuple] = []

    class _MB:
        @staticmethod
        def showwarning(title, message, *_a, **_k):
            warnings.append((title, message))

    monkeypatch.setattr("tkinter.messagebox", _MB)
    monkeypatch.setattr("app.services.download_service.save_config", lambda *a, **k: None)
    svc = _svc(app)
    svc.process_queue = lambda: None  # don't spawn a real worker thread
    return svc, warnings


def test_enqueue_caption_only_missing_url_warns(monkeypatch, tmp_path):
    app = _form_app(tmp_path, url="")
    svc, warnings = _svc_with_warnings(app, monkeypatch)

    svc.enqueue_caption_only_from_form()

    assert app.download_queue == []
    assert warnings and warnings[0][0] == "Missing URL"


def test_enqueue_caption_only_missing_folder_warns(monkeypatch, tmp_path):
    app = _form_app(tmp_path, folder="")
    svc, warnings = _svc_with_warnings(app, monkeypatch)

    svc.enqueue_caption_only_from_form()

    assert app.download_queue == []
    assert warnings and warnings[0][0] == "Missing folder"


def test_enqueue_caption_only_smtv_url_is_a_silent_noop(monkeypatch, tmp_path):
    app = _form_app(tmp_path, smtv_episode=object())
    svc, warnings = _svc_with_warnings(app, monkeypatch)

    svc.enqueue_caption_only_from_form()

    assert app.download_queue == []
    assert warnings == []  # button is hidden for SMTV; this only guards a race


def test_enqueue_caption_only_no_caption_for_language_warns(monkeypatch, tmp_path):
    app = _form_app(tmp_path, caption_langs={"de": "manual"}, current_language="en")
    svc, warnings = _svc_with_warnings(app, monkeypatch)

    svc.enqueue_caption_only_from_form()

    assert app.download_queue == []
    assert warnings and warnings[0][0] == "No captions found"


def test_enqueue_caption_only_builds_correct_task_for_automatic(monkeypatch, tmp_path):
    app = _form_app(
        tmp_path, subtitle_lang="Automatic",
        caption_langs={"en": "auto"}, current_language="en",
    )
    svc, warnings = _svc_with_warnings(app, monkeypatch)

    svc.enqueue_caption_only_from_form()

    assert warnings == []
    assert len(app.download_queue) == 1
    task = app.download_queue[0]
    assert task.caption_only is True
    assert task.caption_kind == "auto"
    assert task.subtitle_lang == ""  # "Automatic" -> empty code; resolved at run time
    assert task.detected_language == "en"
    assert task.url == "https://www.youtube.com/watch?v=abc123"


def test_enqueue_caption_only_builds_correct_task_for_explicit_language(monkeypatch, tmp_path):
    app = _form_app(
        tmp_path, subtitle_lang="German",
        caption_langs={"de": "manual", "en": "auto"}, current_language="en",
    )
    svc, warnings = _svc_with_warnings(app, monkeypatch)

    svc.enqueue_caption_only_from_form()

    assert warnings == []
    assert len(app.download_queue) == 1
    task = app.download_queue[0]
    assert task.caption_only is True
    assert task.caption_kind == "manual"
    assert task.subtitle_lang == "de"
