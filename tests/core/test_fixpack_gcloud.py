"""Hermetic regression tests for the gcloud fix-pack (usage accounting).

NO network, NO service-account JSON, NO google libraries, NO real ffmpeg /
model. These pin the CONFIRMED bug in ``core/backends/google_cloud_stt.py``:

  * monthly minute accounting ran UNCONDITIONALLY after a run (the comment
    claimed "on success only" but there was no guard), so pressing Stop after
    one chunk — or cancelling a batch op — still billed the FULL file
    duration to the local free-tier / cost counter; and
  * accounting always counted the whole-file ``duration`` rather than the
    audio Google ACTUALLY transcribed, over-counting a partial run.

The fix counts only the windows actually sent to ``recognize`` (STANDARD) or
the whole file (BATCH on success), and SKIPS accounting entirely on cancel.

The pure helpers and EOF / unknown-duration chunking (already correct, see
``test_google_cloud_stt`` + ``test_fixpack_C``) are NOT re-tested here.
"""
from __future__ import annotations

import json
import types

import pytest

from core.backends import google_cloud_stt as g


# ------------------------------------------------------------------ fakes


class _FakeWord:
    def __init__(self, word, start, end):
        self.word = word
        self.start_offset = start
        self.end_offset = end
        self.confidence = 0.9
        self.speaker_label = ""


class _FakeResult:
    def __init__(self, transcript, words):
        alt = types.SimpleNamespace(transcript=transcript, words=words)
        self.alternatives = [alt]
        self.result_end_offset = 0.0


class _FakeResponse:
    def __init__(self, results):
        self.results = results


class _FakeCloudSpeech:
    """Minimal stand-in for the cloud_speech types module."""

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


def _fake_recognize(request=None, timeout=None):
    return _FakeResponse([
        _FakeResult("hello world", [
            _FakeWord("hello", 0.0, 0.4),
            _FakeWord("world", 0.4, 0.8),
        ])
    ])


def _ready_backend(tmp_path, **cfg_extra):
    """A backend that is already ``load``ed against an injected config dict.

    The injected config means ``_accumulate_usage`` updates the dict IN PLACE
    and skips the disk ``save_config`` write — so the test reads the counter
    straight off the dict with no I/O.
    """
    sa = tmp_path / "key.json"
    sa.write_text(
        json.dumps({"type": "service_account", "project_id": "p1"}),
        encoding="utf-8",
    )
    cfg = {
        "gcloud_stt_credentials_json": str(sa),
        "gcloud_stt_model": "chirp_2",
        "gcloud_stt_chunk_seconds": 55.0,
    }
    cfg.update(cfg_extra)
    backend = g.GoogleCloudSttBackend(config=cfg)
    backend._project_id = "p1"
    backend._chunk_seconds = 55.0
    backend._model = "chirp_2"
    backend._ready = True  # skip the network-touching client build path
    return backend, cfg


def _wire_standard(monkeypatch, backend, tmp_path, recognize=_fake_recognize):
    """Make a standard run fully hermetic: fake client, fake types, fake ffmpeg."""
    monkeypatch.setattr(
        backend, "_build_client",
        lambda: types.SimpleNamespace(recognize=recognize),
    )
    monkeypatch.setattr(backend, "_cloud_speech_types", lambda: _FakeCloudSpeech)

    def fake_encode(audio_path, start, end):
        p = tmp_path / f"chunk-{start:.3f}.flac"
        p.write_bytes(b"\x00" * 50_000)  # well over _EMPTY_FLAC_BYTES
        return str(p)

    monkeypatch.setattr(g, "_encode_chunk_flac", fake_encode)


# -------------------------------------------------- accounting SKIPPED on cancel


def test_usage_not_counted_when_cancelled_standard(monkeypatch, tmp_path):
    """Pressing Stop mid-standard-run must NOT bill the file to the counter.

    Pre-fix: ``_accumulate_usage`` ran unconditionally with the FULL duration,
    so a cancelled 600 s job still added 10 minutes to the monthly counter.
    """
    backend, cfg = _ready_backend(tmp_path)
    _wire_standard(monkeypatch, backend, tmp_path)

    # Cancel immediately — no chunk is ever sent.
    segs, _info = backend.transcribe_to_segments(
        "/x.wav", language="en", duration=600.0, cancelled=lambda: True,
    )
    assert segs == []
    # The local minute counter must be untouched (no key written).
    assert cfg.get("gcloud_stt_minutes_used", 0.0) in (0.0, None)
    assert backend._last_was_cancelled is True


