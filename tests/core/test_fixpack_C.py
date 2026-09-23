"""Hermetic regression tests for fix-pack C (cloud STT backends).

NO network, NO API key / service-account JSON, NO google libraries, NO real
ffmpeg / model. Each test pins a CONFIRMED bug that fix-pack C resolves in
``core/backends/cloud_stt.py`` (Gemini API) and
``core/backends/google_cloud_stt.py`` (Google Cloud STT v2):

  C1 — per-chunk diarization labels collide across chunks in STANDARD mode;
  C2 — the Gemini inline base64 threshold exceeded the 20 MB inline cap after
       the ~4/3 base64 expansion;
  C3 — an unknown / unreadable duration collapsed the whole file into ONE
       request, truncating long transcripts;
  C4 — ``recognize()`` / ``batch_recognize()`` had no RPC timeout;
  C5 — BATCH mode ignored the cancel callback during the long-running op.
"""
from __future__ import annotations

import math
import types

import pytest

from core.backends import cloud_stt as cs
from core.backends import google_cloud_stt as g


# ============================================================ C2: inline cap

def test_inline_limit_stays_under_20mb_after_base64_expansion():
    """A chunk at the inline ceiling must produce a base64 body well under the
    Gemini 20 MB inline cap (base64 inflates raw bytes by ~4/3).
    """
    cap = 20 * 1024 * 1024
    # Worst case: a chunk exactly at the threshold.
    raw_at_limit = cs.INLINE_LIMIT_BYTES
    base64_size = math.ceil(raw_at_limit * 4 / 3)
    # Must leave clear headroom for the prompt + JSON envelope under 20 MB.
    assert base64_size < cap
    assert (cap - base64_size) >= 32 * 1024  # at least 32 KiB of headroom


def test_inline_threshold_rejects_the_old_18mib_window():
    """The pre-fix 18 MiB raw chunk (which base64-expanded past 20 MB) must now
    route to the Files API, not inline.
    """
    old_threshold = 18 * 1024 * 1024
    # A chunk in the dangerous 14.7-18 MiB window must NOT be inlined now.
    assert cs._should_inline(old_threshold) is False
    assert cs._should_inline(15 * 1024 * 1024) is False
    # Genuinely small chunks still inline.
    assert cs._should_inline(1024) is True
    assert cs._should_inline(cs.INLINE_LIMIT_BYTES) is True
    assert cs._should_inline(cs.INLINE_LIMIT_BYTES + 1) is False


# ============================================================ C3: unknown dur

def test_cloud_stt_plan_chunks_unknown_default_keeps_whole_file_marker():
    """The pure default is unchanged (legacy ``(0.0, 0.0)`` whole-file marker),
    so other callers / tests are not disturbed.
    """
    assert cs.plan_chunks(0.0, 480.0) == [(0.0, 0.0)]
    assert cs.plan_chunks(0.0, 480.0, chunk_when_unknown=False) == [(0.0, 0.0)]


def test_cloud_stt_plan_chunks_unknown_chunks_when_opted_in():
    """With ``chunk_when_unknown=True`` an unknown duration is sliced into a
    bounded run of fixed windows instead of one whole-file request.
    """
    chunks = cs.plan_chunks(0.0, 480.0, chunk_when_unknown=True)
    assert len(chunks) == cs.MAX_UNKNOWN_DURATION_CHUNKS
    assert chunks[0] == (0.0, 480.0)
    assert chunks[1] == (480.0, 960.0)
    for start, end in chunks:
        assert round(end - start, 3) == 480.0


def _ready_cloud_backend(*, chunk_seconds=480.0):
    backend = cs.CloudSttBackend(
        config={"cloud_stt_api_key": "fake", "cloud_stt_model": "m"}
    )
    backend.load()
    backend._chunk_seconds = chunk_seconds
    return backend


