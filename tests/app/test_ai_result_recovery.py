"""Deliberate next-card RED: complete AI text must survive lost UI delivery."""
import pytest
from pathlib import Path
from core import _threads
from core import config
from app.dialogs import transcript_viewer as tv
from tests.app.test_ai_worker_startup import viewer

@pytest.mark.parametrize("mode", ["closed", "dropped"])
def test_completed_ai_text_survives_without_result_widget(tmp_path, monkeypatch, mode):
    state=viewer()
    body="Synthetic complete AI response whose only UI callback disappears"
    profile=tmp_path / "profile"
    monkeypatch.setattr(config, "user_data_dir", lambda: profile)
    monkeypatch.setattr(_threads, "safe_thread", lambda target, **kwargs: target())
    calls=[]
    def work(runner):
        calls.append(True)
        if mode=="closed":
            state._closing=True
        return body
    if mode=="dropped":
        state._post_to_main=lambda callback: None
    tv.TranscriptViewer._run_ai_task(state, "Summarise", work, "en")
    assert calls==[True], "the synthetic provider completed exactly once"
    assert not any(body==text for text, language in state.results)
    saved=[p for p in profile.rglob("*") if p.is_file()]
    assert any(body.encode("utf-8") in p.read_bytes() for p in saved), "completed result has no surviving profile copy"



def test_unsaved_result_prevents_close_and_retries_without_provider(tmp_path, monkeypatch):
    state = viewer()
    state.json_path = "source-at-dispatch.json"
    blocked = tmp_path / "blocked"
    blocked.write_bytes(b"unrelated original")
    monkeypatch.setattr(config, "user_data_dir", lambda: blocked)
    monkeypatch.setattr(_threads, "safe_thread", lambda target, **kwargs: target())
    calls = []
    def work(runner):
        calls.append(True)
        return "complete answer kept in memory"
    state._post_to_main = lambda callback: None
    tv.TranscriptViewer._run_ai_task(state, "Ask", work, "en")
    assert calls == [True] and state._ai_pending_result.save_error
    prompts = []
    monkeypatch.setattr(tv.messagebox, "askyesno", lambda *args, **kwargs: prompts.append(kwargs) or False)
    tv.TranscriptViewer._on_close(state)
    assert state._closing is False and state._ai_busy is False
    assert prompts == [{"parent": state, "default": "no"}]
    monkeypatch.setattr(config, "user_data_dir", lambda: tmp_path / "restored")
    state._post_to_main = lambda callback: callback()
    state._app_config = lambda: {"ai_enabled": False}
    state.segments = []
    state.json_path = "a-different-source.json"
    tv.TranscriptViewer._run_ai_task(state, "Translate", lambda runner: calls.append("unwanted call"))
    assert calls == [True]
    result = state._ai_pending_result
    assert not result.save_error and result.saved_path
    assert result.action == "Ask" and result.source_json == "source-at-dispatch.json"
    assert state._ai_copy_text == "complete answer kept in memory"
    copied = []
    state._copy_to_clipboard = copied.append
    tv.TranscriptViewer._copy_ai_result(state)
    assert copied == ["complete answer kept in memory"]


def test_provider_error_does_not_create_completed_result(tmp_path, monkeypatch):
    state = viewer()
    monkeypatch.setattr(config, "user_data_dir", lambda: tmp_path)
    monkeypatch.setattr(_threads, "safe_thread", lambda target, **kwargs: target())
    def fail(runner):
        raise RuntimeError("synthetic provider failure")
    tv.TranscriptViewer._run_ai_task(state, "Summarise", fail)
    assert "synthetic provider failure" in state.results[-1][0]
    assert not list(tmp_path.rglob("*.txt"))
    assert not getattr(state, "_ai_pending_result", None)


def test_delayed_completion_cannot_unlock_newer_action(tmp_path, monkeypatch):
    state = viewer()
    monkeypatch.setattr(config, "user_data_dir", lambda: tmp_path)
    monkeypatch.setattr(_threads, "safe_thread", lambda target, **kwargs: target())
    posted = []
    state._post_to_main = posted.append
    tv.TranscriptViewer._run_ai_task(state, "Summarise", lambda runner: "first completed text")
    state._set_ai_buttons_busy(False)
    tv.TranscriptViewer._run_ai_task(state, "Ask", lambda runner: "second completed text")
    posted[0]()
    assert state._ai_busy is True
    posted[1]()
    assert state._ai_busy is False and state._ai_copy_text == "second completed text"
    bodies = [path.read_text(encoding="utf-8") for path in tmp_path.rglob("*.txt")]
    assert any(text.endswith("first completed text") for text in bodies)
    assert any(text.endswith("second completed text") for text in bodies)


