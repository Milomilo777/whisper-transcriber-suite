"""The Download action bar applies a button only to the rows it is valid for.

With a finished and a running download selected together, Remove and Re-run
are enabled (valid for the finished row) but used to act on every selected
row: Remove hid the running job while its process and download slot stayed
active, and Re-run queued a copy of it. The dispatcher now filters the
selection by the same rule that enables the buttons
(``download_button_states_for_status``), as the Queue tab's bar does.

No Tk: ``App`` methods run unbound against a plain stand-in.
"""
from __future__ import annotations

import types

import pytest

pytest.importorskip("tkinter")

from app.app import App
from app.domain.tasks import VideoDownloadTask


def _dl(status: str) -> VideoDownloadTask:
    t = VideoDownloadTask(
        url=f"https://example.com/{status}", folder="/tmp", format_label="x",
        format_info={
            "mode": "Audio and video", "output": "mp4",
            "audio": {"kind": "best_audio"}, "video": {"kind": "best_video"},
        },
    )
    t.status = status
    return t


def _fake_app(selection: list[VideoDownloadTask]) -> types.SimpleNamespace:
    app = types.SimpleNamespace(
        download_queue=list(selection),
        download_current=next((t for t in selection if t.status == "running"), None),
        _selected_downloads=lambda: list(selection),
        _update_download_action_bar=lambda: None,
        refresh_download_queue=lambda: None,
        download_service=types.SimpleNamespace(process_queue=lambda: None),
        log=lambda _m: None,
    )
    # The real per-row rule (the one that enables the buttons), bound to the stand-in.
    app._download_button_states = lambda t: App._download_button_states(app, t)  # type: ignore[arg-type]
    return app


def test_remove_on_a_mixed_selection_keeps_the_active_rows():
    running, finished, paused, waiting = _dl("running"), _dl("finished"), _dl("paused"), _dl("waiting")
    app = _fake_app([running, finished, paused, waiting])

    App._download_action_apply(app, lambda t: App.remove_download(app, t), "remove")  # type: ignore[arg-type]

    assert finished not in app.download_queue
    assert running in app.download_queue
    assert paused in app.download_queue      # its only Resume handle stays visible
    assert waiting in app.download_queue


def test_rerun_on_a_mixed_selection_copies_only_the_ended_rows():
    running, failed = _dl("running"), _dl("error")
    app = _fake_app([running, failed])

    App._download_action_apply(app, lambda t: App._rerun_download(app, t), "rerun")  # type: ignore[arg-type]

    copies = [t for t in app.download_queue if t not in (running, failed)]
    assert len(copies) == 1
    assert copies[0].url == failed.url


def test_cancel_on_a_mixed_selection_still_reaches_every_active_row(monkeypatch):
    running, finished, paused = _dl("running"), _dl("finished"), _dl("paused")
    for t in (running, paused):
        t.process = None
    app = _fake_app([running, finished, paused])
    app.cancel = lambda _t: None
    app.download_service.cancel_stopped = lambda _t: None

    App._download_action_apply(app, lambda t: App.cancel_download(app, t), "cancel")  # type: ignore[arg-type]

    assert running.status == "cancelled" and paused.status == "cancelled"
    assert finished.status == "finished"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
