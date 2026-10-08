"""Cloud engines: retry transient failures, keep already-paid chunks (C2.63).

No real cloud call: every request is a fake. Retry waits are patched to zero.
"""
from __future__ import annotations

import email.message
import io
import types
import urllib.error

import pytest

from core.backends import base
from core.backends import cloud_stt as cs
from core.backends import google_cloud_stt as g
from core.backends.base import (
    PartialResultError,
    call_with_retries,
    is_transient_error,
)
from tests.core.test_google_cloud_stt import _FakeCloudSpeech, _result


def _http_error(code, retry_after=None):
    headers = email.message.Message()
    if retry_after is not None:
        headers["Retry-After"] = str(retry_after)
    return urllib.error.HTTPError(
        "https://x.example/", code, "x", headers, io.BytesIO(b"{}"))


@pytest.fixture(autouse=True)
def _no_waits(monkeypatch):
    monkeypatch.setattr(base, "RETRY_DELAYS_S", (0.0, 0.0, 0.0))


# --- the shared helper ------------------------------------------------------

@pytest.mark.parametrize("code", [429, 500, 502, 503, 504, 408])
def test_transient_http_codes(code):
    assert is_transient_error(_http_error(code))


@pytest.mark.parametrize("code", [400, 401, 403, 404])
def test_permanent_http_codes_are_not_retried(code):
    assert not is_transient_error(_http_error(code))


def test_a_wrapped_cause_is_found():
    try:
        try:
            raise _http_error(429)
        except urllib.error.HTTPError as e:
            raise RuntimeError("Rate limit") from e
    except RuntimeError as outer:
        assert is_transient_error(outer)


def test_a_missing_network_is_not_retried():
    err = urllib.error.URLError(OSError("name resolution failed"))
    assert not is_transient_error(err)
    assert is_transient_error(urllib.error.URLError(TimeoutError("slow")))
    assert is_transient_error(TimeoutError("read"))


def test_google_error_class_names_are_matched():
    class ResourceExhausted(Exception):
        pass

    assert is_transient_error(ResourceExhausted("quota"))


def test_call_with_retries_recovers():
    calls = []

    def fn():
        calls.append(1)
        if len(calls) < 3:
            raise _http_error(429)
        return "ok"

    assert call_with_retries(fn, label="t") == "ok"
    assert len(calls) == 3


def test_call_with_retries_gives_up_after_the_last_wait():
    calls = []

    def fn():
        calls.append(1)
        raise _http_error(503)

    with pytest.raises(urllib.error.HTTPError):
        call_with_retries(fn, label="t")
    assert len(calls) == len(base.RETRY_DELAYS_S) + 1


def test_call_with_retries_does_not_retry_a_bad_key():
    calls = []

    def fn():
        calls.append(1)
        raise _http_error(400)

    with pytest.raises(urllib.error.HTTPError):
        call_with_retries(fn, label="t")
    assert len(calls) == 1


def test_a_stop_during_the_wait_ends_the_retries(monkeypatch):
    monkeypatch.setattr(base, "RETRY_DELAYS_S", (5.0, 5.0, 5.0))
    calls = []

    def fn():
        calls.append(1)
        raise _http_error(429)

    with pytest.raises(urllib.error.HTTPError):
        call_with_retries(fn, label="t", cancelled=lambda: True)
    assert len(calls) == 1


# --- Gemini (cloud_stt) -----------------------------------------------------

def _gemini(monkeypatch, tmp_path, fail_from_chunk):
    backend = cs.CloudSttBackend(
        config={"cloud_stt_api_key": "fake", "cloud_stt_model": "m"})
    backend.load()
    backend._chunk_seconds = 10.0

    def fake_encode(audio_path, start, end):
        p = tmp_path / f"c{int(start)}.flac"
        p.write_bytes(b"\x00" * 1000)
        return str(p)

    monkeypatch.setattr(cs, "_encode_chunk_flac", fake_encode)
    sent = {"n": 0}

    def fake_one(self, flac_path, prompt, log_cb=None):
        sent["n"] += 1
        chunk = int(flac_path.replace("\\", "/").rsplit("/", 1)[1][1:].split(".")[0]) // 10
        if chunk >= fail_from_chunk:
            raise RuntimeError("Google is busy")  # not transient: no retries
        return "[00:00:00.000 --> 00:00:01.000] hi"

    monkeypatch.setattr(cs.CloudSttBackend, "_transcribe_one_chunk", fake_one)
    return backend, sent


