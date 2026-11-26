"""Tests for gui._ensure_safe_stdio_encoding().

Real-world regression (2026-08-19): a CLI transcription of a downloaded
video crashed its own progress/log line on every single callback because
the file's title (pulled from a social-media post by yt-dlp) contained an
emoji the Windows console's legacy codepage (cp1252) cannot encode:

    UnicodeEncodeError: 'charmap' codec can't encode character '\\U0001f6a8'
      in position 20: character maps to <undefined>

transcribe() already swallows a raising log callback (core/transcriber.py's
_wrapped), so the run itself did not abort, but every log line for the rest
of a 28-minute transcription was lost, replaced by a repeated traceback.
_ensure_safe_stdio_encoding() reconfigures stdout/stderr to substitute an
unencodable character instead of raising, fixed at the source rather than
patched around each print() call.
"""
from __future__ import annotations

import io
import sys
import types

import gui as _gui


def test_ensure_safe_stdio_encoding_calls_reconfigure_with_replace(monkeypatch):
    calls: list[dict] = []

    class _FakeStream:
        def reconfigure(self, **kwargs):
            calls.append(kwargs)

    fake_out, fake_err = _FakeStream(), _FakeStream()
    monkeypatch.setattr(sys, "stdout", fake_out)
    monkeypatch.setattr(sys, "stderr", fake_err)

    _gui._ensure_safe_stdio_encoding()

    assert calls == [{"errors": "replace"}, {"errors": "replace"}]


def test_ensure_safe_stdio_encoding_tolerates_stream_without_reconfigure(monkeypatch):
    # A stream lacking .reconfigure (e.g. some exotic redirect target)
    # must not crash the helper -- it should simply be skipped.
    monkeypatch.setattr(sys, "stdout", types.SimpleNamespace())
    monkeypatch.setattr(sys, "stderr", types.SimpleNamespace())
    _gui._ensure_safe_stdio_encoding()  # must not raise


def test_ensure_safe_stdio_encoding_tolerates_reconfigure_raising(monkeypatch):
    class _BoomStream:
        def reconfigure(self, **_):
            raise ValueError("already detached")

    monkeypatch.setattr(sys, "stdout", _BoomStream())
    monkeypatch.setattr(sys, "stderr", _BoomStream())
    _gui._ensure_safe_stdio_encoding()  # must not raise


def test_ensure_safe_stdio_encoding_actually_prevents_the_real_crash(monkeypatch):
    """End-to-end proof against a stream shaped like the real failure: a
    TextIOWrapper over cp1252 in strict mode raises on the emoji; after
    running it through the helper the same write no longer raises."""
    raw = io.BytesIO()
    stream = io.TextIOWrapper(raw, encoding="cp1252", errors="strict")
    monkeypatch.setattr(sys, "stdout", stream)
    monkeypatch.setattr(sys, "stderr", io.TextIOWrapper(io.BytesIO(), encoding="cp1252"))

    emoji_line = "[cli] [file=Sweex - \U0001f6a8¡BOMBAZO!] still working..."
    try:
        stream.write(emoji_line)
        stream.flush()
    except UnicodeEncodeError:
        pass
    else:
        raise AssertionError("fixture stream should reproduce the crash before the fix")

    _gui._ensure_safe_stdio_encoding()

    # Same write, same stream, now survives.
    sys.stdout.write(emoji_line)
    sys.stdout.flush()


def test_worker_mode_never_touches_stdio_encoding(monkeypatch):
    """--worker's stdout is a structured JSON-lines protocol the parent
    process depends on byte-for-byte; main() must take the early-return
    branch WITHOUT calling _ensure_safe_stdio_encoding at all."""
    monkeypatch.setattr(sys, "argv", ["gui.py", "--worker"])

    called: list[bool] = []
    monkeypatch.setattr(_gui, "_ensure_safe_stdio_encoding", lambda: called.append(True))

    import core.worker as worker_mod
    monkeypatch.setattr(worker_mod, "main", lambda: 0)

    rc = _gui.main()

    assert rc == 0
    assert called == []


def test_mcp_prepares_bundled_tools_before_starting_raw_stdio(monkeypatch):
    from core import offline, paths
    from core.server import mcp_stdio

    calls = []
    monkeypatch.setattr(sys, "argv", ["gui.py", "mcp"])
    monkeypatch.setattr(_gui, "_ensure_safe_stdio_encoding", lambda: calls.append("reconfigure"))
    monkeypatch.setattr(offline, "install_network_guard", lambda: calls.append("offline"))
    monkeypatch.setattr(paths, "clear_bundled_quarantine", lambda: calls.append("tools"))
    monkeypatch.setattr(mcp_stdio, "main", lambda: calls.append("mcp") or 0)

    assert _gui.main() == 0
    assert calls == ["offline", "tools", "mcp"]
