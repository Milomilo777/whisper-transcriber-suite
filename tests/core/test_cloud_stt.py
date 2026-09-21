"""Hermetic tests for the cloud Speech-to-Text backend (Gemini API).

NO network, NO API key, NO model. These exercise only the pure seams:
the request-payload builder, the response parser, the chunk-timeline
offsetter, the chunk planner, the HTTP-error classifier, and the
key-missing load() path.

The real end-to-end Google call is intentionally NOT tested here (there
is no API key in this environment); the owner live-tests that with their
own key.
"""
from __future__ import annotations

import pytest

from core.backends import cloud_stt as cs
from core.backends import get_backend


# ---------------------------------------------------------------- payload


def test_build_generate_request_file_ref_shape():
    url, body = cs.build_generate_request(
        model="gemini-3.5-flash",
        prompt="hello",
        file_uri="https://x/files/abc",
        file_mime="audio/flac",
    )
    assert url == (
        "https://generativelanguage.googleapis.com/v1beta/"
        "models/gemini-3.5-flash:generateContent"
    )
    # No API key leaks into the built URL — the caller appends it.
    assert "key=" not in url
    parts = body["contents"][0]["parts"]
    assert parts[0] == {"text": "hello"}
    assert parts[1] == {
        "file_data": {"mime_type": "audio/flac", "file_uri": "https://x/files/abc"}
    }
    assert body["generationConfig"]["temperature"] == 0.0


def test_build_generate_request_inline_shape():
    _url, body = cs.build_generate_request(
        model="m", prompt="p", inline_b64="QUJD", inline_mime="audio/flac",
    )
    parts = body["contents"][0]["parts"]
    assert parts[1] == {
        "inline_data": {"mime_type": "audio/flac", "data": "QUJD"}
    }


def test_build_generate_request_requires_exactly_one_source():
    with pytest.raises(ValueError):
        cs.build_generate_request(model="m", prompt="p")  # neither
    with pytest.raises(ValueError):
        cs.build_generate_request(
            model="m", prompt="p", file_uri="u", inline_b64="b"
        )  # both


def test_build_prompt_with_language_hint():
    p = cs.build_prompt("fa")
    assert "VERBATIM" in p
    assert "'fa'" in p


def test_build_prompt_without_language():
    p = cs.build_prompt(None)
    assert "VERBATIM" in p
    assert "spoken language is" not in p


# ---------------------------------------------------------------- parsing


def _canned_response(text: str) -> dict:
    return {
        "candidates": [
            {
                "content": {"parts": [{"text": text}]},
                "finishReason": "STOP",
            }
        ]
    }


def test_extract_text_from_response_happy():
    resp = _canned_response("[00:00:01.000 --> 00:00:02.500] hello")
    assert cs.extract_text_from_response(resp).startswith("[00:00:01")


def test_extract_text_from_response_multipart_concatenates():
    resp = {
        "candidates": [
            {"content": {"parts": [{"text": "a "}, {"text": "b"}]},
             "finishReason": "STOP"}
        ]
    }
    assert cs.extract_text_from_response(resp) == "a b"


def test_extract_text_error_object_surfaces_message():
    resp = {"error": {"message": "API key not valid"}}
    with pytest.raises(RuntimeError) as e:
        cs.extract_text_from_response(resp)
    assert "API key not valid" in str(e.value)


def test_extract_text_no_candidates_raises():
    with pytest.raises(RuntimeError):
        cs.extract_text_from_response({"candidates": []})


def test_extract_text_prompt_feedback_block_raises():
    resp = {"promptFeedback": {"blockReason": "SAFETY"}}
    with pytest.raises(RuntimeError) as e:
        cs.extract_text_from_response(resp)
    assert "SAFETY" in str(e.value)


def test_extract_text_empty_with_bad_finish_reason_raises():
    resp = {
        "candidates": [
            {"content": {"parts": [{"text": ""}]}, "finishReason": "MAX_TOKENS"}
        ]
    }
    with pytest.raises(RuntimeError) as e:
        cs.extract_text_from_response(resp)
    assert "MAX_TOKENS" in str(e.value)


