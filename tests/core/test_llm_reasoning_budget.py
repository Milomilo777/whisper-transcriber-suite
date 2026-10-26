"""Remote reasoning models and the answer budget (Groq openai/gpt-oss-120b, 2026-10-26 click test).

A reasoning model spends part of ``max_tokens`` on hidden reasoning. With the viewer's small
Translate budget Groq answered ``finish_reason: length`` with an EMPTY content (254 of 256 tokens
went to reasoning), and the app showed an empty result with no error. Fakes only: no network.
"""
from __future__ import annotations

import json

import pytest

from core import llm


class _Resp:
    def __init__(self, body: dict):
        self._body = json.dumps(body).encode()

    def read(self, _n=-1):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return None


def _reply(content, finish="stop"):
    return _Resp({"choices": [{"message": {"content": content}, "finish_reason": finish}]})


def _script(monkeypatch, replies):
    sent = []

    def fake(req, timeout=None):
        sent.append(json.loads(req.data.decode("utf-8")))
        return replies[min(len(sent), len(replies)) - 1]

    monkeypatch.setattr(llm.urllib.request, "urlopen", fake)
    return sent


def _runner(base_url="https://llm.example/v1", model="m"):
    return llm.RemoteLLMRunner(llm.RemoteLLMConfig(base_url=base_url, model=model))


def test_an_empty_answer_cut_by_the_limit_is_asked_again_with_more_room(monkeypatch):
    sent = _script(monkeypatch, [_reply("", "length"), _reply("سلام")])
    assert _runner()._chat([{"role": "user", "content": "hi"}], max_tokens=256) == "سلام"
    assert len(sent) == 2
    assert sent[1]["max_tokens"] > sent[0]["max_tokens"]


def test_an_answer_that_stays_empty_is_an_error_not_a_blank_result(monkeypatch):
    sent = _script(monkeypatch, [_reply("", "length")])
    with pytest.raises(llm.RemoteLLMError, match="answer limit"):
        _runner()._chat([{"role": "user", "content": "hi"}], max_tokens=256)
    assert len(sent) == 2


def test_an_empty_but_finished_answer_is_not_retried(monkeypatch):
    sent = _script(monkeypatch, [_reply("", "stop")])
    assert _runner()._chat([{"role": "user", "content": "hi"}]) == ""
    assert len(sent) == 1


def test_action_items_cut_by_the_limit_are_an_error_not_none_found(monkeypatch):
    _script(monkeypatch, [_reply("", "length")])
    with pytest.raises(llm.RemoteLLMError):
        _runner().action_items("Tom will send the quotes by Friday.")


def test_a_groq_retry_gets_more_room_and_stays_inside_the_budget(monkeypatch):
    sent = _script(monkeypatch, [_reply("", "length"), _reply("ok")])
    runner = _runner(llm.GROQ_BASE_URL, llm.GROQ_MODEL)
    assert runner._chat([{"role": "user", "content": "word " * 2000}], max_tokens=600) == "ok"
    assert len(sent) == 2
    assert sent[1]["max_tokens"] > sent[0]["max_tokens"]
    count = llm._token_counter(None)
    for body in sent:
        used = sum(count(m["content"]) for m in body["messages"]) + body["max_tokens"]
        assert used <= llm.GROQ_REQUEST_TOKEN_BUDGET


def test_a_full_budget_is_reported_without_sending_the_same_request_again(monkeypatch):
    # A huge Groq request already gets the most answer room the budget allows; a second,
    # identical request would only spend quota again (Codex review, 2026-10-26).
    sent = _script(monkeypatch, [_reply("", "length")])
    runner = _runner(llm.GROQ_BASE_URL, llm.GROQ_MODEL)
    with pytest.raises(llm.RemoteLLMError, match="no more room") as err:
        runner.translate("word " * 20000, target_language="Persian")
    assert len(sent) == 1
    assert f"({sent[0]['max_tokens']} tokens)" in str(err.value)


def test_both_requests_share_one_wait_allowance(monkeypatch):
    # 429 + Retry-After waits before the empty answer must count against the same per-call total
    # as the waits before the second request (180 s, not 180 s each).
    import email.message
    import io

    slept = []
    monkeypatch.setattr(llm.time, "sleep", slept.append)
    monkeypatch.setattr(llm, "_RETRY_DELAYS_S", (0.0, 0.0, 0.0))
    calls = []

    def fake(req, timeout=None):
        calls.append(req)
        step = ["429", "429", "empty", "429", "429", "ok"][min(len(calls), 6) - 1]
        if step == "429":
            headers = email.message.Message()
            headers["Retry-After"] = "90"
            raise llm.urllib.error.HTTPError(req.full_url, 429, "x", headers, io.BytesIO(b"{}"))
        return _reply("", "length") if step == "empty" else _reply("ok")

    monkeypatch.setattr(llm.urllib.request, "urlopen", fake)
    with pytest.raises(llm.RemoteLLMRateLimitError):
        _runner()._chat([{"role": "user", "content": "hi"}], max_tokens=256)
    assert sum(slept) <= llm._MAX_TOTAL_WAIT_S


def test_groq_gpt_oss_is_asked_for_low_reasoning_effort(monkeypatch):
    sent = _script(monkeypatch, [_reply("ok")])
    _runner(llm.GROQ_BASE_URL, "openai/gpt-oss-120b")._chat([{"role": "user", "content": "hi"}])
    assert sent[0]["reasoning_effort"] == "low"


@pytest.mark.parametrize("base_url, model", [
    ("https://api.openai.com/v1", "openai/gpt-oss-120b"),   # not Groq: the parameter may be refused
    (llm.GROQ_BASE_URL, "llama-3.3-70b-versatile"),          # Groq, but not a gpt-oss model
    ("http://localhost:11434/v1", "gpt-oss:20b"),            # a local server
])
def test_other_providers_and_models_get_no_reasoning_parameter(monkeypatch, base_url, model):
    sent = _script(monkeypatch, [_reply("ok")])
    _runner(base_url, model)._chat([{"role": "user", "content": "hi"}])
    assert "reasoning_effort" not in sent[0]


def test_remote_translate_leaves_room_for_scripts_that_need_more_tokens(monkeypatch):
    # Persian, Arabic, Hindi and CJK need several tokens per English word they translate.
    sent = _script(monkeypatch, [_reply("ok")])
    text = "word " * 143
    _runner().translate(text, target_language="Persian")
    assert sent[0]["max_tokens"] >= 3 * 143