def test_cloud_stt_unknown_duration_chunks_and_stops_at_eof(monkeypatch, tmp_path):
    """End-to-end (no network): when duration is 0 and the probe also fails,
    ``transcribe_to_segments`` must chunk (not send one whole-file request) and
    stop once a slice past EOF comes back empty — instead of truncating.
    """
    backend = _ready_cloud_backend(chunk_seconds=480.0)

    # Probe still cannot read a duration -> unknown path.
    monkeypatch.setattr(
        "core.transcriber.get_duration", lambda _p: 0.0, raising=True
    )

    # Three real chunks of audio, then an EOF (tiny header-only) slice.
    sizes = [200_000, 200_000, 200_000, 100]  # 4th is < _EMPTY_FLAC_BYTES
    made: list[str] = []
    calls = {"n": 0}

    def fake_encode(audio_path, start, end):
        idx = len(made)
        size = sizes[idx] if idx < len(sizes) else 100
        p = tmp_path / f"chunk{idx}.flac"
        p.write_bytes(b"\x00" * size)
        made.append(str(p))
        return str(p)

    monkeypatch.setattr(cs, "_encode_chunk_flac", fake_encode)
    # This test exercises the byte-size fast path with its tiny 100-byte EOF
    # slice; stub the ffprobe probe so the test never spawns a real binary
    # (and never depends on one being installed).
    monkeypatch.setattr(cs, "probe_flac_slice", lambda _p: True)

    def fake_one_chunk(self, flac_path, prompt, log_cb=None):
        calls["n"] += 1
        return "[00:00:00.000 --> 00:00:01.000] hi"

    monkeypatch.setattr(cs.CloudSttBackend, "_transcribe_one_chunk", fake_one_chunk)

    segs, _info = backend.transcribe_to_segments("/no/such.ts", duration=0.0)

    # Only the 3 real chunks were transcribed; the empty 4th stopped the run.
    assert calls["n"] == 3
    assert len(segs) == 3
    # Each chunk's segment was offset onto the global timeline.
    assert [s["start"] for s in segs] == [0.0, 480.0, 960.0]


def test_cloud_stt_known_duration_still_chunks_normally(monkeypatch, tmp_path):
    """A KNOWN duration keeps the existing bounded chunk plan (no regression)."""
    backend = _ready_cloud_backend(chunk_seconds=480.0)
    seen: list[tuple[float, float]] = []

    def fake_encode(audio_path, start, end):
        seen.append((start, end))
        p = tmp_path / f"k{len(seen)}.flac"
        p.write_bytes(b"\x00" * 50_000)
        return str(p)

    monkeypatch.setattr(cs, "_encode_chunk_flac", fake_encode)
    monkeypatch.setattr(
        cs.CloudSttBackend, "_transcribe_one_chunk",
        lambda self, fp, pr, log_cb=None: "[00:00:00.000 --> 00:00:01.000] hi",
    )
    backend.transcribe_to_segments("/x.wav", duration=1000.0)
    assert seen == [(0.0, 480.0), (480.0, 960.0), (960.0, 1000.0)]


# ============================================================ C1: diarization

def test_namespace_speaker_labels_first_chunk_untouched():
    segs = [{"start": 0.0, "end": 1.0, "text": "hi", "speaker": "1"}]
    out = g.namespace_speaker_labels(segs, 0)
    assert out[0]["speaker"] == "1"
    assert out is not segs  # fresh copy
    assert out[0] is not segs[0]


def test_namespace_speaker_labels_later_chunks_are_distinct():
    segs = [
        {"start": 0.0, "end": 1.0, "text": "a", "speaker": "1"},
        {"start": 1.0, "end": 2.0, "text": "b", "speaker": "2"},
    ]
    out = g.namespace_speaker_labels(segs, 1)  # chunk index 1 -> "C2-"
    assert out[0]["speaker"] == "C2-1"
    assert out[1]["speaker"] == "C2-2"
    # Input untouched (pure).
    assert segs[0]["speaker"] == "1"


def test_namespace_speaker_labels_rewrites_word_level_labels():
    segs = [{
        "start": 0.0, "end": 1.0, "text": "hi", "speaker": "1",
        "words": [{"start": 0.0, "end": 0.5, "word": "hi", "speaker": "1"}],
    }]
    out = g.namespace_speaker_labels(segs, 2)  # -> "C3-"
    assert out[0]["speaker"] == "C3-1"
    assert out[0]["words"][0]["speaker"] == "C3-1"
    # Original word dict untouched.
    assert segs[0]["words"][0]["speaker"] == "1"


def test_namespace_speaker_labels_no_speaker_is_noop():
    segs = [{"start": 0.0, "end": 1.0, "text": "no label"}]
    out = g.namespace_speaker_labels(segs, 3)
    assert "speaker" not in out[0]


