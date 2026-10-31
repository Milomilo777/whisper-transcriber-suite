"""Fixpack A regression tests for core.config.

Covers five confirmed bugs in the three-layer configuration loader:

1. A non-finite numeric literal (Infinity / NaN) in an int-typed config key
   used to crash load_config with an uncaught OverflowError at launch.
2. A non-string nested model.name (e.g. {"model": {"name": 123}}) used to
   crash load_config / save_config with AttributeError via hub.model_folder_for.
3. deep_merge_dicts aliased nested dicts from a merge source, so a local
   override mutated the process-wide memoized online config in place.
4. An explicitly empty local config_url did not disable the online fetch (the
   ``or`` fell back to the hard-coded third-party URL).
5. fetch_online_config buffered the whole response body with no size cap.

Every test is hermetic: platformdirs is redirected to tmp_path, urlopen is
monkeypatched, and no real Tk root / network / model is touched.
"""
from __future__ import annotations

import io
import json
import math
from pathlib import Path

import pytest

from core import config as cfg


@pytest.fixture
def isolated_dirs(tmp_path, monkeypatch):
    """Redirect every platformdirs lookup at a tmp_path subfolder.

    Also stubs the legacy-config path away and clears the process-wide
    online memo so tests never leak into one another.
    """
    config_dir = tmp_path / "config"
    cache_dir = tmp_path / "cache"
    monkeypatch.setattr(cfg, "user_config_dir", lambda: config_dir)
    monkeypatch.setattr(cfg, "user_cache_dir", lambda: cache_dir)
    monkeypatch.setattr(
        cfg, "config_path", lambda: str(config_dir / "config.json")
    )
    monkeypatch.setattr(
        cfg, "_legacy_config_path", lambda: str(tmp_path / "no_legacy.json")
    )
    config_dir.mkdir(parents=True, exist_ok=True)
    cfg.refresh_online_config()
    yield tmp_path
    cfg.refresh_online_config()


def _write_local(payload: dict) -> None:
    Path(cfg.config_path()).write_text(
        json.dumps(payload), encoding="utf-8"
    )


def _is_finite_or_missing(value) -> bool:
    return value is None or (
        isinstance(value, (int, float)) and math.isfinite(value)
    )


# --- Fix 1: non-finite numerics --------------------------------------------

def test_infinity_in_int_key_does_not_crash_reverts_to_default(isolated_dirs):
    """A hand-edited config.json with Infinity in an int-typed key must not
    raise OverflowError; the corrupt file is moved aside and defaults win."""
    path = Path(cfg.config_path())
    # Infinity is valid JSON to Python's parser by default — write it raw.
    path.write_text('{"parallel_workers": Infinity}', encoding="utf-8")

    config = cfg.load_config(fetch_online=False)

    assert config["parallel_workers"] == cfg.DEFAULT_CONFIG["parallel_workers"]
    # _read_local_config rejected the non-finite literal as corrupt and
    # renamed the file aside so the next launch starts clean.
    assert Path(str(path) + ".corrupt").exists()


def test_nan_in_float_key_reverts_to_default(isolated_dirs):
    path = Path(cfg.config_path())
    path.write_text('{"vad_threshold": NaN}', encoding="utf-8")

    config = cfg.load_config(fetch_online=False)

    assert config["vad_threshold"] == cfg.DEFAULT_CONFIG["vad_threshold"]


def test_nonfinite_reaching_coercion_pass_is_dropped(isolated_dirs, monkeypatch):
    """Defense in depth: even if a non-finite float reaches the coercion pass
    in-memory (e.g. via a future code path), it reverts to the default rather
    than poisoning downstream int()/comparison logic."""
    merged = cfg.merge_config_sources(
        cfg.DEFAULT_CONFIG,
        online=None,
        local={"vad_threshold": float("inf"), "parallel_workers": 3},
    )
    assert not _is_finite_or_missing(merged.get("vad_threshold"))

    # Feed inf/nan through the load coercion path via a stubbed local reader.
    monkeypatch.setattr(
        cfg, "_read_local_config",
        lambda: {"parallel_workers": float("inf"), "vad_threshold": float("nan")},
    )
    config = cfg.load_config(fetch_online=False)
    assert config["parallel_workers"] == cfg.DEFAULT_CONFIG["parallel_workers"]
    assert config["vad_threshold"] == cfg.DEFAULT_CONFIG["vad_threshold"]


