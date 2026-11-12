"""Tests for core._checkpoint.sweep_partials (audit findings [5] / P2-8).

The partials/ dir otherwise grows without bound: a cancelled-but-never-
resumed or crash-then-declined run leaves its checkpoint JSON (which holds
the full captured-segments list) forever, and a worker killed mid-resume
orphans its .slice.wav. The startup sweep reaps both by age.
"""
from __future__ import annotations

import os
import time

from core import _checkpoint as cp


def test_sweep_partials_removes_old_json_and_orphan_slices(monkeypatch, tmp_path):
    monkeypatch.setattr(cp, "partials_dir", lambda: tmp_path)
    monkeypatch.setattr("core._proc.pid_may_be_alive", lambda pid: False)
    now = time.time()

    old_json = tmp_path / ("a" * 40 + ".json")
    old_json.write_text("{}", encoding="utf-8")
    os.utime(old_json, (now - 30 * 86400, now - 30 * 86400))  # 30 days old

    fresh_json = tmp_path / ("b" * 40 + ".json")
    fresh_json.write_text("{}", encoding="utf-8")  # ~now

    old_slice = tmp_path / ("c" * 40 + ".123-456.slice.wav")
    old_slice.write_bytes(b"x")
    os.utime(old_slice, (now - 3600, now - 3600))  # 1 hour old

    fresh_slice = tmp_path / ("d" * 40 + ".234-567.slice.wav")
    fresh_slice.write_bytes(b"x")  # ~now (a live resume could hold it)

    removed = cp.sweep_partials()

    assert not old_json.exists(), "aged-out checkpoint JSON should be removed"
    assert fresh_json.exists(), "a recent checkpoint must be kept (resumable)"
    assert not old_slice.exists(), "an orphaned old slice should be removed"
    assert fresh_slice.exists(), "a fresh slice (possible live resume) is kept"
    assert removed == 2


def test_sweep_partials_removes_stale_checkpoint_tmp(monkeypatch, tmp_path):
    """A worker killed mid-checkpoint-write leaves ``<key>.json.tmp``
    behind; nothing else ever reclaims it (only ``*.json`` and
    ``*.slice.wav`` were swept), so it lived in partials/ forever."""
    monkeypatch.setattr(cp, "partials_dir", lambda: tmp_path)
    now = time.time()

    old_tmp = tmp_path / ("a" * 40 + ".json.tmp")
    old_tmp.write_text('{"partial":', encoding="utf-8")
    os.utime(old_tmp, (now - 3600, now - 3600))  # 1 hour old

    fresh_tmp = tmp_path / ("b" * 40 + ".json.tmp")
    fresh_tmp.write_text('{"partial":', encoding="utf-8")  # ~now

    removed = cp.sweep_partials()

    assert not old_tmp.exists(), "stale checkpoint write scratch is reaped"
    assert fresh_tmp.exists(), "a fresh scratch file (live writer) is kept"
    assert removed == 1


def test_sweep_partials_removes_scratch_named_as_the_writer_names_it(monkeypatch, tmp_path):
    """The writer uses mkstemp, so its scratch is ``<sha1>.json.<random>.tmp``
    and never matched the ``*.json.tmp`` rule above (S01-3)."""
    import tempfile

    monkeypatch.setattr(cp, "user_data_dir", lambda: tmp_path)
    src = tmp_path / "a.wav"
    src.write_bytes(b"x")
    prefix = cp.checkpoint_path(str(src)).name + "."
    now = time.time()
    names = []
    for _ in range(2):
        fd, name = tempfile.mkstemp(dir=str(cp.partials_dir()), prefix=prefix, suffix=".tmp")
        os.close(fd)
        names.append(name)
    os.utime(names[0], (now - 3600, now - 3600))
    unrelated = cp.partials_dir() / "report.json.notes.tmp"
    unrelated.write_text("keep", encoding="utf-8")
    os.utime(unrelated, (now - 3600, now - 3600))

    removed = cp.sweep_partials()

    assert not os.path.exists(names[0]), "a killed writer's old scratch is reaped"
    assert os.path.exists(names[1]), "a live writer's fresh scratch is kept"
    assert unrelated.exists(), "a file that is not checkpoint scratch is kept"
    assert removed == 1


