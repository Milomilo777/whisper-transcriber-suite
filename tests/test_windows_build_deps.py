"""Pinned Windows build downloads: the pin list, the fetch script, the build manifest tool and the
CI workflow that builds the installer (.github/workflows/windows-installer.yml)."""
from __future__ import annotations

import copy
import hashlib
import http.client
import importlib.util
import io
import json
import os
import re
import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "windows-installer.yml"
BAT = ROOT / "build_embed_installer.bat"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


fetch = _load("fetch_windows_build_deps")
manifest = _load("build_manifest")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _dep(data: bytes, files: list[dict[str, Any]] | None = None, name: str = "tool") -> dict[str, Any]:
    return {"name": name, "version": "1", "url": "https://example.invalid/tool.bin",
            "size": len(data), "sha256": _sha(data),
            "files": files if files is not None else [{"to": "bin/tool.exe", "sha256": _sha(data)}]}


def _opener(data: bytes, calls: list[str] | None = None, fail_first: int = 0):
    state = {"n": 0}

    def opener(url: str, timeout: float):
        state["n"] += 1
        if calls is not None:
            calls.append(url)
        if state["n"] <= fail_first:
            raise urllib.error.URLError("connection reset")
        return io.BytesIO(data)
    return opener


def _zip(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return buf.getvalue()


# ------------------------------------------------------------------ the committed pin list

def test_committed_pins_are_valid():
    deps = fetch.load_pins()
    assert fetch.validate(deps) == []


def test_pins_cover_everything_the_build_bundles_or_runs():
    deps = {d["name"]: d for d in fetch.load_pins()}
    targets = {f["to"] for d in deps.values() for f in d["files"]}
    assert targets == {
        "bin/ffmpeg.exe", "bin/ffprobe.exe", "bin/yt-dlp.exe", "bin/deno.exe",
        "bin/diarization/segmentation.onnx", "bin/diarization/embedding.onnx",
    }
    assert deps["python-build-standalone"]["files"] == []
    assert deps["inno-setup"]["files"] == []
    # core/diarization.py reads exactly these two model files.
    diar = (ROOT / "core" / "diarization.py").read_text(encoding="utf-8")
    assert 'SEGMENTATION_MODEL = "segmentation.onnx"' in diar
    assert 'EMBEDDING_MODEL = "embedding.onnx"' in diar


def test_every_url_is_a_fixed_version_on_a_known_host():
    for dep in fetch.load_pins():
        url = dep["url"]
        assert re.match(r"^https://(github\.com|huggingface\.co)/", url), url
        assert "/latest/" not in url and "/main/" not in url, url
        if "huggingface.co" in url:
            assert re.search(r"/resolve/[0-9a-f]{40}/", url), f"pin a revision: {url}"
        else:
            assert "/releases/download/" in url, url
        assert dep["hash_source"].strip(), dep["name"]


def test_bat_downloads_python_only_through_the_verified_fetch():
    text = BAT.read_text(encoding="utf-8")
    assert "fetch_windows_build_deps.py\" --only python-build-standalone --out" in text
    assert "Invoke-WebRequest" not in text
    assert "PYBSD_" not in text  # the version lives in the pin list only
    # A missing bin\deno.exe is filled from the pin, not from the latest release.
    assert "fetch_windows_build_deps.py\" --select deno" in text
    assert "install_deno" not in text


# ------------------------------------------------------------------ validate()

@pytest.mark.parametrize("mutate,needle", [
    (lambda d: d.update(url="http://example.invalid/x"), "https"),
    (lambda d: d.update(sha256="AB" * 32), "lowercase hex"),
    (lambda d: d.update(sha256="ab" * 31), "lowercase hex"),
    (lambda d: d.update(size=True), "positive integer"),
    (lambda d: d.update(size=0), "positive integer"),
    (lambda d: d["files"][0].update(to="../outside.exe"), "bad target"),
    (lambda d: d["files"][0].update(to="C:/abs.exe"), "bad target"),
    (lambda d: d["files"][0].update(to="bin\\tool.exe"), "bad target"),
    (lambda d: d["files"][0].update(sha256="0" * 64), "download itself"),
    (lambda d: d["files"][0].update(member="../evil"), "bad archive member"),
    (lambda d: d.update(files="bin/tool.exe"), "files must be a list"),
])
def test_validate_rejects_a_bad_entry(mutate, needle):
    dep = _dep(b"payload")
    mutate(dep)
    errors = fetch.validate([dep])
    assert any(needle in e for e in errors), errors


def test_validate_rejects_duplicate_names_and_targets():
    a = _dep(b"a")
    b = copy.deepcopy(a)
    errors = fetch.validate([a, b])
    assert any("duplicate name" in e for e in errors)
    b["name"] = "other"
    b["files"][0]["to"] = "BIN/Tool.exe"  # same file on a case-insensitive disk
    assert any("written twice" in e for e in fetch.validate([a, b]))


# ------------------------------------------------------------------ download()

def test_download_writes_a_matching_file(tmp_path):
    data = b"x" * 3000
    dest = tmp_path / "out" / "tool.bin"
    fetch.download(_dep(data), dest, opener=_opener(data))
    assert dest.read_bytes() == data
    assert not (dest.parent / "tool.bin.part").exists()


def test_download_refuses_a_wrong_hash_and_leaves_nothing(tmp_path):
    dep = _dep(b"expected")
    dest = tmp_path / "tool.bin"
    with pytest.raises(fetch.FetchError, match="pinned"):
        fetch.download(dep, dest, opener=_opener(b"tampered"))
    assert list(tmp_path.iterdir()) == []


def test_download_stops_at_the_first_byte_past_the_pinned_size(tmp_path):
    dep = _dep(b"short")
    with pytest.raises(fetch.FetchError, match="larger than"):
        fetch.download(dep, tmp_path / "t", opener=_opener(b"short but longer"))
    assert list(tmp_path.iterdir()) == []


class _Seq:
    """Opener that answers each call with the next item: bytes, or an exception to raise
    while the body is read."""

    def __init__(self, *items):
        self.items = list(items)
        self.calls = 0

    def __call__(self, url: str, timeout: float):
        item = self.items[min(self.calls, len(self.items) - 1)]
        self.calls += 1
        if isinstance(item, BaseException):
            exc = item

            class _Broken(io.BytesIO):
                def read(self, *a):
                    raise exc
            return _Broken()
        return io.BytesIO(item)


def test_download_retries_a_body_cut_short(tmp_path, monkeypatch):
    monkeypatch.setattr(fetch.time, "sleep", lambda s: None)
    data = b"0123456789" * 10
    opener = _Seq(data[:40], data)
    fetch.download(_dep(data), tmp_path / "t", opener=opener)
    assert opener.calls == 2 and (tmp_path / "t").read_bytes() == data
    with pytest.raises(fetch.FetchError, match="closed after 40 of 100 bytes"):
        fetch.download(_dep(data), tmp_path / "u", opener=_Seq(data[:40]))
    assert sorted(p.name for p in tmp_path.iterdir()) == ["t"]


def test_download_retries_an_incomplete_read(tmp_path, monkeypatch):
    monkeypatch.setattr(fetch.time, "sleep", lambda s: None)
    data = b"payload"
    opener = _Seq(http.client.IncompleteRead(b"pay", 4), data)
    fetch.download(_dep(data), tmp_path / "t", opener=opener)
    assert opener.calls == 2


def test_a_wrong_hash_is_not_retried(tmp_path):
    opener = _Seq(b"tampered", b"expected")
    with pytest.raises(fetch.FetchError, match="pinned"):
        fetch.download(_dep(b"expected"), tmp_path / "t", opener=opener)
    assert opener.calls == 1


def test_redirects_to_plain_http_are_refused():
    handler = fetch._HttpsOnlyRedirects()
    req = urllib.request.Request("https://github.com/x")
    with pytest.raises(urllib.error.URLError, match="non-https"):
        handler.redirect_request(req, None, 302, "Found", {}, "http://cdn.example.invalid/x")
    with pytest.raises(urllib.error.URLError, match="non-https"):
        handler.redirect_request(req, None, 302, "Found", {}, "ftp://cdn.example.invalid/x")
    new = handler.redirect_request(req, None, 302, "Found", {}, "https://cdn.example.invalid/x")
    assert new is not None and new.full_url == "https://cdn.example.invalid/x"


def test_download_retries_network_errors(tmp_path, monkeypatch):
    monkeypatch.setattr(fetch.time, "sleep", lambda s: None)
    data = b"payload"
    calls: list[str] = []
    fetch.download(_dep(data), tmp_path / "t", opener=_opener(data, calls, fail_first=2))
    assert len(calls) == 3
    with pytest.raises(fetch.FetchError, match="after 3 attempts"):
        fetch.download(_dep(data), tmp_path / "u", opener=_opener(data, fail_first=5))
    assert not (tmp_path / "u").exists()


# ------------------------------------------------------------------ install() and check()

def test_install_extracts_verified_members(tmp_path):
    exe, dll = b"MZ exe bytes", b"MZ dll bytes"
    archive = _zip({"pkg/bin/a.exe": exe, "pkg/bin/b.dll": dll, "pkg/readme.txt": b"x"})
    dep = _dep(archive, files=[
        {"member": "pkg/bin/a.exe", "to": "bin/a.exe", "sha256": _sha(exe)},
        {"member": "pkg/bin/b.dll", "to": "bin/sub/b.dll", "sha256": _sha(dll)},
    ])
    assert fetch.install(dep, tmp_path, opener=_opener(archive)) == ["bin/a.exe", "bin/sub/b.dll"]
    assert (tmp_path / "bin" / "a.exe").read_bytes() == exe
    assert (tmp_path / "bin" / "sub" / "b.dll").read_bytes() == dll
    assert sorted(p.name for p in tmp_path.rglob("*") if p.is_file()) == ["a.exe", "b.dll"]


def test_install_writes_nothing_when_one_member_differs(tmp_path):
    archive = _zip({"a.exe": b"good", "b.exe": b"evil"})
    dep = _dep(archive, files=[
        {"member": "a.exe", "to": "bin/a.exe", "sha256": _sha(b"good")},
        {"member": "b.exe", "to": "bin/b.exe", "sha256": _sha(b"expected")},
    ])
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "a.exe").write_bytes(b"old copy")
    with pytest.raises(fetch.FetchError, match="bin/b.exe"):
        fetch.install(dep, tmp_path, opener=_opener(archive))
    assert (tmp_path / "bin" / "a.exe").read_bytes() == b"old copy"
    assert not (tmp_path / "bin" / "b.exe").exists()


