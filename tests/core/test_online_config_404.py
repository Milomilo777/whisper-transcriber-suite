"""An online config that was never published (HTTP 404) is not retried or
logged at every process start."""
from __future__ import annotations

import io
import json
import logging
import urllib.error

import pytest

from core import config as cfg

URL = "https://example.invalid/app_config.json"


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(URL, code, "x", {}, io.BytesIO(b""))  # type: ignore[arg-type]


def _count_calls(monkeypatch, exc):
    calls = []

    def _fake(req, timeout=0):  # noqa: ARG001
        calls.append(1)
        raise exc

    monkeypatch.setattr(cfg.urllib.request, "urlopen", _fake)
    return calls


def test_404_is_logged_once_and_not_refetched(tmp_path, monkeypatch, caplog):
    cache = tmp_path / "app_config_cache.json"
    calls = _count_calls(monkeypatch, _http_error(404))
    with caplog.at_level(logging.DEBUG, logger="core.config"):
        assert cfg.fetch_online_config(URL, cache_path=cache) == {}
        assert cfg.fetch_online_config(URL, cache_path=cache) == {}
    assert len(calls) == 1, "second call must skip the network"
    infos = [r for r in caplog.records if r.levelno >= logging.INFO]
    assert len(infos) == 1 and infos[0].levelno == logging.INFO
    assert "404" in infos[0].getMessage()


def test_404_still_serves_the_cache(tmp_path, monkeypatch):
    cache = tmp_path / "app_config_cache.json"
    cache.write_text(json.dumps({"latest_version": "9.9"}), encoding="utf-8")
    _count_calls(monkeypatch, _http_error(404))
    assert cfg.fetch_online_config(URL, cache_path=cache) == {"latest_version": "9.9"}
    assert cfg.fetch_online_config(URL, cache_path=cache) == {"latest_version": "9.9"}


def test_marker_expires_and_other_errors_are_retried(tmp_path, monkeypatch):
    cache = tmp_path / "app_config_cache.json"
    calls = _count_calls(monkeypatch, _http_error(404))
    cfg.fetch_online_config(URL, cache_path=cache)
    marker = cfg._online_missing_marker(cache)
    import os
    old = marker.stat().st_mtime - 25 * 3600
    os.utime(marker, (old, old))
    cfg.fetch_online_config(URL, cache_path=cache)
    assert len(calls) == 2
    # a 500 is an outage, not "never published": no marker, retried next time
    marker.unlink()
    calls2 = _count_calls(monkeypatch, _http_error(500))
    cfg.fetch_online_config(URL, cache_path=cache)
    cfg.fetch_online_config(URL, cache_path=cache)
    assert len(calls2) == 2 and not marker.exists()


def test_other_url_is_not_blocked_by_marker(tmp_path, monkeypatch):
    cache = tmp_path / "app_config_cache.json"
    calls = _count_calls(monkeypatch, _http_error(404))
    cfg.fetch_online_config(URL, cache_path=cache)
    cfg.fetch_online_config(URL + "2", cache_path=cache)
    assert len(calls) == 2


def test_success_clears_marker(tmp_path, monkeypatch):
    cache = tmp_path / "app_config_cache.json"
    _count_calls(monkeypatch, _http_error(404))
    cfg.fetch_online_config(URL, cache_path=cache)
    marker = cfg._online_missing_marker(cache)
    assert marker.exists()
    marker.write_text("other", encoding="utf-8")  # force a different URL
    class _Resp(io.BytesIO):
        headers: dict = {}
        def __enter__(self): return self
        def __exit__(self, *a): return False
    monkeypatch.setattr(cfg.urllib.request, "urlopen",
                        lambda req, timeout=0: _Resp(b'{"latest_version": "1"}'))
    assert cfg.fetch_online_config(URL, cache_path=cache) == {"latest_version": "1"}
    assert not marker.exists()


def test_404_log_and_marker_do_not_hold_credentials(tmp_path, monkeypatch, caplog):
    cache = tmp_path / "app_config_cache.json"
    url = "https://alice:hunter2@host.example:8443/cfg.json?tok=LEAKME"
    _count_calls(monkeypatch, _http_error(404))
    with caplog.at_level(logging.DEBUG, logger="core.config"):
        cfg.fetch_online_config(url, cache_path=cache)
    text = caplog.text + cfg._online_missing_marker(cache).read_text(encoding="utf-8")
    assert "hunter2" not in text and "LEAKME" not in text and "alice" not in text
    assert "host.example:8443/cfg.json" in caplog.text
    # still recognised as the same URL, and a different one is not
    assert cfg._online_known_missing(cache, url)
    assert not cfg._online_known_missing(cache, url + "x")


def test_future_dated_marker_is_invalid(tmp_path, monkeypatch):
    import os
    import time
    cache = tmp_path / "app_config_cache.json"
    calls = _count_calls(monkeypatch, _http_error(404))
    cfg.fetch_online_config(URL, cache_path=cache)
    marker = cfg._online_missing_marker(cache)
    future = time.time() + 3 * 365 * 86400
    os.utime(marker, (future, future))
    assert not cfg._online_known_missing(cache, URL)
    cfg.fetch_online_config(URL, cache_path=cache)
    assert len(calls) == 2


def test_refresh_online_config_clears_the_marker(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "online_cache_path", lambda: tmp_path / "app_config_cache.json")
    cache = cfg.online_cache_path()
    _count_calls(monkeypatch, _http_error(404))
    cfg.fetch_online_config(URL, cache_path=cache)
    marker = cfg._online_missing_marker(cache)
    assert marker.exists()
    cfg.refresh_online_config()
    assert not marker.exists()
