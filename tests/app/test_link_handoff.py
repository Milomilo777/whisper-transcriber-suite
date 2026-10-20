"""A link pasted on the Transcribe tab: one click downloads it and then transcribes it.

Found in a click-through test (2026-10-21, 2.1.0): Transcribe moved the link to the
Download Videos tab and ticked "Transcribe after download", but the download chain reads
the SAVED setting, which stayed off, so the file downloaded and was never transcribed;
and nothing started until the user found and clicked Download.
"""
from __future__ import annotations

import types
from typing import Any

from app.app import App
from app.services import format_service as fs

URL = "https://example.invalid/talk.mp3"


class _Var:
    def __init__(self, value: Any = "") -> None:
        self.value = value

    def get(self) -> Any:
        return self.value

    def set(self, value: Any) -> None:
        self.value = value


def _transcribe_tab_app() -> types.SimpleNamespace:
    logs: list[str] = []
    selected: list[str] = []
    fake = types.SimpleNamespace(
        fv=_Var(URL), download_url_var=_Var(""), auto_transcribe_var=_Var(False),
        app_config={"auto_transcribe_after_download": False}, log=logs.append, logs=logs,
        nb=types.SimpleNamespace(select=selected.append), selected=selected,
        t1="t1", t3="t3", pending_link_start="",
    )
    fake._save_auto_transcribe_pref = lambda: App._save_auto_transcribe_pref(fake)  # type: ignore[arg-type]
    return fake


def test_transcribe_with_a_link_saves_auto_transcribe_and_waits_to_start() -> None:
    fake = _transcribe_tab_app()
    App.add(fake)  # type: ignore[arg-type]
    assert fake.download_url_var.get() == URL
    assert fake.auto_transcribe_var.get() is True
    # The setting the download chain reads (download_service) is on too.
    assert fake.app_config["auto_transcribe_after_download"] is True
    assert fake.pending_link_start == URL
    assert fake.selected == ["t3"]


class _Combo(dict):  # type: ignore[type-arg]
    pass


def _download_tab_app(url: str, pending: str) -> types.SimpleNamespace:
    calls: list[Any] = []
    logs: list[str] = []
    return types.SimpleNamespace(
        download_url_var=_Var(url), pending_link_start=pending,
        audio_format_combo=_Combo(), video_format_combo=_Combo(),
        audio_format_var=_Var(), video_format_var=_Var(), format_status_var=_Var(),
        app_config={}, update_download_mode=lambda: None, set_download_duration=lambda _d: None,
        update_caption_shortcut_state=lambda: None, hide_yt_dlp_offer=lambda: None,
        yt_dlp_path=lambda: "yt-dlp", add_download="ADD_DOWNLOAD",
        after=lambda ms, fn: calls.append((ms, fn)), calls=calls, log=logs.append, logs=logs,
    )


_PAYLOAD = {"title": "Talk", "formats": [
    {"format_id": "0", "ext": "mp3", "acodec": "mp3", "vcodec": "none"},
]}


def test_formats_in_start_the_waiting_download_once() -> None:
    app = _download_tab_app(URL, pending=URL)
    service = fs.FormatService(app)  # type: ignore[arg-type]
    service._handle_event("formats", URL, _PAYLOAD)
    assert app.calls == [(0, "ADD_DOWNLOAD")]
    assert app.pending_link_start == ""
    service._handle_event("formats", URL, _PAYLOAD)  # a second lookup of the same link
    assert app.calls == [(0, "ADD_DOWNLOAD")]


def test_a_link_typed_on_the_download_tab_never_starts_by_itself() -> None:
    app = _download_tab_app(URL, pending="")
    fs.FormatService(app)._handle_event("formats", URL, _PAYLOAD)  # type: ignore[arg-type]
    assert app.calls == []


def test_a_link_that_cannot_be_read_drops_the_waiting_start_and_says_so() -> None:
    app = _download_tab_app(URL, pending=URL)
    fs.FormatService(app)._handle_event("error", URL, "ERROR: Unsupported URL")  # type: ignore[arg-type]
    assert app.calls == []
    assert app.pending_link_start == ""
    assert any("did not start" in line for line in app.logs)
