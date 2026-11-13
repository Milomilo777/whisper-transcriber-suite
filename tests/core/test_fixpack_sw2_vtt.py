"""Regression for core.writers.vtt._karaoke_payload non-numeric word start.

A converted / hand-edited JSON re-fed for re-export can carry a word whose
``start`` is a non-numeric string (e.g. ``"abc"``). The karaoke payload used
to call ``float(w.get("start"))`` bare, so that single bad word raised
``ValueError`` and aborted the WHOLE VTT write — the rest of the transcript
was lost. Peer writers coerce timestamps defensively; the VTT writer must
do the same: a malformed word never aborts the conversion.
"""
from __future__ import annotations

from core.writers import vtt


def test_vtt_writer_tolerates_non_numeric_word_start():
    """A word with start='abc' must not abort the VTT write.

    Pre-fix this raised ValueError in float('abc'); the fix guards the
    coercion and falls back to the segment start (2.0s).
    """
    segs = [
        {
            "start": 2.0,
            "end": 4.0,
            "text": "hi there",
            "words": [
                {"start": "abc", "end": 2.5, "word": "hi", "probability": 0.9},
                {"start": 2.5, "end": 4.0, "word": "there", "probability": 0.8},
            ],
        }
    ]
    body = vtt.write(segs)  # must not raise
    assert body.startswith("WEBVTT\n")
    # The bad-start word still appears at cue start without a redundant
    # inline marker (WebVTT 4.2.2 requires strictly interior timestamps).
    # Its class span and the good neighbour's valid timestamp both survive.
    assert "<c>hi</c> <00:00:02.500><c>there</c>" in body
    assert "<00:00:02.000>" not in body


def test_vtt_writer_non_numeric_start_with_non_numeric_segment_start():
    """Defensive double fallback: if both the word start and the segment
    start are non-numeric, the timestamp clamps to 0.0 rather than raising.
    """
    seg = {
        "start": "xyz",
        "end": 4.0,
        "text": "only",
        "words": [
            {"start": "abc", "end": 2.5, "word": "only", "probability": 0.9},
        ],
    }
    # write() also coerces seg['start'] for the cue line via float(); guard
    # only the karaoke payload here by exercising _karaoke_payload directly.
    payload = vtt._karaoke_payload(seg)
    assert "<00:00:00.000><c>only</c>" in payload
