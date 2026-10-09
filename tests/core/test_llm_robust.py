"""Remote LLM client robustness (card C2.63, findings S11-16, C5, C6).

Fakes only: ``urlopen`` is replaced, no network, no real model.
"""
from __future__ import annotations

import email.message
import http.client
import io
import json
import os
import time

import pytest

from core import llm

_BODY = json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode()


class _Resp:
    def __init__(self, body=_BODY, exc=None):
        self._body, self._exc = body, exc

    def read(self, _n=-1):
        if self._exc is not None:
            raise self._exc
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return None


def _http_error(req, code, retry_after=None):
    headers = email.message.Message()
    if retry_after is not None:
        headers["Retry-After"] = str(retry_after)
    return llm.urllib.error.HTTPError(
        req.full_url, code, "x", headers, io.BytesIO(b"{}"))


def _runner():
    return llm.RemoteLLMRunner(llm.RemoteLLMConfig(
        base_url="https://llm.example/v1", model="m"))


@pytest.fixture(autouse=True)
def _fast_retries(monkeypatch):
    monkeypatch.setattr(llm, "_RETRY_DELAYS_S", (0.0, 0.0, 0.0))


def _script(monkeypatch, steps):
    """urlopen that plays ``steps`` in order; each is a response or a callable
    taking the request and raising."""
    calls = []

    def fake(req, timeout=None):
        step = steps[min(len(calls), len(steps) - 1)]
        calls.append(req)
        if callable(step):
            raise step(req)
        return step

    monkeypatch.setattr(llm.urllib.request, "urlopen", fake)
    return calls


def test_rate_limit_is_retried_then_succeeds(monkeypatch):
    calls = _script(monkeypatch, [lambda r: _http_error(r, 429),
                                  lambda r: _http_error(r, 503), _Resp()])
    assert _runner()._chat([{"role": "user", "content": "hi"}]) == "ok"
    assert len(calls) == 3


def test_persistent_rate_limit_gives_up_with_a_remote_error(monkeypatch):
    calls = _script(monkeypatch, [lambda r: _http_error(r, 429)])
    with pytest.raises(llm.RemoteLLMError, match="429"):
        _runner()._chat([{"role": "user", "content": "hi"}])
    assert len(calls) == len(llm._RETRY_DELAYS_S) + 1


def test_a_bad_key_is_not_retried(monkeypatch):
    calls = _script(monkeypatch, [lambda r: _http_error(r, 401)])
    with pytest.raises(llm.RemoteLLMError, match="401"):
        _runner()._chat([{"role": "user", "content": "hi"}])
    assert len(calls) == 1


def test_retry_after_is_honoured_and_capped(monkeypatch):
    llm_sleeps = []
    monkeypatch.setattr(llm.time, "sleep", llm_sleeps.append)
    _script(monkeypatch, [lambda r: _http_error(r, 429, retry_after=7),
                          lambda r: _http_error(r, 429, retry_after=9999),
                          _Resp()])
    _runner()._chat([{"role": "user", "content": "hi"}])
    assert llm_sleeps == [7.0, llm._MAX_RETRY_AFTER_S]


@pytest.mark.parametrize("exc", [
    http.client.IncompleteRead(b"par"),
    TimeoutError("read timed out"),
    ConnectionResetError("reset"),
])
def test_a_cut_short_reply_becomes_a_remote_error(monkeypatch, exc):
    calls = _script(monkeypatch, [_Resp(exc=exc)])
    with pytest.raises(llm.RemoteLLMError):
        _runner()._chat([{"role": "user", "content": "hi"}])
    assert len(calls) == len(llm._RETRY_DELAYS_S) + 1  # retried first


def test_a_cut_short_reply_recovers_on_retry(monkeypatch):
    _script(monkeypatch, [_Resp(exc=http.client.IncompleteRead(b"x")), _Resp()])
    assert _runner()._chat([{"role": "user", "content": "hi"}]) == "ok"


def test_invalid_utf8_becomes_a_remote_error(monkeypatch):
    _script(monkeypatch, [_Resp(body=b"\xff\xfe\x00bad")])
    with pytest.raises(llm.RemoteLLMError, match="unexpected response"):
        _runner()._chat([{"role": "user", "content": "hi"}])


