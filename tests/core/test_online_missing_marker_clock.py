"""The 24-hour "config_url gave 404" marker and the file clock (CI flake on Windows)."""
import os
import time

from core import config


def _marker(tmp_path, url, mtime_offset):
    cache = tmp_path / "online.json"
    marker = config._online_missing_marker(cache)
    marker.write_text(config._url_digest(url), encoding="utf-8")
    t = time.time() + mtime_offset
    os.utime(marker, (t, t))
    return cache


def test_a_marker_stamped_a_moment_in_the_future_still_counts(tmp_path):
    # Windows can stamp a file a few milliseconds after time.time() reads.
    url = "https://example.invalid/config.json"
    assert config._online_known_missing(_marker(tmp_path, url, 0.5), url)


def test_a_marker_from_a_clock_far_ahead_is_ignored(tmp_path):
    url = "https://example.invalid/config.json"
    assert not config._online_known_missing(_marker(tmp_path, url, 3600), url)


def test_an_old_marker_expires(tmp_path):
    url = "https://example.invalid/config.json"
    age = config.ONLINE_MISSING_RETRY_SECONDS + 60
    assert not config._online_known_missing(_marker(tmp_path, url, -age), url)
