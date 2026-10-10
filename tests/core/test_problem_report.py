"""Problem reports through the usage-statistics endpoint (core/problem_report.py)."""
import urllib.parse

import pytest

from core import offline
from core import problem_report as pr

# The capped text fields of platform/stats-server/transcription_stats.php ($text_limits).
SERVER_LIMITS = {"model": 128, "language": 32, "status": 32, "program_version": 32,
                 "platform_system": 32, "platform_release": 64, "platform_version": 256,
                 "platform_machine": 32, "platform_processor": 128}


def test_the_text_fields_match_the_server_limits():
    for field, size in pr.TEXT_FIELDS:
        assert SERVER_LIMITS[field] == size
    assert pr.MAX_CHARS == 512


def test_long_text_is_spread_over_the_fields_in_order_and_capped():
    text = "".join(chr(ord("a") + i % 26) for i in range(700))
    parts = pr.split_text(pr.clean_text(text))
    assert "".join(parts[f] for f, _n in pr.TEXT_FIELDS) == text[:512]
    for field, size in pr.TEXT_FIELDS:
        assert len(parts[field]) <= size


def test_cleaning_keeps_persian_and_drops_control_characters():
    persian = "".join(chr(c) for c in (0x633, 0x644, 0x627, 0x645))
    raw = "line one\nline\ttwo " + persian + chr(7) + " " + chr(0xD800)
    out = pr.clean_text(raw)
    assert persian in out
    assert all(ord(ch) >= 32 for ch in out)
    assert chr(0xD800) not in out and chr(0xFFFD) in out


def test_payload_is_a_problem_report_row_with_nothing_personal():
    payload = pr.build_payload("The app froze when I pressed Stop.")
    assert payload["form_submitted"] == "1" and payload["status"] == pr.STATUS
    assert payload["model"].startswith("The app froze")
    for field, value in payload.items():
        if field in SERVER_LIMITS:
            assert len(value) <= SERVER_LIMITS[field], field
    assert "file" not in " ".join(payload) and "country" not in payload


def test_an_empty_report_is_refused_before_any_network():
    with pytest.raises(pr.ProblemReportError):
        pr.build_payload("   \n\t ")


def test_work_offline_blocks_the_send(monkeypatch):
    monkeypatch.setattr(offline, "is_offline", lambda: True)
    with pytest.raises(pr.ProblemReportError, match="offline"):
        pr.send({"stats_url": "https://example.invalid/s.php"}, "hello")


def test_only_http_addresses_are_used(monkeypatch):
    monkeypatch.setattr(offline, "is_offline", lambda: False)
    for url in ("", "file:///etc/passwd", "ftp://example.invalid/x"):
        with pytest.raises(pr.ProblemReportError):
            pr.send({"stats_url": url}, "hello")


def test_send_posts_the_form_to_the_stats_url(monkeypatch):
    monkeypatch.setattr(offline, "is_offline", lambda: False)
    seen = {}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self, n=-1):
            return b"ok"

    def fake_urlopen(req, timeout):
        seen["url"], seen["data"] = req.full_url, req.data
        return _Resp()

    monkeypatch.setattr(pr.urllib.request, "urlopen", fake_urlopen)
    pr.send({"stats_url": "https://stats.example.invalid/t.php"}, "Crash on export")
    form = urllib.parse.parse_qs(seen["data"].decode("utf-8"))
    assert seen["url"] == "https://stats.example.invalid/t.php"
    assert form["status"] == [pr.STATUS] and form["model"] == ["Crash on export"]


def test_network_failure_becomes_a_plain_message(monkeypatch):
    monkeypatch.setattr(offline, "is_offline", lambda: False)

    def boom(req, timeout):
        raise pr.urllib.error.URLError("no route")

    monkeypatch.setattr(pr.urllib.request, "urlopen", boom)
    with pytest.raises(pr.ProblemReportError, match="Could not reach"):
        pr.send({"stats_url": "https://stats.example.invalid/t.php"}, "x")