def test_install_reports_a_missing_member(tmp_path):
    archive = _zip({"other.exe": b"x"})
    dep = _dep(archive, files=[{"member": "a.exe", "to": "bin/a.exe", "sha256": _sha(b"x")}])
    with pytest.raises(fetch.FetchError, match="no member a.exe"):
        fetch.install(dep, tmp_path, opener=_opener(archive))


def test_install_skips_the_network_when_targets_already_match(tmp_path):
    data = b"tool"
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "tool.exe").write_bytes(data)
    calls: list[str] = []
    assert fetch.install(_dep(data), tmp_path, opener=_opener(data, calls)) == []
    assert calls == []


def test_install_replaces_a_file_that_differs_from_its_pin(tmp_path):
    data = b"pinned build"
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "tool.exe").write_bytes(b"self-updated or tampered copy")
    calls: list[str] = []
    assert fetch.install(_dep(data), tmp_path, opener=_opener(data, calls)) == ["bin/tool.exe"]
    assert calls and (tmp_path / "bin" / "tool.exe").read_bytes() == data


def test_select_fills_only_the_named_entry(tmp_path, monkeypatch):
    pins = tmp_path / "pins.json"
    a, b = _dep(b"aaa", name="a"), _dep(b"bbb", name="b")
    a["files"][0]["to"], b["files"][0]["to"] = "bin/a.exe", "bin/b.exe"
    pins.write_text(json.dumps({"deps": [a, b]}), encoding="utf-8")
    # main() calls install() without an opener; swap its default for a fake network.
    monkeypatch.setattr(fetch.install, "__kwdefaults__", {"opener": _opener(b"bbb")})
    assert fetch.main(["--pins", str(pins), "--root", str(tmp_path), "--select", "b"]) == 0
    assert (tmp_path / "bin" / "b.exe").read_bytes() == b"bbb"
    assert not (tmp_path / "bin" / "a.exe").exists()
    assert fetch.main(["--pins", str(pins), "--root", str(tmp_path), "--check", "--select", "b"]) == 0
    assert fetch.main(["--pins", str(pins), "--root", str(tmp_path), "--check"]) == 1
    assert fetch.main(["--pins", str(pins), "--select", "nope", "--check"]) == 1