def test_parse_transcript_timestamped_lines():
    text = (
        "[00:00:01.000 --> 00:00:02.500] hello world\n"
        "[00:00:02.500 --> 00:00:05.000] second line"
    )
    segs = cs.parse_transcript_to_segments(text)
    assert len(segs) == 2
    assert segs[0] == {"start": 1.0, "end": 2.5, "text": "hello world"}
    assert segs[1] == {"start": 2.5, "end": 5.0, "text": "second line"}


def test_parse_transcript_mm_ss_and_comma_decimal():
    text = "[01:02,250 --> 01:03,750] short clip"
    segs = cs.parse_transcript_to_segments(text)
    assert segs[0]["start"] == pytest.approx(62.25)
    assert segs[0]["end"] == pytest.approx(63.75)


def test_parse_transcript_continuation_line_appends():
    text = (
        "[00:00:00.000 --> 00:00:04.000] a long\n"
        "wrapped utterance"
    )
    segs = cs.parse_transcript_to_segments(text)
    assert len(segs) == 1
    assert segs[0]["text"] == "a long wrapped utterance"


def test_parse_transcript_strips_markdown_fence():
    text = "```\n[00:00:00.000 --> 00:00:01.000] hi\n```"
    segs = cs.parse_transcript_to_segments(text)
    assert len(segs) == 1
    assert segs[0]["text"] == "hi"


def test_parse_transcript_untimestamped_falls_back_to_single_segment():
    segs = cs.parse_transcript_to_segments("just some text no timestamps")
    assert len(segs) == 1
    assert segs[0]["start"] == 0.0
    assert segs[0]["text"] == "just some text no timestamps"


def test_parse_transcript_empty_is_empty():
    assert cs.parse_transcript_to_segments("   ") == []


def test_full_parse_pipeline_from_canned_response():
    """extract -> parse, end to end, on a realistic canned JSON."""
    text = "[00:00:00.000 --> 00:00:03.200] verbatim words here"
    resp = _canned_response(text)
    extracted = cs.extract_text_from_response(resp)
    segs = cs.parse_transcript_to_segments(extracted)
    assert segs == [{"start": 0.0, "end": 3.2, "text": "verbatim words here"}]


# ---------------------------------------------------------------- offset


def test_offset_segments_shifts_to_global_timeline():
    chunk_segs = [
        {"start": 0.0, "end": 2.0, "text": "a"},
        {"start": 2.0, "end": 4.0, "text": "b"},
    ]
    # Chunk N starts at 480 s on the global timeline.
    shifted = cs.offset_segments(chunk_segs, 480.0)
    assert shifted[0] == {"start": 480.0, "end": 482.0, "text": "a"}
    assert shifted[1] == {"start": 482.0, "end": 484.0, "text": "b"}
    # Input untouched (pure).
    assert chunk_segs[0]["start"] == 0.0


def test_offset_segments_shifts_word_timings_too():
    segs = [{
        "start": 0.0, "end": 1.0, "text": "hi",
        "words": [{"start": 0.0, "end": 0.5, "word": "hi"}],
    }]
    shifted = cs.offset_segments(segs, 10.0)
    assert shifted[0]["words"][0]["start"] == 10.0
    assert shifted[0]["words"][0]["end"] == 10.5


# ---------------------------------------------------------------- chunks


def test_plan_chunks_splits_evenly():
    chunks = cs.plan_chunks(1000.0, 480.0)
    assert chunks == [(0.0, 480.0), (480.0, 960.0), (960.0, 1000.0)]


def test_plan_chunks_single_when_short():
    assert cs.plan_chunks(120.0, 480.0) == [(0.0, 120.0)]


def test_plan_chunks_unknown_duration_returns_whole_file_marker():
    # 0.0 end means "to end of file" for the ffmpeg slicer.
    assert cs.plan_chunks(0.0, 480.0) == [(0.0, 0.0)]


def test_should_inline_threshold():
    assert cs._should_inline(1024) is True
    assert cs._should_inline(cs.INLINE_LIMIT_BYTES + 1) is False


# ---------------------------------------------------------------- flac probe


