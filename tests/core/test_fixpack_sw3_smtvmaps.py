"""Fixpack sw3 regression for app.services.download_service — smtvmaps.

A stale SMTV episode A is correctly rejected when the form url is a DIFFERENT
url B (page_url mismatch), so format_info['episode'] is NOT set. BUT the
audio_format_map / video_format_map still hold episode A's kind=='smtv'
selector dicts (carrying A's CDN url) until B's debounced 800ms lookup fires.
The prior guard only protected the 'episode' key, so format_info['audio'] /
['video'] still pulled the stale kind=='smtv' dict straight from the map.

Routing keys off _is_smtv_task, which trips on ANY kind=='smtv' sub-dict, so
the task still routed to _run_smtv_task and streamed episode A's video file
while writing url B's transcript -> mixed content.

This test leaves the SMTV maps IN PLACE (does not overwrite them, unlike the
prior fix's test) and asserts the resulting task is NOT an SMTV task and that
no kind=='smtv' sub-dict survives in its format_info. It FAILS on the pre-fix
code (the stale video selector flowed through unscrubbed).

Hermetic: App.__new__ + stubbed attrs, no Tk root, no network, no model, no
worker thread.
"""
from __future__ import annotations

import sys
import types

from app.services.download_service import DownloadService, _is_smtv_task
from core.integrations import smtv as smtv_mod


SMTV_A = "https://www.suprememastertv.com/en1/v/111111.html"
SMTV_B = "https://www.suprememastertv.com/en1/v/222222.html"


def _episode(page_url: str) -> smtv_mod.SmtvEpisode:
    return smtv_mod.SmtvEpisode(
        vid=page_url.rsplit("/", 1)[-1].split(".")[0],
        title="Episode",
        page_url=page_url,
        lang_prefix="en",
        files=[
            smtv_mod.SmtvFile(
                quality="396p",
                relative_path="clip.mp4",
                download_url=f"https://cdn.example/{page_url[-12:]}?file=clip.mp4",
            )
        ],
    )


class _Var:
    def __init__(self, value: str = "") -> None:
        self._v = value

    def get(self) -> str:
        return self._v

    def set(self, v) -> None:  # noqa: ANN001
        self._v = v


def _bare_app(monkeypatch, tmp_path, *, url: str, episode):
    """A stub App carrying exactly what enqueue_from_form touches."""
    if "faster_whisper" not in sys.modules:
        fw = types.ModuleType("faster_whisper")
        fw.WhisperModel = object  # type: ignore[attr-defined]
        sys.modules["faster_whisper"] = fw
    from app.app import App

    import app.services.download_service as ds
    monkeypatch.setattr(ds, "save_config", lambda *a, **k: None)
    import tkinter.messagebox as _mb
    warnings: list = []
    monkeypatch.setattr(_mb, "showwarning", lambda *a, **k: warnings.append(a))

    app = App.__new__(App)
    app.download_url_var = _Var(url)
    app.download_folder_var = _Var(str(tmp_path))
    app.download_mode_var = _Var("Audio and video")
    app.audio_format_var = _Var("")
    app.video_format_var = _Var("SD 396p")
    app.output_format_var = _Var("mp4")
    app.audio_format_map = {}
    app.video_format_map = {}
    app._smtv_episode = episode
    app.app_config = {}
    app.current_video_title = "Episode"
    app.current_video_language = "en"
    app.download_subtitles_var = _Var("")
    app.auto_transcribe_var = _Var(False)
    app.subtitle_lang_var = _Var("")
    app.download_start_time_var = _Var("")
    app.download_end_time_var = _Var("")
    app._download_duration = 0.0
    app.smtv_download_all_parts_var = None
    app.download_queue = []
    app.refresh_download_queue = lambda *a, **k: None

    captured: dict = {}

    class _Events:
        def put(self, item) -> None:  # noqa: ANN001
            captured.setdefault("events", []).append(item)

    app.download_events = _Events()

    svc = DownloadService(app)
    svc.process_queue = lambda *a, **k: None  # don't spawn a worker thread
    return app, svc, captured, warnings


def test_stale_smtv_map_dict_not_routed_as_smtv_task(monkeypatch, tmp_path):
    """Episode A rejected for url B, but A's kind=='smtv' video map left in
    place: the enqueued task must NOT be an SMTV task and must carry no
    kind=='smtv' sub-dict."""
    app, svc, _, warnings = _bare_app(
        monkeypatch, tmp_path, url=SMTV_B, episode=_episode(SMTV_A)
    )
    # The episode is rejected (page_url A != url B), so this is a normal
    # (non-SMTV) download and an audio format is required. Supply one so the
    # enqueue runs instead of bailing on the missing-format warning.
    app.audio_format_var = _Var("Best audio")
    app.audio_format_map = {"Best audio": {"kind": "best_audio"}}
    # CRITICAL: leave the stale SMTV video map IN PLACE (do NOT overwrite it).
    # This is episode A's selector that the unscrubbed code shipped verbatim.
    app.video_format_map = {
        "SD 396p": {
            "kind": "smtv",
            "mode": "video-396",
            "quality": "396p",
            "url": "https://cdn.example/111111?file=clip.mp4",
        }
    }

    svc.enqueue_from_form()

    assert len(app.download_queue) == 1
    task = app.download_queue[0]
    # No SMTV episode was pinned (prior guard) ...
    assert "episode" not in (task.format_info or {})
    # ... and crucially the task does NOT route to the SMTV streamer ...
    assert _is_smtv_task(task) is False
    # ... because no kind=='smtv' sub-dict survived into format_info.
    for key in ("audio", "video"):
        sub = (task.format_info or {}).get(key)
        if isinstance(sub, dict):
            assert sub.get("kind") != "smtv"
