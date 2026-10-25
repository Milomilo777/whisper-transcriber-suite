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
    assert not (tmp_path / server.GUARD_CONFIG_NAME).exists()


def test_config_is_removed_when_the_process_cannot_start(tmp_path, monkeypatch):
    def boom(*_a, **_k):
        raise OSError("no such program")

    monkeypatch.setattr(server.subprocess, "Popen", boom)
    monkeypatch.setattr("core.js_runtime.yt_dlp_js_args", lambda _p=None: [])
    with pytest.raises(OSError):
        server._download_url("https://example.com/v", str(tmp_path))
    assert not (tmp_path / server.GUARD_CONFIG_NAME).exists()
