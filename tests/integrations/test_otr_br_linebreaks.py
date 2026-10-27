"""An .otr paragraph with a <br> line break (Shift+Enter in oTranscribe)
must export to SRT with the words separated, not glued together.
"""
from __future__ import annotations

import json


def _otr_text(paragraph_html: str) -> str:
    return json.dumps(
        {"text": paragraph_html, "media": "", "media-source": "", "media-time": 20.0},
        ensure_ascii=False,
    )


def _paragraph(body_html: str, ts: float) -> str:
    return (
        f'<p><span class="timestamp" contenteditable="false" '
        f'data-timestamp="{ts:.3f}">0:00</span>{body_html}</p>'
    )


def test_br_inside_a_paragraph_separates_words(tmp_path):
    p = tmp_path / "br.otr"
    p.write_text(
        _otr_text(
            _paragraph(" line one<br>line two", 1.0)
            + _paragraph(" second", 5.0)
        ),
        encoding="utf-8",
    )
    from core.integrations.otranscribe import otr_to_srt

    srt = otr_to_srt(str(p))
    assert "line one line two" in srt
    assert "line oneline two" not in srt


def test_self_closing_br_inside_a_paragraph_separates_words(tmp_path):
    p = tmp_path / "br_selfclosed.otr"
    p.write_text(
        _otr_text(_paragraph(" alpha<br/>beta", 1.0)), encoding="utf-8"
    )
    from core.integrations.otranscribe import otr_to_srt

    srt = otr_to_srt(str(p))
    assert "alpha beta" in srt
    assert "alphabeta" not in srt


def test_br_does_not_swallow_the_following_untimed_paragraph_merge(tmp_path):
    # A paragraph whose body is "one<br>two" followed by an untimed
    # paragraph must still merge the untimed text into the same cue.
    p = tmp_path / "br_merge.otr"
    p.write_text(
        _otr_text(_paragraph(" one<br>two", 1.0) + "<p>loose note</p>"),
        encoding="utf-8",
    )
    from core.integrations.otranscribe import otr_to_srt

    srt = otr_to_srt(str(p))
    assert "one two" in srt
    assert "loose note" in srt
    # merged into the same cue: only one timestamp line
    assert srt.count("-->") == 1