def test_check_lists_missing_and_changed_files(tmp_path):
    good, bad = _dep(b"good", name="good"), _dep(b"bad", name="bad")
    good["files"][0]["to"] = "bin/good.exe"
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "good.exe").write_bytes(b"good")
    assert fetch.check([good], tmp_path) == []
    (tmp_path / "bin" / "good.exe").write_bytes(b"changed")
    assert fetch.check([good, bad], tmp_path) == [
        "differs from the pin: bin/good.exe", "missing: bin/tool.exe"]


def test_main_check_and_only_exit_codes(tmp_path, capsys):
    pins = tmp_path / "pins.json"
    pins.write_text(json.dumps({"deps": [_dep(b"tool")]}), encoding="utf-8")
    assert fetch.main(["--pins", str(pins), "--root", str(tmp_path), "--check"]) == 1
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "tool.exe").write_bytes(b"tool")
    assert fetch.main(["--pins", str(pins), "--root", str(tmp_path), "--check"]) == 0
    assert fetch.main(["--pins", str(pins), "--only", "nope", "--out", str(tmp_path / "x")]) == 1
    with pytest.raises(SystemExit):
        fetch.main(["--pins", str(pins), "--only", "tool"])
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"deps": [{**_dep(b"t"), "url": "http://x"}]}), encoding="utf-8")
    assert fetch.main(["--pins", str(bad), "--check"]) == 1
    assert "https" in capsys.readouterr().err