def test_two_chunks_no_longer_collide_under_one_label():
    """The bug: 'Speaker 1' from chunk 0 and chunk 1 merged into one apparent
    person. After namespacing, the two chunks carry DISTINCT labels.
    """
    chunk0 = g.namespace_speaker_labels(
        [{"start": 0.0, "end": 1.0, "text": "a", "speaker": "1"}], 0
    )
    chunk1 = g.namespace_speaker_labels(
        [{"start": 0.0, "end": 1.0, "text": "b", "speaker": "1"}], 1
    )
    assert chunk0[0]["speaker"] != chunk1[0]["speaker"]


# -- end-to-end through _run_standard (fake client) -----------------------

class _FakeWord:
    def __init__(self, word, start, end, speaker):
        self.word = word
        self.start_offset = start
        self.end_offset = end
        self.confidence = 0.9
        self.speaker_label = speaker


class _FakeResult:
    def __init__(self, transcript, words):
        alt = types.SimpleNamespace(transcript=transcript, words=words)
        self.alternatives = [alt]
        self.result_end_offset = 0.0


class _FakeResponse:
    def __init__(self, results):
        self.results = results


def _diarized_backend(tmp_path):
    import json
    sa = tmp_path / "key.json"
    sa.write_text(
        json.dumps({"type": "service_account", "project_id": "p1"}),
        encoding="utf-8",
    )
    backend = g.GoogleCloudSttBackend(config={
        "gcloud_stt_credentials_json": str(sa),
        "gcloud_stt_diarization": True,
        "gcloud_stt_model": "chirp_2",
    })
    backend._project_id = "p1"
    backend._diarization = True
    backend._chunk_seconds = 55.0
    return backend


class _FakeCloudSpeech:
    """Minimal stand-in for the cloud_speech types module used by
    build_recognition_config + the recognize request builder.
    """

    class AutoDetectDecodingConfig:
        def __init__(self, **kw):
            self.kw = kw

    class SpeakerDiarizationConfig:
        def __init__(self, **kw):
            self.kw = kw

    class RecognitionFeatures:
        def __init__(self, **kw):
            self.kw = kw

    class RecognitionConfig:
        def __init__(self, **kw):
            self.kw = kw

    class RecognizeRequest:
        def __init__(self, **kw):
            self.kw = kw


def test_run_standard_diarization_namespaces_across_chunks(monkeypatch, tmp_path):
    """Two chunks each labelling their speaker "1" must NOT merge into one
    apparent speaker after stitching onto the global timeline.
    """
    backend = _diarized_backend(tmp_path)

    # Each chunk returns a single speaker labelled "1".
    def fake_recognize(request=None, timeout=None):
        return _FakeResponse([
            _FakeResult("hello world", [
                _FakeWord("hello", 0.0, 0.4, "1"),
                _FakeWord("world", 0.4, 0.8, "1"),
            ])
        ])

    monkeypatch.setattr(
        backend, "_build_client",
        lambda: types.SimpleNamespace(recognize=fake_recognize),
    )
    monkeypatch.setattr(backend, "_cloud_speech_types", lambda: _FakeCloudSpeech)

    made = {"n": 0}

    def fake_encode(audio_path, start, end):
        made["n"] += 1
        p = tmp_path / f"c{made['n']}.flac"
        p.write_bytes(b"\x00" * 50_000)
        return str(p)

    monkeypatch.setattr(g, "_encode_chunk_flac", fake_encode)

    # duration 100s @ 55s chunks -> 2 chunks.
    segs = backend._run_standard(
        "/x.wav", "auto", True, 100.0, None, None, None, None
    )
    speakers = {s.get("speaker") for s in segs if s.get("speaker")}
    # Chunk 0 keeps "1"; chunk 1 becomes "C2-1" — two distinct labels, no merge.
    assert "1" in speakers
    assert "C2-1" in speakers


# ============================================================ C4: RPC timeout

def test_recognize_is_called_with_a_timeout(monkeypatch, tmp_path):
    """The synchronous recognize() must be called with an explicit RPC
    deadline so a half-open connection cannot wedge the worker forever.
    """
    import json
    sa = tmp_path / "key.json"
    sa.write_text(
        json.dumps({"type": "service_account", "project_id": "p1"}),
        encoding="utf-8",
    )
    backend = g.GoogleCloudSttBackend(config={
        "gcloud_stt_credentials_json": str(sa),
        "gcloud_stt_recognize_timeout_s": 123.0,
    })
    backend._project_id = "p1"
    backend._chunk_seconds = 55.0

    captured = {}

    def fake_recognize(request=None, timeout=None):
        captured["timeout"] = timeout
        return _FakeResponse([_FakeResult("hi", [])])

    monkeypatch.setattr(
        backend, "_build_client",
        lambda: types.SimpleNamespace(recognize=fake_recognize),
    )

    monkeypatch.setattr(backend, "_cloud_speech_types", lambda: _FakeCloudSpeech)
    monkeypatch.setattr(
        g, "_encode_chunk_flac",
        lambda a, s, e: str(_mk(tmp_path, "r.flac")),
    )

    backend._run_standard("/x.wav", "auto", False, 40.0, None, None, None, None)
    assert captured["timeout"] == 123.0


