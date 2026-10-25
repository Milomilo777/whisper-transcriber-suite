"""Checkpoint data safety: the run-start source identity is authoritative, a
checkpoint that cannot be quarantined is never overwritten or deleted, and a
kept-aside checkpoint leaves a readable text copy that the sweep never reaps.

Hermetic: real files under tmp_path, no model, no ffmpeg.
"""
from __future__ import annotations

import os
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
    return sorted(path.parent.glob(path.name + ".unverified-*"))


def _no_rename(*_a, **_k):
    raise PermissionError(13, "locked")


def _fail(*_a, **_k):
    raise OSError(28, "no space left")


def test_kept_names_are_unique_and_keep_the_json_infix(data_dir, source):
    names = set()
    for _ in range(3):
        _write(source)
        kept = cp.quarantine_checkpoint(str(source), "r")
        assert kept is not None and ".json.unverified-" in kept.name
        names.add(kept.name)
    assert len(names) == 3


def test_failed_rename_falls_back_to_a_verified_copy(data_dir, source, monkeypatch):
    _write(source)
    path = cp.checkpoint_path(str(source))
    original = path.read_bytes()

    with monkeypatch.context() as m:
        m.setattr(cp.os, "rename", _no_rename)
        with pytest.raises(cp.CheckpointInUseError) as ei:
            cp.quarantine_checkpoint(str(source), "test reason")
        # A second attempt reuses the identical copy: no duplicate, no new sidecar.
        with pytest.raises(cp.CheckpointInUseError) as ei2:
            cp.quarantine_checkpoint(str(source), "test reason")

    kept = ei.value.kept
    assert kept is not None and kept.read_bytes() == original
    assert ei2.value.kept == kept
    assert _kept(source) == [kept]
    assert len(list(path.parent.glob("*.txt"))) == 1
    assert "saved text is not overwritten" in str(ei.value)
    # The copy never deletes the original; the stopped task left it in place.
    assert path.read_bytes() == original
    cp._RUN_IDENTITY.clear()
    _write(source, segments=[])
    cp.delete_checkpoint(str(source))
    assert kept.read_bytes() == original
    assert cp.recovery_text_path(kept).exists()


def test_read_back_comparison_catches_a_corrupt_copy(data_dir, source, monkeypatch):
    _write(source)
    path = cp.checkpoint_path(str(source))
    original = path.read_bytes()
    real_sync = cp._strict_sync

    def _corrupting_sync(f):
        real_sync(f)
        name = f.name
        with open(name, "r+b") as g:  # same length, different bytes
            g.write(b"X")

    with monkeypatch.context() as m:
        m.setattr(cp.os, "rename", _no_rename)
        m.setattr(cp, "_strict_sync", _corrupting_sync)
        with pytest.raises(cp.CheckpointNotKeptError) as ei:
            cp.quarantine_checkpoint(str(source), "r")
    assert not isinstance(ei.value, cp.CheckpointInUseError)
    assert path.read_bytes() == original
    assert _kept(source) == []


def test_rename_and_copy_failure_leaves_the_checkpoint_untouched(
        data_dir, source, monkeypatch):
    _write(source)
    path = cp.checkpoint_path(str(source))
    original = path.read_bytes()

    with monkeypatch.context() as m:
        m.setattr(cp.os, "rename", _fail)
        m.setattr(cp, "_strict_sync", _fail)
        with pytest.raises(cp.CheckpointNotKeptError):
            cp.quarantine_checkpoint(str(source), "test reason")

    assert path.read_bytes() == original
    assert _kept(source) == []


def test_eio_on_fsync_of_the_copy_is_a_failure(data_dir, source, monkeypatch):
    _write(source)
    path = cp.checkpoint_path(str(source))
    original = path.read_bytes()

    def _eio(_fd):
        raise OSError(5, "I/O error")

    with monkeypatch.context() as m:
        m.setattr(cp.os, "rename", _no_rename)
        m.setattr(cp.os, "fsync", _eio)
        with pytest.raises(cp.CheckpointNotKeptError):
            cp.quarantine_checkpoint(str(source), "r")

    assert path.read_bytes() == original
    assert _kept(source) == []  # the half-made copy this attempt created is removed


