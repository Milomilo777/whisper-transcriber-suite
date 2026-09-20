"""Regression: the transcript viewer must not crash when a loaded
segment's ``words`` is a list of NON-dict elements.

A normal Whisper transcript carries ``words`` as a list of dicts
(``{"word": ..., "start": ..., "end": ..., "probability": ...}``). But
a hand-edited or unrelated JSON may carry a list of NON-dict elements
(e.g. ``words: [1, 2]`` or ``["a"]``). ``_segment_min_probability``
iterated that list and called ``w.get("probability", ...)`` on each
element; on a non-dict that raises ``AttributeError`` — which the
``(TypeError, ValueError)`` handler does NOT catch — crashing the viewer
during construction (``_populate_listbox`` calls the helper for every
row) and bypassing the friendly "pick the .json" guard in
``_load_segments``.

These tests exercise the pure helper seam without a Tk root, a media
file, VLC, or a network. On the pre-fix code the non-dict cases raise
``AttributeError`` and fail.
"""
from __future__ import annotations


def test_segment_min_probability_skips_non_dict_words():
    from app.dialogs.transcript_viewer import _segment_min_probability

    # List of ints — the canonical crash case (w.get on an int).
    assert _segment_min_probability({"words": [1, 2]}) is None
    # List of strings.
    assert _segment_min_probability({"words": ["a", "b"]}) is None
    # Mixed: a couple of garbage entries plus one real word dict. The
    # non-dicts are skipped; the real probability still drives the result.
    seg_mixed = {"words": [1, "x", {"probability": 0.42}, None]}
    assert _segment_min_probability(seg_mixed) == 0.42
    # None / non-list ``words`` still collapses cleanly to None.
    assert _segment_min_probability({"words": None}) is None
    assert _segment_min_probability({}) is None


def test_segment_min_probability_still_handles_real_dicts():
    """The fix must not regress the normal list-of-dicts path."""
    from app.dialogs.transcript_viewer import _segment_min_probability

    seg = {"words": [{"probability": 0.9}, {"probability": 0.7}, {"probability": 0.95}]}
    assert _segment_min_probability(seg) == 0.7
    # Empty word list → no probabilities available.
    assert _segment_min_probability({"words": []}) is None
    # A dict word with a non-numeric probability is coerced/skipped by the
    # existing (TypeError, ValueError) guard, not the new isinstance one.
    assert _segment_min_probability({"words": [{"probability": "abc"}]}) is None


class _StubLabel:
    """Minimal stand-in for the ttk.Label the karaoke path configures."""

    def __init__(self) -> None:
        self.text = ""

    def configure(self, *, text: str = "") -> None:
        self.text = text


def _make_karaoke_viewer(segments):
    """Build a TranscriptViewer instance WITHOUT running __init__ (no Tk
    root / no VLC), wired with just the attributes ``_update_karaoke``
    reads. Same pure-seam pattern as test_fixpack_sw4_karaoke.py."""
    from app.dialogs.transcript_viewer import TranscriptViewer

    v = TranscriptViewer.__new__(TranscriptViewer)
    v.segments = segments  # type: ignore[attr-defined]
    v._active_segment_idx = None  # type: ignore[attr-defined]
    v._active_word_idx = None  # type: ignore[attr-defined]
    v._words_lbl = _StubLabel()  # type: ignore[attr-defined]

    def _set_active_segment(idx):
        v._active_segment_idx = idx  # type: ignore[attr-defined]
        v._active_word_idx = None  # type: ignore[attr-defined]

    v._set_active_segment = _set_active_segment  # type: ignore[attr-defined]
    return v


def test_update_karaoke_skips_non_dict_words():
    """A segment whose ``words`` is a list of non-dicts must not raise
    during a 250-ms playhead tick. Pre-fix ``w.get("start")`` on an int
    raised AttributeError; the caller swallows it, but live word
    highlighting for that segment silently never worked."""
    from app.dialogs.transcript_viewer import TranscriptViewer

    segments = [{"start": 0.0, "end": 2.0, "text": "hello there", "words": [1, 2]}]
    viewer = _make_karaoke_viewer(segments)

    TranscriptViewer._update_karaoke(viewer, 1.0)  # must not raise

    assert viewer._active_segment_idx == 0  # type: ignore[attr-defined]
    assert viewer._active_word_idx is None  # type: ignore[attr-defined]


def test_update_karaoke_mixed_words_skips_junk_and_highlights_real_word():
    """Non-dict entries mixed with a real word dict are skipped; the real
    word still drives the karaoke highlight."""
    from app.dialogs.transcript_viewer import TranscriptViewer

    segments = [
        {
            "start": 0.0, "end": 4.0, "text": "hi",
            "words": [
                1,
                {"word": "hi", "start": 0.0, "end": 4.0, "probability": 0.9},
                "junk",
            ],
        },
    ]
    viewer = _make_karaoke_viewer(segments)

    TranscriptViewer._update_karaoke(viewer, 1.0)

    assert viewer._words_lbl.text == "[hi]"  # type: ignore[attr-defined]