def test_usage_not_counted_when_cancelled_batch(monkeypatch, tmp_path):
    """A batch op cancelled mid-flight bills nothing (no partial result)."""
    backend, cfg = _ready_backend(
        tmp_path, gcloud_stt_batch_mode=True, gcloud_stt_bucket="b",
    )
    backend._batch_mode = True
    backend._bucket = "b"

    # storage_available() True so we reach the batch path; the upload/op are
    # faked so nothing touches the network.
    monkeypatch.setattr(g, "storage_available", lambda: True)
    monkeypatch.setattr(
        backend, "_build_client",
        lambda: types.SimpleNamespace(
            batch_recognize=lambda request=None, timeout=None: object()
        ),
    )
    monkeypatch.setattr(backend, "_cloud_speech_types", lambda: _FakeCloudSpeech)

    # Extend the fake types module with the batch-only classes.
    _FakeCloudSpeech.BatchRecognizeRequest = type(
        "BatchRecognizeRequest",
        (),
        {
            "__init__": lambda self, **kw: setattr(self, "kw", kw),
            "ProcessingStrategy": types.SimpleNamespace(DYNAMIC_BATCHING=1),
        },
    )
    _FakeCloudSpeech.BatchRecognizeFileMetadata = lambda uri=None: uri
    _FakeCloudSpeech.RecognitionOutputConfig = lambda **kw: kw
    _FakeCloudSpeech.InlineOutputConfig = lambda **kw: kw

    monkeypatch.setattr(g, "_encode_chunk_flac", lambda a, s, e: str(_mk(tmp_path)))
    monkeypatch.setattr(
        backend, "_upload_to_gcs", lambda local, log: ("gs://b/x.flac", "x.flac")
    )
    monkeypatch.setattr(backend, "_delete_gcs_blob", lambda name, log: None)
    # The await returns (None, True) -> user cancelled the long-running op.
    monkeypatch.setattr(
        backend, "_await_batch_with_cancel", lambda op, c, log: (None, True)
    )

    segs, _info = backend.transcribe_to_segments(
        "/x.wav", language="en", duration=600.0, cancelled=lambda: False,
    )
    assert segs == []
    assert cfg.get("gcloud_stt_minutes_used", 0.0) in (0.0, None)
    assert backend._last_was_cancelled is True


# -------------------------------------------------- counts only transcribed audio


def test_usage_counts_only_transcribed_seconds_on_partial(monkeypatch, tmp_path):
    """A run cancelled after the 1st chunk bills ~one chunk, not the whole file.

    Pre-fix: the full 600 s (10 min) duration was billed regardless of how
    much was actually sent. Post-fix: only the windows actually sent to
    ``recognize`` are counted, including on cancel.
    """
    backend, cfg = _ready_backend(tmp_path)
    _wire_standard(monkeypatch, backend, tmp_path)

    # Allow chunk 0 to be sent, then cancel before chunk 1.
    state = {"checks": 0}

    def cancelled():
        state["checks"] += 1
        # The idx-0 top-of-loop check and the post-pause check pass; the
        # idx-1 top-of-loop check trips the cancel.
        return state["checks"] > 2

    segs, _info = backend.transcribe_to_segments(
        "/x.wav", language="en", duration=600.0, cancelled=cancelled,
    )
    # One chunk's worth of audio was transcribed before the user cancelled.
    assert backend._last_billable_seconds == pytest.approx(55.0)
    assert backend._last_was_cancelled is True
    # Google already billed that chunk, so a cancel must still record it in
    # the local free-tier counter (55 s / 60) rather than discard it.
    assert cfg.get("gcloud_stt_minutes_used", 0.0) == pytest.approx(55.0 / 60, abs=1e-3)
    assert segs  # chunk 0 produced segments


def test_usage_counts_transcribed_not_full_duration_on_success(monkeypatch, tmp_path):
    """A completed run bills the audio sent, clamped to the real duration.

    Three 55 s windows cover a 130 s file: 55 + 55 + 20 = 130 s = 2.166 min,
    NOT 3 * 55 = 165 s. The last window is clamped to the real end of file.
    """
    backend, cfg = _ready_backend(tmp_path)
    _wire_standard(monkeypatch, backend, tmp_path)

    segs, _info = backend.transcribe_to_segments(
        "/x.wav", language="en", duration=130.0, cancelled=lambda: False,
    )
    assert backend._last_was_cancelled is False
    # Billed seconds == the real duration (last chunk clamped), not 3*55.
    assert backend._last_billable_seconds == pytest.approx(130.0)
    # Counter reflects only the transcribed minutes (130 s / 60).
    assert cfg["gcloud_stt_minutes_used"] == pytest.approx(130.0 / 60.0, abs=0.01)
    assert cfg.get("gcloud_stt_minutes_month")
    assert segs


def test_usage_counted_on_full_success(monkeypatch, tmp_path):
    """A normal, uncancelled run DOES bill (the fix must not break the happy path)."""
    backend, cfg = _ready_backend(tmp_path)
    _wire_standard(monkeypatch, backend, tmp_path)

    backend.transcribe_to_segments(
        "/x.wav", language="en", duration=40.0, cancelled=lambda: False,
    )
    # Single 40 s chunk -> 40 s billed -> ~0.667 min recorded.
    assert backend._last_was_cancelled is False
    assert backend._last_billable_seconds == pytest.approx(40.0)
    assert cfg["gcloud_stt_minutes_used"] == pytest.approx(40.0 / 60.0, abs=0.01)


# ------------------------------------------------------------------ helpers


def _mk(tmp_path):
    p = tmp_path / "batch.flac"
    p.write_bytes(b"\x00" * 50_000)
    return p