def test_an_oversized_reply_is_refused(monkeypatch):
    monkeypatch.setattr(llm, "_MAX_RESPONSE_BYTES", 50)
    _script(monkeypatch, [_Resp(body=b"x" * 500)])
    with pytest.raises(llm.RemoteLLMError, match="larger than expected"):
        _runner()._chat([{"role": "user", "content": "hi"}])


def test_connection_refused_fails_at_once(monkeypatch):
    calls = _script(monkeypatch, [
        lambda r: llm.urllib.error.URLError(ConnectionRefusedError("refused"))])
    with pytest.raises(llm.RemoteLLMError, match="Could not reach"):
        _runner()._chat([{"role": "user", "content": "hi"}])
    assert len(calls) == 1


# --- translate_segments reports its gaps -----------------------------------

class _FlakyRunner:
    def translate(self, text, target_language="English"):
        if text == "bad":
            raise llm.RemoteLLMError("HTTP 429")
        return text.upper()


def test_translate_segments_reports_failed_indices():
    segments = [{"text": "a"}, {"text": "bad"}, {"text": "  "}, {"text": "c"}]
    failed: list[int] = []
    out = llm.translate_segments(_FlakyRunner(), segments, failed=failed)
    assert out == ["A", "", "", "C"]
    assert failed == [1]  # the blank source segment is not a failure


def test_translate_segments_still_works_without_the_report():
    out = llm.translate_segments(_FlakyRunner(), [{"text": "a"}])
    assert out == ["A"]


# --- model download: a part file of its own --------------------------------

class _DownloadResp:
    headers = {"content-length": "6"}

    def __init__(self, on_read):
        self._chunks = [b"abc", b"def"]
        self._on_read = on_read

    def read(self, _n=-1):
        self._on_read()
        return self._chunks.pop(0) if self._chunks else b""

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return None


def test_each_model_download_uses_its_own_part_file(tmp_path, monkeypatch):
    dest = tmp_path / "model.gguf"
    seen: list[list[str]] = []
    monkeypatch.setattr(llm, "is_model_present", lambda p=None: False)
    monkeypatch.setattr(llm.offline, "require_online", lambda *_a: None)
    monkeypatch.setattr(
        llm.urllib.request, "urlopen",
        lambda req, timeout=None: _DownloadResp(
            lambda: seen.append(sorted(os.listdir(tmp_path)))))
    llm.download_default_model(dest=dest)
    parts = [n for names in seen for n in names if n.endswith(".part")]
    assert parts and "model.gguf.part" not in parts
    assert dest.read_bytes() == b"abcdef"
    assert not [n for n in os.listdir(tmp_path) if n.endswith(".part")]


def test_only_old_part_files_are_cleaned_up(tmp_path, monkeypatch):
    dest = tmp_path / "model.gguf"
    old = tmp_path / "model.gguf.111-aaaa.part"
    young = tmp_path / "model.gguf.222-bbbb.part"
    for p in (old, young):
        p.write_bytes(b"x")
    long_ago = time.time() - 2 * llm._STALE_PART_AGE_S
    os.utime(old, (long_ago, long_ago))
    llm._remove_stale_parts(dest)
    assert not old.exists()
    assert young.exists()  # may belong to a download running right now

@pytest.mark.parametrize("base_url", [
    "file:///etc/hosts",
    "ftp://llm.example/v1",
    "llm.example/v1",
    "http://[::1",  # unparseable
    "",
])
def test_a_non_web_base_url_is_refused_before_any_request(monkeypatch, base_url):
    calls = _script(monkeypatch, [_Resp()])
    runner = llm.RemoteLLMRunner(llm.RemoteLLMConfig(base_url=base_url, model="m"))
    with pytest.raises(llm.RemoteLLMError, match="http"):
        runner._chat([{"role": "user", "content": "hi"}])
    assert calls == []


@pytest.mark.parametrize("base_url", [
    "http://localhost:11434/v1",
    "HTTPS://llm.example/v1",
])
def test_http_and_https_base_urls_are_still_used(monkeypatch, base_url):
    calls = _script(monkeypatch, [_Resp()])
    runner = llm.RemoteLLMRunner(llm.RemoteLLMConfig(base_url=base_url, model="m"))
    assert runner._chat([{"role": "user", "content": "hi"}]) == "ok"
    assert len(calls) == 1
