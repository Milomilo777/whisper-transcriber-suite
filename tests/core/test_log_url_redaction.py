"""Log lines never carry the query string of a (signed) URL."""
from __future__ import annotations

import logging

from core import logging_setup as ls

_SIGNED = (
    "https://cas-bridge.xethub.hf.co/xet-bridge-us/abc/def"
    "?X-Amz-Algorithm=AWS4&Policy=eyJTdGF0ZW1lbnQ&Signature=s3cr3t&Key-Pair-Id=K2L8"
)


def test_redact_keeps_scheme_host_path_and_drops_query():
    out = ls.redact_urls(f"GET {_SIGNED} -> 200")
    assert out == "GET https://cas-bridge.xethub.hf.co/xet-bridge-us/abc/def?<redacted> -> 200"
    assert "Signature" not in out and "Policy" not in out


def test_redact_drops_user_info_and_fragment():
    out = ls.redact_urls("see https://user:pw@host.example:8443/a/b#frag now")
    assert out == "see https://host.example:8443/a/b now"


def test_redact_leaves_plain_text_and_plain_urls_alone():
    text = "Downloading https://huggingface.co/x/resolve/main/m.bin -> /tmp/m.bin"
    assert ls.redact_urls(text) == text
    assert ls.redact_urls("no url here ? a=b") == "no url here ? a=b"


def test_redact_stops_at_quote_and_bracket():
    out = ls.redact_urls(f"url='{_SIGNED}' ({_SIGNED})")
    assert "Signature" not in out
    assert out.startswith("url='https://cas-bridge.xethub.hf.co/xet-bridge-us/abc/def?<redacted>' (")
    assert out.endswith("?<redacted>)")


def test_formatter_redacts_message_args_and_traceback():
    fmt = ls.RedactingFormatter("%(message)s")
    try:
        raise RuntimeError(f"failed {_SIGNED}")
    except RuntimeError:
        import sys
        rec = logging.LogRecord("t", logging.INFO, __file__, 1, "fetch %s", (_SIGNED,), sys.exc_info())
    text = fmt.format(rec)
    assert "Signature" not in text and "Policy" not in text and "Key-Pair-Id" not in text
    assert "https://cas-bridge.xethub.hf.co/xet-bridge-us/abc/def" in text


def test_setup_logging_handlers_use_redacting_formatter(tmp_path, monkeypatch):
    monkeypatch.setattr(ls, "user_log_dir", lambda: tmp_path)
    monkeypatch.setattr(ls, "_configured", False)
    root = logging.getLogger()
    before = list(root.handlers)
    try:
        ls.setup_logging("INFO")
        added = [h for h in root.handlers if h not in before]
        assert added and all(isinstance(h.formatter, ls.RedactingFormatter) for h in added)
        logging.getLogger("x").info("dl %s", _SIGNED)
        for h in added:
            h.flush()
        body = (tmp_path / "app.log").read_text(encoding="utf-8")
        assert "Signature" not in body and "cas-bridge.xethub.hf.co/xet-bridge-us/abc/def" in body
    finally:
        for h in list(root.handlers):
            if h not in before:
                root.removeHandler(h)
                h.close()
