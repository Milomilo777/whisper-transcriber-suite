"""Tests for surfacing the real format-lookup failure reason (2026-08-23).

Real-world regression: a Facebook URL's format lookup failed (yt-dlp's
extractor rejected it -- a common shape for Facebook/Instagram, which
increasingly need a logged-in session or break outright on a page-structure
change) and the ONLY place that failure reason went was a small status
label next to the format dropdowns. Clicking Download then hit the
"missing audio format" guard, which showed a generic "Wait for formats to
load, then select an audio format." -- misleading once the lookup has
already failed and will never load -- and nothing about the failure ever
reached the download log the user was actually watching.

``DownloadService._warn_format_missing`` now reads ``app.format_lookup_error``
(set by ``FormatService`` whenever a lookup fails) and, when non-empty,
shows the real reason in the popup AND writes it to the log -- for
Facebook, Instagram, or any other site whose extractor breaks, not just
the one previously investigated (cookie-jar read failures on X/Twitter,
fixed separately in ``_media_phase``).
"""
from __future__ import annotations

import types
import tkinter.messagebox  # noqa: F401  -- ensures tkinter.messagebox is a bound attribute to monkeypatch

from app.services.download_service import DownloadService


class _Var:
    def __init__(self, value: str = "") -> None:
        self._v = value

    def get(self):  # noqa: ANN201
        return self._v

    def set(self, v) -> None:  # noqa: ANN001
        self._v = v


def _app(*, format_lookup_error: str = "") -> types.SimpleNamespace:
    """A bare App stub carrying exactly what enqueue_from_form touches."""
    log_lines: list[str] = []
    app = types.SimpleNamespace(
        download_url_var=_Var("https://www.facebook.com/watch/?v=123"),
        download_folder_var=_Var(r"C:\dl"),
        download_mode_var=_Var("Audio and video"),
        audio_format_var=_Var(""),
        video_format_var=_Var(""),
        output_format_var=_Var("mp4"),
        audio_format_map={},
        video_format_map={},
        app_config={},
        current_video_title="",
        current_video_language="",
        download_subtitles_var=_Var(""),
        subtitle_lang_var=_Var(""),
        download_start_time_var=_Var(""),
        download_end_time_var=_Var(""),
        smtv_download_all_parts_var=None,
        _smtv_episode=None,
        download_queue=[],
        refresh_download_queue=lambda: None,
        process_queue=lambda: None,
        format_lookup_error=format_lookup_error,
        log=log_lines.append,
    )
    app._log_lines = log_lines  # type: ignore[attr-defined]
    return app


def _svc_with_warnings(app, monkeypatch):
    warnings: list[tuple] = []

    class _MB:
        @staticmethod
        def showwarning(title, message, *_a, **_k):
            warnings.append((title, message))

    monkeypatch.setattr("tkinter.messagebox", _MB)
    svc = DownloadService.__new__(DownloadService)
    svc.app = app  # type: ignore[attr-defined]
    return svc, warnings


def test_missing_audio_format_shows_real_lookup_failure_reason(monkeypatch):
    reason = "ERROR: [facebook] 123: Cannot parse data"
    app = _app(format_lookup_error=reason)
    svc, warnings = _svc_with_warnings(app, monkeypatch)

    DownloadService.enqueue_from_form(svc)

    assert app.download_queue == []
    assert len(warnings) == 1
    title, message = warnings[0]
    assert title == "Missing audio format"
    assert reason in message
    # The real reason must also land in the visible download log, not just
    # the popup -- the log is where the user actually looks afterwards.
    assert any(reason in line for line in app._log_lines)


def test_missing_audio_format_without_lookup_error_keeps_generic_message(monkeypatch):
    """No failure recorded (lookup still running / never started) -> the
    original 'wait for it to load' message, unchanged, and nothing logged."""
    app = _app(format_lookup_error="")
    svc, warnings = _svc_with_warnings(app, monkeypatch)

    DownloadService.enqueue_from_form(svc)

    assert len(warnings) == 1
    title, message = warnings[0]
    assert title == "Missing audio format"
    assert "Wait for formats to load" in message
    assert app._log_lines == []


def test_missing_video_format_shows_real_lookup_failure_reason(monkeypatch):
    reason = "ERROR: [Instagram] 456: Requested content is not available"
    app = _app(format_lookup_error=reason)
    app.audio_format_var = _Var("Best audio")
    app.audio_format_map = {"Best audio": {"kind": "best_audio"}}
    svc, warnings = _svc_with_warnings(app, monkeypatch)

    DownloadService.enqueue_from_form(svc)

    assert app.download_queue == []
    assert len(warnings) == 1
    title, message = warnings[0]
    assert title == "Missing video format"
    assert reason in message
    assert any(reason in line for line in app._log_lines)