def test_fingerprint_changes_only_for_non_default_guard_and_window(monkeypatch):
    base = {"vad_enabled": True, "whisper_model": "small"}
    plain = cp.config_fingerprint(base)
    import hashlib
    import json

    assert plain == hashlib.sha1(
        json.dumps(base, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    # Default values, in any spelling, keep every existing checkpoint valid.
    for extra in ({"vad_window_s": 30}, {"vad_window_s": "30"}, {"vad_window_s": True},
                  {"loop_guard_repeats": 3}, {"loop_guard_repeats": "3"},
                  {"loop_guard_repeats": True}):
        assert cp.config_fingerprint({**base, **extra}) == plain, extra
    for extra in ({"vad_window_s": 0}, {"vad_window_s": 10},
                  {"loop_guard_repeats": 0}, {"loop_guard_repeats": 5}):
        assert cp.config_fingerprint({**base, **extra}) != plain, extra
    assert cp.config_fingerprint({**base, "loop_guard_repeats": 5}) != \
        cp.config_fingerprint({**base, "loop_guard_repeats": 6})


def test_sweep_partials_never_raises_on_missing_dir(monkeypatch, tmp_path):
    missing = tmp_path / "does-not-exist"
    monkeypatch.setattr(cp, "partials_dir", lambda: missing)
    # Must not raise even when the dir can't be listed.
    assert cp.sweep_partials() == 0


def test_sweep_preserves_actual_timing_recovery_after_retention_age(monkeypatch, tmp_path):
    import json
    from pathlib import Path
    from core import transcriber
    monkeypatch.setattr(cp, "user_data_dir", lambda: tmp_path)
    segments = [{"start": 30.0, "end": 40.0, "text": "Irreplaceable decoded words",
                 "words": [{"start": 30.0, "end": 31.0, "word": "Irreplaceable"}]}]
    kept = Path(transcriber._keep_timing_recovery("source.wav", segments, "synthetic timing failure"))
    original = kept.read_bytes()
    assert json.loads(original)["segments"] == segments
    os.utime(kept, (1, 1))
    removed = cp.sweep_partials()
    assert kept.exists(), "a recovery record is not an expired resume checkpoint"
    assert kept.read_bytes() == original
    assert removed == 0


def test_sweep_preserves_unrelated_json_scratch_and_audio(monkeypatch, tmp_path):
    monkeypatch.setattr(cp, "partials_dir", lambda: tmp_path)
    names = ["edited-transcript.json", "manual-recovery.json", "notes.json.tmp",
             "original.slice.wav", "A" * 40 + ".json", "a" * 39 + ".json",
             "a" * 41 + ".json", "g" * 40 + ".json", "notes.json.private.tmp"]
    for name in names:
        path = tmp_path / name
        path.write_bytes(b"irreplaceable unrelated bytes")
        os.utime(path, (1, 1))
    assert cp.sweep_partials() == 0
    for name in names:
        assert (tmp_path / name).read_bytes() == b"irreplaceable unrelated bytes"


def test_sweep_keeps_recent_owned_files_and_reaps_all_owned_stale_shapes(monkeypatch, tmp_path):
    import tempfile
    monkeypatch.setattr(cp, "partials_dir", lambda: tmp_path)
    key = cp.source_key(str(tmp_path / "source.wav"))
    # Current writer shapes, plus older fixed scratch/hash-only or PID slices.
    monkeypatch.setattr("core._proc.pid_may_be_alive", lambda pid: False)
    suffixes = [".json", ".json.tmp", ".123.slice.wav", ".123-456.slice.wav"]
    legacy = tmp_path / (key + ".slice.wav")
    legacy.write_bytes(b"unknown legacy owner")
    os.utime(legacy, (1, 1))
    stale = [tmp_path / (key + suffix) for suffix in suffixes]
    for path in stale:
        path.write_bytes(b"owned stale data")
        os.utime(path, (1, 1))
    fd, name = tempfile.mkstemp(prefix=key+".json.", suffix=".tmp", dir=tmp_path)
    os.close(fd)
    os.utime(name, (1, 1))
    assert cp.sweep_partials() == len(stale) + 1
    assert not any(path.exists() for path in stale)
    assert not os.path.exists(name)
    assert legacy.read_bytes() == b"unknown legacy owner"


def test_sweep_age_thresholds_still_control_valid_checkpoint_names(monkeypatch, tmp_path):
    monkeypatch.setattr(cp, "partials_dir", lambda: tmp_path)
    key = cp.source_key("synthetic-source.wav")
    checkpoint = tmp_path / (key + ".json")
    checkpoint.write_bytes(b"owned checkpoint")
    aged = time.time() - 20 * 86400
    os.utime(checkpoint, (aged, aged))
    assert cp.sweep_partials(max_age_days=30) == 0
    assert checkpoint.read_bytes() == b"owned checkpoint"
    assert cp.sweep_partials(max_age_days=14) == 1
    assert not checkpoint.exists()