def test_fsync_not_supported_is_tolerated(data_dir, source, monkeypatch):
    import errno

    _write(source)
    original = cp.checkpoint_path(str(source)).read_bytes()

    def _unsupported(_fd):
        raise OSError(errno.EINVAL, "fsync not supported")

    with monkeypatch.context() as m:
        m.setattr(cp.os, "rename", _no_rename)
        m.setattr(cp.os, "fsync", _unsupported)
        with pytest.raises(cp.CheckpointInUseError) as ei:
            cp.quarantine_checkpoint(str(source), "r")
    assert ei.value.kept is not None and ei.value.kept.read_bytes() == original


def test_existing_target_name_is_never_overwritten_or_deleted(
        data_dir, source, monkeypatch):
    _write(source)
    path = cp.checkpoint_path(str(source))
    original = path.read_bytes()
    taken = path.with_name(path.name + ".unverified-taken")
    taken.write_bytes(b"someone else's file")
    names = iter(["taken", "taken", "fresh1", "fresh2"])
    monkeypatch.setattr(
        cp, "_kept_name", lambda p: p.with_name(p.name + ".unverified-" + next(names))
    )

    # rename path: skips the taken name
    kept = cp.quarantine_checkpoint(str(source), "r")
    assert kept is not None and kept.name.endswith("fresh1")
    assert kept.read_bytes() == original
    assert taken.read_bytes() == b"someone else's file"

    # copy path: exclusive creation refuses the taken name (different bytes, so
    # the identical-copy reuse does not apply)
    _write(source, last_end_time=1.0)
    names2 = iter(["taken", "fresh3", "taken", "fresh4"])
    monkeypatch.setattr(
        cp, "_kept_name", lambda p: p.with_name(p.name + ".unverified-" + next(names2))
    )
    monkeypatch.setattr(cp.os, "rename", _no_rename)
    with pytest.raises(cp.CheckpointInUseError) as ei:
        cp.quarantine_checkpoint(str(source), "r")
    kept2 = ei.value.kept
    assert kept2 is not None and kept2.name.endswith("fresh4")
    assert taken.read_bytes() == b"someone else's file"


def test_exclusive_copy_failure_does_not_delete_a_foreign_file(
        data_dir, source, monkeypatch):
    _write(source)
    path = cp.checkpoint_path(str(source))
    taken = path.with_name(path.name + ".unverified-taken")
    taken.write_bytes(b"foreign")
    monkeypatch.setattr(
        cp, "_kept_name", lambda p: p.with_name(p.name + ".unverified-taken")
    )
    monkeypatch.setattr(cp.os, "rename", _no_rename)
    with pytest.raises(cp.CheckpointNotKeptError):
        cp.quarantine_checkpoint(str(source), "r")
    assert taken.read_bytes() == b"foreign"
    assert path.exists()


def test_original_replaced_during_the_copy_is_never_deleted(
        data_dir, source, monkeypatch):
    _write(source, segments=SEGS)
    path = cp.checkpoint_path(str(source))
    older = path.read_bytes()
    newer = older.replace(b"first words", b"FIRST WORDS")  # same length
    assert len(newer) == len(older) and newer != older
    real_sync = cp._strict_sync

    def _sync_then_writer_replaces(f):
        real_sync(f)
        tmp = path.with_name("writer.tmp")
        tmp.write_bytes(newer)
        os.replace(tmp, path)

    with monkeypatch.context() as m:
        m.setattr(cp.os, "rename", _no_rename)
        m.setattr(cp, "_strict_sync", _sync_then_writer_replaces)
        with pytest.raises(cp.CheckpointInUseError) as ei:
            cp.quarantine_checkpoint(str(source), "r")

    kept = ei.value.kept
    assert kept is not None and kept.read_bytes() == older
    assert path.read_bytes() == newer  # the newer checkpoint survives


def test_checkpoint_already_kept_by_another_process_returns_none(
        data_dir, source, monkeypatch):
    _write(source)
    path = cp.checkpoint_path(str(source))
    other = path.with_name(path.name + ".unverified-other")
    real_rename = os.rename

    def _other_wins(src, dst):
        real_rename(src, other)  # the other process moved it first
        raise FileNotFoundError(2, "gone")

    with monkeypatch.context() as m:
        m.setattr(cp.os, "rename", _other_wins)
        assert cp.quarantine_checkpoint(str(source), "r") is None
    assert other.exists()  # the winner's file is untouched


