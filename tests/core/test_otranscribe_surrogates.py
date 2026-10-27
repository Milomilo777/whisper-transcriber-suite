"""Lone surrogate halves must never survive into oTranscribe converter output.

A hand-edited ``.otr`` / transcription ``.json`` can carry a lone surrogate
half as a JSON ``\\ud83d`` escape (``core.writers.base.replace_lone_surrogates``
documents the same threat for every text writer). ``str.encode("utf-8")``
refuses such a string, so the app's ``_write_text_atomic`` write of the
converted SRT / .otr fails wholesale — the Import .otr -> SRT menu action and
the subtitle-extras export lose the whole file instead of importing it with
U+FFFD like every other text format does.
"""
from __future__ import annotations

import json

from core.integrations.otranscribe import otr_to_srt, whisper_json_to_otr

_OTR_WITH_HALF = {
    "text": (
        '<p><span class="timestamp" contenteditable="false" '
        'data-timestamp="1.000">0:01</span>&nbsp;hi \ud83d bye</p>'
    ),
    "media-time": 0,
}


def test_otr_to_srt_output_is_utf8_encodable(tmp_path):
    otr_path = tmp_path / "hand_edited.otr"
    otr_path.write_text(json.dumps(_OTR_WITH_HALF), encoding="ascii")
    out = otr_to_srt(str(otr_path))
    out.encode("utf-8")  # UnicodeEncodeError before the fix
    assert "\ufffd" in out


def test_whisper_json_to_otr_output_is_utf8_encodable(tmp_path):
    json_path = tmp_path / "hand_edited.json"
    json_path.write_text(
        json.dumps([{"start": 1.0, "end": 2.0, "text": "hi \ud83d bye"}]),
        encoding="ascii",
    )
    out = whisper_json_to_otr(str(json_path))
    out.encode("utf-8")  # UnicodeEncodeError before the fix
    assert "\ufffd" in out
