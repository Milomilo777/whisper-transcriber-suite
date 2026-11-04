"""Hermetic tests for overflow handling in core.integrations.otranscribe."""
from __future__ import annotations

import json
from pathlib import Path

from core.integrations import otranscribe


def test_otr_to_srt_clamps_overflowing_finite_timestamps(tmp_path: Path) -> None:
    otr_file = tmp_path / "अudio_टेस्ट.otr"
    payload = {
        "text": (
            '<p><span class="timestamp" data-timestamp="1e308">0:00</span>'
            "\u00a0Hello world</p>"
            '<p><span class="timestamp" data-timestamp="-1e308">0:00</span>'
            "\u00a0Second line</p>"
        ),
        "media": "C:\\Users\\टेस्ट\\clip.mp3",
        "media-source": "",
        "media-time": 1e308,
    }
    otr_file.write_text(json.dumps(payload), encoding="utf-8")

    srt = otranscribe.otr_to_srt(str(otr_file))
    assert "1\n00:00:00,000 --> 00:00:00,000\nHello world" in srt
    assert "2\n00:00:00,000 --> 00:00:00,000\nSecond line" in srt


def test_otr_to_srt_handles_empty_and_non_string_text_payload(tmp_path: Path) -> None:
    otr_file = tmp_path / "empty.otr"
    otr_file.write_text(json.dumps({"text": 12345, "media-time": "bad"}), encoding="utf-8")
    assert otranscribe.otr_to_srt(str(otr_file)) == ""


def test_fmt_otr_time_preserves_truncation_contract() -> None:
    assert otranscribe.fmt_otr_time(0.0) == "0:00"
    assert otranscribe.fmt_otr_time(1.9) == "0:01"
    assert otranscribe.fmt_otr_time(59.9) == "0:59"
    assert otranscribe.fmt_otr_time(3661.8) == "1:01:01"
    assert otranscribe.fmt_otr_time(float("nan")) == "0:00"
    assert otranscribe.fmt_otr_time(float("inf")) == "0:00"
    assert otranscribe.fmt_otr_time(-5.0) == "0:00"
    assert otranscribe.fmt_otr_time("not-a-number") == "0:00"  # type: ignore[arg-type]
    assert otranscribe.fmt_otr_time(None) == "0:00"  # type: ignore[arg-type]
