"""The real Action items button retains a malformed reply rather than claiming none."""
from pathlib import Path
from types import SimpleNamespace
import pytest
from core import _threads, config, llm
from app.dialogs import transcript_viewer as tv
from tests.app.test_ai_worker_startup import viewer


@pytest.mark.parametrize("raw", ["Send the report tomorrow.", '["Send the report",',
                                  '[{"task":"Send the report"}]', '["Send report", null]'])
def test_action_button_displays_and_saves_the_original_invalid_reply(tmp_path, monkeypatch, raw):
    state = viewer()
    state.json_path = "synthetic transcript.json"
    state.language = "en"
    state._full_transcript_text = lambda: "synthetic transcript with actionable tasks"
    state._run_ai_task = tv.TranscriptViewer._run_ai_task.__get__(state)
    calls = []
    runner = SimpleNamespace(_chat=lambda messages, **kwargs: calls.append(messages) or raw)
    runner.action_items = lambda text: llm.RemoteLLMRunner.action_items(runner, text)
    state._get_llm_runner = lambda: (runner, "")
    monkeypatch.setattr(config, "user_data_dir", lambda: tmp_path)
    monkeypatch.setattr(_threads, "safe_thread", lambda target, **kwargs: target())
    tv.TranscriptViewer._run_action_items(state)
    assert len(calls) == 1
    assert raw in state._ai_copy_text
    assert "(no action items detected)" not in state._ai_copy_text
    assert "not a valid action-item list" in state._ai_copy_text
    saved = Path(state._ai_pending_result.saved_path)
    assert saved.read_text(encoding="utf-8").endswith(state._ai_copy_text)
    assert state._ai_busy is False


def test_valid_empty_array_still_displays_no_action_items(tmp_path, monkeypatch):
    state = viewer()
    state.language = "en"
    state._full_transcript_text = lambda: "synthetic conversation without tasks"
    state._run_ai_task = tv.TranscriptViewer._run_ai_task.__get__(state)
    runner = SimpleNamespace(_chat=lambda *args, **kwargs: "[]")
    runner.action_items = lambda text: llm.LLMRunner.action_items(runner, text)
    state._get_llm_runner = lambda: (runner, "")
    monkeypatch.setattr(config, "user_data_dir", lambda: tmp_path)
    monkeypatch.setattr(_threads, "safe_thread", lambda target, **kwargs: target())
    tv.TranscriptViewer._run_action_items(state)
    assert state._ai_copy_text == "(no action items detected)"


def test_nonempty_length_limited_remote_reply_survives_real_response_extraction(tmp_path, monkeypatch):
    import io
    import json
    state = viewer()
    state.json_path = "synthetic transcript.json"
    state.language = "en"
    state._full_transcript_text = lambda: "A colleague will send the report tomorrow."
    state._run_ai_task = tv.TranscriptViewer._run_ai_task.__get__(state)
    raw = '["Send the report tomorrow", "Call'
    response = json.dumps({"choices": [{"message": {"content": raw}, "finish_reason": "length"}]}).encode("utf-8")
    requests = []
    def fake_http(req, timeout=None):
        requests.append(json.loads(req.data))
        return io.BytesIO(response)
    monkeypatch.setattr(llm.urllib.request, "urlopen", fake_http)
    runner = llm.RemoteLLMRunner(llm.RemoteLLMConfig(base_url="https://llm.invalid/v1", model="synthetic-model"))
    state._get_llm_runner = lambda: (runner, "")
    monkeypatch.setattr(config, "user_data_dir", lambda: tmp_path)
    monkeypatch.setattr(_threads, "safe_thread", lambda target, **kwargs: target())
    tv.TranscriptViewer._run_action_items(state)
    assert len(requests) == 1, "invalid nonempty replies must not trigger another provider request"
    assert raw in state._ai_copy_text
    assert "(no action items detected)" not in state._ai_copy_text
    saved = Path(state._ai_pending_result.saved_path)
    assert saved.read_text(encoding="utf-8").endswith(state._ai_copy_text)
