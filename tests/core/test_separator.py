"""Tests for the Demucs vocal separator wrapper."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

from core import separator as sep


def test_is_available_false_when_demucs_missing(monkeypatch):
    monkeypatch.setitem(sys.modules, "demucs", None)
    assert sep.is_available() is False
    assert "demucs" in sep.availability_reason()


def test_is_available_restores_gc_state():
    """Regression for the 2026-08-15 GC-mid-import crash class (see
    core/backends/google_cloud_stt.py); demucs pulls torch, same risk."""
    import gc
    for was_enabled in (True, False):
        if was_enabled:
            gc.enable()
        else:
            gc.disable()
        try:
            sep.is_available()
            assert gc.isenabled() is was_enabled
        finally:
            gc.enable()


# ---------- behaviour matrix ---------------------------------------------------


def test_separate_vocals_disabled_returns_input(tmp_path):
    src = tmp_path / "audio.wav"
    src.write_bytes(b"riff")
    assert sep.separate_vocals(str(src), enabled=False) == str(src)


def test_separate_vocals_missing_demucs_returns_input(tmp_path, monkeypatch):
    monkeypatch.setattr(sep, "is_available", lambda: False)
    src = tmp_path / "audio.wav"
    src.write_bytes(b"riff")
    logs: list[str] = []
    out = sep.separate_vocals(str(src), enabled=True, log=logs.append)
    assert out == str(src)
    assert any("demucs" in s.lower() for s in logs)


def test_separate_vocals_cache_hit_skips_demucs(tmp_path, monkeypatch):
    src = tmp_path / "audio.wav"
    src.write_bytes(b"\x00" * 4096)
    monkeypatch.setattr(sep, "is_available", lambda: True)
    monkeypatch.setattr(sep, "cache_dir", lambda: tmp_path / "cache")
    # Pre-create the cached vocals stem so the cache-hit branch runs.
    cached = sep._cached_vocals_path(str(src), sep.DEFAULT_MODEL)
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_bytes(b"v" * 4096)
    # If demucs were invoked we'd see a CLI call; trip-wire it.
    monkeypatch.setattr(
        sep, "_run_demucs_cli",
        lambda *a, **kw: pytest.fail("demucs ran on cache hit"),
    )
    out = sep.separate_vocals(str(src), enabled=True)
    assert out == str(cached)


def test_separate_vocals_cache_hit_refreshes_mtime(tmp_path, monkeypatch):
    """A cache hit counts as use: the stem's mtime is refreshed so
    LRU eviction / the in-use grace period see it as active."""
    src = tmp_path / "audio.wav"
    src.write_bytes(b"\x00" * 4096)
    monkeypatch.setattr(sep, "is_available", lambda: True)
    monkeypatch.setattr(sep, "cache_dir", lambda: tmp_path / "cache")
    cached = sep._cached_vocals_path(str(src), sep.DEFAULT_MODEL)
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_bytes(b"v" * 4096)
    stale = time.time() - 10 * 86400
    os.utime(cached, (stale, stale))

    out = sep.separate_vocals(str(src), enabled=True)
    assert out == str(cached)
    assert cached.stat().st_mtime > stale + 86400


def test_separate_vocals_falls_back_to_input_when_stem_cannot_be_cached(tmp_path, monkeypatch):
    """If demucs's vocals stem can neither be moved nor copied into
    the cache, return the original input -- not a path inside the
    temp tree that finally: is about to delete."""
    src = tmp_path / "audio.wav"
    src.write_bytes(b"\x00" * 4096)
    monkeypatch.setattr(sep, "is_available", lambda: True)
    monkeypatch.setattr(sep, "cache_dir", lambda: tmp_path / "cache")

    def _fake_run(audio_path, out_dir, *, model, log=None):
        stem_dir = Path(out_dir) / model / Path(audio_path).stem
        stem_dir.mkdir(parents=True, exist_ok=True)
        (stem_dir / "vocals.wav").write_bytes(b"v" * 8192)

    def _locked_replace(*_a, **_kw):
        raise OSError("locked")

    def _no_space_copyfile(*_a, **_kw):
        raise OSError("no space left on device")

    monkeypatch.setattr(sep, "_run_demucs_cli", _fake_run)
    monkeypatch.setattr(sep.os, "replace", _locked_replace)
    monkeypatch.setattr(sep.shutil, "copyfile", _no_space_copyfile)

    out = sep.separate_vocals(str(src), enabled=True)
    assert out == str(src)


def test_separate_vocals_orphan_survivor_is_keyed_and_prunable(tmp_path, monkeypatch):
    """When the stem can be rescued out of the temp tree but not into
    the hashed cache slot, the survivor must be per-source (no
    cross-source collision) and match the '*_vocals.wav' prune glob
    (no permanent leak) -- the old bare 'vocals.wav' name did neither."""
    src = tmp_path / "audio.wav"
    src.write_bytes(b"\x00" * 4096)
    other = tmp_path / "other.wav"
    other.write_bytes(b"\x01" * 4096)
    monkeypatch.setattr(sep, "is_available", lambda: True)
    monkeypatch.setattr(sep, "cache_dir", lambda: tmp_path / "cache")

    def _fake_run(audio_path, out_dir, *, model, log=None):
        stem_dir = Path(out_dir) / model / Path(audio_path).stem
        stem_dir.mkdir(parents=True, exist_ok=True)
        (stem_dir / "vocals.wav").write_bytes(b"v" * 8192)

    monkeypatch.setattr(sep, "_run_demucs_cli", _fake_run)
    monkeypatch.setattr(
        sep.os, "replace",
        lambda *_a, **_kw: (_ for _ in ()).throw(OSError("locked")),
    )
    real_copyfile = sep.shutil.copyfile

    def _flaky_copyfile(s, d, **_kw):
        if Path(d).name.endswith("_orphan_vocals.wav"):
            return real_copyfile(s, d)
        raise OSError("locked cache slot")

    monkeypatch.setattr(sep.shutil, "copyfile", _flaky_copyfile)

    out_a = sep.separate_vocals(str(src), enabled=True)
    out_b = sep.separate_vocals(str(other), enabled=True)
    assert out_a != out_b
    assert Path(out_a).name.endswith("_orphan_vocals.wav")
    assert Path(out_b).name.endswith("_orphan_vocals.wav")
    assert Path(out_a).is_file() and Path(out_b).is_file()
    prunable = {p.name for p in (tmp_path / "cache").glob("*_vocals.wav")}
    assert Path(out_a).name in prunable and Path(out_b).name in prunable


def test_separate_vocals_falls_back_to_input_on_demucs_error(tmp_path, monkeypatch):
    src = tmp_path / "audio.wav"
    src.write_bytes(b"\x00" * 4096)
    monkeypatch.setattr(sep, "is_available", lambda: True)
    monkeypatch.setattr(sep, "cache_dir", lambda: tmp_path / "cache")

    def _boom(*a, **kw):
        raise RuntimeError("demucs exploded")

    monkeypatch.setattr(sep, "_run_demucs_cli", _boom)
    logs: list[str] = []
    out = sep.separate_vocals(str(src), enabled=True, log=logs.append)
    assert out == str(src)
    assert any("demucs" in s.lower() for s in logs)


# ---------- cache eviction (P2-6 / finding [6]) --------------------------------


def _make_stem(cache: Path, name: str, size: int, mtime: float) -> Path:
    cache.mkdir(parents=True, exist_ok=True)
    p = cache / f"{name}_vocals.wav"
    p.write_bytes(b"x" * size)
    os.utime(p, (mtime, mtime))
    return p


def test_prune_cache_evicts_oldest_over_budget(tmp_path, monkeypatch):
    cache = tmp_path / "demucs"
    monkeypatch.setattr(sep, "cache_dir", lambda: cache)
    mb = 1024 * 1024
    old = _make_stem(cache, "a", mb, 1000.0)
    mid = _make_stem(cache, "b", mb, 2000.0)
    new = _make_stem(cache, "c", mb, 3000.0)

    # Budget 2 MB, 3 MB present → exactly one (the oldest) is evicted.
    removed = sep.prune_cache(budget_mb=2)
    assert removed == 1
    assert not old.exists()
    assert mid.exists()
    assert new.exists()


def test_prune_cache_never_evicts_the_keeper(tmp_path, monkeypatch):
    cache = tmp_path / "demucs"
    monkeypatch.setattr(sep, "cache_dir", lambda: cache)
    mb = 1024 * 1024
    keeper = _make_stem(cache, "a", mb, 1000.0)  # oldest → would be first out
    _make_stem(cache, "b", mb, 2000.0)
    _make_stem(cache, "c", mb, 3000.0)

    # Budget 1 MB, but the just-written keeper (oldest) must survive.
    sep.prune_cache(budget_mb=1, keep=str(keeper))
    assert keeper.exists()


def test_prune_cache_disabled_when_budget_zero(tmp_path, monkeypatch):
    cache = tmp_path / "demucs"
    monkeypatch.setattr(sep, "cache_dir", lambda: cache)
    _make_stem(cache, "a", 1024 * 1024, 1000.0)
    assert sep.prune_cache(budget_mb=0) == 0
    assert (cache / "a_vocals.wav").exists()


def test_prune_cache_keeps_recently_written_stem(tmp_path, monkeypatch):
    """A fresh stem may be mid-read by another concurrent worker, so
    the in-use grace period must protect it even over budget -- the
    old code evicted it before the reader could open it."""
    cache = tmp_path / "demucs"
    monkeypatch.setattr(sep, "cache_dir", lambda: cache)
    mb = 1024 * 1024
    now = time.time()
    fresh = _make_stem(cache, "fresh", 2 * mb, now)
    old = _make_stem(cache, "old", 2 * mb, now - 3600)

    removed = sep.prune_cache(budget_mb=1)
    assert fresh.exists()
    assert not old.exists()
    assert removed == 1


def test_clear_cache_removes_dir(tmp_path, monkeypatch):
    cache = tmp_path / "demucs"
    monkeypatch.setattr(sep, "cache_dir", lambda: cache)
    _make_stem(cache, "a", 1024, 1000.0)
    sep.clear_cache()
    assert not cache.exists()


def test_separate_vocals_caches_run_output(tmp_path, monkeypatch):
    """A successful demucs run must move its vocals.wav into the cache
    so the next call short-circuits."""
    src = tmp_path / "audio.wav"
    src.write_bytes(b"\x00" * 4096)
    monkeypatch.setattr(sep, "is_available", lambda: True)
    cache = tmp_path / "cache"
    monkeypatch.setattr(sep, "cache_dir", lambda: cache)

    def _fake_run(audio_path, out_dir, *, model, log=None):
        # Mimic demucs's typical output layout: out_dir/<model>/<stem>/vocals.wav
        stem_dir = Path(out_dir) / model / Path(audio_path).stem
        stem_dir.mkdir(parents=True, exist_ok=True)
        (stem_dir / "vocals.wav").write_bytes(b"v" * 8192)

    monkeypatch.setattr(sep, "_run_demucs_cli", _fake_run)
    out = sep.separate_vocals(str(src), enabled=True)
    cached = sep._cached_vocals_path(str(src), sep.DEFAULT_MODEL)
    assert out == str(cached)
    assert cached.exists()
    assert cached.read_bytes() == b"v" * 8192


# ---------- cache key ----------------------------------------------------------


def test_cache_key_changes_with_mtime(tmp_path):
    p = tmp_path / "x.wav"
    p.write_bytes(b"a" * 1024)
    k1 = sep._cache_key(str(p), "htdemucs")
    import os, time
    # Bump mtime by 10 seconds — same path, different cache key.
    new_mtime = p.stat().st_mtime + 10
    os.utime(str(p), (new_mtime, new_mtime))
    k2 = sep._cache_key(str(p), "htdemucs")
    assert k1 != k2


def test_cache_key_differs_per_model(tmp_path):
    p = tmp_path / "x.wav"
    p.write_bytes(b"a" * 1024)
    k1 = sep._cache_key(str(p), "htdemucs")
    k2 = sep._cache_key(str(p), "mdx_extra")
    assert k1 != k2


def test_cache_key_stable_for_missing_path():
    # Should not crash even when the file doesn't exist.
    k1 = sep._cache_key("/no/such/file.wav", "htdemucs")
    k2 = sep._cache_key("/no/such/file.wav", "htdemucs")
    assert k1 == k2


def test_find_vocals_in_descends_into_subdirs(tmp_path):
    nested = tmp_path / "a" / "b" / "c"
    nested.mkdir(parents=True)
    target = nested / "vocals.wav"
    target.write_bytes(b"x")
    found = sep._find_vocals_in(tmp_path)
    assert found == target
