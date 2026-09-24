"""Deno for yt-dlp (core.js_runtime) -- YouTube needs a JS runtime (#8)."""
from __future__ import annotations

import hashlib
import io
import os
import zipfile

import pytest

from core import js_runtime as js


@pytest.fixture
def no_deno(monkeypatch, tmp_path):
    monkeypatch.setattr(js, "bundled_binary", lambda name: name)
    monkeypatch.setattr(js, "user_cache_dir", lambda: tmp_path / "cache")
    monkeypatch.setattr(js.shutil, "which", lambda _n: None)
    return tmp_path


def test_no_deno_means_no_extra_yt_dlp_args(no_deno):
    assert js.find_deno() is None
    assert js.yt_dlp_js_args() == []


def test_installed_deno_is_passed_to_yt_dlp(no_deno, monkeypatch):
    monkeypatch.setattr(js, "yt_dlp_version", lambda _p=None: (2026, 8, 19))
    target = js.installed_deno_path()
    target.parent.mkdir(parents=True)
    target.write_bytes(b"")
    assert js.yt_dlp_js_args() == ["--js-runtimes", f"deno:{target}"]


def test_old_yt_dlp_gets_no_js_runtimes_option(no_deno, monkeypatch):
    # --js-runtimes arrived in yt-dlp 2025.11.12; an older binary would fail
    # every call with "no such option".
    target = js.installed_deno_path()
    target.parent.mkdir(parents=True)
    target.write_bytes(b"")
    monkeypatch.setattr(js, "yt_dlp_version", lambda _p=None: (2025, 10, 22))
    assert js.yt_dlp_js_args() == []
    monkeypatch.setattr(js, "yt_dlp_version", lambda _p=None: ())  # unknown
    assert js.yt_dlp_js_args() == []


def test_deno_on_path_is_left_to_yt_dlp(no_deno, monkeypatch, tmp_path):
    # yt-dlp finds a Deno on PATH itself; no option needed (or safe on old yt-dlp).
    on_path = tmp_path / "deno"
    on_path.write_bytes(b"")
    monkeypatch.setattr(js.shutil, "which", lambda _n: str(on_path))
    monkeypatch.setattr(js, "yt_dlp_version", lambda _p=None: (2026, 8, 19))
    assert js.find_deno() == str(on_path)
    assert js.yt_dlp_js_args() == []


def test_yt_dlp_version_is_read_once_per_binary(tmp_path, monkeypatch):
    exe = tmp_path / "yt-dlp"
    exe.write_bytes(b"")
    calls = []

    class _Res:
        returncode = 0
        stdout = "2026.08.19\n"

    import subprocess
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: calls.append(a) or _Res())
    js._yt_dlp_version_cache.clear()
    assert js.yt_dlp_version(str(exe)) == (2026, 8, 19)
    assert js.yt_dlp_version(str(exe)) == (2026, 8, 19)
    assert len(calls) == 1
    assert js.yt_dlp_version(str(tmp_path / "missing")) == ()


def test_bundled_deno_wins(no_deno, monkeypatch, tmp_path):
    bundled = tmp_path / "bin" / "deno"
    bundled.parent.mkdir()
    bundled.write_bytes(b"")
    monkeypatch.setattr(js, "bundled_binary", lambda name: str(bundled))
    assert js.find_deno() == str(bundled)


@pytest.mark.parametrize("system, machine, asset", [
    ("Windows", "AMD64", "deno-x86_64-pc-windows-msvc.zip"),
    ("Windows", "ARM64", "deno-aarch64-pc-windows-msvc.zip"),
    ("Darwin", "arm64", "deno-aarch64-apple-darwin.zip"),
    ("Darwin", "x86_64", "deno-x86_64-apple-darwin.zip"),
    ("Linux", "x86_64", "deno-x86_64-unknown-linux-gnu.zip"),
    ("Linux", "armv7l", None),
])
def test_release_asset_per_platform(system, machine, asset):
    assert js.release_asset_name(system, machine) == asset


def test_checksum_parsing_handles_both_published_formats():
    h = "a" * 64
    assert js._expected_sha256(f"{h}  deno-x86_64-unknown-linux-gnu.zip\n") == h
    assert js._expected_sha256(f"Algorithm : SHA256\nHash      : {h.upper()}\n") == h
    with pytest.raises(RuntimeError):
        js._expected_sha256("<html>not found</html>")


@pytest.mark.parametrize("url, yes", [
    ("https://www.youtube.com/watch?v=x", True),
    ("https://youtu.be/x", True),
    ("https://music.youtube.com/watch?v=x", True),
    ("https://m.youtube.com/shorts/x", True),
    ("https://www.instagram.com/p/x", False),
    ("https://notyoutube.com/x", False),
    ("", False),
])
def test_is_youtube_url(url, yes):
    assert js.is_youtube_url(url) is yes


def test_missing_runtime_messages_are_recognised():
    assert js.mentions_missing_js_runtime(
        "WARNING: [youtube] No supported JavaScript runtime could be found."
    )
    assert not js.mentions_missing_js_runtime("ERROR: Video unavailable")


def _fake_release(exe_name: str) -> tuple[bytes, str]:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(exe_name, b"#!/bin/sh\necho deno 9.9.9\n")
    data = buf.getvalue()
    return data, hashlib.sha256(data).hexdigest()


class _Resp:
    def __init__(self, data: bytes):
        self._data = data
        self.text = data.decode("latin-1")
        self.headers = {"content-length": str(len(data))}

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size=1):
        for i in range(0, len(self._data), chunk_size):
            yield self._data[i:i + chunk_size]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _patch_requests(monkeypatch, zip_bytes: bytes, checksum_text: str):
    import requests

    def fake_get(url, stream=False, timeout=None):
        return _Resp(checksum_text.encode() if url.endswith(".sha256sum") else zip_bytes)

    monkeypatch.setattr(requests, "get", fake_get)


def test_install_verifies_and_unpacks(no_deno, monkeypatch):
    data, digest = _fake_release(js._exe_name())
    _patch_requests(monkeypatch, data, f"{digest}  deno.zip")
    pcts: list[int] = []
    path = js.install_deno(progress_cb=pcts.append)
    assert path == str(js.installed_deno_path()) and os.path.isfile(path)
    assert pcts and pcts[-1] == 100
    if os.name != "nt":
        assert os.access(path, os.X_OK)


def test_install_refuses_a_checksum_mismatch(no_deno, monkeypatch):
    data, _digest = _fake_release(js._exe_name())
    _patch_requests(monkeypatch, data, "b" * 64)
    with pytest.raises(RuntimeError, match="checksum"):
        js.install_deno()
    assert js.find_deno() is None  # nothing half-installed


def test_download_command_carries_the_js_runtime_args():
    from app.services.download_service import build_download_command
    from app.domain.tasks import VideoDownloadTask

    task = VideoDownloadTask(
        url="https://youtu.be/x", folder="/out", format_label="x",
        format_info={"mode": "Audio and video", "output": "mp4",
                     "audio": {"kind": "best_audio"}, "video": {"kind": "best_video"}},
    )
    cmd = build_download_command(task, yt_dlp_path="yt-dlp", bin_path="",
                                 js_runtime_args=["--js-runtimes", "deno:/d"])
    assert cmd[cmd.index("--js-runtimes") + 1] == "deno:/d"
    assert cmd.index("--js-runtimes") < cmd.index("--")
