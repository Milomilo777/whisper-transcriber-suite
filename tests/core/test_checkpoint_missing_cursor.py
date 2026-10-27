"""Checkpoint safety: a MISSING ``last_end_time`` is recovered like a malformed one.

``_recover_resume_cursor`` recovers a non-numeric cursor from the saved
segments (the latest end among them) so the resume continues where the
captured text stops. A missing/empty cursor field is the same damage class
(hand-edited or partially damaged JSON), but it returned 0.0 even when
segments existed, so a resume re-decoded the file from the start and
concatenated the whole captured transcript a second time (every line twice
in the final outputs). It must recover from the segments the same way;
only a checkpoint with nothing captured starts at 0.
"""
from __future__ import annotations

import json
import sys
import time
import types

import pytest

from core import _checkpoint as cp


@pytest.fixture
def transcriber(monkeypatch, tmp_path):
    if "core.transcriber" not in sys.modules:
        fake_fw = types.ModuleType("faster_whisper")
        fake_fw.WhisperModel = object  # type: ignore[attr-defined]
        sys.modules.setdefault("faster_whisper", fake_fw)
    import core.config as cfg
    import core.transcriber as t

    monkeypatch.setattr(cfg, "user_data_dir", lambda: tmp_path / "data")
    monkeypatch.setattr(cp, "user_data_dir", lambda: tmp_path / "data")
    monkeypatch.setitem(t.config, "transcribe_backend", "faster_whisper")
    monkeypatch.setattr(t, "MODEL", None, raising=False)
    monkeypatch.setattr(t, "MODEL_READY", True, raising=False)
    monkeypatch.setattr(t, "MODEL_ERROR", None, raising=False)
    monkeypatch.setattr(t, "_ensure_default_backend_loaded", lambda log_cb=None: None)
    getattr(cp, "_RUN_IDENTITY", {}).clear()
    yield t
    getattr(cp, "_RUN_IDENTITY", {}).clear()


@pytest.fixture
def audio(tmp_path):
    p = tmp_path / "media.wav"
    p.write_bytes(b"A" * 64)
    return p


SEGS = [
    {"start": 0.0, "end": 40.0, "text": "a"},
    {"start": 40.0, "end": 80.0, "text": "b"},
]


def _write(t, task, audio):
    with t._runtime_overrides_scope(task):
        fp = cp.config_fingerprint(t.config)
        model_name = str(t.config.get("model", {}).get("name", "")) \
            or str(t.config.get("whisper_model", ""))
    return cp.write_checkpoint(
        str(audio), backend="faster_whisper", model_name=model_name,
        language="en", language_probability=0.9, cfg_fingerprint=fp,
        last_end_time=80.0, segments=SEGS, checkpoint_time=time.time(),
    )


@pytest.mark.parametrize("damage", [None, ""], ids=["missing", "empty"])
def test_missing_cursor_is_recovered_from_segments(
        transcriber, audio, monkeypatch, damage):
    from core.task import TranscriptionTask

    task = TranscriptionTask(str(audio))
    _write(transcriber, task, audio)
    path = cp.checkpoint_path(str(audio))
    data = json.loads(path.read_text(encoding="utf-8"))
    if damage is None:
        del data["last_end_time"]
    else:
        data["last_end_time"] = damage
    path.write_text(json.dumps(data), encoding="utf-8")

    seen: dict[str, float] = {}

    def _slice(src, start, out_dir):
        seen["start"] = start
        raise RuntimeError("fresh run would fail here")

    monkeypatch.setattr(transcriber, "_slice_audio_from", _slice)
    assert transcriber.resume_transcription(task) is False

    # The tail must start where the saved segments stop (80 s), not at 0:
    # a 0 s cursor makes the resume decode the captured stretch again and
    # concatenate every saved line a second time.
    assert seen["start"] == 80.0
    kept = json.loads(path.read_text(encoding="utf-8"))
    assert [s["text"] for s in kept["segments"]] == ["a", "b"]  # nothing deleted


def test_recover_cursor_missing_key_rules(transcriber):
    f = transcriber._recover_resume_cursor
    # Nothing captured and no cursor: a plain run from the start.
    assert f({"segments": []}) == 0.0
    assert f({}) == 0.0
    # Segments captured but no cursor: continue at the latest saved end.
    assert f({"segments": [{"end": 3}, {"end": 9.5}]}) == 9.5
    # Segments captured but none usable: no trustworthy cursor.
    assert f({"segments": [{"end": "?"}]}) is None
    assert f({"segments": ["junk"]}) is None