def test_gemini_keeps_finished_chunks_when_a_later_one_fails(monkeypatch, tmp_path):
    backend, sent = _gemini(monkeypatch, tmp_path, fail_from_chunk=2)
    with pytest.raises(PartialResultError) as info:
        backend.transcribe_to_segments("/no/such.wav", duration=30.0)
    assert len(info.value.segments) == 2
    assert [round(s["start"]) for s in info.value.segments] == [0, 10]
    assert "Google is busy" in str(info.value)
    assert sent["n"] == 3


def test_gemini_first_chunk_failure_is_a_plain_error(monkeypatch, tmp_path):
    backend, _ = _gemini(monkeypatch, tmp_path, fail_from_chunk=0)
    with pytest.raises(RuntimeError) as info:
        backend.transcribe_to_segments("/no/such.wav", duration=30.0)
    assert not isinstance(info.value, PartialResultError)


def test_gemini_retries_a_rate_limited_chunk(monkeypatch, tmp_path):
    backend = cs.CloudSttBackend(
        config={"cloud_stt_api_key": "fake", "cloud_stt_model": "m"})
    backend.load()
    backend._chunk_seconds = 10.0

    def fake_encode(audio_path, start, end):
        p = tmp_path / "c0.flac"
        p.write_bytes(b"\x00" * 1000)
        return str(p)

    monkeypatch.setattr(cs, "_encode_chunk_flac", fake_encode)
    attempts = {"n": 0}

    def fake_one(self, flac_path, prompt, log_cb=None):
        attempts["n"] += 1
        if attempts["n"] < 3:
            try:
                raise _http_error(429)
            except urllib.error.HTTPError as e:
                raise RuntimeError("Rate limit") from e
        return "[00:00:00.000 --> 00:00:01.000] hi"

    monkeypatch.setattr(cs.CloudSttBackend, "_transcribe_one_chunk", fake_one)
    segs, _ = backend.transcribe_to_segments("/no/such.wav", duration=8.0)
    assert attempts["n"] == 3
    assert len(segs) == 1


# --- Google Cloud (standard mode) -------------------------------------------

def _google(monkeypatch, tmp_path, recognize):
    backend = g.GoogleCloudSttBackend(config={})
    backend._project_id = "p1"
    backend._chunk_seconds = 10.0

    def fake_encode(audio_path, start, end):
        p = tmp_path / f"g{int(start)}.flac"
        p.write_bytes(b"\x00" * 1000)
        return str(p)

    monkeypatch.setattr(g, "_encode_chunk_flac", fake_encode)
    monkeypatch.setattr(
        backend, "_build_client",
        lambda: types.SimpleNamespace(recognize=recognize))
    monkeypatch.setattr(backend, "_cloud_speech_types", lambda: _FakeCloudSpeech)
    return backend


def test_google_keeps_finished_chunks_when_a_later_one_fails(monkeypatch, tmp_path):
    calls = {"n": 0}

    def recognize(request=None, timeout=None):
        calls["n"] += 1
        if calls["n"] >= 2:
            raise ValueError("backend exploded")  # not transient
        return types.SimpleNamespace(results=[_result("hello", result_end=2.0)])

    backend = _google(monkeypatch, tmp_path, recognize)
    with pytest.raises(PartialResultError) as info:
        backend._run_standard("/no/such.wav", "auto", False, 30.0,
                              None, None, None, None)
    assert len(info.value.segments) == 1
    assert calls["n"] == 2


