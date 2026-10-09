"""Corresponding source of the bundled GPL FFmpeg builds: the pin list, the fetch tool (stubbed
downloads only) and the notices / release docs that must name the same sources."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import io
import json
import re
import sys
import urllib.error
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, TOOLS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_load("fetch_windows_build_deps")  # the source tool imports it by name
src = _load("fetch_ffmpeg_source")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _dep(data: bytes, platform: str = "windows", name: str = "ffmpeg-source-x") -> dict[str, Any]:
    return {"name": name, "version": "1", "url": "https://example.invalid/ffmpeg.tar",
            "size": len(data), "sha256": _sha(data), "platform": platform,
            "asset_name": "App-v{app_version}-source-ffmpeg-1.tar", "files": []}


def _opener(data: bytes, calls: list[str] | None = None):
    def opener(url: str, timeout: float):
        if calls is not None:
            calls.append(url)
        return io.BytesIO(data)
    return opener


def _no_leftovers(folder: Path) -> list[str]:
    return sorted(p.name for p in folder.iterdir())


# ------------------------------------------------------------------ the committed pin list

def test_committed_pins_are_valid_and_cover_both_platforms():
    deps = src.load_pins()
    assert {d["platform"] for d in deps} == {"windows", "macos"}
    assert all(d["url"].startswith("https://") for d in deps)


def _windows_build() -> dict[str, Any]:
    return next(d for d in json.loads(
        (ROOT / "platform" / "windows" / "build-deps.json").read_text(encoding="utf-8"))["deps"]
        if d["name"] == "ffmpeg")


def test_windows_pin_names_the_source_of_the_pinned_windows_build():
    windows = next(d for d in src.load_pins() if d["platform"] == "windows")
    build = _windows_build()
    release = re.match(r"([0-9]+\.[0-9]+(?:\.[0-9]+)?) ", build["version"])
    if release:
        # A gyan.dev release build is the upstream release: the source is the release tarball.
        version = release.group(1)
        assert windows["url"] == f"https://ffmpeg.org/releases/ffmpeg-{version}.tar.xz"
        assert f"FFmpeg {version} " in windows["version"]
        assert f"-source-ffmpeg-{version}." in windows["asset_name"]
        assert f"/{version}/ffmpeg-{version}-" in build["url"]
        return
    short = re.search(r"git-([0-9a-f]{10})", build["version"])  # a gyan.dev git build
    assert short, build["version"]
    assert short.group(1) in windows["version"]
    assert short.group(1) in windows["url"]
    assert short.group(1) in windows["asset_name"]


def test_windows_ffmpeg_pin_is_not_older_than_the_security_fixed_release():
    # FFmpeg 9.0 / 9.0.2 carry the fixes for CVE-2026-8461, -30998, -30999, -66038, -70629 and
    # -70631; the 2026-05-06 git build that was pinned before predates them.
    release = re.match(r"([0-9]+)\.([0-9]+)(?:\.([0-9]+))? ", _windows_build()["version"])
    assert release, "pin the Windows FFmpeg to a numbered release, not an old git snapshot"
    assert tuple(int(x or 0) for x in release.groups()) >= (9, 0, 2)


def test_macos_pin_matches_the_version_of_the_pinned_mac_binaries():
    macos = next(d for d in src.load_pins() if d["platform"] == "macos")
    script = (ROOT / "platform" / "macos" / "pyinstaller" / "fetch_mac_binaries.sh").read_text(
        encoding="utf-8")
    for arch in ("X86_64", "ARM64"):
        url = re.search(rf'^FFMPEG_{arch}_URL="([^"]+)"', script, re.M)
        assert url, arch
        assert re.search(r"(?<![0-9.])9\.0\.2(?![0-9.]*[0-9])", url.group(1)), url.group(1)
    assert "ffmpeg-9.0.2.tar.xz" in macos["url"]
    assert "9.0.2" in macos["asset_name"]


def test_validator_rejects_a_pin_list_missing_a_platform(tmp_path):
    pins = tmp_path / "pins.json"
    only_windows = [d for d in src.load_pins() if d["platform"] == "windows"]
    pins.write_text(json.dumps({"deps": only_windows}), encoding="utf-8")
    with pytest.raises(src.FetchError, match="every platform"):
        src.load_pins(pins)


def test_validator_rejects_a_duplicate_asset_name_for_different_files(tmp_path):
    deps = copy.deepcopy(src.load_pins())
    deps[1]["asset_name"] = deps[0]["asset_name"]
    deps[1]["sha256"] = "0" * 64
    pins = tmp_path / "pins.json"
    pins.write_text(json.dumps({"deps": deps}), encoding="utf-8")
    with pytest.raises(src.FetchError, match="used twice"):
        src.load_pins(pins)


def test_two_platforms_may_share_one_identical_tarball(tmp_path):
    data = b"one official release tarball"
    windows, macos = _dep(data, "windows", "w"), _dep(data, "macos", "m")
    pins = tmp_path / "pins.json"
    pins.write_text(json.dumps({"deps": [windows, macos]}), encoding="utf-8")
    deps = src.load_pins(pins)
    out = tmp_path / "out"
    out.mkdir()
    calls: list[str] = []
    paths = src.fetch(deps, out, "2.0.0", opener=_opener(data, calls))
    assert paths[0] == paths[1] and calls == ["https://example.invalid/ffmpeg.tar"]  # fetched once
    assert _no_leftovers(out) == ["App-v2.0.0-source-ffmpeg-1.tar"]
    assert src.check(deps, out, "2.0.0") == []
    (out / paths[0].name).unlink()
    assert src.check(deps, out, "2.0.0") == ["missing: App-v2.0.0-source-ffmpeg-1.tar"]  # reported once


@pytest.mark.parametrize("bad", ["../escape-{app_version}.tar", "noversion.tar", "a b-{app_version}.tar",
                                 "ok-{app_version}.tar\n"])
def test_validator_rejects_unsafe_asset_names(tmp_path, bad):
    deps = copy.deepcopy(src.load_pins())
    deps[0]["asset_name"] = bad
    pins = tmp_path / "pins.json"
    pins.write_text(json.dumps({"deps": deps}), encoding="utf-8")
    with pytest.raises(src.FetchError, match="asset_name"):
        src.load_pins(pins)


# ------------------------------------------------------------------ the fetch tool

def test_fetch_writes_the_verified_tarball_under_its_release_name(tmp_path):
    data = b"pretend source tarball"
    calls: list[str] = []
    paths = src.fetch([_dep(data)], tmp_path, "2.0.0", opener=_opener(data, calls))
    assert [p.name for p in paths] == ["App-v2.0.0-source-ffmpeg-1.tar"]
    assert paths[0].read_bytes() == data
    assert _no_leftovers(tmp_path) == ["App-v2.0.0-source-ffmpeg-1.tar"]
    assert calls == ["https://example.invalid/ffmpeg.tar"]


def test_hash_mismatch_fails_loudly_and_leaves_nothing_behind(tmp_path):
    good = b"the real source"
    evil = b"the real sourcE"  # same length, different bytes
    with pytest.raises(src.FetchError, match="sha256"):
        src.fetch([_dep(good)], tmp_path, "2.0.0", opener=_opener(evil))
    assert _no_leftovers(tmp_path) == []


def test_oversized_download_fails_and_leaves_nothing_behind(tmp_path):
    data = b"x" * 100
    with pytest.raises(src.FetchError, match="larger"):
        src.fetch([_dep(data)], tmp_path, "2.0.0", opener=_opener(data + b"extra"))
    assert _no_leftovers(tmp_path) == []


def test_network_failure_after_retries_leaves_nothing_behind(tmp_path, monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)

    def opener(url: str, timeout: float):
        raise urllib.error.URLError("connection reset")
    with pytest.raises(src.FetchError, match="failed after"):
        src.fetch([_dep(b"data")], tmp_path, "2.0.0", opener=opener)
    assert _no_leftovers(tmp_path) == []


def test_a_bad_file_in_the_output_folder_is_replaced_not_trusted(tmp_path):
    data = b"the real source"
    (tmp_path / "App-v2.0.0-source-ffmpeg-1.tar").write_bytes(b"corrupt")
    src.fetch([_dep(data)], tmp_path, "2.0.0", opener=_opener(data))
    assert (tmp_path / "App-v2.0.0-source-ffmpeg-1.tar").read_bytes() == data


def test_a_verified_file_is_not_downloaded_again(tmp_path):
    data = b"the real source"
    (tmp_path / "App-v2.0.0-source-ffmpeg-1.tar").write_bytes(data)
    calls: list[str] = []
    src.fetch([_dep(data)], tmp_path, "2.0.0", opener=_opener(data, calls))
    assert calls == []


def test_check_reports_missing_and_differing_files_without_network(tmp_path):
    data = b"the real source"
    dep = _dep(data)
    assert src.check([dep], tmp_path, "2.0.0") == ["missing: App-v2.0.0-source-ffmpeg-1.tar"]
    (tmp_path / "App-v2.0.0-source-ffmpeg-1.tar").write_bytes(b"corrupt")
    assert src.check([dep], tmp_path, "2.0.0") == ["differs from the pin: App-v2.0.0-source-ffmpeg-1.tar"]
    (tmp_path / "App-v2.0.0-source-ffmpeg-1.tar").write_bytes(data)
    assert src.check([dep], tmp_path, "2.0.0") == []


@pytest.mark.parametrize("version", [
    "2.0", "v2.0.0", "2.0.0-dev", "../2.0.0", "", "2.0.0\n",
    chr(0x662) + "." + chr(0x660) + "." + chr(0x660),  # Arabic-Indic digits: not plain ASCII digits
])
def test_app_version_must_be_plain_x_y_z(version):
    with pytest.raises(src.FetchError, match="X.Y.Z"):
        src.asset_name(_dep(b"d"), version)


def test_select_filters_by_platform_and_rejects_unknown():
    deps = [_dep(b"a", "windows", "w"), _dep(b"b", "macos", "m")]
    assert [d["name"] for d in src.select(deps, "macos")] == ["m"]
    assert [d["name"] for d in src.select(deps, "all")] == ["w", "m"]
    with pytest.raises(src.FetchError, match="platform"):
        src.select(deps, "linux")


def test_main_downloads_nothing_for_a_bad_version(tmp_path, capsys):
    assert src.main(["--out", str(tmp_path), "--app-version", "latest"]) == 1
    assert "X.Y.Z" in capsys.readouterr().err
    assert _no_leftovers(tmp_path) == []


# ------------------------------------------------------------------ notices and release docs

def test_notices_name_every_pinned_source_and_the_release_copy():
    notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    for dep in src.load_pins():
        assert dep["url"] in notices, dep["name"]
        assert dep["sha256"] in notices, dep["name"]
    assert "attached to each GitHub release" in notices
    assert "martin-riedl.de/ffmpeg/build-script" in notices


def test_release_process_documents_attaching_the_source():
    text = (ROOT / "docs" / "RELEASE_PROCESS.md").read_text(encoding="utf-8")
    assert "tools/fetch_ffmpeg_source.py" in text
    assert "source-ffmpeg" in text
    # The tool and the docs agree on the naming scheme.
    for dep in src.load_pins():
        name = dep["asset_name"].replace("{app_version}", "X.Y.Z")
        assert name in text, name