def test_result_copy_excludes_configuration_and_credentials(tmp_path, monkeypatch):
    state = viewer()
    state._app_config = lambda: {"ai_enabled": True, "llm_api_key": "dummy-credential-not-for-storage"}
    state.json_path = "synthetic source.json"
    monkeypatch.setattr(config, "user_data_dir", lambda: tmp_path)
    monkeypatch.setattr(_threads, "safe_thread", lambda target, **kwargs: target())
    tv.TranscriptViewer._run_ai_task(state, "Ask", lambda runner: "safe synthetic answer")
    saved, = tmp_path.rglob("*.txt")
    assert "dummy-credential-not-for-storage" not in saved.read_text(encoding="utf-8")
    assert "synthetic source.json" in saved.read_text(encoding="utf-8")



def test_source_and_language_are_snapshotted_before_provider_work(tmp_path, monkeypatch):
    state = viewer()
    state.json_path = "original transcript.json"
    monkeypatch.setattr(config, "user_data_dir", lambda: tmp_path)
    monkeypatch.setattr(_threads, "safe_thread", lambda target, **kwargs: target())
    def work(runner):
        state.json_path = "newly opened transcript.json"
        return "completed original result"
    tv.TranscriptViewer._run_ai_task(state, "Summarise", work, "en")
    result = state._ai_pending_result
    assert result.source_json == "original transcript.json" and result.language == "en"
    assert result.saved_path in state.results[-1][0]
    assert state._ai_copy_text == "completed original result"


def test_throwing_dispatcher_cannot_remove_completed_result(tmp_path, monkeypatch):
    state = viewer()
    monkeypatch.setattr(config, "user_data_dir", lambda: tmp_path)
    monkeypatch.setattr(_threads, "safe_thread", lambda target, **kwargs: target())
    def fail_dispatch(callback):
        raise RuntimeError("synthetic lost main-thread dispatcher")
    state._post_to_main = fail_dispatch
    tv.TranscriptViewer._run_ai_task(state, "Ask", lambda runner: "completed before dispatcher failure")
    result = state._ai_pending_result
    assert result.text == "completed before dispatcher failure" and result.saved_path
    assert not state._ai_worker_state.is_set()
    assert Path(result.saved_path).read_text(encoding="utf-8").endswith(result.text)


def test_actual_ask_button_retries_saved_answer_with_empty_question_and_ai_off(tmp_path, monkeypatch):
    from types import SimpleNamespace
    state = viewer()
    state.json_path = "original question source.json"
    state.language = "en"
    state._run_ai_task = tv.TranscriptViewer._run_ai_task.__get__(state)
    blocked = tmp_path / "blocked"
    blocked.write_bytes(b"unrelated original")
    monkeypatch.setattr(config, "user_data_dir", lambda: blocked)
    monkeypatch.setattr(_threads, "safe_thread", lambda target, **kwargs: target())
    calls = []
    tv.TranscriptViewer._run_ai_task(state, "Ask", lambda runner: calls.append(True) or "original complete answer", "en")
    assert calls == [True] and not state._ai_pending_result.saved_path
    monkeypatch.setattr(config, "user_data_dir", lambda: tmp_path / "repaired")
    state.json_path = "different currently opened source.json"
    state._ai_question_var = SimpleNamespace(get=lambda: "")
    state._app_config = lambda: {"ai_enabled": False}
    state._get_llm_runner = lambda: (_ for _ in ()).throw(AssertionError("file-only retry must not build provider"))
    notices = []
    monkeypatch.setattr(tv, "notify", lambda *args, **kwargs: notices.append(args))
    tv.TranscriptViewer._run_ask(state)
    saved = state._ai_pending_result
    assert saved.saved_path and not saved.save_error
    assert saved.source_json == "original question source.json" and saved.action == "Ask"
    assert saved.text == "original complete answer" and calls == [True]
    assert notices == []
