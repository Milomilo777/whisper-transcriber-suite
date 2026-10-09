"""A damaged "online config not published" marker file is treated as absent.

The marker records that the online config answered HTTP 404 so the next
start does not ask again. If its bytes are not valid UTF-8 (a torn write, a
disk fault) reading it raises ``UnicodeDecodeError``, a ``ValueError`` that
used to escape the ``OSError`` handler and abort the whole config load.
"""
from __future__ import annotations

import io
import urllib.error

from core import config as cfg

_URL = "https://example.invalid/app_config.json"


def _not_found() -> urllib.error.HTTPError:
    return urllib.error.HTTPError(_URL, 404, "x", {}, io.BytesIO(b""))  # type: ignore[arg-type]


def _count_fetches(monkeypatch) -> list[int]:
    calls: list[int] = []

    def _fake(req, timeout=0):  # noqa: ARG001
        calls.append(1)
        raise _not_found()

    monkeypatch.setattr(cfg.urllib.request, "urlopen", _fake)
    return calls


def test_a_valid_marker_still_suppresses_the_fetch(tmp_path, monkeypatch):
    cache = tmp_path / "app_config_cache.json"
    calls = _count_fetches(monkeypatch)
    cfg.fetch_online_config(_URL, cache_path=cache)
    assert cfg._online_known_missing(cache, _URL) is True
    cfg.fetch_online_config(_URL, cache_path=cache)
    assert len(calls) == 1


def test_a_marker_with_invalid_utf8_counts_as_missing(tmp_path, monkeypatch):
    cache = tmp_path / "app_config_cache.json"
    calls = _count_fetches(monkeypatch)
    cfg.fetch_online_config(_URL, cache_path=cache)
    cfg._online_missing_marker(cache).write_bytes(b"\xff\xfe\x80 not utf-8")

    assert cfg._online_known_missing(cache, _URL) is False
    assert cfg.fetch_online_config(_URL, cache_path=cache) == {}
    assert len(calls) == 2, "an unreadable marker must not suppress the fetch"
