"""Tests for the local LLM panel (download + runner + parsing)."""
from __future__ import annotations

import email.message
import io
import json
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from core import llm


# ---------- availability -------------------------------------------------------


def test_runtime_available_false_when_module_missing(monkeypatch):
    monkeypatch.setitem(sys.modules, "llama_cpp", None)
    assert llm.runtime_available() is False
    assert "llama-cpp-python" in llm.runtime_availability_reason()


def test_runtime_available_restores_gc_state():
    """Regression for the 2026-08-15 GC-mid-import crash class (see
    core/backends/google_cloud_stt.py); llama-cpp-python is native, same
    risk."""
    import gc
    for was_enabled in (True, False):
        if was_enabled:
            gc.enable()
        else:
            gc.disable()
        try:
            llm.runtime_available()
            assert gc.isenabled() is was_enabled
        finally:
            gc.enable()


# ---------- model file presence ------------------------------------------------


def test_is_model_present_false_when_missing(tmp_path):
    assert llm.is_model_present(tmp_path / "no-such.gguf") is False


def test_is_model_present_false_when_too_small(tmp_path):
    p = tmp_path / "tiny.gguf"
    p.write_bytes(b"x" * 1024)  # 1 KB — below the sanity threshold
    assert llm.is_model_present(p) is False


def test_is_model_present_true_when_large_enough(tmp_path):
    p = tmp_path / "big.gguf"
    # 101 MB of zeros — fast to write via seek+truncate.
    with p.open("wb") as f:
        f.seek(101_000_000)
        f.write(b"\0")
    assert llm.is_model_present(p) is True


# ---------- download -----------------------------------------------------------


def test_download_skips_when_model_already_present(tmp_path, monkeypatch):
    dest = tmp_path / "model.gguf"
    with dest.open("wb") as f:
        f.seek(101_000_000)
        f.write(b"\0")
    # If urlopen is called we'd see ConnectionRefused; the skip path
    # must never reach it.
    monkeypatch.setattr(llm.urllib.request, "urlopen",
                        lambda *a, **kw: pytest.fail("download attempted"))
    logs: list[str] = []
    result = llm.download_default_model(log=logs.append, dest=dest)
    assert result == str(dest)
    assert any("already present" in s for s in logs)


def test_download_writes_atomically_via_part(tmp_path, monkeypatch):
    """Successful download must produce the final file via os.replace
    and leave no .part residue."""
    dest = tmp_path / "model.gguf"
    payload = b"\x47\x47\x55\x46" + b"\0" * 1024  # GGUF magic + filler

    class _FakeResponse:
        headers = {"content-length": str(len(payload))}

        def __init__(self):
            self._data = payload
            self._pos = 0

        def read(self, chunk_size: int) -> bytes:
            if self._pos >= len(self._data):
                return b""
            chunk = self._data[self._pos:self._pos + chunk_size]
            self._pos += len(chunk)
            return chunk

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

    monkeypatch.setattr(llm.urllib.request, "urlopen",
                        lambda *a, **kw: _FakeResponse())
    # Bypass the post-download size sanity check so the test isn't
    # forced to fabricate 100 MB of payload.
    monkeypatch.setattr(llm, "is_model_present", lambda path=None: False)
    result = llm.download_default_model(dest=dest)
    assert Path(result).exists()
    assert (tmp_path / "model.gguf").read_bytes()[:4] == b"GGUF"
    leftovers = [p.name for p in tmp_path.iterdir() if p.name.endswith(".part")]
    assert leftovers == []


def test_download_cleans_up_part_on_cancel(tmp_path, monkeypatch):
    """A mid-flight cancel must delete the .part file."""
    import threading
    dest = tmp_path / "model.gguf"
    cancel = threading.Event()
    cancel.set()  # already cancelled

    class _FakeResponse:
        headers = {"content-length": "10000"}

        def read(self, _chunk_size: int) -> bytes:
            return b"x" * 1000

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

    monkeypatch.setattr(llm.urllib.request, "urlopen",
                        lambda *a, **kw: _FakeResponse())
    monkeypatch.setattr(llm, "is_model_present", lambda path=None: False)
    with pytest.raises(RuntimeError, match="cancelled"):
        llm.download_default_model(dest=dest, cancel_event=cancel)
    assert not (dest.with_suffix(dest.suffix + ".part")).exists()