# ------------------------------------------------------------------ build_manifest.py

def _tree(root: Path, files: dict[str, bytes]) -> Path:
    for rel, data in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    return root


def test_manifest_records_every_file(tmp_path):
    tree = _tree(tmp_path / "embed_build", {"gui.py": b"print()", "bin/ffmpeg.exe": b"MZ"})
    m = manifest.build(tree)
    assert m["files"] == {
        "bin/ffmpeg.exe": {"size": 2, "sha256": _sha(b"MZ")},
        "gui.py": {"size": 7, "sha256": _sha(b"print()")},
    }


def test_manifest_compare_flags_strict_paths_and_size_drift(tmp_path):
    base = {"bin/ffmpeg.exe": b"MZ" * 50, "Lib/site-packages/av/x.pyd": b"a" * 100,
            "app/__pycache__/x.pyc": b"1"}
    a = manifest.build(_tree(tmp_path / "a", base))
    same = manifest.build(_tree(tmp_path / "same", {**base, "app/__pycache__/x.pyc": b"22"}))
    lines, failures = manifest.compare(a, same, ["bin/"], 0.10)
    assert failures == []
    assert lines[0] == "A = a (2 files), B = same (2 files)"  # __pycache__ is not compared
    assert len(lines) == 2 and lines[1].startswith("total bytes 200 -> 200 ")
    changed = manifest.build(_tree(tmp_path / "b", {**base, "bin/ffmpeg.exe": b"MZ" * 49 + b"XY"}))
    lines, failures = manifest.compare(a, changed, ["bin/"], 0.10)
    assert failures == ["strict path differs: bin/ffmpeg.exe"]
    assert any(line.startswith("bin: ") and "same size other bytes 1" in line for line in lines)
    grown = manifest.build(_tree(tmp_path / "c", {**base, "Lib/site-packages/av/y.pyd": b"b" * 100}))
    lines, failures = manifest.compare(a, grown, ["bin/"], 0.10)
    assert failures and "total size" in failures[0]
    assert any("only B: Lib/site-packages/av/y.pyd" in line for line in lines)