def test_original_gone_when_the_copy_starts_returns_none(data_dir, source, monkeypatch):
    _write(source)
    path = cp.checkpoint_path(str(source))

    def _locked_then_gone(src, dst):
        os.unlink(path)  # another process kept it aside meanwhile
        raise PermissionError(13, "locked")

    with monkeypatch.context() as m:
        m.setattr(cp.os, "rename", _locked_then_gone)
        assert cp.quarantine_checkpoint(str(source), "r") is None
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
    monkeypatch.setattr(
        cp, "validate_checkpoint",
        lambda *a, **k: cp.UNVERIFIABLE_PREFIX + " (test)",
    )
    started = []
    monkeypatch.setattr(t, "transcribe", lambda *a, **k: started.append(1))
    logs: list[str] = []
    with monkeypatch.context() as m:
        m.setattr(cp.os, "rename", _fail)
        m.setattr(cp, "_strict_sync", _fail)
        with pytest.raises(cp.CheckpointNotKeptError):
            t.resume_transcription(TranscriptionTask(str(source)), log_cb=logs.append)

    assert path.read_bytes() == original
    assert not started
    assert any("saved text is not overwritten" in m for m in logs)


# --- defect E: changed or missing media keeps the text -----------------------


@pytest.fixture
def resume_env(data_dir, monkeypatch):
    if "core.transcriber" not in sys.modules:
        fake_fw = types.ModuleType("faster_whisper")
        fake_fw.WhisperModel = object  # type: ignore[attr-defined]
        sys.modules.setdefault("faster_whisper", fake_fw)
    import core.transcriber as t

    monkeypatch.setattr(t, "_ensure_default_backend_loaded", lambda log_cb=None: None)
    monkeypatch.setattr(t, "_current_backend_and_model", lambda: ("faster_whisper", "m"))
    return t


@pytest.mark.parametrize("reason", [
    "source file no longer exists: x",
    "source file size has changed since checkpoint",
    "source file mtime has changed since checkpoint",
    "could not stat source: boom",
    "checkpoint missing source_size",
    "checkpoint missing source_mtime",
    "checkpoint source_size is not a number: 'x'",
    "checkpoint source_mtime is not a number: 'x'",
    "checkpoint missing source_path",
    "checkpoint schema_version 9 != expected 1",
    "checkpoint payload is not a dict",
    "some reason added in the future",
    cp.UNVERIFIABLE_PREFIX + " (x)",
])
def test_media_problems_keep_the_text(resume_env, source, monkeypatch, reason):
    from core.task import TranscriptionTask

    t = resume_env
    _write(source)
    path = cp.checkpoint_path(str(source))
    original = path.read_bytes()
    monkeypatch.setattr(cp, "validate_checkpoint", lambda *a, **k: reason)
    assert t.resume_transcription(TranscriptionTask(str(source))) is False
    assert not path.exists()
    kept = _kept(source)
    assert len(kept) == 1 and kept[0].read_bytes() == original
    assert cp.recovery_text_path(kept[0]).exists()


@pytest.mark.parametrize("reason", [
    "transcription config changed since checkpoint",
    "model changed: checkpoint='a' current='b'",
    "backend changed: checkpoint='a' current='b'",
    "checkpoint segments field is not a list",
])
def test_config_problems_still_discard_the_partial(resume_env, source, monkeypatch, reason):
    from core.task import TranscriptionTask

    t = resume_env
    _write(source)
    monkeypatch.setattr(cp, "validate_checkpoint", lambda *a, **k: reason)
    assert t.resume_transcription(TranscriptionTask(str(source))) is False
    assert not cp.checkpoint_path(str(source)).exists()
    assert _kept(source) == []


def test_really_replaced_media_keeps_the_checkpoint_on_resume(resume_env, source):
    from core.task import TranscriptionTask

    t = resume_env
    cp.note_source_identity(str(source))
    _write(source, backend="faster_whisper", model_name="m")
    original = cp.checkpoint_path(str(source)).read_bytes()
    _replace_media(source)
    task = TranscriptionTask(str(source))
    assert t.resume_transcription(task) is False
    kept = _kept(source)
    assert len(kept) == 1 and kept[0].read_bytes() == original


# --- defect D: identity at every run route -----------------------------------


