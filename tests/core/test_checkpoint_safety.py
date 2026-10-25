"""Checkpoint data safety: the run-start source identity is authoritative, a
checkpoint that cannot be quarantined is never overwritten or deleted, and a
kept-aside checkpoint leaves a readable text copy that the sweep never reaps.

Hermetic: real files under tmp_path, no model, no ffmpeg.
"""
from __future__ import annotations

import os
import shutil
import sys
import time
import types

import pytest

from core import _checkpoint as cp

SEGS = [
    {"start": 0.0, "end": 40.0, "text": "first words"},
    {"start": 3725.0, "end": 3800.0, "text": "much later words"},
]


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(cp, "user_data_dir", lambda: tmp_path / "data")
    cp._RUN_IDENTITY.clear()
    yield tmp_path / "data"
    cp._RUN_IDENTITY.clear()


@pytest.fixture
def source(tmp_path):
    p = tmp_path / "audio.wav"
    p.write_bytes(b"A" * 64)
    return p


def _write(src, **over):
    kwargs = dict(
        backend="b", model_name="m", language="en", language_probability=0.9,
        cfg_fingerprint="c", last_end_time=3800.0, segments=SEGS,
        checkpoint_time=1000.0,
    )
    kwargs.update(over)
    return cp.write_checkpoint(str(src), **kwargs)


def _validate(data):
    return cp.validate_checkpoint(data, backend="b", model_name="m", cfg_fingerprint="c")


def _replace_media(src):
    src.write_bytes(b"B" * 99)
    st = src.stat()
    os.utime(src, (st.st_atime, st.st_mtime + 500))


# --- defect 1: identity ------------------------------------------------------


def test_media_swapped_mid_run_keeps_the_run_start_identity(data_dir, source):
    cp.note_source_identity(str(source))
    _write(source)
    _replace_media(source)
    _write(source)  # the stat succeeds and sees the new media

    data = cp.load_checkpoint(str(source))
    assert data["source_size"] == 64
    # The segments came from the original media, so the resume must refuse.
    assert _validate(data) == "source file size has changed since checkpoint"


def test_first_write_without_a_note_records_what_it_sees(data_dir, source):
    _write(source)
    assert cp.load_checkpoint(str(source))["source_size"] == 64


def test_failed_stat_at_run_start_drops_an_older_note(data_dir, source, monkeypatch):
    cp.note_source_identity(str(source))
    assert str(source) and os.path.abspath(str(source)) in cp._RUN_IDENTITY
    real = os.stat

    def _boom(p, *a, **kw):
        if os.path.abspath(os.fspath(p)) == os.path.abspath(str(source)):
            raise OSError(116, "share hiccup")
        return real(p, *a, **kw)

    monkeypatch.setattr(cp.os, "stat", _boom)
    cp.note_source_identity(str(source))
    monkeypatch.setattr(cp.os, "stat", real)
    # A note from an earlier run on other media must not survive.
    assert os.path.abspath(str(source)) not in cp._RUN_IDENTITY


# --- defect 2: quarantine failure -------------------------------------------


def _kept(src):
    path = cp.checkpoint_path(str(src))
    return sorted(
        p for p in path.parent.glob(path.name + ".unverified-*") if p.suffix != ".txt"
    )


def test_failed_rename_falls_back_to_a_verified_copy(data_dir, source, monkeypatch):
    _write(source)
    path = cp.checkpoint_path(str(source))
    original = path.read_bytes()

    def _no_rename(*_a, **_k):
        raise PermissionError(13, "locked")

    with monkeypatch.context() as m:
        m.setattr(cp.os, "replace", _no_rename)
        kept = cp.quarantine_checkpoint(str(source), "test reason")

    assert kept is not None and kept.read_bytes() == original
    # A fresh run may now write over / delete the original.
    cp._RUN_IDENTITY.clear()
    _write(source, segments=[])
    cp.delete_checkpoint(str(source))
    assert kept.read_bytes() == original