@pytest.mark.parametrize("rel,expected", [
    ("Lib/site-packages/av/__init__.py", "Lib/site-packages/av"),
    ("Lib/site-packages/av-18.0.0.dist-info/RECORD", "Lib/site-packages/av"),
    ("Lib/site-packages/av.libs/x.dll", "Lib/site-packages/av"),
    ("Lib/site-packages/_sounddevice.py", "Lib/site-packages/_sounddevice"),
    ("python/python.exe", "python"),
    ("gui.py", "(top level)"),
])
def test_manifest_areas(rel, expected):
    assert manifest.area(rel) == expected


# ------------------------------------------------------------------ the workflow

def _workflow() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_workflow_triggers_on_build_files_and_by_hand_only():
    text = _workflow()
    on = text.split("\non:\n", 1)[1].split("\npermissions:", 1)[0]
    assert "branches: [master]" in on and "workflow_dispatch:" in on
    assert "pull_request" not in on and "schedule" not in on
    for path in ("build_embed_installer.bat", "installer_embed.iss", "requirements.txt",
                 "platform/windows/build-deps.json", "tools/fetch_windows_build_deps.py",
                 ".github/workflows/windows-installer.yml"):
        assert f"      - {path}\n" in on, path


def test_workflow_is_read_only_and_never_publishes():
    text = _workflow()
    assert "permissions:\n  contents: read\n" in text
    assert "secrets." not in text
    for banned in ("gh release", "action-gh-release", "git tag", "git push", "contents: write"):
        assert banned not in text, banned
    assert "retention-days: 7" in text
    assert "persist-credentials: false" in text


def test_workflow_actions_are_pinned_to_commits():
    uses = re.findall(r"uses:\s*(\S+)", _workflow())
    assert uses
    for ref in uses:
        assert re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", ref), ref


def test_workflow_builds_with_pinned_tools_and_smoke_tests_the_install():
    text = _workflow()
    assert "runs-on: windows-latest" in text
    assert "python tools/fetch_windows_build_deps.py --only inno-setup" in text
    assert "call build_embed_installer.bat" in text
    assert "& $env:ISCC /Qp installer_embed.iss" in text
    assert "'/VERYSILENT'" in text and "tools\\smoke_windows_install.py" in text
    assert "unins000.exe" in text
    # The bytes that ship are checked against the pins, not only the downloads.
    assert "fetch_windows_build_deps.py --check --root embed_build" in text
    assert "fetch_windows_build_deps.py --check --root $dir" in text


def test_workflow_runs_when_shipped_code_changes_and_never_cancels_a_build():
    text = _workflow()
    on = text.split("\non:\n", 1)[1].split("\npermissions:", 1)[0]
    for path in ("gui.py", "app/**", "core/**", "assets/**", "tools/smoke_windows_install.py"):
        assert f"      - {path}\n" in on, path
    assert "cancel-in-progress: false" in text
    assert "cancel-in-progress: true" not in text


def test_workflow_smoke_tests_the_portable_tree_too():
    text = _workflow()
    assert r"tools\smoke_windows_install.py (Resolve-Path embed_build).Path" in text
    # After the manifest (the smoke run writes __pycache__) and after the zip.
    assert text.index("Write the build manifest") < text.index("Smoke test the Portable tree")
    assert text.index("Zip the Portable build") < text.index("Smoke test the Portable tree")


def test_workflow_tests_an_upgrade_over_the_installed_copy():
    text = _workflow()
    upgrade = text.index("$log2 = Join-Path $env:RUNNER_TEMP 'wts-upgrade.log'")
    # Second silent install into the same folder, then the log must show that
    # PrepareToInstall found and removed the first one, then the smoke test again.
    assert "'Removed the previous version'" in text
    assert text.index("unins000.exe") > upgrade
    assert text.count(r"tools\smoke_windows_install.py $dir $env:APP_VERSION") == 2


