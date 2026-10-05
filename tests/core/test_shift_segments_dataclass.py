"""_shift_segments must move word times on faster-whisper 1.1+ too.

faster-whisper 1.1 turned ``Segment`` and ``Word`` from NamedTuples into
dataclasses. ``_shift_segments`` only knew ``_replace``, so on a clipped run
the segment fell back to an in-place shift and every word kept its
slice-relative time (a Transcribe-tab time range starting at 100 s gave
words at 1 s instead of 101 s).
"""
from __future__ import annotations

import sys
import types
from dataclasses import dataclass, field
from typing import Any


def _transcriber():
    if "core.transcriber" not in sys.modules:
        fake = types.ModuleType("faster_whisper")
        fake.WhisperModel = object  # type: ignore[attr-defined]
        sys.modules.setdefault("faster_whisper", fake)
    import core.transcriber as t

    return t


@dataclass
class Word:
    start: float
    end: float
    word: str = "w"
    probability: float = 0.9


@dataclass
class Segment:
    start: float
    end: float
    text: str = "x"
    words: Any = field(default_factory=list)


def test_dataclass_segments_and_words_are_shifted_without_mutation():
    t = _transcriber()
    word = Word(1.0, 1.5)
    seg = Segment(1.0, 2.0, "hi", [word])
    out = list(t._shift_segments([seg], 100.0))[0]
    assert (out.start, out.end) == (101.0, 102.0)
    assert [(w.start, w.end) for w in out.words] == [(101.0, 101.5)]
    assert out.text == "hi"
    assert (seg.start, word.start) == (1.0, 1.0)  # engine objects untouched


def test_real_faster_whisper_types_when_available():
    try:
        from faster_whisper.transcribe import Segment as FWSegment, Word as FWWord
    except Exception:  # noqa: BLE001 - stubbed faster_whisper in this session
        return
    t = _transcriber()
    word = FWWord(start=0.5, end=0.9, word="hi", probability=0.9)
    seg = FWSegment(id=1, seek=0, start=0.5, end=1.0, text="hi", tokens=[],
                    avg_logprob=0.0, compression_ratio=1.0, no_speech_prob=0.0,
                    words=[word], temperature=0.0)
    out = list(t._shift_segments([seg], 10.0))[0]
    assert (out.start, out.words[0].start, out.words[0].end) == (10.5, 10.5, 10.9)
