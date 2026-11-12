"""Store policy and writable-path bootstrap without GUI or package registration."""
from __future__ import annotations

import json
import runpy
import sys
import tempfile
from pathlib import Path

import pytest

from core import distribution


@pytest.fixture
def store_runtime(tmp_path, monkeypatch):
    resources = tmp_path / "resources"
    resources.mkdir()
    marker = resources / "STORE_BUILD.json"
    marker.write_text(json.dumps({
        "schema": 1, "variant": "microsoft-store", "runtime_guards": True,
        "download_policy": "omit",
    }), encoding="utf-8")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(resources), raising=False)
    monkeypatch.setattr(distribution, "_package_family_name", lambda: "Whisper.Test_abcdefghijklm")
    monkeypatch.setattr(distribution, "_local_app_data", lambda: tmp_path / "local")
    return marker


def test_source_environment_cannot_enable_store_mode(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.setenv("STORE_BUILD", "1")
    monkeypatch.setenv("WTS_STORE_BUILD", "1")
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    (tmp_path / "STORE_BUILD.json").write_text('{}', encoding="utf-8")
    assert not distribution.is_store_build()


def test_frozen_marker_enables_policy(store_runtime):
    assert distribution.is_store_build()
    for feature in ("self_update", "media_download", "dynamic_runtime"):
        with pytest.raises(distribution.StoreFeatureUnavailable):
            distribution.require_feature(feature)


def test_store_retain_download_policy_keeps_media_download(store_runtime):
    marker = json.loads(store_runtime.read_text(encoding="utf-8"))
    marker["download_policy"] = "retain"
    store_runtime.write_text(json.dumps(marker), encoding="utf-8")
    assert distribution.is_store_build()
    assert distribution.media_download_enabled()
    distribution.require_feature("media_download")
    for feature in ("self_update", "dynamic_runtime"):
        with pytest.raises(distribution.StoreFeatureUnavailable):
            distribution.require_feature(feature)


def test_store_omit_download_policy_refuses_media_download(store_runtime, monkeypatch):
    monkeypatch.setenv("WTS_STORE_DOWNLOAD_POLICY", "retain")
    assert not distribution.media_download_enabled()
    with pytest.raises(distribution.StoreFeatureUnavailable):
        distribution.require_feature("media_download")


@pytest.mark.parametrize("policy", [None, "", "download", True, 1, [], {}])
def test_store_download_policy_is_required_and_validated(store_runtime, policy):
    marker = json.loads(store_runtime.read_text(encoding="utf-8"))
    if policy is None:
        marker.pop("download_policy")
    else:
        marker["download_policy"] = policy
    store_runtime.write_text(json.dumps(marker), encoding="utf-8")
    with pytest.raises(distribution.StoreBuildError):
        distribution.is_store_build()
    with pytest.raises(distribution.StoreBuildError):
        distribution.media_download_enabled()
    with pytest.raises(distribution.StoreBuildError):
        distribution.require_feature("media_download")


@pytest.mark.parametrize("content", [
    "{", "[]", '{}',
    '{"schema":true,"variant":"microsoft-store","runtime_guards":true,"download_policy":"omit"}',
    '{"schema":1,"variant":"other","runtime_guards":true,"download_policy":"omit"}',
    '{"schema":1,"variant":"microsoft-store","runtime_guards":false,"download_policy":"omit"}',
])
def test_invalid_marker_fails_closed(store_runtime, content):
    store_runtime.write_text(content, encoding="utf-8")
    with pytest.raises(distribution.StoreBuildError):
        distribution.is_store_build()
    with pytest.raises(distribution.StoreBuildError):
        distribution.require_feature("self_update")


def test_frozen_standard_build_has_no_side_effects(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setenv("WTS_PROFILE_DIR", "deliberate-profile")
    before = dict(distribution.os.environ)
    previous_temp = tempfile.tempdir
    assert distribution.bootstrap() is None
    assert dict(distribution.os.environ) == before
    assert tempfile.tempdir == previous_temp
    distribution.require_feature("self_update")
    distribution.require_feature("media_download")
    assert distribution.media_download_enabled()


def test_invalid_marker_encoding_fails_closed(store_runtime):
    store_runtime.write_bytes(b"\xff\xfe")
    with pytest.raises(distribution.StoreBuildError):
        distribution.is_store_build()


def test_store_uses_package_identity_and_ignores_profile_override(store_runtime, tmp_path, monkeypatch):
    monkeypatch.setenv("WTS_PROFILE_DIR", str(tmp_path / "unsafe"))
    expected = tmp_path / "local" / "Packages" / "Whisper.Test_abcdefghijklm" / "LocalState"
    assert distribution.store_profile_root() == expected


def test_missing_identity_fails_before_environment_changes(store_runtime, monkeypatch):
    def no_identity():
        raise distribution.StoreBuildError("Package identity is required.")
    monkeypatch.setattr(distribution, "_package_family_name", no_identity)
    before = dict(distribution.os.environ)
    with pytest.raises(distribution.StoreBuildError, match="identity"):
        distribution.bootstrap()
    assert dict(distribution.os.environ) == before


@pytest.mark.parametrize("family", ["", "../other", "a/b", "a\\b", "a:other", ".."])
def test_invalid_package_family_cannot_escape_root(store_runtime, monkeypatch, family):
    monkeypatch.setattr(distribution, "_package_family_name", lambda: family)
    with pytest.raises(distribution.StoreBuildError):
        distribution.store_profile_root()


def test_bootstrap_routes_profile_temp_and_library_caches(store_runtime, monkeypatch):
    for name in distribution._ENVIRONMENT_SUBDIRS:
        monkeypatch.setenv(name, "old-value")
    monkeypatch.setenv("WTS_PROFILE_DIR", "old-profile")
    monkeypatch.setattr(tempfile, "tempdir", "old-temp")
    root = distribution.bootstrap()
    assert root is not None
    assert distribution.os.environ["WTS_PROFILE_DIR"] == str(root)
    for name, subdir in distribution._ENVIRONMENT_SUBDIRS.items():
        value = Path(distribution.os.environ[name])
        assert value == root / subdir
        assert value.is_dir()
        assert value.is_relative_to(root)
    assert tempfile.gettempdir() == str(root / "temp")
    assert distribution.bootstrap() == root


def test_unknown_feature_is_rejected(monkeypatch):
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    with pytest.raises(ValueError, match="Unknown"):
        distribution.require_feature("self_udpate")


def test_unwritable_store_root_does_not_change_environment(store_runtime, monkeypatch):
    before = dict(distribution.os.environ)
    def fail_mkdir(*args, **kwargs):
        raise PermissionError("Read-only test root")
    monkeypatch.setattr(Path, "mkdir", fail_mkdir)
    with pytest.raises(PermissionError):
        distribution.bootstrap()
    assert dict(distribution.os.environ) == before


def test_runtime_hook_calls_bootstrap(monkeypatch):
    calls = []
    monkeypatch.setattr(distribution, "bootstrap", lambda: calls.append(True))
    hook = Path(__file__).resolve().parents[2] / "platform/windows/store/runtime_hook.py"
    runpy.run_path(str(hook))
    assert calls == [True]