# ---------- LLMRunner --------------------------------------------------------


def test_runner_load_raises_when_runtime_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(llm, "runtime_available", lambda: False)
    r = llm.LLMRunner(llm.LLMConfig(model_path=str(tmp_path / "x.gguf")))
    with pytest.raises(llm.LLMUnavailable):
        r.load()


def test_runner_load_raises_when_model_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(llm, "runtime_available", lambda: True)
    fake_llama_cpp = types.ModuleType("llama_cpp")
    fake_llama_cpp.Llama = MagicMock()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "llama_cpp", fake_llama_cpp)
    r = llm.LLMRunner(llm.LLMConfig(model_path=str(tmp_path / "no.gguf")))
    with pytest.raises(FileNotFoundError):
        r.load()


def test_runner_load_constructs_llama_once(tmp_path, monkeypatch):
    """Second load() call must be a no-op (no double instantiation)."""
    monkeypatch.setattr(llm, "runtime_available", lambda: True)
    fake_module = types.ModuleType("llama_cpp")
    fake_llama_class = MagicMock()
    fake_module.Llama = fake_llama_class  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "llama_cpp", fake_module)
    model_file = tmp_path / "m.gguf"
    model_file.write_bytes(b"\0" * 100)
    r = llm.LLMRunner(llm.LLMConfig(model_path=str(model_file)))
    r.load()
    r.load()
    assert fake_llama_class.call_count == 1


def test_runner_summarise_returns_completion_text(tmp_path, monkeypatch):
    monkeypatch.setattr(llm, "runtime_available", lambda: True)
    fake_module = types.ModuleType("llama_cpp")

    class _FakeLlama:
        def __init__(self, **_kw):
            pass

        def create_chat_completion(self, **kw):
            return {
                "choices": [
                    {"message": {"content": "- bullet one\n- bullet two"}}
                ]
            }

    fake_module.Llama = _FakeLlama  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "llama_cpp", fake_module)
    model_file = tmp_path / "m.gguf"
    model_file.write_bytes(b"\0" * 100)
    r = llm.LLMRunner(llm.LLMConfig(model_path=str(model_file)))
    out = r.summarise("This is a transcript about widgets.")
    assert "bullet one" in out
    assert "bullet two" in out


def test_runner_action_items_parses_json_array(tmp_path, monkeypatch):
    monkeypatch.setattr(llm, "runtime_available", lambda: True)
    fake_module = types.ModuleType("llama_cpp")

    class _FakeLlama:
        def __init__(self, **_kw):
            pass

        def create_chat_completion(self, **kw):
            return {
                "choices": [
                    {"message": {"content": '["call Alice", "email Bob"]'}}
                ]
            }

    fake_module.Llama = _FakeLlama  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "llama_cpp", fake_module)
    model_file = tmp_path / "m.gguf"
    model_file.write_bytes(b"\0" * 100)
    r = llm.LLMRunner(llm.LLMConfig(model_path=str(model_file)))
    items = r.action_items("transcript")
    assert items == ["call Alice", "email Bob"]


# ---------- JSON list parser ---------------------------------------------------


def test_parse_json_list_strict_array():
    assert llm._parse_json_list('["a", "b", "c"]') == ["a", "b", "c"]


def test_parse_json_list_strips_markdown_fence():
    raw = '```json\n["x", "y"]\n```'
    assert llm._parse_json_list(raw) == ["x", "y"]


def test_parse_json_list_strips_leading_prose():
    raw = 'Here are the items:\n["one", "two"]'
    assert llm._parse_json_list(raw) == ["one", "two"]


