"""The caption fetches retry once without browser cookies when yt-dlp cannot
read the cookie database (browser open and holding a lock on it).

Real-world case: "Use captions instead" failed three times with
``Could not copy Chrome cookie database`` while the normal download of the
same link, which already had this retry, finished. Both caption fetches
(``_run_caption_only_task`` and the pre-download ``_subtitle_phase``) share one
runner, so both get the same fallback.
"""
from __future__ import annotations

import types
import tkinter.messagebox  # noqa: F401
from queue import Queue

from app.domain.tasks import VideoDownloadTask
from app.services.download_service import DownloadService

COOKIE_ERROR_LINE = (
    "ERROR: Could not copy Chrome cookie database. See "
    "https://github.com/yt-dlp/yt-dlp/issues/7271 for more info"
)
LOGIN_ERROR_LINE = "ERROR: Private video. Sign in if you've been granted access to this video"

VTT = "WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nHello there\n"


class _FakeProcess:
    def __init__(self, lines: list[str], returncode: int):
        self.stdout = iter(lines)
        self._returncode = returncode

    def wait(self) -> int:
        return self._returncode


def _cookie_aware_popen(monkeypatch, caption_path):
    """Fake yt-dlp: prints the cookie-database error and exits 1 whenever
    ``--cookies-from-browser`` is on the command line, writes the caption
    otherwise. Returns the list of argv lists it was started with."""
    calls: list[list[str]] = []

    def _popen(command, **_):  # noqa: ANN001, ANN003
        if "--skip-download" in command:
            calls.append(list(command))
        if "--cookies-from-browser" in command:
            return _FakeProcess([COOKIE_ERROR_LINE], 1)
        return _FakeProcess([f"Writing video subtitles to: {caption_path}"], 0)

    monkeypatch.setattr("app.services.download_service.subprocess.Popen", _popen)
    return calls


def _app(cookies: str = "brave") -> types.SimpleNamespace:
    return types.SimpleNamespace(
        app_config={
            "output_formats": ["srt"],
            "auto_transcribe_after_download": False,
            "cookies_from_browser": cookies,
        },
        entry_file=__file__,
        download_events=Queue(),
        history=None,
        download_current=None,
        log=lambda *_a, **_k: None,
        yt_dlp_path=lambda: "yt-dlp",
        bin_path=lambda: "",
    )


def _task(tmp_path) -> VideoDownloadTask:
    return VideoDownloadTask(
        url="https://www.youtube.com/watch?v=abc123",
        folder=str(tmp_path),
        format_label="Captions only (English)",
        format_info={"mode": "Captions", "audio": None, "video": None, "output": ""},
        title="Sample video (captions only)",
        subtitles_enabled=True,
        subtitle_lang="en",
        detected_language="en",
        caption_only=True,
        caption_kind="manual",
    )


def _svc(app) -> DownloadService:  # noqa: ANN001
    svc = DownloadService.__new__(DownloadService)
    svc.app = app  # type: ignore[attr-defined]
    return svc


def _drain(app) -> list[tuple]:  # noqa: ANN001
    events = []
    while not app.download_events.empty():
        events.append(app.download_events.get_nowait())
    return events


def test_caption_only_retries_without_cookies_and_writes_the_caption(monkeypatch, tmp_path):
    caption = tmp_path / "video.en.vtt"
    caption.write_text(VTT, encoding="utf-8")
    calls = _cookie_aware_popen(monkeypatch, caption)
    app = _app("brave")

    _svc(app)._run_caption_only_task(_task(tmp_path))

    assert len(calls) == 2
    assert "--cookies-from-browser" in calls[0]
    assert "--cookies-from-browser" not in calls[1]
    events = _drain(app)
    kinds = [e[0] for e in events]
    assert "done_full" in kinds
    assert "error" not in kinds
    retry_lines = [
        e for e in events if e[0] == "log" and "without cookies" in str(e[2]).lower()
    ]
    assert len(retry_lines) == 1


def test_caption_only_does_not_retry_when_no_cookies_are_configured(monkeypatch, tmp_path):
    caption = tmp_path / "video.en.vtt"
    caption.write_text(VTT, encoding="utf-8")
    calls: list[list[str]] = []

    def _popen(command, **_):  # noqa: ANN001, ANN003
        if "--skip-download" in command:
            calls.append(list(command))
        return _FakeProcess([COOKIE_ERROR_LINE], 1)

    monkeypatch.setattr("app.services.download_service.subprocess.Popen", _popen)
    app = _app("")

    _svc(app)._run_caption_only_task(_task(tmp_path))

    assert len(calls) == 1
    assert any(e[0] == "error" for e in _drain(app))


def test_caption_only_does_not_retry_on_a_real_login_error(monkeypatch, tmp_path):
    calls: list[list[str]] = []

    def _popen(command, **_):  # noqa: ANN001, ANN003
        if "--skip-download" in command:
            calls.append(list(command))
        return _FakeProcess([LOGIN_ERROR_LINE], 1)

    monkeypatch.setattr("app.services.download_service.subprocess.Popen", _popen)
    app = _app("brave")

    _svc(app)._run_caption_only_task(_task(tmp_path))

    assert len(calls) == 1
    assert any(e[0] == "error" for e in _drain(app))


def test_caption_only_retries_only_once_when_the_retry_also_fails(monkeypatch, tmp_path):
    calls: list[list[str]] = []

    def _popen(command, **_):  # noqa: ANN001, ANN003
        if "--skip-download" in command:
            calls.append(list(command))
        return _FakeProcess([COOKIE_ERROR_LINE], 1)

    monkeypatch.setattr("app.services.download_service.subprocess.Popen", _popen)
    app = _app("brave")

    _svc(app)._run_caption_only_task(_task(tmp_path))

    assert len(calls) == 2
    assert "--cookies-from-browser" not in calls[1]
    assert any(e[0] == "error" for e in _drain(app))


def test_caption_only_does_not_retry_after_a_cancel(monkeypatch, tmp_path):
    calls: list[list[str]] = []
    task = _task(tmp_path)

    def _popen(command, **_):  # noqa: ANN001, ANN003
        if "--skip-download" in command:
            calls.append(list(command))
        task.cancelled = True
        return _FakeProcess([COOKIE_ERROR_LINE], 1)

    monkeypatch.setattr("app.services.download_service.subprocess.Popen", _popen)
    app = _app("brave")

    _svc(app)._run_caption_only_task(task)

    assert len(calls) == 1
    assert ("done", task, "cancelled") in _drain(app)


def test_subtitle_phase_retries_without_cookies_too(monkeypatch, tmp_path):
    caption = tmp_path / "video.en.vtt"
    caption.write_text(VTT, encoding="utf-8")
    calls = _cookie_aware_popen(monkeypatch, caption)
    app = _app("brave")

    _svc(app)._subtitle_phase(_task(tmp_path))

    assert len(calls) == 2
    assert "--cookies-from-browser" not in calls[1]
    events = _drain(app)
    assert any(e[0] == "subtitle_status" and "saved" in str(e[2]) for e in events)