def test_rename_and_copy_failure_leaves_the_checkpoint_untouched(
        data_dir, source, monkeypatch):
    _write(source)
    path = cp.checkpoint_path(str(source))
    original = path.read_bytes()

    def _fail(*_a, **_k):
        raise OSError(28, "no space left")

    with monkeypatch.context() as m:
        m.setattr(cp.os, "replace", _fail)
        m.setattr(shutil, "copy2", _fail)
        with pytest.raises(cp.CheckpointNotKeptError):
            cp.quarantine_checkpoint(str(source), "test reason")

    assert path.read_bytes() == original
    assert _kept(source) == []


def test_resume_stops_the_task_when_the_checkpoint_cannot_be_kept(
        data_dir, source, monkeypatch):
    if "core.transcriber" not in sys.modules:
        fake_fw = types.ModuleType("faster_whisper")
        fake_fw.WhisperModel = object  # type: ignore[attr-defined]
        sys.modules.setdefault("faster_whisper", fake_fw)
    import core.transcriber as t
    from core.task import TranscriptionTask

    _write(source)
    path = cp.checkpoint_path(str(source))
    original = path.read_bytes()
    monkeypatch.setattr(t, "_ensure_default_backend_loaded", lambda log_cb=None: None)
    monkeypatch.setattr(t, "_current_backend_and_model", lambda: ("faster_whisper", "m"))
    # An unverifiable media identity sends the resume down the quarantine branch.
    monkeypatch.setattr(
        cp, "validate_checkpoint",
        lambda *a, **k: cp.UNVERIFIABLE_PREFIX + " (test)",
    )

    def _fail(*_a, **_k):
        raise OSError(28, "no space left")

    started = []
    monkeypatch.setattr(t, "transcribe", lambda *a, **k: started.append(1))
    logs: list[str] = []
    with monkeypatch.context() as m:
        m.setattr(cp.os, "replace", _fail)
        m.setattr(shutil, "copy2", _fail)
        with pytest.raises(cp.CheckpointNotKeptError):
            t.resume_transcription(TranscriptionTask(str(source)), log_cb=logs.append)

    assert path.read_bytes() == original
    assert not started
    assert any("saved text is not overwritten" in m for m in logs)


# --- defect 3: readable sidecar, sweep keeps both ----------------------------


def test_quarantine_writes_a_readable_text_copy(data_dir, source):
    _write(source)
    kept = cp.quarantine_checkpoint(str(source), "media identity unknown")
    assert kept is not None
    sidecar = cp.recovery_text_path(kept)
    raw = sidecar.read_bytes()
    assert b"\r" not in raw
    text = raw.decode("utf-8")
    assert os.path.abspath(str(source)) in text
    assert "media identity unknown" in text
    assert "[00:00:00] first words" in text
    assert "[01:02:05] much later words" in text


def test_sidecar_failure_never_fails_the_quarantine(data_dir, source, monkeypatch):
    _write(source)
    monkeypatch.setattr(
        cp, "_recovery_text", lambda *a, **k: (_ for _ in ()).throw(ValueError("x"))
    )
    kept = cp.quarantine_checkpoint(str(source), "r")
    assert kept is not None and kept.exists()


def test_sidecar_survives_a_corrupt_checkpoint(data_dir, source):
    _write(source)
    cp.checkpoint_path(str(source)).write_text("{not json", encoding="utf-8")
    kept = cp.quarantine_checkpoint(str(source), "r")
    assert kept is not None
    text = cp.recovery_text_path(kept).read_text(encoding="utf-8")
    assert "no readable segments" in text


def test_sweep_never_deletes_kept_aside_files(data_dir, source):
    _write(source)
    kept = cp.quarantine_checkpoint(str(source), "r")
    assert kept is not None
    sidecar = cp.recovery_text_path(kept)
    old = time.time() - 400 * 86400
    for p in (kept, sidecar):
        os.utime(p, (old, old))
    cp.sweep_partials(max_age_days=1.0, slice_max_age_minutes=0.0)
    assert kept.exists() and sidecar.exists()
