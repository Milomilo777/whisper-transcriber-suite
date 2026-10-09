"""Download-area defects from an external review pass (branch fix/gemini-b1).

* a yt-dlp failure whose stderr was only whitespace produced an EMPTY error text
  (the fallback chain was stripped after, not before, choosing a source);
* a ``automatic_captions`` value that is a non-empty list instead of an object
  raised ``AttributeError`` in the lookup handler, so no formats were shown.

Hermetic: fake app, scripted yt-dlp results, no network.
"""
from __future__ import annotations

import pytest

from app.services.format_service import FormatService
from tests.core.test_format_service import _LookupApp, _run_lookup

_FALLBACK = "yt-dlp could not read this URL"


class _HandlerApp(_LookupApp):
    def update_download_mode(self) -> None:
        pass

    def update_caption_shortcut_state(self) -> None:
        pass


@pytest.mark.parametrize("stdout, stderr, expected", [
    ("", "   \n", _FALLBACK),
    ("  \n", "\n\n", _FALLBACK),
    ("stdout text\n", "  \n", "stdout text"),
    ("", "ERROR: real reason\n", "ERROR: real reason"),
])
def test_failed_lookup_never_reports_an_empty_error(monkeypatch, stdout, stderr, expected):
    app = _LookupApp()
    _run_lookup(monkeypatch, app, [(1, stdout, stderr)])
    kind, _url, text = app.format_events.get_nowait()
    assert kind == "error"
    assert text == expected


@pytest.mark.parametrize("auto_caps", [["en"], [{"ext": "vtt"}], "en", 5])
def test_non_object_automatic_captions_do_not_break_the_handler(auto_caps):
    app = _HandlerApp()
    app.after = lambda *_a, **_k: None  # type: ignore[assignment]
    payload = {"title": "t", "formats": [], "automatic_captions": auto_caps}
    FormatService(app)._handle_event("formats", "http://x", payload)  # type: ignore[arg-type]
    assert app.current_video_language == ""  # type: ignore[attr-defined]
    assert app.current_video_caption_langs == {}  # type: ignore[attr-defined]


def test_object_automatic_captions_still_give_the_first_language():
    app = _HandlerApp()
    payload = {"title": "t", "formats": [],
               "automatic_captions": {"fa": [{"ext": "vtt"}], "en": []}}
    FormatService(app)._handle_event("formats", "http://x", payload)  # type: ignore[arg-type]
    assert app.current_video_language == "fa"  # type: ignore[attr-defined]
