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


def test_sweep_partials_never_raises_on_missing_dir(monkeypatch, tmp_path):
    missing = tmp_path / "does-not-exist"
    monkeypatch.setattr(cp, "partials_dir", lambda: missing)
    # Must not raise even when the dir can't be listed.
    assert cp.sweep_partials() == 0