class _FakeResp:
    """Minimal context-manager stand-in for an http.client response."""

    def __init__(self, body: bytes = b"", headers: dict | None = None):
        self._body = body
        self.headers = headers or {}

    def __enter__(self) -> "_FakeResp":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def read(self, n: int = -1) -> bytes:
        return self._body


def _probe_result(monkeypatch, *, returncode=0, stdout="", raises=None):
    def fake_run(cmd, **kwargs):  # noqa: ANN001
        if raises is not None:
            raise raises
        import types as _t
        return _t.SimpleNamespace(returncode=returncode, stdout=stdout, stderr="")

    monkeypatch.setattr(cs.subprocess, "run", fake_run)


def test_flac_slice_has_audio_true_for_real_duration(monkeypatch):
    _probe_result(monkeypatch, stdout="55.000000\n")
    assert cs.flac_slice_has_audio("/x.flac") is True


def test_flac_slice_has_audio_false_for_na_empty_container(monkeypatch):
    """A past-EOF FLAC is a valid container with NO audio frames; ffprobe
    reports its duration as "N/A" (measured on a real ffmpeg-produced slice).
    """
    _probe_result(monkeypatch, stdout="N/A\n")
    assert cs.flac_slice_has_audio("/x.flac") is False


def test_flac_slice_has_audio_conservative_on_probe_failure(monkeypatch):
    """ffprobe failing (exit != 0, missing binary, timeout, or unexpected
    non-numeric output) must NOT be read as 'empty' — that would silently
    truncate a multi-chunk transcript."""
    _probe_result(monkeypatch, returncode=1, stdout="")
    assert cs.flac_slice_has_audio("/x.flac") is True

    _probe_result(monkeypatch, stdout="")
    assert cs.flac_slice_has_audio("/x.flac") is True

    _probe_result(monkeypatch, stdout="weird\n")
    assert cs.flac_slice_has_audio("/x.flac") is True

    _probe_result(monkeypatch, raises=FileNotFoundError("no ffprobe"))
    assert cs.flac_slice_has_audio("/x.flac") is True


def test_unknown_duration_stops_on_past_eof_slice_above_byte_threshold(
    monkeypatch, tmp_path
):
    """Regression: a past-EOF FLAC is a full ~8 KiB container (measured),
    ABOVE _EMPTY_FLAC_BYTES, so the byte-size test alone never fired and the
    bounded chunk plan was fired at Google in its entirety (up to 120 empty
    requests for Gemini). The duration probe must stop the run instead.
    """
    backend = cs.CloudSttBackend(
        config={"cloud_stt_api_key": "fake", "cloud_stt_model": "m"}
    )
    backend.load()
    backend._chunk_seconds = 480.0
    monkeypatch.setattr(
        "core.transcriber.get_duration", lambda _p: 0.0, raising=True
    )

    # Chunk 0 is real audio; chunk 1 is a REALISTIC past-EOF slice: a valid
    # ~8.3 KiB FLAC container with zero audio frames (> _EMPTY_FLAC_BYTES).
    sizes = [200_000, 8_286, 8_286]
    made: list[str] = []

    def fake_encode(audio_path, start, end):
        idx = len(made)
        p = tmp_path / f"chunk{idx}.flac"
        p.write_bytes(b"\x00" * sizes[idx])
        made.append(str(p))
        return str(p)

    monkeypatch.setattr(cs, "_encode_chunk_flac", fake_encode)
    monkeypatch.setattr(
        cs, "flac_slice_has_audio", lambda path: not path.endswith("chunk1.flac")
    )

    calls = {"n": 0}

    def fake_one_chunk(self, flac_path, prompt):
        calls["n"] += 1
        return "[00:00:00.000 --> 00:00:01.000] hi"

    monkeypatch.setattr(cs.CloudSttBackend, "_transcribe_one_chunk", fake_one_chunk)

    segs, _info = backend.transcribe_to_segments("/no/such.ts", duration=0.0)

    assert calls["n"] == 1  # only the real chunk was sent to Google
    assert len(segs) == 1
    assert segs[0]["start"] == 0.0


# ---------------------------------------------------------------- malformed


