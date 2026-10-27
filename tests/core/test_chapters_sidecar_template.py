"""Auto-chapters sidecar must follow the output_filename_template.

The transcript outputs (srt/json/...) are named by expanding
``output_filename_template``; the auto-chapters ``<name>.chapters.json``
sidecar is derived by the transcript viewer from the JSON file it opened
(``splitext(json_path)[0] + ".chapters.json"``). When the template adds a
token such as ``{lang}``, the outputs move to ``show.en.json`` but the
sidecar was still written at the raw, un-templated ``show.chapters.json``,
so the viewer looked for ``show.en.chapters.json`` and found nothing — the
auto-chapters became invisible on every templated export.
"""
from __future__ import annotations

import os

import pytest


@pytest.fixture
def transcriber(monkeypatch):
    import sys
    if "core.transcriber" not in sys.modules:
        import types as _t
        fake_fw = _t.ModuleType("faster_whisper")
        fake_fw.WhisperModel = object  # type: ignore[attr-defined]
        sys.modules.setdefault("faster_whisper", fake_fw)
    import core.transcriber as t
    return t


def test_chapters_sidecar_tracks_templated_json(transcriber, tmp_path, monkeypatch):
    monkeypatch.setattr(transcriber, "config", {
        "output_formats": ["json"],
        "output_filename_template": "{base}.{lang}.{ext}",
    })
    base = str(tmp_path / "show")
    seg = [{"start": 0.0, "end": 1.0, "text": "hello"}]
    chapters = [{"title": "Intro", "start": 0.0, "end": 5.0}]
    written = transcriber._write_outputs(
        base, seg, str(tmp_path / "show.mp4"), lang="en", chapters=chapters
    )
    json_path = next(p for p in written if p.endswith(".json"))
    # The viewer derives the sidecar from the JSON it opens.
    viewer_sidecar = os.path.splitext(json_path)[0] + ".chapters.json"
    assert os.path.isfile(viewer_sidecar), (
        "the auto-chapters sidecar must sit next to the templated JSON "
        f"(expected {viewer_sidecar})"
    )