def test_parse_json_list_returns_empty_on_garbage():
    assert llm._parse_json_list("not json at all") == []
    assert llm._parse_json_list("") == []
    assert llm._parse_json_list("[unclosed") == []


def test_parse_json_list_coerces_numbers_to_strings():
    assert llm._parse_json_list('[1, "two", 3.5]') == ["1", "two", "3.5"]


def test_parse_json_list_rejects_non_array():
    assert llm._parse_json_list('{"key": "value"}') == []


def test_parse_json_list_ignores_trailing_prose_after_array():
    """A chatty model appending a sentence AFTER a valid array used to make
    the whole response unparseable, silently reporting "no action items"."""
    raw = '["call Alice", "email Bob"]\n\nLet me know if you need more.'
    assert llm._parse_json_list(raw) == ["call Alice", "email Bob"]


def test_parse_json_list_handles_fence_with_trailing_prose():
    raw = '```json\n["x", "y"]\n```\nDone!'
    assert llm._parse_json_list(raw) == ["x", "y"]


def test_parse_json_list_takes_only_the_first_array():
    assert llm._parse_json_list('["a"] and also ["b"]') == ["a"]


# ---------- wrapped-quote stripping (2026-08-16 real-hardware finding) ------
# The local Qwen2.5-1.5B model sometimes wraps a short per-segment
# translation in quote marks despite the prompt saying not to -- observed
# live in a bilingual-subtitle pass, e.g. '"D\'accord, on va passer..."'.


def test_strip_wrapped_quotes_removes_matching_double_quotes():
    assert llm._strip_wrapped_quotes('"Bonjour tout le monde."') == "Bonjour tout le monde."


def test_strip_wrapped_quotes_removes_matching_single_quotes():
    assert llm._strip_wrapped_quotes("'Hola mundo.'") == "Hola mundo."


def test_strip_wrapped_quotes_removes_matching_curly_quotes():
    assert llm._strip_wrapped_quotes("“Guten Tag.”") == "Guten Tag."
    assert llm._strip_wrapped_quotes("‘Guten Tag.’") == "Guten Tag."


def test_strip_wrapped_quotes_leaves_unwrapped_text_alone():
    assert llm._strip_wrapped_quotes("Bonjour tout le monde.") == "Bonjour tout le monde."


def test_strip_wrapped_quotes_leaves_mismatched_quotes_alone():
    # Only the LAST char is a quote -- not a wrapping pair, don't touch it.
    assert llm._strip_wrapped_quotes('She said "hello.') == 'She said "hello.'


def test_strip_wrapped_quotes_leaves_internal_quoted_phrase_alone():
    # The quote marks aren't at the very start/end, so this is a real
    # quoted phrase inside the sentence, not a wrapper -- must not strip.
    text = 'He said "hello" to everyone.'
    assert llm._strip_wrapped_quotes(text) == text


def test_strip_wrapped_quotes_handles_short_and_empty_input():
    assert llm._strip_wrapped_quotes("") == ""
    assert llm._strip_wrapped_quotes('"') == '"'
    assert llm._strip_wrapped_quotes('""') == ""


def test_runner_translate_strips_wrapped_quotes(tmp_path, monkeypatch):
    monkeypatch.setattr(llm, "runtime_available", lambda: True)
    fake_module = types.ModuleType("llama_cpp")

    class _FakeLlama:
        def __init__(self, **_kw):
            pass

        def create_chat_completion(self, **_kw):
            return {"choices": [{"message": {"content": '"Bonjour."'}}]}

    fake_module.Llama = _FakeLlama  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "llama_cpp", fake_module)
    model_file = tmp_path / "m.gguf"
    model_file.write_bytes(b"\0" * 100)
    r = llm.LLMRunner(llm.LLMConfig(model_path=str(model_file)))
    assert r.translate("Hello.", target_language="French") == "Bonjour."


