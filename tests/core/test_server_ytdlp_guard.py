"""A server link job never lets ffmpeg fetch HLS/DASH segments unguarded.

yt-dlp falls back to ffmpeg for live streams and for HLS it cannot parse
itself; ffmpeg ignores the proxy environment for https links. The job
therefore refuses live streams and gives ffmpeg its own ``-http_proxy``
through a per-job config file (the password stays off the command line).

Hermetic: yt-dlp is replaced by a fake process; option parsing is offline.
"""
from __future__ import annotations

import os

import pytest

from core import server
from core.server import dlproxy


class _SpyPopen:
    seen: list = []
    configs: list = []
    stdout_text = ""
    returncode = 0

    def __init__(self, cmd, **kwargs):
        type(self).seen.append(list(cmd))
        path = cmd[cmd.index("--config-locations") + 1]
        with open(path, encoding="utf-8") as handle:
            type(self).configs.append((path, handle.read()))
        self.pid = 4242

    def communicate(self, timeout=None):
        return type(self).stdout_text, ""

    def poll(self):
        return None


def _leftovers(folder):
    return [n for n in os.listdir(folder)
            if n.startswith(server.GUARD_CONFIG_PREFIX)]


@pytest.fixture
def spy(monkeypatch):
    _SpyPopen.seen = []
    _SpyPopen.configs = []
    _SpyPopen.stdout_text = ""
    monkeypatch.setattr(server.subprocess, "Popen", _SpyPopen)
    monkeypatch.setattr("core.js_runtime.yt_dlp_js_args", lambda _p=None: [])
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
                 "http_proxy", "https_proxy", "all_proxy", "no_proxy"):
        monkeypatch.delenv(name, raising=False)


def test_command_refuses_live_and_uses_a_guard_config_file(tmp_path, spy):
    (tmp_path / "clip.mp4").write_bytes(b"media")
    server._download_url("https://example.com/v", str(tmp_path))
    cmd = _SpyPopen.seen[0]
    url = dlproxy.shared_proxy().url
    password = url.split("//wts:", 1)[1].split("@", 1)[0]
    assert cmd[cmd.index("--match-filters") + 1] == "!is_live"
    assert "--ignore-config" in cmd
    assert cmd[cmd.index("--downloader") + 1] == "native"
    assert not any(password in part for part in cmd), "password in argv"
    assert "--proxy" not in cmd and "--downloader-args" not in cmd
    path, text = _SpyPopen.configs[0]
    assert os.path.dirname(path) == str(tmp_path)
    assert f"--proxy {url}" in text
    assert f'--downloader-args "ffmpeg_i:-http_proxy {url}"' in text
    assert not os.path.exists(path), "config (holds the password) not removed"


def test_config_file_is_read_by_yt_dlp_as_proxy_and_ffmpeg_proxy(tmp_path):
    options = pytest.importorskip("yt_dlp.options")
    url = "http://wts:Ab_-9z@127.0.0.1:5555"
    path = server._write_guard_config(str(tmp_path), url)
    _parser, opts, args = options.parseOpts(
        ["--ignore-config", "--config-locations", path, "--", "https://x/y"])
    assert opts.proxy == url
    assert opts.external_downloader_args == {
        "ffmpeg_i": ["-http_proxy", url]}
    assert args == ["https://x/y"]


def test_the_match_filter_skips_a_live_info_dict_and_keeps_a_vod_one():
    utils = pytest.importorskip("yt_dlp.utils")
    keep = utils.match_filter_func(server.NOT_LIVE_FILTER)
    assert keep({"id": "1", "title": "t", "is_live": True}) is not None
    assert keep({"id": "2", "title": "t", "is_live": False}) is None
    assert keep({"id": "3", "title": "t"}) is None  # unknown = not live


def test_a_filtered_out_live_stream_gets_a_clear_error(tmp_path, spy):
    _SpyPopen.stdout_text = (
        "[download] Some live does not pass filter (!is_live), skipping ..\n")
    with pytest.raises(RuntimeError, match="live streams are not supported"):
        server._download_url("https://example.com/v", str(tmp_path))
    assert _leftovers(tmp_path) == []


def test_config_is_removed_when_the_process_cannot_start(tmp_path, monkeypatch):
    def boom(*_a, **_k):
        raise OSError("no such program")

    monkeypatch.setattr(server.subprocess, "Popen", boom)
    monkeypatch.setattr("core.js_runtime.yt_dlp_js_args", lambda _p=None: [])
    with pytest.raises(OSError):
        server._download_url("https://example.com/v", str(tmp_path))
    assert _leftovers(tmp_path) == []


class _HalfWriter:
    """File object that takes the first line and then fails (disk full)."""

    def __init__(self, real):
        self._real = real

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._real.close()
        return False

    def write(self, text):
        self._real.write(text.split("\n", 1)[0] + "\n")
        self._real.flush()
        raise OSError(28, "No space left on device")


def test_config_is_removed_when_writing_it_fails_midway(tmp_path, monkeypatch):
    real_fdopen = os.fdopen
    monkeypatch.setattr(server.os, "fdopen",
                        lambda *a, **k: _HalfWriter(real_fdopen(*a, **k)))
    monkeypatch.setattr("core.js_runtime.yt_dlp_js_args", lambda _p=None: [])
    with pytest.raises(OSError, match="No space"):
        server._download_url("https://example.com/v", str(tmp_path))
    assert _leftovers(tmp_path) == []


@pytest.mark.parametrize("target", ["core.js_runtime.yt_dlp_js_args",
                                    "core.paths.bin_dir"])
def test_config_is_removed_when_building_the_command_fails(
        tmp_path, monkeypatch, target):
    def boom(*_a, **_k):
        raise RuntimeError("cannot build the command")

    monkeypatch.setattr("core.js_runtime.yt_dlp_js_args", lambda _p=None: [])
    monkeypatch.setattr(target, boom)
    with pytest.raises(RuntimeError, match="cannot build"):
        server._download_url("https://example.com/v", str(tmp_path))
    assert _leftovers(tmp_path) == []


def test_an_existing_file_or_alias_is_never_reused(tmp_path, monkeypatch):
    monkeypatch.setattr(server.secrets, "token_hex", lambda _n: "fixed")
    taken = tmp_path / (server.GUARD_CONFIG_PREFIX + "fixed"
                        + server.GUARD_CONFIG_SUFFIX)
    taken.write_text("keep me")
    with pytest.raises(FileExistsError):
        server._write_guard_config(str(tmp_path), "http://wts:x@127.0.0.1:1")
    assert taken.read_text() == "keep me"
    monkeypatch.undo()
    first = server._write_guard_config(str(tmp_path), "http://wts:x@127.0.0.1:1")
    second = server._write_guard_config(str(tmp_path), "http://wts:x@127.0.0.1:1")
    assert first != second
