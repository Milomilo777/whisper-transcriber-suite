"""Small hardening fixes: online-config cache, report address, writer inputs."""
from __future__ import annotations

import io
import json
import os
import urllib.error

import pytest

from core import config as cfg
from core import problem_report, writers
from core.writers.base import MAX_SECONDS, coerce_seconds, normalize_text

_URL = "https://example.invalid/app_config.json"


class _Body:
    def __init__(self, raw: bytes) -> None:
        self._raw = raw
        self.headers: dict[str, str] = {}

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False

    def read(self, n=-1):
        return self._raw if n < 0 else self._raw[:n]


def test_online_config_cache_is_written_atomically(tmp_path, monkeypatch):
    cache = tmp_path / "online.json"
    cache.write_text(json.dumps({"old": 1}), encoding="utf-8")
    monkeypatch.setattr(
        cfg.urllib.request, "urlopen",
        lambda req, timeout=0: _Body(json.dumps({"new": 2}).encode()),
    )

    def _crash(src, dst):
        raise OSError("disk gone")

    monkeypatch.setattr(os, "replace", _crash)
    assert cfg.fetch_online_config(_URL, cache_path=cache) == {"new": 2}
    # The failed replace left the old cache whole and no temp file behind.
    assert json.loads(cache.read_text(encoding="utf-8")) == {"old": 1}
    assert [p.name for p in tmp_path.iterdir()] == ["online.json"]


def test_online_config_cache_and_marker_round_trip(tmp_path, monkeypatch):
    cache = tmp_path / "online.json"
    monkeypatch.setattr(
        cfg.urllib.request, "urlopen",
        lambda req, timeout=0: _Body(json.dumps({"k": "v"}).encode()),
    )
    assert cfg.fetch_online_config(_URL, cache_path=cache) == {"k": "v"}
    saved = json.loads(cache.read_text(encoding="utf-8"))
    # The cache also records when it was saved (the 30-day stats_url limit).
    assert isinstance(saved.pop(cfg._ONLINE_CACHE_SAVED_AT), (int, float))
    assert saved == {"k": "v"}

    def _not_found(req, timeout=0):
        raise urllib.error.HTTPError(_URL, 404, "x", {}, io.BytesIO(b""))  # type: ignore[arg-type]

    monkeypatch.setattr(cfg.urllib.request, "urlopen", _not_found)
    other = tmp_path / "other.json"
    cfg.fetch_online_config(_URL, cache_path=other)
    assert cfg._online_known_missing(other, _URL)
    assert sorted(p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")) == []


@pytest.mark.parametrize("url", ["http://[bad", "https://[::1", "", "ftp://x/y", "no-scheme"])
def test_report_with_an_unusable_address_says_there_is_none(url, monkeypatch):
    monkeypatch.setattr(problem_report.offline, "is_offline", lambda: False)
    with pytest.raises(problem_report.ProblemReportError, match="no report address"):
        problem_report.send({"stats_url": url}, "it broke")


def test_normalize_text_strips_c0_controls_but_keeps_spacing():
    assert normalize_text("a\x00b\x07c\x1bd\x7fe") == "abcde"
    assert normalize_text("a\tb\nc  d\x0be\x1ff") == "a b c d e f"


def test_srt_never_carries_a_nul():
    out = writers.get_writer("srt")([{"start": 0, "end": 1, "text": "he\x00llo"}])
    assert "\x00" not in out and "hello" in out


@pytest.mark.parametrize("value", [1e308, -1e308, 10.0**305, "1e300"])
def test_huge_finite_times_are_clamped(value):
    assert abs(coerce_seconds(value)) <= MAX_SECONDS


@pytest.mark.parametrize("fmt", ["srt", "vtt", "txt", "json", "tsv", "lrc", "md"])
def test_writers_survive_a_huge_finite_time(fmt):
    try:
        writer = writers.get_writer(fmt)
    except Exception:  # noqa: BLE001 — a format this build does not offer
        pytest.skip(fmt)
    out = writer([{"start": 1e308, "end": 1.7e308, "text": "x"}])
    assert "x" in out