def test_remote_runner_translate_strips_wrapped_quotes(monkeypatch):
    monkeypatch.setattr(
        llm.urllib.request, "urlopen",
        lambda req, timeout=None: _FakeHTTPResponse(_chat_completion_body("'Hola.'")),
    )
    runner = llm.RemoteLLMRunner(llm.RemoteLLMConfig(base_url="https://api.openai.com/v1", model="m"))
    assert runner.translate("Hello.", target_language="Spanish") == "Hola."


# ---------- RemoteLLMRunner ------------------------------------------------


class _FakeHTTPResponse:
    def __init__(self, body: bytes):
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return None


def _chat_completion_body(content: str) -> bytes:
    return json.dumps(
        {"choices": [{"message": {"content": content}}]}
    ).encode("utf-8")


def test_remote_runner_chat_posts_expected_payload(monkeypatch):
    captured: dict = {}

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["headers"] = dict(req.header_items())
        captured["body"] = json.loads(req.data.decode("utf-8"))
        captured["timeout"] = timeout
        return _FakeHTTPResponse(_chat_completion_body("hi there"))

    monkeypatch.setattr(llm.urllib.request, "urlopen", fake_urlopen)
    runner = llm.RemoteLLMRunner(
        llm.RemoteLLMConfig(base_url="https://api.openai.com/v1", model="gpt-4o-mini", api_key="sk-test")
    )
    out = runner._chat([{"role": "user", "content": "hello"}])
    assert out == "hi there"
    assert captured["url"] == "https://api.openai.com/v1/chat/completions"
    assert captured["body"]["model"] == "gpt-4o-mini"
    assert captured["headers"].get("Authorization") == "Bearer sk-test"


def test_remote_runner_chat_omits_auth_header_when_key_blank(monkeypatch):
    captured: dict = {}

    def fake_urlopen(req, timeout=None):
        captured["headers"] = dict(req.header_items())
        return _FakeHTTPResponse(_chat_completion_body("ok"))

    monkeypatch.setattr(llm.urllib.request, "urlopen", fake_urlopen)
    runner = llm.RemoteLLMRunner(
        llm.RemoteLLMConfig(base_url="http://localhost:11434/v1", model="llama3")
    )
    runner._chat([{"role": "user", "content": "hello"}])
    assert "Authorization" not in captured["headers"]


def test_remote_runner_strips_trailing_slash_from_base_url(monkeypatch):
    captured: dict = {}

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        return _FakeHTTPResponse(_chat_completion_body("ok"))

    monkeypatch.setattr(llm.urllib.request, "urlopen", fake_urlopen)
    runner = llm.RemoteLLMRunner(
        llm.RemoteLLMConfig(base_url="https://example.com/v1/", model="m")
    )
    runner._chat([{"role": "user", "content": "hi"}])
    assert captured["url"] == "https://example.com/v1/chat/completions"


def test_remote_runner_http_error_becomes_remote_llm_error(monkeypatch):
    def fake_urlopen(req, timeout=None):
        raise llm.urllib.error.HTTPError(
            req.full_url, 401, "Unauthorized", email.message.Message(),
            io.BytesIO(b'{"error":"bad key"}'),
        )

    monkeypatch.setattr(llm.urllib.request, "urlopen", fake_urlopen)
    runner = llm.RemoteLLMRunner(llm.RemoteLLMConfig(base_url="https://api.openai.com/v1", model="m"))
    with pytest.raises(llm.RemoteLLMError, match="401"):
        runner._chat([{"role": "user", "content": "hi"}])


def test_remote_runner_url_error_becomes_remote_llm_error(monkeypatch):
    def fake_urlopen(req, timeout=None):
        raise llm.urllib.error.URLError("connection refused")

    monkeypatch.setattr(llm.urllib.request, "urlopen", fake_urlopen)
    runner = llm.RemoteLLMRunner(llm.RemoteLLMConfig(base_url="http://localhost:1234/v1", model="m"))
    with pytest.raises(llm.RemoteLLMError, match="Could not reach"):
        runner._chat([{"role": "user", "content": "hi"}])