def test_recognize_timeout_default_is_bounded(tmp_path):
    backend = g.GoogleCloudSttBackend(config={})
    assert backend._recognize_timeout() == 300.0
    backend2 = g.GoogleCloudSttBackend(
        config={"gcloud_stt_recognize_timeout_s": "not-a-number"}
    )
    assert backend2._recognize_timeout() == 300.0


def test_batch_submit_timeout_default_is_bounded():
    backend = g.GoogleCloudSttBackend(config={})
    assert backend._batch_submit_timeout() == 120.0


# ============================================================ C5: batch cancel

class _FakeOperation:
    """A fake long-running op mimicking google-api-core's LRO.

    ``result(timeout=)`` raises ``concurrent.futures.TimeoutError`` until
    ``ready_after`` polls elapse, then returns ``response``. It blocks for the
    requested ``timeout`` (like a real LRO) when ``block`` is True, so the
    overall-deadline test advances wall-clock deterministically. Records
    ``cancel()`` calls.
    """

    def __init__(self, response, ready_after=2, block=False):
        self._response = response
        self._calls = 0
        self._ready_after = ready_after
        self._block = block
        self.cancelled_calls = 0

    def result(self, timeout=None):
        import concurrent.futures as _f
        import time as _t
        self._calls += 1
        if self._calls >= self._ready_after:
            return self._response
        if self._block and timeout:
            _t.sleep(min(timeout, 0.01))
        raise _f.TimeoutError()

    def cancel(self):
        self.cancelled_calls += 1


def test_await_batch_returns_response_when_not_cancelled():
    backend = g.GoogleCloudSttBackend(config={"gcloud_stt_batch_poll_s": 0.001})
    sentinel = object()
    op = _FakeOperation(sentinel, ready_after=3)
    resp, was_cancelled = backend._await_batch_with_cancel(op, lambda: False, None)
    assert resp is sentinel
    assert was_cancelled is False
    assert op.cancelled_calls == 0
    assert op._calls == 3  # polled until ready


def test_await_batch_honors_cancel_promptly():
    """A Stop pressed during the batch wait must cancel the op and return
    promptly instead of blocking for the whole timeout.
    """
    backend = g.GoogleCloudSttBackend(config={"gcloud_stt_batch_poll_s": 0.001})
    op = _FakeOperation(object(), ready_after=10_000)  # would never finish
    resp, was_cancelled = backend._await_batch_with_cancel(op, lambda: True, None)
    assert resp is None
    assert was_cancelled is True
    assert op.cancelled_calls == 1


def test_await_batch_cancel_after_a_few_polls():
    backend = g.GoogleCloudSttBackend(config={"gcloud_stt_batch_poll_s": 0.001})
    op = _FakeOperation(object(), ready_after=10_000)
    state = {"n": 0}

    def cancelled():
        state["n"] += 1
        # Not cancelled the first two checks, then Stop is pressed.
        return state["n"] > 2

    resp, was_cancelled = backend._await_batch_with_cancel(op, cancelled, None)
    assert was_cancelled is True
    assert op.cancelled_calls == 1


def test_await_batch_overall_timeout_raises():
    """When the op never finishes and the overall batch budget elapses, a
    clean TimeoutError is raised (not an infinite loop).
    """
    import concurrent.futures as _f
    backend = g.GoogleCloudSttBackend(config={
        "gcloud_stt_batch_poll_s": 0.001,
        "gcloud_stt_batch_timeout_s": 0.05,  # tiny overall budget
    })
    # Never finishes in time, and each poll blocks briefly so wall-clock
    # advances past the 0.05 s overall budget deterministically.
    op = _FakeOperation(object(), ready_after=10**12, block=True)
    with pytest.raises(_f.TimeoutError):
        backend._await_batch_with_cancel(op, lambda: False, None)


def _mk(tmp_path, name):
    p = tmp_path / name
    p.write_bytes(b"\x00" * 50_000)
    return p
