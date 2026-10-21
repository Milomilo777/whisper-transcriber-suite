"""The caption shortcut never uses the previous link's metadata.

Typing a new link schedules a lookup 800 ms later. The previous link's
formats were already dropped at once, but its title, language and caption
tracks (and the "Use the subtitles" button built from them) stayed until
the lookup ran, so the still-visible button queued the new link under the
old link's title, language and caption kind. Now the metadata and the
button go with the formats, and the shortcut refuses to queue while a
lookup for the current link is pending.

No Tk: plain stand-ins for the app and its variables.
"""
from __future__ import annotations

import tkinter.messagebox  # noqa: F401  -- binds the attribute the tests monkeypatch
import types

import pytest

from app.services.download_service import DownloadService
from app.services.format_service import FormatService


class _Var:
    def __init__(self, value: str = "") -> None:
        self._v = value

    def get(self) -> str:
        return self._v

    def set(self, v) -> None:  # noqa: ANN001
        self._v = v


def _app_with_link_a(tmp_path) -> types.SimpleNamespace:
    calls: list[str] = []
    app = types.SimpleNamespace(
        download_url_var=_Var("https://www.youtube.com/watch?v=aaaaaaaaaaa"),
        download_folder_var=_Var(str(tmp_path)),
        subtitle_lang_var=_Var("Automatic"),
        current_video_caption_langs={"en": "manual"},
        current_video_language="en",
        current_video_title="Video A",
        _smtv_episode=None,
        app_config={},
        download_queue=[],
        refresh_download_queue=lambda: None,
        audio_format_map={"best": "a"},
        video_format_map={"best": "a"},
        format_lookup_error="",
        format_lookup_after=None,
        after=lambda _ms, _fn: "after#1",
        after_cancel=lambda _id: None,
        update_caption_shortcut_state=lambda: calls.append("shortcut"),
        _calls=calls,
    )
    return app


def _svc(app, monkeypatch) -> tuple[DownloadService, list[tuple]]:
    warnings: list[tuple] = []

    class _MB:
        @staticmethod
        def showwarning(title, message, *_a, **_k):
            warnings.append((title, message))

    monkeypatch.setattr("tkinter.messagebox", _MB)
    monkeypatch.setattr("app.services.download_service.save_config", lambda *a, **k: None)
    svc = DownloadService.__new__(DownloadService)
    svc.app = app  # type: ignore[attr-defined]
    svc.process_queue = lambda: None  # type: ignore[method-assign]
    return svc, warnings


def test_a_new_link_drops_the_previous_links_caption_metadata_at_once(tmp_path):
    app = _app_with_link_a(tmp_path)
    app.download_url_var.set("https://www.youtube.com/watch?v=bbbbbbbbbbb")

    FormatService(app).schedule_lookup()  # type: ignore[arg-type]

    assert app.current_video_caption_langs == {}
    assert app.current_video_language == "" and app.current_video_title == ""
    assert app._calls == ["shortcut"]  # the button is re-evaluated (hidden) now, not 800 ms later


def test_the_shortcut_refuses_the_new_link_while_its_lookup_is_pending(tmp_path, monkeypatch):
    app = _app_with_link_a(tmp_path)
    svc, warnings = _svc(app, monkeypatch)
    # Link B replaces A; the lookup timer is armed but has not fired.
    app.download_url_var.set("https://www.youtube.com/watch?v=bbbbbbbbbbb")
    FormatService(app).schedule_lookup()  # type: ignore[arg-type]
    assert app.format_lookup_after == "after#1"

    svc.enqueue_caption_only_from_form()

    assert app.download_queue == []
    assert warnings and warnings[0][0] == "No captions found"


def test_stale_metadata_alone_never_queues_the_new_link(tmp_path, monkeypatch):
    """Belt and braces: even with A's metadata still in place, a pending
    lookup means it is not B's."""
    app = _app_with_link_a(tmp_path)
    svc, warnings = _svc(app, monkeypatch)
    app.download_url_var.set("https://www.youtube.com/watch?v=bbbbbbbbbbb")
    app.format_lookup_after = "after#1"

    svc.enqueue_caption_only_from_form()

    assert app.download_queue == []
    assert warnings and warnings[0][0] == "No captions found"


def test_the_shortcut_still_queues_a_looked_up_link(tmp_path, monkeypatch):
    app = _app_with_link_a(tmp_path)
    svc, warnings = _svc(app, monkeypatch)

    svc.enqueue_caption_only_from_form()

    assert warnings == []
    (task,) = app.download_queue
    assert task.title == "Video A (captions only)" and task.caption_kind == "manual"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