def test_every_workflow_pins_actions_and_starts_read_only():
    for path in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        text = path.read_text(encoding="utf-8")
        for ref in re.findall(r"uses:\s*(\S+)", text):
            assert re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", ref), f"{path.name}: {ref}"
        top = re.search(r"(?m)^permissions:\n((?:  .*\n)+)", text)
        assert top, f"{path.name} has no top-level permissions"
        if path.name != "site-data.yml":  # commits the refreshed site data
            assert top.group(1) == "  contents: read\n", f"{path.name}: {top.group(1)!r}"


# ------------------------------------------------------------------ Portable tree contents

def test_bat_puts_assets_into_the_embed_tree_and_checks_them():
    text = BAT.read_text(encoding="utf-8")
    copy = text.index(r'copy /Y "%ROOT%assets\%%F" "%BUILD%\assets\" >nul')
    assert "for %%F in (whisper.ico whisper.png sample_clip.mp3) do" in text
    assert r'xcopy /I /Y "%ROOT%assets\icons\*" "%BUILD%\assets\icons\" >nul' in text
    check = text.index(r"ERROR: assets\%%F missing from embed tree")
    # Copied (and checked) before the tree is declared complete.
    assert copy < check < text.index("build complete")
    assert "for %%F in (LICENSE THIRD_PARTY_NOTICES.md) do (" in text
    assert text.index(r"ERROR: %%F missing from embed tree") < text.index("build complete")


def test_installer_takes_assets_from_the_embed_tree_only():
    iss = (ROOT / "installer_embed.iss").read_text(encoding="utf-8")
    sources = re.findall(r'(?m)^Source:\s*"([^"]+)"', iss)
    assert sources == [r"embed_build\*"]


smoke = _load("smoke_windows_install")


def test_smoke_lists_every_module_of_the_tree(tmp_path):
    for rel in ("app/__init__.py", "app/dpi.py", "app/theme/__init__.py", "app/theme/tokens.py",
                "core/__init__.py", "core/server/tls.py", "core/server/__init__.py",
                "core/__pycache__/x.py", "core/server/static/index.html"):
        f = tmp_path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("", encoding="utf-8")
    assert smoke.app_modules(str(tmp_path)) == [
        "app", "app.dpi", "app.theme", "app.theme.tokens", "core", "core.server", "core.server.tls"]


def test_smoke_covers_the_real_tree_and_the_gui_dependencies():
    names = smoke.app_modules(str(ROOT))
    assert "app.app" in names and "app.dpi" in names and "core.star_invite" in names
    assert len(names) > 100
    for dep in ("PIL.ImageTk", "pystray", "watchdog.observers", "sounddevice"):
        assert dep in smoke.RUNTIME_MODULES
    assert any(a.endswith("sample_clip.mp3") for a in smoke.REQUIRED_ASSETS)


def _fake_ffmpeg(tmp_path, listing: str) -> str:
    """A stand-in ffmpeg.exe-like program: prints *listing* for any arguments."""
    import sys

    program = tmp_path / "fake_ffmpeg.py"
    program.write_text("print(" + repr(listing) + ")\n", encoding="utf-8")
    launcher = tmp_path / "fake_ffmpeg.cmd"
    launcher.write_text(f'@"{sys.executable}" "{program}" %*\r\n', encoding="utf-8", newline="")
    return str(launcher)


_LISTING = (
    "Filters:\n  T.. = Timeline support\n"
    " ... scale             V->V       Scale the input video size.\n"
    " .. subtitles         V->V       Render text subtitles onto input video using the libass library.\n"
)


@pytest.mark.skipif(os.name != "nt", reason="the stand-in is a .cmd launcher")
def test_smoke_requires_the_subtitles_filter_in_ffmpeg(tmp_path):
    assert smoke.BURN_FILTERS == ("subtitles",)
    assert smoke.ffmpeg_missing_filters(_fake_ffmpeg(tmp_path, _LISTING), smoke.BURN_FILTERS) == []
    without = "\n".join(ln for ln in _LISTING.splitlines() if "subtitles " not in ln)
    assert smoke.ffmpeg_missing_filters(_fake_ffmpeg(tmp_path, without), smoke.BURN_FILTERS) == ["subtitles"]