# --- Fix 2: non-string model.name ------------------------------------------

def test_non_string_model_name_does_not_crash_load(isolated_dirs):
    """{"model": {"name": 123}} survives the top-level dict check; the nested
    int name must be coerced away instead of crashing model_folder_for."""
    _write_local({"model": {"name": 123, "url": "u", "md5": "m"}})

    # Must not raise AttributeError: 'int' object has no attribute 'strip'.
    config = cfg.load_config(fetch_online=False)

    # A concrete model_path was still derived (using the placeholder name).
    assert config["model_path"]
    assert "whisper-model" in config["model_path"].replace("\\", "/")


def test_non_string_model_name_does_not_crash_save(isolated_dirs):
    payload = dict(cfg.DEFAULT_CONFIG)
    payload["model"] = {"name": None, "url": "u", "md5": "m"}
    payload["model_path"] = "D:/some/custom/path"

    # Must not raise; the persistable-path computation guards the name.
    cfg.save_config(payload)

    on_disk = json.loads(Path(cfg.config_path()).read_text(encoding="utf-8"))
    assert isinstance(on_disk, dict)


# --- Fix 3: deep_merge_dicts must not alias / mutate a merge source --------

def test_deep_merge_does_not_mutate_source_nested_dict():
    online = {"model_catalog": {"slugX": {"label": "orig", "url": "u"}}}
    local = {"model_catalog": {"slugX": {"label": "LOCAL_OVERRIDE"}}}

    merged = cfg.merge_config_sources(cfg.DEFAULT_CONFIG, online, local)

    # The merged result reflects the local override...
    assert merged["model_catalog"]["slugX"]["label"] == "LOCAL_OVERRIDE"
    # ...but the online INPUT is untouched (purity / no cache contamination).
    assert online["model_catalog"]["slugX"]["label"] == "orig"
    # And the merged nested object is NOT the same object as either source.
    assert merged["model_catalog"]["slugX"] is not online["model_catalog"]["slugX"]
    assert merged["model_catalog"]["slugX"] is not local["model_catalog"]["slugX"]


def test_deep_merge_dicts_new_key_is_deepcopied():
    dest: dict = {}
    src = {"a": {"nested": [1, 2]}}
    cfg.deep_merge_dicts(dest, src)
    dest["a"]["nested"].append(3)
    # Mutating dest must not reach back into src.
    assert src["a"]["nested"] == [1, 2]


def test_online_memo_not_contaminated_across_loads(isolated_dirs, monkeypatch):
    """Two load_config() calls in one process share _ONLINE_MEMO; a local
    catalog override on the first call must NOT leak into the second."""
    online_payload = {
        "model_catalog": {
            "slugX": {"label": "ORIG", "hf_repo": "Systran/faster-whisper-x", "md5": "m"}
        }
    }

    def _fake_urlopen(req, timeout=0):  # noqa: ARG001
        return io.BytesIO(json.dumps(online_payload).encode("utf-8"))

    monkeypatch.setattr(cfg.urllib.request, "urlopen", _fake_urlopen)

    # First load: local overrides the slug label.
    _write_local({"model_catalog": {"slugX": {"label": "FIRST_LOCAL"}}})
    first = cfg.load_config(fetch_online=True)
    assert first["model_catalog"]["slugX"]["label"] == "FIRST_LOCAL"

    # Second load: NO local override of the slug. It must come back from the
    # untouched online layer as ORIG, not the contaminated FIRST_LOCAL.
    _write_local({"theme": "light"})
    second = cfg.load_config(fetch_online=True)
    assert second["model_catalog"]["slugX"]["label"] == "ORIG"
    # The sibling keys from the online layer survived the merge too.
    assert second["model_catalog"]["slugX"]["hf_repo"] == "Systran/faster-whisper-x"


# --- Fix 4: explicitly empty config_url disables the online fetch ----------