def test_google_retries_a_quota_error(monkeypatch, tmp_path):
    class ResourceExhausted(Exception):
        pass

    calls = {"n": 0}

    def recognize(request=None, timeout=None):
        calls["n"] += 1
        if calls["n"] < 3:
            raise ResourceExhausted("quota")
        return types.SimpleNamespace(results=[_result("hello", result_end=2.0)])

    backend = _google(monkeypatch, tmp_path, recognize)
    segs = backend._run_standard("/no/such.wav", "auto", False, 8.0,
                                 None, None, None, None)
    assert calls["n"] == 3
    assert len(segs) == 1


# --- the transcriber saves the partial as a checkpoint -----------------------

def test_transcriber_checkpoints_a_partial_result(monkeypatch, tmp_path):
    from core import transcriber as t

    saved = {}

    def fake_write(task, segments, last_end, lang, prob, log_cb, **kw):
        saved.update(segments=list(segments), last_end=last_end, lang=lang)

    monkeypatch.setattr(t, "_write_periodic_checkpoint", fake_write)

    class _Backend:
        def transcribe_to_segments(self, *a, **k):
            raise PartialResultError(
                "boom", [{"start": 0.0, "end": 9.0, "text": "x"}], "en")

    monkeypatch.setattr(t, "_get_alt_backend", lambda name, log_cb: _Backend())
    monkeypatch.setattr(t, "get_duration", lambda _p: 20.0)
    monkeypatch.setattr(t, "require_audio_stream", lambda _p: None)
    monkeypatch.setattr(t, "_maybe_denoise", lambda p, **k: (p, None))
    task = types.SimpleNamespace(
        file_path=str(tmp_path / "a.wav"), language=None, cancelled=False,
        paused=False, clip_start=None, clip_end=None, checkpoint_failures=0)
    with pytest.raises(PartialResultError):
        t._transcribe_via_alt_backend("cloud", task, None, None, None)
    assert saved["segments"] == [{"start": 0.0, "end": 9.0, "text": "x"}]
    assert saved["last_end"] == 9.0
    assert saved["lang"] == "en"


# --- C7: hotwords / initial prompt are no longer silently ignored -----------

def test_gemini_prompt_carries_the_vocabulary_hint():
    plain = cs.build_prompt("en")
    hinted = cs.build_prompt("en", "Zorblax,  Qwerty\nIndustries")
    assert "Zorblax, Qwerty Industries" in hinted
    assert "Zorblax" not in plain
    assert len(cs.build_prompt("en", "x" * 5000)) < len(plain) + 800


def test_gemini_sends_hotwords_to_the_model(monkeypatch, tmp_path):
    backend = cs.CloudSttBackend(
        config={"cloud_stt_api_key": "fake", "cloud_stt_model": "m"})
    backend.load()
    def fake_encode(audio_path, start, end):
        path = tmp_path / "c0.flac"
        path.write_bytes(b"\x00" * 100)
        return str(path)

    monkeypatch.setattr(cs, "_encode_chunk_flac", fake_encode)
    seen = {}

    def fake_one(self, flac_path, prompt, log_cb=None):
        seen["prompt"] = prompt
        return "[00:00:00.000 --> 00:00:01.000] hi"

    monkeypatch.setattr(cs.CloudSttBackend, "_transcribe_one_chunk", fake_one)
    backend.transcribe_to_segments(
        "/no/such.wav", duration=5.0, hotwords="Zorblax", initial_prompt="")
    assert "Zorblax" in seen["prompt"]


def test_google_says_it_ignores_hotwords(monkeypatch, tmp_path):
    backend = g.GoogleCloudSttBackend(config={})
    backend._project_id = "p1"
    notes: list[str] = []
    monkeypatch.setattr(
        backend, "_run_standard", lambda *a, **k: [])
    monkeypatch.setattr(backend, "is_ready", lambda: True)
    backend.transcribe_to_segments(
        "/no/such.wav", duration=5.0, hotwords="Zorblax", log_cb=notes.append)
    assert any("hotwords" in n for n in notes)