def test_remote_runner_malformed_response_becomes_remote_llm_error(monkeypatch):
    monkeypatch.setattr(
        llm.urllib.request, "urlopen",
        lambda req, timeout=None: _FakeHTTPResponse(b"not json"),
    )
    runner = llm.RemoteLLMRunner(llm.RemoteLLMConfig(base_url="https://api.openai.com/v1", model="m"))
    with pytest.raises(llm.RemoteLLMError, match="unexpected response"):
        runner._chat([{"role": "user", "content": "hi"}])


def test_remote_runner_action_items_parses_json_array(monkeypatch):
    monkeypatch.setattr(
        llm.urllib.request, "urlopen",
        lambda req, timeout=None: _FakeHTTPResponse(_chat_completion_body('["a", "b"]')),
    )
    runner = llm.RemoteLLMRunner(llm.RemoteLLMConfig(base_url="https://api.openai.com/v1", model="m"))
    assert runner.action_items("transcript") == ["a", "b"]


def test_remote_runner_translate_and_ask(monkeypatch):
    monkeypatch.setattr(
        llm.urllib.request, "urlopen",
        lambda req, timeout=None: _FakeHTTPResponse(_chat_completion_body("Bonjour")),
    )
    runner = llm.RemoteLLMRunner(llm.RemoteLLMConfig(base_url="https://api.openai.com/v1", model="m"))
    assert runner.translate("Hello", target_language="French") == "Bonjour"
    assert runner.ask("transcript", "what?") == "Bonjour"
    assert runner.is_loaded() is True
    runner.load()  # no-op, must not raise
    runner.unload()  # no-op, must not raise


# ---------- build_runner_from_config ---------------------------------------


def test_build_runner_returns_none_when_ai_disabled():
    assert llm.build_runner_from_config({"ai_enabled": False}) is None


def test_build_runner_local_returns_none_without_model(tmp_path, monkeypatch):
    monkeypatch.setattr(llm, "runtime_available", lambda: True)
    cfg = {"ai_enabled": True, "llm_provider": "local", "ai_model_path": str(tmp_path / "missing.gguf")}
    assert llm.build_runner_from_config(cfg) is None


def test_build_runner_local_returns_runner_when_model_present(tmp_path, monkeypatch):
    monkeypatch.setattr(llm, "runtime_available", lambda: True)
    fake_module = types.ModuleType("llama_cpp")
    fake_module.Llama = MagicMock()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "llama_cpp", fake_module)
    model_file = tmp_path / "m.gguf"
    with model_file.open("wb") as f:  # >100 MB sanity floor (is_model_present)
        f.seek(101_000_000)
        f.write(b"\0")
    cfg = {"ai_enabled": True, "llm_provider": "local", "ai_model_path": str(model_file)}
    runner = llm.build_runner_from_config(cfg)
    assert isinstance(runner, llm.LLMRunner)


def test_build_runner_remote_returns_none_without_base_url_or_model():
    cfg = {"ai_enabled": True, "llm_provider": "remote", "llm_remote_base_url": "", "llm_remote_model": ""}
    assert llm.build_runner_from_config(cfg) is None
    cfg2 = {
        "ai_enabled": True, "llm_provider": "remote",
        "llm_remote_base_url": "https://api.openai.com/v1", "llm_remote_model": "",
    }
    assert llm.build_runner_from_config(cfg2) is None


def test_build_runner_remote_returns_configured_runner():
    cfg = {
        "ai_enabled": True,
        "llm_provider": "remote",
        "llm_remote_base_url": "https://api.openai.com/v1",
        "llm_remote_model": "gpt-4o-mini",
        "llm_remote_api_key": "sk-abc",
    }
    runner = llm.build_runner_from_config(cfg)
    assert isinstance(runner, llm.RemoteLLMRunner)
    assert runner.cfg.base_url == "https://api.openai.com/v1"
    assert runner.cfg.model == "gpt-4o-mini"
    assert runner.cfg.api_key == "sk-abc"


# ---------- translate_segments ----------------------------------------------


