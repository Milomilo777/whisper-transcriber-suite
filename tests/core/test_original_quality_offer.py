"""The site's original-quality ('max') video file must be offered in the Download tab.

``core.integrations.smtv`` treats ``max`` as a first-class quality:
``best_url_for_mode`` picks it first for ``video-best`` ("the site's recent
label for the original-quality video file, sometimes 4K"), ``video-max`` is in
its quality map, and ``AUDIO_SOURCE_QUALITIES`` ends with it. But
``FormatService._apply_smtv_formats`` only mapped 1080p / 720p / 396p, so a
page whose video files include a ``max`` entry never listed it — and a page
whose ONLY video file is ``max`` showed zero video formats, making a video
download of that episode impossible.

Hermetic: SimpleNamespace app, no Tk root, no network.
"""
from __future__ import annotations

import types

from app.services.format_service import FormatService
from core.integrations import smtv as smtv_mod

PAGE = "https://example.com/en1/v/123.html"

_NAMES = {
    "audio": "Show-p1.mp3",
    "1080p": "Show-p1-1080p.mp4",
    "720p": "Show-p1-2m.mp4",
    "396p": "Show-p1-700k.mp4",
    "max": "Show-p1-max.mp4",
}


def _episode(*qualities: str) -> smtv_mod.SmtvEpisode:
    files = [
        smtv_mod.SmtvFile(
            q, f"2021/0520/{_NAMES[q]}", f"https://cdn.example/dl?file=2021/0520/{_NAMES[q]}"
        )
        for q in qualities
    ]
    return smtv_mod.SmtvEpisode(
        vid="123", title="Show", page_url=PAGE, lang_prefix="en",
        files=files, transcript_text="",
    )


class _Var:
    def __init__(self, value: str = "") -> None:
        self.value = value

    def get(self) -> str:
        return self.value

    def set(self, value: str) -> None:
        self.value = value


def _format_app() -> types.SimpleNamespace:
    return types.SimpleNamespace(
        set_download_duration=lambda _s: None,
        update_download_mode=lambda: None,
        update_caption_shortcut_state=lambda: None,
        audio_format_combo={}, video_format_combo={},
        audio_format_var=_Var(), video_format_var=_Var(), format_status_var=_Var(),
    )


def test_max_only_page_still_offers_a_video_format():
    app = _format_app()
    FormatService(app)._apply_smtv_formats(_episode("max"))  # type: ignore[arg-type]
    assert app.video_format_combo["values"], (
        "a page whose only video file is the original-quality 'max' entry "
        "must still offer a video download"
    )
    entry = app.video_format_map[app.video_format_var.get()]
    assert entry["kind"] == "smtv"
    assert entry["mode"] == "video-max"
    assert entry["url"].endswith("Show-p1-max.mp4")


def test_max_file_is_offered_alongside_the_other_qualities():
    app = _format_app()
    FormatService(app)._apply_smtv_formats(_episode("max", "720p", "396p"))  # type: ignore[arg-type]
    urls = [str(entry["url"]) for entry in app.video_format_map.values()]
    assert any(u.endswith("Show-p1-max.mp4") for u in urls), (
        "the original-quality file the page lists must be one of the choices"
    )


def test_max_is_never_the_default_when_other_qualities_exist():
    """The original file can be huge: it is listed last, whatever order the page lists it in."""
    app = _format_app()
    FormatService(app)._apply_smtv_formats(_episode("max", "1080p", "720p"))  # type: ignore[arg-type]
    entry = app.video_format_map[app.video_format_var.get()]
    assert entry["mode"] != "video-max"
    assert list(app.video_format_map.values())[-1]["mode"] == "video-max"