def test_language_model_route_notes_the_identity_of_its_own_run(
        data_dir, source, monkeypatch):
    if "core.transcriber" not in sys.modules:
        fake_fw = types.ModuleType("faster_whisper")
        fake_fw.WhisperModel = object  # type: ignore[attr-defined]
        sys.modules.setdefault("faster_whisper", fake_fw)
    import core.language_models as lm
    import core.transcriber as t
    from core.task import TranscriptionTask

    # Run A is interrupted: its checkpoint stays and its identity stays cached.
    task_a = TranscriptionTask(str(source))
    t._note_run_identity(task_a)
    t._write_periodic_checkpoint(task_a, [dict(SEGS[0])], 40.0, "en", 0.9, None)
    assert cp.load_checkpoint(str(source))["source_size"] == 64
    # The file is replaced by B and run B arrives through the alt-backend route.
    _replace_media(source)
    monkeypatch.setattr(lm, "by_model", lambda _id: types.SimpleNamespace(engine="other"))
    monkeypatch.setattr(t, "release_default_model", lambda: None)
    monkeypatch.setattr(t, "_language_model_backend", lambda *a, **k: object())
    task_b = TranscriptionTask(str(source))
    # A reused task: its flag is already set, so the writer's fallback stays
    # silent and only the route's own note can give B its identity.
    task_b.identity_noted = True

    def _backend_run(name, task, *a, **k):
        t._write_periodic_checkpoint(task, [dict(SEGS[1])], 80.0, "en", 0.9, None)

    monkeypatch.setattr(t, "_transcribe_via_alt_backend", _backend_run)
    t.transcribe_with_language_model("some-model", task_b)

    data = cp.load_checkpoint(str(source))
    assert data["source_size"] == 99
    assert _validate(data).startswith("backend changed")  # identity checks passed


def test_checkpoint_writer_notes_identity_when_no_route_did(data_dir, source):
    if "core.transcriber" not in sys.modules:
        fake_fw = types.ModuleType("faster_whisper")
        fake_fw.WhisperModel = object  # type: ignore[attr-defined]
        sys.modules.setdefault("faster_whisper", fake_fw)
    import core.transcriber as t
    from core.task import TranscriptionTask

    cp.note_source_identity(str(source))  # stale note of an earlier run on A
    _replace_media(source)
    task = TranscriptionTask(str(source))  # a route that never noted
    t._write_periodic_checkpoint(task, [dict(SEGS[0])], 40.0, "en", 0.9, None)
    assert cp.load_checkpoint(str(source))["source_size"] == 99


# --- defect 3 / F: readable sidecar, sweep keeps both ------------------------


def test_quarantine_writes_a_readable_text_copy(data_dir, source):
    _write(source)
    kept = cp.quarantine_checkpoint(str(source), "media identity unknown")
    assert kept is not None
    sidecar = cp.recovery_text_path(kept)
    assert ".json" not in sidecar.name
    raw = sidecar.read_bytes()
    assert b"\r" not in raw
    text = raw.decode("utf-8")
    assert os.path.abspath(str(source)) in text
    assert "media identity unknown" in text
    assert "[00:00:00] first words" in text
    assert "[01:02:05] much later words" in text


def test_sidecar_lists_every_segment_despite_bad_starts(data_dir, source):
    segs = [
        {"start": float("nan"), "end": 1.0, "text": "nan words"},
        {"start": float("inf"), "end": 1.0, "text": "inf words"},
        {"start": float("-inf"), "end": 1.0, "text": "neg inf words"},
        {"start": 1e300, "end": 1.0, "text": "huge words"},
        {"start": "7", "end": 1.0, "text": "string start words"},
        {"start": None, "end": 1.0, "text": "none start words"},
        {"start": -5, "end": 1.0, "text": "negative words"},
        {"start": 61.5, "end": 70.0, "text": "good words"},
    ]
    _write(source, segments=segs)
    kept = cp.quarantine_checkpoint(str(source), "r")
    assert kept is not None
    text = cp.recovery_text_path(kept).read_text(encoding="utf-8")
    for seg in segs:
        assert seg["text"] in text
    assert "[00:01:01] good words" in text
    assert text.count("??:??:??") == 7


def test_sidecar_failure_never_fails_the_quarantine(data_dir, source, monkeypatch):
    _write(source)

    def _boom(_kept):
        raise ValueError("x")

    monkeypatch.setattr(cp, "recovery_text_path", _boom)
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