class _StubRunner:
    def __init__(self, fail_on: set[str] | None = None):
        self.calls: list[str] = []
        self.fail_on = fail_on or set()

    def translate(self, text: str, *, target_language: str = "English") -> str:
        self.calls.append(text)
        if text in self.fail_on:
            raise RuntimeError("boom")
        return f"[{target_language}] {text}"


def test_translate_segments_maps_1_to_1():
    segs = [{"text": "hello"}, {"text": "world"}]
    out = llm.translate_segments(_StubRunner(), segs, target_language="French")
    assert out == ["[French] hello", "[French] world"]


def test_translate_segments_blank_source_yields_blank_without_calling_runner():
    runner = _StubRunner()
    segs = [{"text": ""}, {"text": "  "}, {"text": "hi"}]
    out = llm.translate_segments(runner, segs)
    assert out == ["", "", "[English] hi"]
    assert runner.calls == ["hi"]


def test_translate_segments_one_failure_does_not_abort_the_rest():
    runner = _StubRunner(fail_on={"bad"})
    segs = [{"text": "good1"}, {"text": "bad"}, {"text": "good2"}]
    out = llm.translate_segments(runner, segs)
    assert out == ["[English] good1", "", "[English] good2"]


def test_translate_segments_calls_progress_cb_with_running_totals():
    calls: list[tuple[int, int]] = []
    segs = [{"text": "a"}, {"text": "b"}, {"text": "c"}]
    llm.translate_segments(_StubRunner(), segs, progress_cb=lambda done, total: calls.append((done, total)))
    assert calls == [(1, 3), (2, 3), (3, 3)]


def test_translate_segments_cancel_event_short_circuits_remaining():
    import threading
    cancel = threading.Event()
    runner = _StubRunner()

    def translate_then_cancel(text, *, target_language="English"):
        cancel.set()
        return f"[{target_language}] {text}"

    runner.translate = translate_then_cancel  # type: ignore[method-assign]
    segs = [{"text": "first"}, {"text": "second"}, {"text": "third"}]
    out = llm.translate_segments(runner, segs, cancel_event=cancel)
    assert out == ["[English] first", "", ""]


# ---------- local context-window fitting -------------------------------------
#
# The local runner is loaded with a fixed ``n_ctx`` (4096 by default) and
# llama-cpp-python raises BEFORE decoding once the prompt reaches that many
# tokens (llama_cpp 0.3.34: ``if len(prompt_tokens) >= self._n_ctx: raise
# ValueError(...)``). The transcript viewer feeds whole transcripts to
# summarise/action-items/ask/translate, so an un-fitted long prompt used to
# fail with a raw "Requested tokens ... exceed context window" error.


