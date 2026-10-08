"""Log lines never carry the query string of a (signed) URL."""
from __future__ import annotations

import logging

import pytest

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


def test_redact_handles_every_url_in_a_line_even_when_quoted():
    out = ls.redact_urls(f"url='{_SIGNED}' ({_SIGNED})")
    assert "Signature" not in out and "Policy" not in out
    assert out.count("https://cas-bridge.xethub.hf.co/xet-bridge-us/abc/def?<redacted>") == 2


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


def test_download_error_text_has_no_signed_query(tmp_path):
    from core.model_manager import _describe_download_error

    text = _describe_download_error(RuntimeError(f"403 for url: {_SIGNED}"), tmp_path, "huggingface.co")
    assert "Signature" not in text and "Policy" not in text
    assert "cas-bridge.xethub.hf.co/xet-bridge-us/abc/def" in text


@pytest.mark.parametrize("url", [
    "https://x.com/a?name=O'Brien&sig=LEAKME",
    'https://x.com/a?name="q"&sig=LEAKME',
    "https://x.com/a?x[]=1&sig=LEAKME",
    "https://x.com/a?x=(1)&sig=LEAKME",
    "https://x.com/a?x=<1>&sig=LEAKME",
    "https://x.com/a#sig=LEAKME",
    "https://x.com?email=a@b.com&sig=LEAKME",
])
def test_nothing_after_the_question_mark_survives(url):
    out = ls.redact_urls(f"got {url} end")
    assert "LEAKME" not in out and "b.com" not in out
    assert out.startswith("got https://x.com")


def test_userinfo_is_stripped_only_before_the_path():
    assert ls.redact_urls("https://x.com?email=a@b.com&sig=S1") == "https://x.com?<redacted>"
    assert ls.redact_urls("https://u:pw@host:80/p@q") == "https://host:80/p@q"
    assert ls.redact_urls("https://u@host") == "https://host"


@pytest.mark.parametrize("text", [
    _SIGNED, f"x '{_SIGNED}' y", "https://u:pw@h.com/p?a=1#f",
    "https://www.youtube.com/watch?v=abc&t=5&list=PL1&sig=S1",
    "https://x.com/p?", "https://x.com/a?b=c.", "no url", "http://x.com/?<redacted>",
])
def test_redaction_is_idempotent(text):
    once = ls.redact_urls(text)
    assert ls.redact_urls(once) == once
    assert "<redacted><redacted>" not in once


def test_formatter_over_describe_error_is_not_doubled(tmp_path):
    from core.model_manager import _describe_download_error

    text = _describe_download_error(RuntimeError(f"403 {_SIGNED}"), tmp_path, "huggingface.co")
    rec = logging.LogRecord("t", logging.INFO, __file__, 1, "%s", (text,), None)
    assert "<redacted><redacted>" not in ls.RedactingFormatter("%(message)s").format(rec)


@pytest.mark.parametrize("host", ["youtube.com", "www.youtube.com", "m.youtube.com", "WWW.YouTube.com"])
def test_youtube_keeps_only_v_and_list(host):
    out = ls.redact_urls(f"https://{host}/watch?v=dQw4w9WgXcQ&sig=LEAKME&list=PL-1_a&t=5s")
    assert out == f"https://{host}/watch?v=dQw4w9WgXcQ&list=PL-1_a"
    assert ls.redact_urls(f"https://{host}/watch?token=LEAKME") == f"https://{host}/watch?<redacted>"
    assert "evil" not in ls.redact_urls(f"https://{host}/watch?v=a%20evil&list=PL1")


def test_other_hosts_and_youtu_be_are_unaffected_by_the_youtube_rule():
    assert ls.redact_urls("https://youtu.be/dQw4w9WgXcQ?t=5") == "https://youtu.be/dQw4w9WgXcQ?<redacted>"
    assert ls.redact_urls("https://notyoutube.com/watch?v=abc") == "https://notyoutube.com/watch?<redacted>"
    assert ls.redact_urls("https://youtube.com.evil.io/watch?v=abc") == "https://youtube.com.evil.io/watch?<redacted>"


def test_server_error_text_uses_the_shared_redaction():
    from core.server.jobs import redact_urls_in_text

    out = redact_urls_in_text("fail https://x.com/a?name=O'Brien&sig=LEAKME (retry)")
    assert "LEAKME" not in out and out.startswith("fail https://x.com/a")
