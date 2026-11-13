"""Rescue limits prioritize collapsed text and report unexamined stretches."""
from core import collapse_rescue as cr
import pytest


def segment(start, end, text):
    return {"start": start, "end": end, "text": text}


def reading(start, end):
    return [segment(start, end, "one two three four five six seven eight")]


def test_silent_gaps_cannot_starve_a_later_collapsed_window():
    normal = [segment(20 + i * 21, 21 + i * 21, "normal words") for i in range(21)]
    end = normal[-1]["end"]
    collapsed = segment(end, end + 30, "hm")
    original = normal + [collapsed]
    checked = []

    def speech(start, stop):
        checked.append((start, stop))
        return [(start, stop)] if start == end else []

    result, report = cr.rescue(original, end + 30, speech, reading)
    assert any(a == end for a, _b, _old, _new in report.rescued)
    assert all(result[i] is item for i, item in enumerate(normal))
    assert not any(item is collapsed for item in result)
    assert len(checked) <= cr.MAX_SPANS


def test_every_collapsed_window_beyond_the_check_limit_is_reported(monkeypatch):
    monkeypatch.setattr(cr, "MAX_RESCUED_FRACTION", 1.0)
    original = [segment(i * 30, (i + 1) * 30, "hm") for i in range(cr.MAX_SPANS + 2)]
    checked = []

    def speech(start, end):
        checked.append((start, end))
        return [(start, end)]

    _out, report = cr.rescue(original, len(original) * 30, speech, reading)
    accounted = {(a, b) for a, b, *_ in report.rescued + report.kept}
    assert accounted == {(item["start"], item["end"]) for item in original}
    assert len(checked) <= cr.MAX_SPANS
    assert len(report.rescued) == cr.MAX_SPANS
    assert all("limit" in why for _a, _b, why in report.kept)


def test_unexamined_gaps_are_not_silently_treated_as_speechless():
    original = [segment(20 + i * 21, 21 + i * 21, "normal words") for i in range(cr.MAX_SPANS + 2)]
    checked = []

    def speech(start, end):
        checked.append((start, end))
        return []

    result, report = cr.rescue(original, original[-1]["end"], speech, reading)
    assert all(a is b for a, b in zip(result, original))
    assert len(checked) == cr.MAX_SPANS
    assert len(report.kept) == 2
    assert all("limit" in why for _a, _b, why in report.kept)


def test_prioritized_selection_still_splices_in_original_time_order():
    before, collapsed, after = segment(0, 1, "original start"), segment(20, 50, "hm"), segment(50, 51, "original end")

    def read(start, end):
        label = "gap" if start < 20 else "collapsed"
        return [segment(start, end, label + " one two three four five six seven")]

    result, report = cr.rescue([before, collapsed, after], 51, lambda a, b: [(a, b)], read)
    assert len(report.rescued) == 2
    assert result[0] is before and result[-1] is after
    assert not any(item is collapsed for item in result)
    assert [item["start"] for item in result] == sorted(item["start"] for item in result)
    assert any(item["text"].startswith("gap ") for item in result)
    assert any(item["text"].startswith("collapsed ") for item in result)


@pytest.mark.parametrize("has_collapsed_tail", [False, True])
def test_transcriber_delivers_recovered_tail_and_limit_warnings(monkeypatch, has_collapsed_tail):
    """Exercise the real caller, selection, shifting and log callback together."""
    import sys
    from types import ModuleType, SimpleNamespace

    import numpy as np
    from core import transcriber as tr
    from core.backends import nvidia_asr

    original = [segment(20 + i * 21, 21 + i * 21, "normal words")
                for i in range(cr.MAX_SPANS + 2)]
    tail_start = original[-1]["end"]
    if has_collapsed_tail:
        original.append(segment(tail_start, tail_start + 30, "hm"))
    duration = original[-1]["end"]
    checked, decoded, messages, paused = [], [], [], []
    vad = ModuleType("faster_whisper.vad")

    def speech(audio, options):
        start, end = map(float, audio)
        checked.append((start, end))
        return ([{"start": 0, "end": int((end - start) * cr.SAMPLE_RATE)}]
                if has_collapsed_tail and start == tail_start else [])

    def decode(path, start, end):
        decoded.append((start, end))
        # Synthetic metadata for the stub VAD/model; no real PCM is inferred.
        return np.array([start, end], dtype=np.float64)

    def transcribe(audio, **kwargs):
        assert kwargs["vad_filter"] is False
        assert kwargs["condition_on_previous_text"] is False
        return [SimpleNamespace(start=0.0, end=float(audio[1] - audio[0]),
                                text="one two three four five six seven eight")], None

    vad.VadOptions = lambda **kwargs: SimpleNamespace(**kwargs)
    vad.get_speech_timestamps = speech
    monkeypatch.setitem(sys.modules, "faster_whisper.vad", vad)
    monkeypatch.setattr(sys.modules["faster_whisper"], "vad", vad, raising=False)
    monkeypatch.setattr(tr, "MODEL", object())
    monkeypatch.setattr(tr, "_LM_RUNNER", SimpleNamespace(slot=None))
    monkeypatch.setattr(tr, "mixed_language_pair", lambda task: None)
    monkeypatch.setattr(tr, "_whisper_runner", lambda *a, **k: SimpleNamespace(transcribe=transcribe))
    monkeypatch.setattr(nvidia_asr, "_decode_window", decode)
    result = tr._rescue_collapsed(
        SimpleNamespace(cancelled=False, file_path="synthetic.wav"), original,
        "synthetic.wav", {}, False, "en", duration, messages.append,
        before_piece=lambda: paused.append(True),
    )
    assert len(checked) == cr.MAX_SPANS
    assert all(result[i] is item for i, item in enumerate(original[:cr.MAX_SPANS + 2]))
    warnings = [line for line in messages if line.startswith("WARN:")]
    assert len(warnings) == (3 if has_collapsed_tail else 2)
    assert all("speech-check limit" in line for line in warnings)
    if has_collapsed_tail:
        recovered = result[cr.MAX_SPANS + 2:]
        assert recovered[0]["start"] == tail_start and recovered[-1]["end"] == duration
        assert all(a["end"] == b["start"] for a, b in zip(recovered, recovered[1:]))
        assert all(item["text"].startswith("one two") for item in recovered)
        assert original[-1]["text"] == "hm"
        assert paused and len(decoded) > len(checked)
        assert any(line.startswith("Read ") for line in messages)
    else:
        assert not paused and len(decoded) == len(checked)