class _ContextAwareLlama:
    """Fake Llama that enforces a real context window on every call."""

    def __init__(self, *, n_ctx: int = 4096, chars_per_token: int = 4) -> None:
        self.n_ctx = n_ctx
        self._chars_per_token = chars_per_token
        self.calls: list[tuple[str, int]] = []

    def tokenize(self, data: bytes, add_bos: bool = False, special: bool = False):
        return list(range(1 + len(data) // self._chars_per_token))

    def create_chat_completion(self, *, messages, max_tokens, temperature=0.3):
        content = str(messages[-1]["content"])
        prompt_tokens = len(self.tokenize(content.encode("utf-8")))
        if prompt_tokens >= self.n_ctx:
            raise ValueError(
                f"Requested tokens ({prompt_tokens}) exceed context window "
                f"of {self.n_ctx}"
            )
        self.calls.append((content, max_tokens))
        return {"choices": [{"message": {"content": "summary ok"}}]}


class _NoTokenizeLlama:
    """Fake Llama without a ``tokenize`` method — exercises the char fallback."""

    def __init__(self, *, n_ctx: int = 4096) -> None:
        self.n_ctx = n_ctx
        self.calls: list[tuple[str, int]] = []

    def create_chat_completion(self, *, messages, max_tokens, temperature=0.3):
        content = str(messages[-1]["content"])
        if len(content) // 4 >= self.n_ctx:
            raise ValueError("Requested tokens exceed context window")
        self.calls.append((content, max_tokens))
        return {"choices": [{"message": {"content": "ok"}}]}


def _runner_with_fake_llama(monkeypatch, tmp_path, fake):
    monkeypatch.setattr(llm, "runtime_available", lambda: True)
    fake_module = types.ModuleType("llama_cpp")
    fake_module.Llama = lambda **_kw: fake  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "llama_cpp", fake_module)
    model_file = tmp_path / "m.gguf"
    model_file.write_bytes(b"\0" * 100)
    return llm.LLMRunner(llm.LLMConfig(model_path=str(model_file), n_ctx=fake.n_ctx))


def test_long_transcript_summarise_is_fitted_to_the_context_window(
    monkeypatch, tmp_path
):
    fake = _ContextAwareLlama()
    runner = _runner_with_fake_llama(monkeypatch, tmp_path, fake)
    assert runner.summarise("word " * 6000) == "summary ok"
    content, _max_tokens = fake.calls[-1]
    assert "truncated" in content
    assert len(content) < 30000


def test_long_prompt_fits_even_when_every_char_is_a_token(monkeypatch, tmp_path):
    """CJK-style tokenization (1 token/char) must also fit — the char-ratio
    estimate alone would still overflow the window."""
    fake = _ContextAwareLlama(chars_per_token=1)
    runner = _runner_with_fake_llama(monkeypatch, tmp_path, fake)
    assert runner.summarise("字" * 8000) == "summary ok"
    content, _max_tokens = fake.calls[-1]
    assert "truncated" in content
    assert len(content) < 8000


def test_short_transcript_is_not_truncated(monkeypatch, tmp_path):
    fake = _ContextAwareLlama()
    runner = _runner_with_fake_llama(monkeypatch, tmp_path, fake)
    text = "a short transcript about widgets"
    runner.summarise(text)
    content, max_tokens = fake.calls[-1]
    assert text in content
    assert "truncated" not in content
    assert max_tokens == 600


def test_ask_keeps_the_question_when_the_transcript_is_truncated(
    monkeypatch, tmp_path
):
    fake = _ContextAwareLlama()
    runner = _runner_with_fake_llama(monkeypatch, tmp_path, fake)
    runner.ask("word " * 6000, "What is the widget count?")
    content, _max_tokens = fake.calls[-1]
    assert "truncated" in content
    assert "What is the widget count?" in content


def test_long_translate_fits_and_keeps_answer_room(monkeypatch, tmp_path):
    fake = _ContextAwareLlama()
    runner = _runner_with_fake_llama(monkeypatch, tmp_path, fake)
    runner.translate("word " * 4000, target_language="French")
    content, max_tokens = fake.calls[-1]
    assert "truncated" in content
    assert max_tokens >= 1


def test_fitting_falls_back_when_the_model_has_no_tokenizer(monkeypatch, tmp_path):
    fake = _NoTokenizeLlama()
    runner = _runner_with_fake_llama(monkeypatch, tmp_path, fake)
    assert runner.summarise("x" * 30000) == "ok"
    content, _max_tokens = fake.calls[-1]
    assert "truncated" in content
    assert len(content) < 30000


def test_fit_messages_to_context_leaves_a_short_prompt_untouched():
    messages = [{"role": "user", "content": "hello"}]
    fitted, max_tokens = llm._fit_messages_to_context(
        messages, 100, 4096, lambda text: max(1, len(text) // 4)
    )
    assert fitted == messages
    assert max_tokens == 100


def test_truncate_middle_keeps_head_and_tail():
    text = "HEAD-" + "x" * 100 + "-TAIL"
    out = llm._truncate_middle(text, 60)
    assert len(out) <= 60
    assert out.startswith("HEAD-")
    assert out.endswith("-TAIL")
    assert "truncated" in out


def test_truncate_middle_is_a_noop_when_it_fits():
    assert llm._truncate_middle("short", 99) == "short"