def test_empty_local_config_url_disables_fetch(isolated_dirs, monkeypatch):
    """A user who blanks config_url to opt out of the network must NOT have
    the hard-coded default URL silently restored."""
    _write_local({"config_url": ""})

    def _must_not_call(req, timeout=0):  # noqa: ARG001
        raise AssertionError("urlopen must not be called for an empty config_url")

    monkeypatch.setattr(cfg.urllib.request, "urlopen", _must_not_call)

    # No network call -> no exception.
    config = cfg.load_config(fetch_online=True)
    assert config["theme"] == cfg.DEFAULT_CONFIG["theme"]


def test_absent_config_url_still_uses_default(isolated_dirs, monkeypatch):
    """A MISSING config_url key still falls back to the default URL (the fix
    only special-cases an explicitly-empty value)."""
    called = {"n": 0}
    online_payload = {"latest_version": "9.9.9"}

    def _fake_urlopen(req, timeout=0):  # noqa: ARG001
        called["n"] += 1
        return io.BytesIO(json.dumps(online_payload).encode("utf-8"))

    monkeypatch.setattr(cfg.urllib.request, "urlopen", _fake_urlopen)
    _write_local({"theme": "dark"})  # no config_url key

    config = cfg.load_config(fetch_online=True)
    assert called["n"] == 1  # the default URL was fetched
    assert config["latest_version"] == "9.9.9"


# --- Fix 5: response-size cap ----------------------------------------------

def test_fetch_online_rejects_oversized_body(tmp_path, monkeypatch):
    """A body larger than MAX_CONFIG_BYTES is not parsed; the call falls back
    to the cache instead of buffering / returning the giant payload."""
    cached = {"latest_version": "cached"}
    cache = tmp_path / "cache.json"
    cache.write_text(json.dumps(cached), encoding="utf-8")

    big = b'{"latest_version": "' + b"x" * (cfg.MAX_CONFIG_BYTES + 1024) + b'"}'

    def _fake_urlopen(req, timeout=0):  # noqa: ARG001
        return io.BytesIO(big)

    monkeypatch.setattr(cfg.urllib.request, "urlopen", _fake_urlopen)
    result = cfg.fetch_online_config("https://host/app.json", cache_path=cache)
    assert result == cached  # oversized body rejected -> cache fallback


def test_fetch_online_rejects_oversized_content_length(tmp_path, monkeypatch):
    """A Content-Length above the cap aborts before the body is read."""
    cached = {"latest_version": "cached"}
    cache = tmp_path / "cache.json"
    cache.write_text(json.dumps(cached), encoding="utf-8")

    read_happened = {"yes": False}

    class _FakeResp:
        headers = {"Content-Length": str(cfg.MAX_CONFIG_BYTES + 1)}

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self, *a):
            read_happened["yes"] = True
            return b"{}"

    def _fake_urlopen(req, timeout=0):  # noqa: ARG001
        return _FakeResp()

    monkeypatch.setattr(cfg.urllib.request, "urlopen", _fake_urlopen)
    result = cfg.fetch_online_config("https://host/app.json", cache_path=cache)
    assert result == cached
    assert read_happened["yes"] is False  # body never read


def test_fetch_online_accepts_normal_body(tmp_path, monkeypatch):
    """A small, well-formed body still parses (no false positive from the cap)."""
    payload = {"stats_url": "https://x/stats"}

    def _fake_urlopen(req, timeout=0):  # noqa: ARG001
        return io.BytesIO(json.dumps(payload).encode("utf-8"))

    monkeypatch.setattr(cfg.urllib.request, "urlopen", _fake_urlopen)
    cache = tmp_path / "cache.json"
    result = cfg.fetch_online_config("https://host/app.json", cache_path=cache)
    assert result == payload


def test_fetch_online_rejects_nonfinite_in_payload(tmp_path, monkeypatch):
    """An Infinity literal in the online payload is treated as corrupt and the
    call falls through to the cache (then to {})."""
    def _fake_urlopen(req, timeout=0):  # noqa: ARG001
        return io.BytesIO(b'{"latest_version": Infinity}')

    monkeypatch.setattr(cfg.urllib.request, "urlopen", _fake_urlopen)
    cache = tmp_path / "missing.json"
    result = cfg.fetch_online_config("https://host/app.json", cache_path=cache)
    assert result == {}
