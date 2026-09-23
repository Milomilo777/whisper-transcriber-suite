"""Hermetic tests for the REAL Google Cloud Speech-to-Text v2 backend.

NO network, NO service-account JSON, NO google libraries. These exercise
only the pure seams:

  * the service-account JSON reader (project_id extraction + clear errors),
  * the recognizer-path builder,
  * the RecognitionConfig builder (against a FAKE cloud_speech module),
  * the v2 response -> segments parser (canned duck-typed results, incl.
    word timings + speaker labels),
  * the chunk planner + timeline offsetter,
  * the monthly-usage accumulator (rolls over on a new month),
  * the error classifier,
  * load() with a missing / bad JSON path -> clear error.

The real end-to-end Google call is intentionally NOT tested here (there is
no service-account JSON in this environment); the owner live-tests that.
"""
from __future__ import annotations

import datetime as dt
import gc
import json
import threading
import types

import pytest

from core.backends import get_backend
from core.backends import google_cloud_stt as g


# ---------------------------------------------------------------- JSON / project_id


def _write_sa_json(tmp_path, **extra) -> str:
    data = {"type": "service_account", "project_id": "my-proj-123"}
    data.update(extra)
    p = tmp_path / "key.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return str(p)


def test_read_project_id_happy(tmp_path):
    path = _write_sa_json(tmp_path)
    assert g.read_project_id(path) == "my-proj-123"


def test_read_project_id_empty_path():
    with pytest.raises(RuntimeError) as e:
        g.read_project_id("")
    assert "service-account JSON" in str(e.value)


def test_read_project_id_missing_file(tmp_path):
    with pytest.raises(RuntimeError) as e:
        g.read_project_id(str(tmp_path / "nope.json"))
    assert "not found" in str(e.value)


