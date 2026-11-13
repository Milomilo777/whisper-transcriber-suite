"""Regression for core.writers.vtt._karaoke_payload non-string word text.

A converted / hand-edited JSON re-fed for re-export can carry a word whose
``word`` (text) field is a non-string truthy value (e.g. the number ``42``).
The karaoke payload used to call ``(w.get("word") or "").strip()`` bare, so
that single bad word kept the non-string value and ``.strip()`` raised
``AttributeError`` ('int' object has no attribute 'strip') — aborting the
WHOLE VTT write and losing the rest of the transcript. The round-2 fix
guarded only the numeric start coercion, not the word text. Peer writers
coerce defensively (speaker_prefix uses str()); the VTT writer must too: a
malformed word never aborts the conversion.
"""
from __future__ import annotations

from core.writers import vtt


def test_vtt_writer_tolerates_non_string_word_text():
    """A word whose text is a number must not abort the VTT write.

    Pre-fix this raised AttributeError on int.strip(); the fix coerces the
    word text to str before the string ops, so it survives as "42".
    """
    segs = [
        {
            "start": 0.0,
            "end": 1.0,
            "text": "42",
            "words": [
                {"start": 0.0, "end": 1.0, "word": 42, "probability": 0.9},
            ],
        }
    ]
    body = vtt.write(segs)  # must not raise
    assert body.startswith("WEBVTT\n")
    # The numeric word text is coerced to its string form; nothing dropped.
    assert "<c>42</c>" in body
    assert "<00:00:00.000>" not in body  # No activation tag at the cue boundary.


def test_vtt_writer_non_string_word_text_with_good_neighbour():
    """A non-string word in a mixed list must not drop the good words."""
    segs = [
        {
            "start": 2.0,
            "end": 4.0,
            "text": "hi 7",
            "words": [
                {"start": 2.0, "end": 2.5, "word": "hi", "probability": 0.9},
                {"start": 2.5, "end": 4.0, "word": 7, "probability": 0.8},
            ],
        }
    ]
    body = vtt.write(segs)  # must not raise
    assert "<c>hi</c> <00:00:02.500><c>7</c>" in body
    assert "<00:00:02.000>" not in body


def test_vtt_writer_none_word_text_is_skipped():
    """A word whose text is None (absent) still coerces to "" and is skipped,
    not crashed — preserving the prior empty-token behaviour.
    """
    seg = {
        "start": 0.0,
        "end": 1.0,
        "text": "",
        "words": [
            {"start": 0.0, "end": 1.0, "word": None, "probability": 0.9},
        ],
    }
    payload = vtt._karaoke_payload(seg)
    assert payload == ""