def test_post_json_non_json_body_raises_clear_error(monkeypatch):
    """A 200 with a non-JSON body (captive portal / proxy HTML) must surface
    a clear RuntimeError, not a raw json.JSONDecodeError."""
    monkeypatch.setattr(
        cs.urllib.request, "urlopen",
        lambda req, timeout=None: _FakeResp(b"<html>proxy login</html>"),
    )
    backend = cs.CloudSttBackend(config={"cloud_stt_api_key": "k"})
    backend.load()
    with pytest.raises(RuntimeError) as e:
        backend._post_json("https://x", {}, 10)
    assert "not valid JSON" in str(e.value)


def test_post_json_truncated_body_raises_clear_error(monkeypatch):
    """A connection closed mid-body (IncompleteRead) must surface a clear
    RuntimeError, not the raw http.client exception."""
    import http.client

    class _BrokenResp(_FakeResp):
        def read(self, n: int = -1) -> bytes:
            raise http.client.IncompleteRead(b"partial", 100)

    monkeypatch.setattr(
        cs.urllib.request, "urlopen",
        lambda req, timeout=None: _BrokenResp(),
    )
    backend = cs.CloudSttBackend(config={"cloud_stt_api_key": "k"})
    backend.load()
    with pytest.raises(RuntimeError) as e:
        backend._post_json("https://x", {}, 10)
    assert "complete response" in str(e.value)


def test_wait_for_active_non_json_body_raises_clear_error(monkeypatch):
    monkeypatch.setattr(
        cs.urllib.request, "urlopen",
        lambda req, timeout=None: _FakeResp(b"nope"),
    )
    backend = cs.CloudSttBackend(config={"cloud_stt_api_key": "k"})
    backend.load()
    with pytest.raises(RuntimeError) as e:
        backend._wait_for_active("files/abc")
    assert "not valid JSON" in str(e.value)


# ---------------------------------------------------------------- errors


def test_classify_http_error_bad_key():
    msg = cs.classify_http_error(403, '{"error":"denied"}')
    assert "Invalid Google API key" in msg


def test_classify_http_error_quota():
    msg = cs.classify_http_error(429, "rate limited")
    assert "quota" in msg.lower()


def test_classify_http_error_model_not_found():
    msg = cs.classify_http_error(404, "no such model")
    assert "renamed or retired" in msg


# ---------------------------------------------------------------- load()


def test_load_without_key_sets_clear_error():
    backend = cs.CloudSttBackend(config={"cloud_stt_api_key": ""})
    statuses: list[str] = []
    ok = backend.load(statuses.append)
    assert ok is False
    assert backend.is_ready() is False
    err = backend.get_error() or ""
    assert "No Google API key" in err
    assert any("key" in s.lower() for s in statuses)


def test_load_with_key_is_ready_no_network():
    backend = cs.CloudSttBackend(
        config={"cloud_stt_api_key": "fake-key", "cloud_stt_model": "m"}
    )
    ok = backend.load()
    assert ok is True
    assert backend.is_ready() is True
    assert backend.get_error() is None


def test_transcribe_without_key_raises():
    backend = cs.CloudSttBackend(config={"cloud_stt_api_key": ""})
    with pytest.raises(RuntimeError):
        backend.transcribe_to_segments("/tmp/whatever.wav", duration=1.0)


def test_ping_key_without_key_returns_false():
    backend = cs.CloudSttBackend(config={"cloud_stt_api_key": ""})
    backend.load()
    ok, msg = backend.ping_key()
    assert ok is False
    assert "No API key" in msg


# ---------------------------------------------------------------- factory


def test_get_backend_returns_cloud_stt():
    b = get_backend("cloud_stt")
    assert b.name == "cloud_stt"


def test_get_backend_unknown_still_falls_back_to_faster_whisper():
    # Stub faster_whisper so the fallback import doesn't need the wheel.
    import sys
    import types
    if "faster_whisper" not in sys.modules:
        fake = types.ModuleType("faster_whisper")
        fake.WhisperModel = object  # type: ignore[attr-defined]
        sys.modules["faster_whisper"] = fake
    b = get_backend("does_not_exist")
    assert b.name == "faster_whisper"
