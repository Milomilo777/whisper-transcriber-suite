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
    now = time.time()

    old_json = tmp_path / "aaa.json"
    old_json.write_text("{}", encoding="utf-8")
    os.utime(old_json, (now - 30 * 86400, now - 30 * 86400))  # 30 days old

    fresh_json = tmp_path / "bbb.json"
    fresh_json.write_text("{}", encoding="utf-8")  # ~now

    old_slice = tmp_path / "ccc.slice.wav"
    old_slice.write_bytes(b"x")
    os.utime(old_slice, (now - 3600, now - 3600))  # 1 hour old

    fresh_slice = tmp_path / "ddd.slice.wav"
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

    old_tmp = tmp_path / "aaa.json.tmp"
    old_tmp.write_text('{"partial":', encoding="utf-8")
    os.utime(old_tmp, (now - 3600, now - 3600))  # 1 hour old

    fresh_tmp = tmp_path / "bbb.json.tmp"
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