def test_read_project_id_not_json(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("this is not json {{{", encoding="utf-8")
    with pytest.raises(RuntimeError) as e:
        g.read_project_id(str(p))
    assert "corrupt" in str(e.value) or "could not read" in str(e.value).lower()


def test_read_project_id_no_project_id(tmp_path):
    p = tmp_path / "noproj.json"
    p.write_text(json.dumps({"type": "service_account"}), encoding="utf-8")
    with pytest.raises(RuntimeError) as e:
        g.read_project_id(str(p))
    assert "project_id" in str(e.value)


# ---------------------------------------------------------------- recognizer path


def test_recognizer_path_global():
    assert g.recognizer_path("p1", "global") == (
        "projects/p1/locations/global/recognizers/_"
    )


def test_recognizer_path_uses_default_location():
    # No explicit location -> the shipped regional default (chirp_2 lives
    # there, not in "global").
    assert g.recognizer_path("p1") == (
        f"projects/p1/locations/{g.DEFAULT_LOCATION}/recognizers/_"
    )


def test_recognizer_path_regional():
    assert g.recognizer_path("p1", "europe-west4") == (
        "projects/p1/locations/europe-west4/recognizers/_"
    )


# ---------------------------------------------------------------- chunk planner


def test_plan_chunks_splits_under_one_minute():
    chunks = g.plan_chunks(130.0, 55.0)
    assert chunks == [(0.0, 55.0), (55.0, 110.0), (110.0, 130.0)]


def test_plan_chunks_single_when_short():
    assert g.plan_chunks(40.0, 55.0) == [(0.0, 40.0)]


def test_plan_chunks_unknown_duration_chunks_under_inline_cap():
    """An unknown duration must STILL be sliced into inline-sized windows,
    not collapsed to one whole-file request that blows the ~1 min inline cap.
    """
    chunks = g.plan_chunks(0.0, 55.0)
    # Many bounded windows, each exactly chunk_seconds long, starting at 0.
    assert len(chunks) == g.MAX_UNKNOWN_DURATION_CHUNKS
    assert chunks[0] == (0.0, 55.0)
    assert chunks[1] == (55.0, 110.0)
    for start, end in chunks:
        assert round(end - start, 3) == 55.0  # each under the 1-min cap


def test_plan_chunks_unknown_duration_whole_file_when_disabled():
    """Batch mode keeps the single whole-file (0,0) marker via the flag."""
    assert g.plan_chunks(0.0, 55.0, chunk_when_unknown=False) == [(0.0, 0.0)]


def test_run_standard_unknown_duration_stops_on_past_eof_slice(
    monkeypatch, tmp_path
):
    """Regression: a past-EOF FLAC slice is a full ~8 KiB container (measured
    with this module's own encode command), ABOVE _EMPTY_FLAC_BYTES, so the
    byte-size test alone never fired and the bounded chunk plan (1200 windows)
    was fired at Google in its entirety. The shared ffprobe probe
    (flac_slice_has_audio) must stop the run after the last real chunk.
    """
    backend = g.GoogleCloudSttBackend(config={})
    backend._project_id = "p1"
    backend._chunk_seconds = 55.0
    monkeypatch.setattr(
        "core.transcriber.get_duration", lambda _p: 0.0, raising=True
    )

    # Chunk 0 is real audio; chunk 1 is a REALISTIC past-EOF slice.
    sizes = [200_000, 8_286, 8_286]
    made: list[str] = []

    def fake_encode(audio_path, start, end):
        idx = len(made)
        p = tmp_path / f"g{idx}.flac"
        p.write_bytes(b"\x00" * sizes[idx])
        made.append(str(p))
        return str(p)

    monkeypatch.setattr(g, "_encode_chunk_flac", fake_encode)
    monkeypatch.setattr(
        g, "probe_flac_slice", lambda path: not path.endswith("g1.flac")
    )

    calls = {"n": 0}

    def fake_recognize(request=None, timeout=None):
        calls["n"] += 1
        return types.SimpleNamespace(results=[])

    monkeypatch.setattr(
        backend, "_build_client",
        lambda: types.SimpleNamespace(recognize=fake_recognize),
    )
    monkeypatch.setattr(backend, "_cloud_speech_types", lambda: _FakeCloudSpeech)

    segs = backend._run_standard(
        "/no/such.ts", "auto", False, 0.0, None, None, None, None
    )

    assert calls["n"] == 1  # only the real chunk was sent to Google
    assert segs == []
    # Only the one window actually sent is billed.
    assert backend._last_billable_seconds == pytest.approx(55.0)
    assert backend._last_was_cancelled is False


# ---------------------------------------------------------------- offset


def test_offset_segments_shifts_to_global_timeline():
    chunk_segs = [
        {"start": 0.0, "end": 2.0, "text": "a"},
        {"start": 2.0, "end": 4.0, "text": "b"},
    ]
    shifted = g.offset_segments(chunk_segs, 55.0)
    assert shifted[0] == {"start": 55.0, "end": 57.0, "text": "a"}
    assert shifted[1] == {"start": 57.0, "end": 59.0, "text": "b"}
    # Pure — input untouched.
    assert chunk_segs[0]["start"] == 0.0


def test_offset_segments_shifts_word_timings_too():
    segs = [{
        "start": 0.0, "end": 1.0, "text": "hi",
        "words": [{"start": 0.0, "end": 0.5, "word": "hi"}],
    }]
    shifted = g.offset_segments(segs, 10.0)
    assert shifted[0]["words"][0]["start"] == 10.0
    assert shifted[0]["words"][0]["end"] == 10.5


def test_offset_segments_zero_is_copy():
    segs = [{"start": 1.0, "end": 2.0, "text": "x"}]
    out = g.offset_segments(segs, 0.0)
    assert out == segs
    assert out is not segs  # still a fresh copy


# ---------------------------------------------------------------- offset->seconds


def test_offset_to_seconds_timedelta():
    assert g._offset_to_seconds(dt.timedelta(seconds=2, milliseconds=500)) == 2.5


def test_offset_to_seconds_raw_duration_like():
    dur = types.SimpleNamespace(seconds=3, nanos=500_000_000)
    assert g._offset_to_seconds(dur) == pytest.approx(3.5)


def test_offset_to_seconds_number_and_none():
    assert g._offset_to_seconds(4.0) == 4.0
    assert g._offset_to_seconds(None) == 0.0


# ---------------------------------------------------------------- response parser


def _word(word, start, end, *, conf=0.9, speaker=""):
    return types.SimpleNamespace(
        word=word,
        start_offset=dt.timedelta(seconds=start),
        end_offset=dt.timedelta(seconds=end),
        confidence=conf,
        speaker_label=speaker,
    )


def _result(transcript, words=(), result_end=0.0):
    alt = types.SimpleNamespace(transcript=transcript, words=list(words))
    return types.SimpleNamespace(
        alternatives=[alt],
        result_end_offset=dt.timedelta(seconds=result_end),
    )


def test_parse_results_text_only_uses_result_end_offset():
    results = [
        _result("hello there", result_end=2.0),
        _result("second part", result_end=5.0),
    ]
    segs = g.parse_recognize_results(results, want_words=False)
    assert len(segs) == 2
    assert segs[0]["text"] == "hello there"
    assert segs[0]["start"] == 0.0
    assert segs[0]["end"] == 2.0
    # Second segment advances from the previous end.
    assert segs[1]["start"] == 2.0
    assert segs[1]["end"] == 5.0
    assert "words" not in segs[0]


def test_parse_results_with_word_timings():
    words = [_word("hello", 0.5, 1.0), _word("world", 1.0, 1.8)]
    results = [_result("hello world", words=words)]
    segs = g.parse_recognize_results(results, want_words=True)
    assert len(segs) == 1
    seg = segs[0]
    assert seg["text"] == "hello world"
    assert seg["start"] == pytest.approx(0.5)
    assert seg["end"] == pytest.approx(1.8)
    assert len(seg["words"]) == 2
    assert seg["words"][0] == {
        "start": 0.5, "end": 1.0, "word": "hello", "probability": 0.9,
    }


def test_parse_results_diarization_speaker_label():
    words = [
        _word("hi", 0.0, 0.4, speaker="1"),
        _word("there", 0.4, 0.9, speaker="1"),
    ]
    results = [_result("hi there", words=words)]
    segs = g.parse_recognize_results(results, want_words=True, want_speaker=True)
    assert segs[0]["speaker"] == "1"
    assert segs[0]["words"][0]["speaker"] == "1"


def test_parse_results_skips_empty_alternatives():
    empty = types.SimpleNamespace(alternatives=[])
    results = [empty, _result("kept", result_end=1.0)]
    segs = g.parse_recognize_results(results)
    assert len(segs) == 1
    assert segs[0]["text"] == "kept"


def test_parse_results_empty_input():
    assert g.parse_recognize_results(None) == []
    assert g.parse_recognize_results([]) == []


# ---------------------------------------------------------------- config builder


class _FakeCloudSpeech:
    """A stand-in for google.cloud.speech_v2.types.cloud_speech.

    Each "class" just records the kwargs it was built with so the test can
    assert the exact field shapes without importing the google libs.
    """

    class AutoDetectDecodingConfig:
        def __init__(self, **kw):
            self.kw = kw

    class SpeakerDiarizationConfig:
        def __init__(self, **kw):
            self.kw = kw

    class RecognitionFeatures:
        def __init__(self, **kw):
            self.__dict__.update(kw)
            self.kw = kw

    class RecognitionConfig:
        def __init__(self, **kw):
            self.__dict__.update(kw)
            self.kw = kw

    class RecognizeRequest:
        def __init__(self, **kw):
            self.kw = kw


def test_build_recognition_config_words_no_diarization():
    cfg = g.build_recognition_config(
        _FakeCloudSpeech,
        language_code="en-US",
        model="long",
        want_words=True,
        diarization=False,
    )
    assert cfg.language_codes == ["en-US"]
    assert cfg.model == "long"
    assert cfg.features.enable_word_time_offsets is True
    assert cfg.features.enable_word_confidence is True
    assert "diarization_config" not in cfg.features.kw
    assert isinstance(cfg.auto_decoding_config, _FakeCloudSpeech.AutoDetectDecodingConfig)


def test_build_recognition_config_diarization_forces_word_offsets():
    cfg = g.build_recognition_config(
        _FakeCloudSpeech,
        language_code="auto",
        model="long",
        want_words=False,
        diarization=True,
        min_speakers=2,
        max_speakers=6,
    )
    # Diarization must force word offsets on (labels ride the word stream).
    assert cfg.features.enable_word_time_offsets is True
    diar = cfg.features.kw["diarization_config"]
    assert diar.kw == {"min_speaker_count": 2, "max_speaker_count": 6}


def test_build_recognition_config_diarization_zero_speakers_defaults():
    """The UI has no min/max inputs, so both arrive 0 when diarization is on.

    A SpeakerDiarizationConfig() with no counts is rejected by Google v2, so
    the builder must default to a sane 1..6 range instead of omitting them.
    """
    cfg = g.build_recognition_config(
        _FakeCloudSpeech,
        language_code="auto",
        model="long",
        want_words=False,
        diarization=True,
        min_speakers=0,
        max_speakers=0,
    )
    diar = cfg.features.kw["diarization_config"]
    assert diar.kw == {"min_speaker_count": 1, "max_speaker_count": 6}


def test_build_recognition_config_diarization_min_only_defaults_max():
    """A positive min with max=0 still gets a valid (>= min) max."""
    cfg = g.build_recognition_config(
        _FakeCloudSpeech,
        language_code="auto",
        model="long",
        want_words=False,
        diarization=True,
        min_speakers=3,
        max_speakers=0,
    )
    diar = cfg.features.kw["diarization_config"]
    assert diar.kw["min_speaker_count"] == 3
    assert diar.kw["max_speaker_count"] >= 3


# ---------------------------------------------------------------- language norm


def test_normalize_language_code_auto_for_empty():
    assert g.normalize_language_code(None) == "auto"
    assert g.normalize_language_code("") == "auto"
    assert g.normalize_language_code("   ") == "auto"
    # The literal "auto" passes straight through (case-insensitive).
    assert g.normalize_language_code("auto") == "auto"
    assert g.normalize_language_code("AUTO") == "auto"


def test_normalize_language_code_bare_iso_maps_to_bcp47():
    # The v2 API rejects bare ISO codes — they must become full BCP-47 tags.
    assert g.normalize_language_code("en") == "en-US"
    assert g.normalize_language_code("EN") == "en-US"
    assert g.normalize_language_code("fa") == "fa-IR"
    assert g.normalize_language_code("ko") == "ko-KR"
    assert g.normalize_language_code("es") == "es-ES"
    assert g.normalize_language_code("pt") == "pt-BR"
    assert g.normalize_language_code("zh") == "cmn-Hans-CN"


def test_normalize_language_code_already_bcp47_canonical_case():
    # Already-hyphenated codes pass through, re-cased to canonical form.
    assert g.normalize_language_code("en-US") == "en-US"
    assert g.normalize_language_code("en-us") == "en-US"
    assert g.normalize_language_code("PT-br") == "pt-BR"
    # Script subtag (4 letters) is Title-cased, region upper-cased.
    assert g.normalize_language_code("cmn-hans-cn") == "cmn-Hans-CN"


def test_normalize_language_code_unknown_passthrough():
    # An unknown bare code is passed through (lower-cased) so Google can
    # surface a clear, classify-able error rather than us guessing wrong.
    assert g.normalize_language_code("xx") == "xx"
    assert g.normalize_language_code("ZZ") == "zz"


# ---------------------------------------------------------------- phrase grouping


def _w(word, start, end, *, speaker="", prob=0.9):
    d = {"word": word, "start": start, "end": end, "probability": prob}
    if speaker:
        d["speaker"] = speaker
    return d


def test_group_words_gap_split():
    # A > 0.6s silent gap before "world" starts a new phrase.
    words = [
        _w("hello", 0.0, 0.4),
        _w("there", 0.4, 0.8),
        _w("world", 2.0, 2.4),  # gap 0.8 - 2.0 = 1.2s > 0.6
    ]
    segs = g.group_words_into_phrases(words)
    assert len(segs) == 2
    assert segs[0]["text"] == "hello there"
    assert segs[0]["start"] == 0.0
    assert segs[0]["end"] == 0.8
    assert segs[1]["text"] == "world"
    assert segs[1]["start"] == 2.0


def test_group_words_no_split_small_gap():
    # Gaps <= 0.6s stay in one phrase.
    words = [_w("a", 0.0, 0.4), _w("b", 0.9, 1.2), _w("c", 1.5, 1.8)]
    segs = g.group_words_into_phrases(words)
    assert len(segs) == 1
    assert segs[0]["text"] == "a b c"


def test_group_words_max_length_split():
    # No gaps, but the running phrase passes ~12s -> split.
    words = [_w(f"w{i}", float(i), float(i) + 1.0) for i in range(20)]
    segs = g.group_words_into_phrases(words, max_gap=100.0, max_duration=12.0)
    assert len(segs) >= 2
    for seg in segs:
        assert (seg["end"] - seg["start"]) <= 12.0 + 1.0  # last word can spill


def test_group_words_punctuation_split():
    # A sentence-ending word forces the NEXT word into a new phrase.
    words = [
        _w("Hello", 0.0, 0.4),
        _w("world.", 0.4, 0.8),
        _w("Next", 0.9, 1.2),
        _w("one", 1.2, 1.5),
    ]
    segs = g.group_words_into_phrases(words)
    assert len(segs) == 2
    assert segs[0]["text"] == "Hello world."
    assert segs[1]["text"] == "Next one"


def test_group_words_drops_empty_and_zero_length():
    # The live "30->30 et" artifact: an empty token AND a zero-length word.
    words = [
        _w("real", 0.0, 0.5),
        _w("", 0.5, 0.6),       # empty token -> dropped before grouping
        _w("et", 30.0, 30.0),   # zero-length -> phrase has zero duration
    ]
    segs = g.group_words_into_phrases(words)
    # "et" starts a new phrase (gap 0.5 -> 30.0) but is zero-length -> dropped.
    assert len(segs) == 1
    assert segs[0]["text"] == "real"


def test_group_words_speaker_grouping():
    # A speaker change starts a new phrase; the label rides onto the segment.
    words = [
        _w("hi", 0.0, 0.4, speaker="1"),
        _w("there", 0.4, 0.8, speaker="1"),
        _w("hello", 0.9, 1.3, speaker="2"),
    ]
    segs = g.group_words_into_phrases(words, want_speaker=True)
    assert len(segs) == 2
    assert segs[0]["speaker"] == "1"
    assert segs[0]["text"] == "hi there"
    assert segs[1]["speaker"] == "2"
    assert segs[1]["text"] == "hello"


def test_group_words_want_words_attaches_word_list():
    words = [_w("hello", 0.0, 0.4), _w("world", 0.4, 0.8)]
    segs = g.group_words_into_phrases(words, want_words=True)
    assert len(segs) == 1
    assert [w["word"] for w in segs[0]["words"]] == ["hello", "world"]
    # Default (want_words False) carries no per-word list.
    assert "words" not in g.group_words_into_phrases(words)[0]


def test_group_words_empty_input():
    assert g.group_words_into_phrases([]) == []
    assert g.group_words_into_phrases([_w("", 0.0, 0.0)]) == []


def test_parse_results_resegments_one_big_result_into_phrases():
    # The live failure mode: ONE result holding the whole transcript as words,
    # which must be re-segmented into multiple readable phrases (not 1 block).
    words = [
        _word("President", 0.0, 0.44),
        _word("Trump", 0.44, 0.88),
        _word("said.", 0.88, 1.3),       # sentence end -> split after
        _word("Later", 3.0, 3.4),        # also a 1.7s gap -> split
        _word("today", 3.4, 3.8),
    ]
    results = [_result("President Trump said. Later today", words=words)]
    segs = g.parse_recognize_results(results, want_words=True)
    assert len(segs) == 2
    assert segs[0]["text"] == "President Trump said."
    assert segs[0]["start"] == pytest.approx(0.0)
    assert segs[1]["text"] == "Later today"
    assert segs[1]["start"] == pytest.approx(3.0)


def test_parse_results_no_words_fallback_preserved():
    # A result with no words still yields one segment from result_end_offset.
    results = [_result("plain transcript", result_end=3.0)]
    segs = g.parse_recognize_results(results, want_words=False)
    assert len(segs) == 1
    assert segs[0]["text"] == "plain transcript"
    assert segs[0]["start"] == 0.0
    assert segs[0]["end"] == 3.0


def test_parse_results_mixed_words_then_textonly_keeps_order():
    # Words result re-segmented, then a text-only result appended after it.
    words = [_word("hello", 0.0, 0.4), _word("world", 0.4, 0.8)]
    results = [
        _result("hello world", words=words),
        _result("tail text", result_end=5.0),
    ]
    segs = g.parse_recognize_results(results, want_words=False)
    assert [s["text"] for s in segs] == ["hello world", "tail text"]
    # The text-only fallback advances from the word phrase's end.
    assert segs[1]["start"] == pytest.approx(0.8)
    assert segs[1]["end"] == pytest.approx(5.0)


# ---------------------------------------------------------------- usage accumulator


def test_accumulate_minutes_same_month_adds():
    now = dt.datetime(2026, 6, 6, tzinfo=dt.timezone.utc)
    total, marker = g.accumulate_minutes(10.0, "2026-06", 5.0, now=now)
    assert total == 15.0
    assert marker == "2026-06"


def test_accumulate_minutes_new_month_resets():
    now = dt.datetime(2026, 7, 1, tzinfo=dt.timezone.utc)
    total, marker = g.accumulate_minutes(58.0, "2026-06", 3.0, now=now)
    assert total == 3.0  # reset to just the new run
    assert marker == "2026-07"


def test_accumulate_minutes_empty_marker_starts_fresh():
    now = dt.datetime(2026, 6, 6, tzinfo=dt.timezone.utc)
    total, marker = g.accumulate_minutes(0.0, "", 2.0, now=now)
    assert total == 2.0
    assert marker == "2026-06"


def test_month_marker_format():
    assert g.month_marker(dt.datetime(2026, 1, 9)) == "2026-01"
    assert g.month_marker(dt.datetime(2026, 12, 31)) == "2026-12"


# -------------------------------------------------- usage/cost display helpers


def test_effective_minutes_same_month_returns_stored():
    assert g.effective_minutes_this_month(12.5, "2026-06", "2026-06") == 12.5


def test_effective_minutes_stale_month_resets_to_zero():
    # Stored month is older than now -> the local counter has rolled over.
    assert g.effective_minutes_this_month(58.0, "2026-05", "2026-06") == 0.0


def test_effective_minutes_empty_marker_is_zero():
    assert g.effective_minutes_this_month(9.0, "", "2026-06") == 0.0


def test_effective_minutes_clamps_negative():
    assert g.effective_minutes_this_month(-3.0, "2026-06", "2026-06") == 0.0


def test_estimate_cost_standard_rate():
    # 100 minutes * $0.016/min = $1.60.
    assert g.estimate_cost(100.0, batch=False) == pytest.approx(1.60)


def test_estimate_cost_batch_rate_is_cheaper():
    # 100 minutes * $0.004/min = $0.40 (~75% cheaper than standard).
    assert g.estimate_cost(100.0, batch=True) == pytest.approx(0.40)


def test_estimate_cost_clamps_negative():
    assert g.estimate_cost(-10.0, batch=False) == 0.0


def test_format_usage_current_month_shows_minutes_and_cost():
    s = g.format_usage(
        minutes_used=12.5,
        month_stored="2026-06",
        month_now="2026-06",
        cap=60,
        batch=False,
    )
    assert "12.5 / 60 free minutes" in s
    # 12.5 min * $0.016 = $0.20.
    assert "$0.20" in s
    assert "$300 credit" in s
    assert "standard rate" in s


def test_format_usage_stale_month_shows_zero():
    s = g.format_usage(
        minutes_used=58.0,
        month_stored="2026-05",
        month_now="2026-06",
        cap=60,
        batch=False,
    )
    # Monthly reset — effective minutes are 0 and cost is $0.00.
    assert "0.0 / 60 free minutes" in s
    assert "$0.00" in s


def test_format_usage_batch_rate_label_and_cheaper_cost():
    s = g.format_usage(
        minutes_used=100.0,
        month_stored="2026-06",
        month_now="2026-06",
        cap=60,
        batch=True,
    )
    assert "batch rate" in s
    # 100 min * $0.004 = $0.40 (vs $1.60 standard).
    assert "$0.40" in s


def test_format_usage_invalid_cap_falls_back_to_60():
    s = g.format_usage(
        minutes_used=0.0,
        month_stored="2026-06",
        month_now="2026-06",
        cap=0,
        batch=False,
    )
    assert "/ 60 free minutes" in s


# ---------------------------------------------------------------- error classifier


def test_classify_error_permission_denied():
    class PermissionDenied(Exception):
        pass
    msg = g.classify_google_error(
        PermissionDenied("Cloud Speech-to-Text API has not been used")
    )
    assert "Enable the Speech-to-Text API" in msg


def test_classify_error_unauthenticated():
    class Unauthenticated(Exception):
        pass
    msg = g.classify_google_error(Unauthenticated("invalid JWT signature"))
    assert "credentials" in msg.lower()


def test_classify_error_quota():
    class ResourceExhausted(Exception):
        pass
    msg = g.classify_google_error(ResourceExhausted("Quota exceeded"))
    assert "quota" in msg.lower()


def test_classify_error_standalone_429_is_quota():
    """A standalone 429 status token reads as a rate limit."""
    msg = g.classify_google_error(Exception("HTTP 429: Too Many Requests"))
    assert "quota / rate limit" in msg.lower()


def test_classify_error_embedded_429_is_not_quota():
    """Digits 429 inside a larger number/filename must NOT read as quota."""
    msg = g.classify_google_error(ValueError("failed to process clip_4290.mp4"))
    assert "Google Cloud transcription failed" in msg
    assert "rate limit" not in msg.lower()


def test_classify_error_invalid_argument_model():
    class InvalidArgument(Exception):
        pass
    msg = g.classify_google_error(InvalidArgument("Unsupported model: bogus"))
    assert "model" in msg.lower()


def test_classify_error_offline():
    class ServiceUnavailable(Exception):
        pass
    msg = g.classify_google_error(ServiceUnavailable("failed to connect"))
    assert "reach Google" in msg


def test_classify_error_generic_fallback():
    msg = g.classify_google_error(ValueError("something weird"))
    assert "Google Cloud transcription failed" in msg


# ---------------------------------------------------------------- minutes helper


def test_minutes_for_uses_known_duration_without_probe():
    # 90 s known duration -> 1.5 min, no ffprobe call.
    assert g._minutes_for("/does/not/exist.wav", 90.0) == pytest.approx(1.5)


# ---------------------------------------------------------------- load()


def test_load_missing_credentials_clear_error(monkeypatch):
    # Pretend the google lib IS importable so load() reaches the JSON check.
    monkeypatch.setattr(g, "runtime_available", lambda: True)
    # Neutralise any build-bundled key so the "no credentials at all" path is
    # exercised (a dev/build tree may carry creds/gcloud_stt.json).
    monkeypatch.setattr(g, "bundled_credentials_path", lambda: "")
    backend = g.GoogleCloudSttBackend(config={"gcloud_stt_credentials_json": ""})
    statuses: list[str] = []
    ok = backend.load(statuses.append)
    assert ok is False
    assert backend.is_ready() is False
    err = backend.get_error() or ""
    assert "service-account JSON" in err
    assert statuses and "JSON" in statuses[-1]


def test_load_bad_json_path_clear_error(monkeypatch, tmp_path):
    monkeypatch.setattr(g, "runtime_available", lambda: True)
    backend = g.GoogleCloudSttBackend(
        config={"gcloud_stt_credentials_json": str(tmp_path / "missing.json")}
    )
    ok = backend.load()
    assert ok is False
    assert "not found" in (backend.get_error() or "")


def test_load_installs_google_lib_on_first_use(monkeypatch):
    """When the google lib is missing, load() installs it on demand (the
    worker path, not only the Advanced 'Test connection' path) instead of just
    erroring — otherwise a direct Transcribe on a fresh machine fails."""
    monkeypatch.setattr(g, "bundled_credentials_path", lambda: "")
    state = {"avail": False, "install": 0, "force": None}
    monkeypatch.setattr(g, "runtime_available", lambda: state["avail"])

    import core.optional_deps as od

    # Fresh-machine case: find_spec also reports nothing present, so the
    # repair path must NOT be taken (force=False).
    monkeypatch.setattr(od, "is_available", lambda feature: False)

    def fake_install(feature, log_cb=None, cancel_event=None, timeout=None, force=False):
        assert feature == "google_cloud_stt"
        state["install"] += 1
        state["force"] = force
        state["avail"] = True  # pretend pip succeeded
        return True

    monkeypatch.setattr(od, "install", fake_install)
    monkeypatch.setattr(od, "activate", lambda: None)

    backend = g.GoogleCloudSttBackend(config={"gcloud_stt_credentials_json": ""})
    ok = backend.load()
    assert state["install"] == 1  # install attempted on first use
    assert state["force"] is False  # fresh case: nothing to repair
    # No creds were configured, so it can't finish loading, but it DID get
    # past the runtime gate (proving the auto-install + re-check ran).
    assert ok is False
    assert "service-account JSON" in (backend.get_error() or "")


def test_load_repairs_broken_cache_with_force_install(monkeypatch):
    """find_spec sees a present-but-broken cache (e.g. a grpcio .pyd built
    for another Python) while the real import in runtime_available() fails.
    load() must detect that and pass force=True so optional_deps.install()
    doesn't short-circuit on is_available() and actually repairs the cache."""
    monkeypatch.setattr(g, "bundled_credentials_path", lambda: "")
    state = {"avail": False, "install": 0, "force": None}
    monkeypatch.setattr(g, "runtime_available", lambda: state["avail"])

    import core.optional_deps as od

    # Broken-cache case: find_spec reports it present even though the real
    # import fails (runtime_available() is False).
    monkeypatch.setattr(od, "is_available", lambda feature: True)

    def fake_install(feature, log_cb=None, cancel_event=None, timeout=None, force=False):
        assert feature == "google_cloud_stt"
        state["install"] += 1
        state["force"] = force
        state["avail"] = True  # pretend the forced reinstall fixed it
        return True

    monkeypatch.setattr(od, "install", fake_install)
    monkeypatch.setattr(od, "activate", lambda: None)

    backend = g.GoogleCloudSttBackend(config={"gcloud_stt_credentials_json": ""})
    ok = backend.load()
    assert state["install"] == 1
    assert state["force"] is True  # broken cache -> force a clean reinstall
    assert ok is False
    assert "service-account JSON" in (backend.get_error() or "")


def test_load_lib_missing_clear_error(monkeypatch):
    # Lib missing AND the on-demand install can't run (e.g. offline): degrade
    # to a clear, actionable error instead of a raw failure.
    monkeypatch.setattr(g, "bundled_credentials_path", lambda: "")
    monkeypatch.setattr(g, "runtime_available", lambda: False)
    import core.optional_deps as od
    monkeypatch.setattr(od, "install", lambda *a, **k: False)
    monkeypatch.setattr(od, "activate", lambda: None)
    backend = g.GoogleCloudSttBackend(config={"gcloud_stt_credentials_json": ""})
    ok = backend.load()
    assert ok is False
    assert "could not be installed" in (backend.get_error() or "").lower()


def test_load_ok_with_valid_json(monkeypatch, tmp_path):
    monkeypatch.setattr(g, "runtime_available", lambda: True)
    path = _write_sa_json(tmp_path)
    backend = g.GoogleCloudSttBackend(
        config={"gcloud_stt_credentials_json": path, "gcloud_stt_model": "long"}
    )
    ok = backend.load()
    assert ok is True
    assert backend.is_ready() is True
    assert backend.get_error() is None


def test_load_batch_without_bucket_refused(monkeypatch, tmp_path):
    monkeypatch.setattr(g, "runtime_available", lambda: True)
    path = _write_sa_json(tmp_path)
    backend = g.GoogleCloudSttBackend(config={
        "gcloud_stt_credentials_json": path,
        "gcloud_stt_batch_mode": True,
        "gcloud_stt_bucket": "",
    })
    ok = backend.load()
    assert ok is False
    assert "bucket" in (backend.get_error() or "").lower()


def test_transcribe_without_load_raises(monkeypatch):
    monkeypatch.setattr(g, "runtime_available", lambda: False)
    backend = g.GoogleCloudSttBackend(config={"gcloud_stt_credentials_json": ""})
    with pytest.raises(RuntimeError):
        backend.transcribe_to_segments("/tmp/whatever.wav", duration=1.0)


# ---------------------------------------------------------------- factory


def test_get_backend_returns_google_cloud_stt():
    b = get_backend("google_cloud_stt")
    assert b.name == "google_cloud_stt"


def test_get_backend_keeps_gemini_cloud_stt_separate():
    b = get_backend("cloud_stt")
    assert b.name == "cloud_stt"


# ---------------------------------------------------------------- batch parse


def test_parse_batch_response_inline_by_uri():
    backend = g.GoogleCloudSttBackend(config={})
    uri = "gs://bucket/whisper-project/123-audio.flac"
    transcript = types.SimpleNamespace(
        results=[_result("batch words here", result_end=4.0)]
    )
    file_result = types.SimpleNamespace(transcript=transcript)
    response = types.SimpleNamespace(results={uri: file_result})
    segs = backend._parse_batch_response(response, uri, want_words=False)
    assert len(segs) == 1
    assert segs[0]["text"] == "batch words here"


def test_parse_batch_response_falls_back_to_single_value():
    backend = g.GoogleCloudSttBackend(config={})
    transcript = types.SimpleNamespace(
        results=[_result("only result", result_end=2.0)]
    )
    file_result = types.SimpleNamespace(transcript=transcript)
    # URI key doesn't match -> single-value fallback.
    response = types.SimpleNamespace(results={"gs://other/x": file_result})
    segs = backend._parse_batch_response(
        response, "gs://bucket/mine.flac", want_words=False
    )
    assert segs[0]["text"] == "only result"


def test_parse_batch_response_no_results_raises():
    backend = g.GoogleCloudSttBackend(config={})
    response = types.SimpleNamespace(results={})
    with pytest.raises(RuntimeError) as e:
        backend._parse_batch_response(response, "gs://b/x.flac", want_words=False)
    assert "no batch results" in str(e.value).lower()


# ------------------------------------------------------- availability hardening
#
# Regression coverage for the 2026-08-15 crash: a Windows fatal exception
# (STATUS_BREAKPOINT) inside proto-plus's message-class creation, when a GC
# pass landed mid-import of ``google.cloud.speech_v2``. These run the REAL
# ``runtime_available``/``storage_available`` bodies (no monkeypatch), which
# is safe and hermetic either way: whether or not the real google-cloud
# package is installed, the ``ImportError`` path and the success path both
# go through the same try/finally, so the GC-state assertion holds in both
# environments without needing the package to be present.


def test_runtime_available_restores_gc_state(monkeypatch):
    """GC must end up exactly as it started, regardless of import outcome."""
    for was_enabled in (True, False):
        if was_enabled:
            gc.enable()
        else:
            gc.disable()
        try:
            g.runtime_available()
            assert gc.isenabled() is was_enabled
        finally:
            gc.enable()  # never leave GC off for the rest of the suite


def test_storage_available_restores_gc_state(monkeypatch):
    for was_enabled in (True, False):
        if was_enabled:
            gc.enable()
        else:
            gc.disable()
        try:
            g.storage_available()
            assert gc.isenabled() is was_enabled
        finally:
            gc.enable()


def test_runtime_available_disables_gc_during_the_import(monkeypatch):
    """The import itself must run with GC off, not just before/after it."""
    seen: dict[str, bool] = {}

    real_import = __import__

    def spying_import(name, *a, **kw):
        if name == "google.cloud.speech_v2":
            seen["gc_enabled_during_import"] = gc.isenabled()
        return real_import(name, *a, **kw)

    gc.enable()
    monkeypatch.setattr("builtins.__import__", spying_import)
    try:
        g.runtime_available()
    finally:
        gc.enable()
    assert seen.get("gc_enabled_during_import") is False


def test_runtime_available_serializes_concurrent_calls():
    """A concurrent caller must block on the shared lock, not race through.

    Doesn't reproduce the native crash itself (inherently timing-dependent,
    not something a unit test should try to pin down) — proves the
    serialization contract the fix relies on: only one caller is ever
    inside the import step at a time.
    """
    from core._gc_import_guard import _lock as guard_lock

    acquired = guard_lock.acquire(timeout=1.0)
    assert acquired, "test setup: could not acquire the lock"
    result: dict[str, bool] = {}

    def call():
        result["done"] = g.runtime_available()

    t = threading.Thread(target=call, daemon=True)
    t.start()
    t.join(timeout=0.3)
    try:
        assert t.is_alive(), "runtime_available() did not block on the lock"
    finally:
        guard_lock.release()
    t.join(timeout=3.0)
    assert not t.is_alive(), "runtime_available() never returned after unlock"
    assert "done" in result