# --- H / I: conservative classification, finite identity ---------------------


def test_only_the_listed_reasons_discard():
    for reason in (
        "backend changed: checkpoint='a' current='b'",
        "model changed: checkpoint='a' current='b'",
        "transcription config changed since checkpoint",
        "checkpoint segments field is not a list",
    ):
        assert cp.keeps_text(reason) is False
    for reason in (
        "checkpoint schema_version 9 != expected 1",
        "checkpoint missing source_path",
        "source file no longer exists: x",
        "something nobody has thought of yet",
    ):
        assert cp.keeps_text(reason) is True
    assert cp.keeps_text("") is False  # a valid checkpoint is not kept aside


def test_schema_mismatch_with_missing_media_keeps_the_text(resume_env, source, monkeypatch):
    from core.task import TranscriptionTask

    t = resume_env
    _write(source)
    path = cp.checkpoint_path(str(source))
    original = path.read_bytes()
    data = cp.load_checkpoint(str(source))
    data["schema_version"] = 9
    path.write_text(__import__("json").dumps(data), encoding="utf-8")
    original = path.read_bytes()
    source.unlink()
    assert t.resume_transcription(TranscriptionTask(str(source))) is False
    kept = _kept(source)
    assert len(kept) == 1 and kept[0].read_bytes() == original


@pytest.mark.parametrize("field", ["source_mtime", "source_size"])
@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf"), True, 10 ** 400, "5"])
def test_unusable_identity_numbers_are_unverifiable(data_dir, source, field, bad):
    _write(source)
    data = cp.load_checkpoint(str(source))
    data[field] = bad
    reason = _validate(data)
    assert reason.startswith(cp.UNVERIFIABLE_PREFIX)


def test_nan_mtime_with_equal_size_changed_media_is_not_accepted(data_dir, source):
    cp.note_source_identity(str(source))
    _write(source)
    data = cp.load_checkpoint(str(source))
    assert _validate(data) == ""  # control: the genuine checkpoint validates
    data["source_mtime"] = float("nan")
    source.write_bytes(b"B" * 64)  # same size, different content
    st = source.stat()
    os.utime(source, (st.st_atime, st.st_mtime + 500))
    assert _validate(data).startswith(cp.UNVERIFIABLE_PREFIX)


def test_infinite_size_keeps_the_checkpoint_aside_without_error(resume_env, source):
    from core.task import TranscriptionTask

    t = resume_env
    _write(source)
    path = cp.checkpoint_path(str(source))
    data = cp.load_checkpoint(str(source))
    data["source_size"] = float("inf")
    path.write_text(__import__("json").dumps(data), encoding="utf-8")
    original = path.read_bytes()
    assert t.resume_transcription(TranscriptionTask(str(source))) is False
    kept = _kept(source)
    assert len(kept) == 1 and kept[0].read_bytes() == original


# --- J: the unsupported-backend early return -------------------------------


def test_unsupported_backend_keeps_a_checkpoint_of_replaced_media(resume_env, source, monkeypatch):
    from core.task import TranscriptionTask

    t = resume_env
    monkeypatch.setattr(t, "_current_backend_and_model", lambda: ("cloud_stt", "m"))
    cp.note_source_identity(str(source))
    _write(source, backend="faster_whisper", model_name="m")
    original = cp.checkpoint_path(str(source)).read_bytes()
    _replace_media(source)
    assert t.resume_transcription(TranscriptionTask(str(source))) is False
    assert not cp.checkpoint_path(str(source)).exists()
    kept = _kept(source)
    assert len(kept) == 1 and kept[0].read_bytes() == original
    assert cp.recovery_text_path(kept[0]).exists()


def test_unsupported_backend_leaves_a_checkpoint_of_verified_media_in_place(
        resume_env, source, monkeypatch):
    from core.task import TranscriptionTask

    t = resume_env
    monkeypatch.setattr(t, "_current_backend_and_model", lambda: ("cloud_stt", "m"))
    cp.note_source_identity(str(source))
    _write(source, backend="faster_whisper", model_name="m")
    assert t.resume_transcription(TranscriptionTask(str(source))) is False
    assert cp.checkpoint_path(str(source)).exists()
    assert _kept(source) == []
