"""A value that carries a line break cannot forge a second log line.

Log messages interpolate text that is not under the app's control: a video
title from yt-dlp, a file name that holds a newline (legal on Linux and
macOS), a value read back from ``hardware.json`` or a request line from the
local HTTP API. ``RedactingFormatter`` sits on every log handler, so it
escapes line breaks in the message once for all of them. The traceback block
keeps its own line breaks.
"""
from __future__ import annotations

import io
import logging
import sys

import pytest

from core import hardware
from core.logging_setup import LOG_FORMAT, RedactingFormatter

FORGED = "2026-01-01 00:00:00,000 ERROR core.fake — forged entry"


def _format(msg: str, *args: object, exc: bool = False) -> str:
    exc_info = None
    if exc:
        try:
            raise ValueError("boom")
        except ValueError:
            exc_info = sys.exc_info()
    record = logging.LogRecord(
        "core.test", logging.INFO, __file__, 1, msg, args or None, exc_info
    )
    return RedactingFormatter(LOG_FORMAT).format(record)


@pytest.mark.parametrize(
    "separator",
    ["\n", "\r", "\r\n", "\x0b", "\x0c", "\x85", " ", " "],
    ids=["lf", "cr", "crlf", "vt", "ff", "nel", "ls", "ps"],
)
def test_a_line_break_in_an_argument_does_not_start_a_new_line(separator):
    out = _format("device=%s", f"cpu{separator}{FORGED}")
    assert len(out.splitlines()) == 1
    # The text is kept, only the break is made visible.
    assert FORGED in out


def test_a_line_break_in_the_message_itself_is_escaped():
    out = _format(f"first\n{FORGED}")
    assert len(out.splitlines()) == 1
    assert "first\\n2026" in out


def test_a_plain_message_is_unchanged():
    out = _format("loaded %s in %.1f s", "large-v3", 2.5)
    assert out.endswith("core.test — loaded large-v3 in 2.5 s")


def test_the_traceback_keeps_its_line_breaks():
    out = _format("failed: %s", "a\nb", exc=True)
    lines = out.splitlines()
    assert lines[0].endswith("failed: a\\nb")
    assert any(line.startswith("Traceback") for line in lines[1:])
    assert lines[-1] == "ValueError: boom"


def test_urls_are_still_redacted_after_the_escape():
    out = _format("GET %s", "https://host/p?token=abc\nnext")
    assert "token=abc" not in out
    assert len(out.splitlines()) == 1


def test_a_bad_format_call_still_fails_like_before():
    record = logging.LogRecord(
        "core.test", logging.INFO, __file__, 1, "%s %s", ("only-one",), None
    )
    with pytest.raises(TypeError):
        RedactingFormatter(LOG_FORMAT).format(record)


def test_the_formatter_does_not_edit_the_record_for_other_handlers():
    record = logging.LogRecord(
        "core.test", logging.INFO, __file__, 1, "v=%s", ("a\nb",), None
    )
    RedactingFormatter(LOG_FORMAT).format(record)
    assert record.getMessage() == "v=a\nb"


def test_a_device_setting_with_a_line_break_cannot_forge_a_log_line():
    """The path Sonar traced: config value -> detect_device_for() -> logger."""
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(RedactingFormatter(LOG_FORMAT))
    root = logging.getLogger()
    old_level = root.level
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    try:
        hardware.detect_device_for(
            {"device": f"cpu\n{FORGED}", "compute_type": f"int8\r{FORGED}"}
        )
    finally:
        root.removeHandler(handler)
        root.setLevel(old_level)
    lines = stream.getvalue().splitlines()
    assert len(lines) == 1
    assert "device_choice" in lines[0]
