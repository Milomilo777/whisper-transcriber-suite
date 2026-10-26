"""The status bar's short line for an engine log message.

The worker sends every engine message as one ``log`` event; the log panel keeps them all, word for
word. The status bar is read by people who are not looking at the log, so it gets a short, plain
line instead (click-through test 2026-10-21: it showed "[file=audio.flac] Loop guard: kept 6
identical lines ... avg_logprob=-0.44, compression_ratio=2.28" and full temporary-file paths, cut
off at the window edge). Tk-free.
"""
from __future__ import annotations

import os
import re

from app import rtl_shaping
from app.i18n import _, display

#: Longest status line; the bar shares its row with the device label.
MAX_CHARS = 110

_FILE_PREFIX = re.compile(r"^\[file=(?P<name>[^\]]*)\]\s*")
_SEGMENT = re.compile(r"^\[\s*(?P<pct>\d{1,3})%\]\s+[\d:.]+\s+-->\s+[\d:.]+\s+\|\s*(?P<text>.*)$")
_PROCESSING = re.compile(r"^Processing(?: \([^)]*\))?:\s*(?P<path>.+)$")
#: Engine diagnostics for the log only: they keep the previous status line.
_LOG_ONLY = (
    re.compile(r"^Loop guard\b"),
    re.compile(r"\b(avg_logprob|compression_ratio|no_speech_prob)="),
    re.compile(r"^Resume: transcribing tail slice\b"),
    re.compile(r"^model_path_resolved\b"),
)


def _clip(text: str) -> str:
    # A shaped text (Linux, right to left) is cut as logical text and shaped again: cutting the
    # visual string would drop the logical beginning and put the ellipsis at the wrong end.
    text = " ".join(rtl_shaping.logical(text).split())
    if len(text) > MAX_CHARS:
        text = text[: MAX_CHARS - 1].rstrip() + "…"
    return display(text, logical=True)


def status_line(message: str) -> str | None:
    """The status bar text for ``message``, or None to keep the current one (a diagnostic)."""
    message = (message or "").strip()
    if not message:
        return None
    name = ""
    match = _FILE_PREFIX.match(message)
    if match:
        name = match.group("name")
        message = message[match.end():]
    if any(p.search(message) for p in _LOG_ONLY):
        return None
    segment = _SEGMENT.match(message)
    if segment:
        text = segment.group("text").strip()
        head = _("{name}: {percent}% done", name=name, percent=segment.group("pct")) if name else \
            _("{percent}% done", percent=segment.group("pct"))
        # The words in quotes: a bare fragment ("1% done — Mum告诉我的") read as the app switching
        # language (round-2 screenshot critics, 2026-10-21). A template, so a translation picks
        # its own quote marks.
        if not text:
            return _clip(head)
        # Clip the words, not the line, so the closing quote stays.
        room = MAX_CHARS - len(_("{progress} — “{words}”", progress=head, words=""))
        if room < 8:  # a long file name leaves no room for words worth reading
            return _clip(head)
        words = " ".join(text.split())
        if len(words) > room:
            words = words[: max(1, room - 1)].rstrip() + "…"
        return _clip(_("{progress} — “{words}”", progress=head, words=words))
    processing = _PROCESSING.match(message)
    if processing:
        return _clip(_("Transcribing {name}…", name=os.path.basename(processing.group("path").strip())))
    return _clip(f"{name}: {message}" if name else message)
