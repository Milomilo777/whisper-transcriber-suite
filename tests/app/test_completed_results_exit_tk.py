"""Real Tk viewer and app exit acceptance for memory-only completed results.

Run on the remote real desktop; no provider, native ASR, model or microphone is used.
"""
from __future__ import annotations

import pytest
import threading

from app import app as app_module
from app.dialogs import transcript_viewer as tv
from core import llm
from tests.app.test_exit_unsaved_viewers import app, calls, _make_json


def open_viewer(root, tmp_path, name="talk"):
    state = tv.TranscriptViewer(root, _make_json(tmp_path, name))
    state.withdraw()
    state._dirty = False
    return state


def memory_result(state, body="completed synthetic answer"):
    record = llm.SavedAIResult(body, "Ask", state.json_path, save_error="synthetic storage refusal")
    state._ai_pending_result = record
    return record


def test_real_viewer_declining_active_close_keeps_later_failed_result(app, tmp_path, monkeypatch):
    state = open_viewer(app, tmp_path)
    state._ai_worker_state = threading.Event()
    state._ai_worker_state.set()
    asked = []
    monkeypatch.setattr(tv.messagebox, "askyesno", lambda *a, **kw: asked.append(kw) or False)
    state._on_close()
    assert state.winfo_exists() and not state._closing
    pending = memory_result(state, "response finished after close was declined")
    state._ai_worker_state.clear()
    state._on_close()
    assert state.winfo_exists() and state._ai_pending_result is pending
    assert asked == [{"parent": state, "default": "no"}] * 2


def test_real_app_rechecks_failed_save_completed_in_active_question(app, calls, tmp_path, monkeypatch):
    state = open_viewer(app, tmp_path)
    active = threading.Event()
    active.set()
    state._ai_worker_state = active
    asked = []
    def answer(title, message, **kwargs):
        asked.append(message)
        assert kwargs == {"parent": state, "default": "no"}
        if len(asked) == 1:
            def complete():
                memory_result(state, "completed while active question ran")
                active.clear()
            app.after_idle(complete)
            app.update_idletasks()
            return True
        return False
    monkeypatch.setattr(tv.messagebox, "askyesno", answer)
    app.on_exit()
    assert len(asked) == 2
    assert "still running" in asked[0] and "completed AI result" in asked[1]
    assert state.winfo_exists() and not app._closing and calls == []


def test_app_exit_keeps_real_viewer_and_memory_answer_when_discard_declined(app, calls, tmp_path, monkeypatch):
    state = open_viewer(app, tmp_path)
    pending = memory_result(state)
    asked = []
    monkeypatch.setattr(tv.messagebox, "askyesno", lambda *a, **kw: asked.append(kw) or False)
    app.on_exit()
    assert asked == [{"parent": state, "default": "no"}]
    assert state.winfo_exists() and state._ai_pending_result is pending
    assert not app._closing and calls == []


def test_real_app_two_pass_exit_confirms_unchanged_answer_once(app, calls, tmp_path, monkeypatch):
    state = open_viewer(app, tmp_path)
    memory_result(state)
    asked = []
    monkeypatch.setattr(tv.messagebox, "askyesno", lambda *a, **kw: asked.append(kw["parent"]) or True)
    app.on_exit()
    assert asked == [state]
    assert app._closing and "stop_all" in calls and calls[-1] == "destroy"


def test_real_tk_idle_completion_in_earlier_viewer_during_later_question(app, calls, tmp_path, monkeypatch):
    first = open_viewer(app, tmp_path, "first")
    second = open_viewer(app, tmp_path, "second")
    memory_result(second)
    asked, completed = [], []

    def answer(*args, **kwargs):
        asked.append(kwargs["parent"])
        if kwargs["parent"] is second:
            app.after_idle(lambda: completed.append(memory_result(first, "new first answer")))
            app.update_idletasks()
            return True
        return False

    monkeypatch.setattr(tv.messagebox, "askyesno", answer)
    app.on_exit()
    assert asked == [second, first]
    assert len(completed) == 1 and first._ai_pending_result is completed[0]
    assert not app._closing and calls == []


def test_real_tk_completion_during_transcript_discard_is_protected(app, calls, tmp_path, monkeypatch):
    state = open_viewer(app, tmp_path)
    state._dirty = True
    completed, asked = [], []

    def discard_edits(*args, **kwargs):
        app.after_idle(lambda: completed.append(memory_result(state)))
        app.update_idletasks()
        return False

    monkeypatch.setattr(tv.messagebox, "askyesnocancel", discard_edits)
    monkeypatch.setattr(tv.messagebox, "askyesno", lambda *a, **kw: asked.append(kw["parent"]) or False)
    app.on_exit()
    assert asked == [state] and len(completed) == 1
    assert not app._closing and calls == []
    assert state.winfo_exists() and state._ai_pending_result is completed[0]


def test_real_viewer_close_rechecks_result_after_edit_question(app, calls, tmp_path, monkeypatch):
    state = open_viewer(app, tmp_path)
    state._dirty = True
    asked = []

    def answer(message_title, message, **kwargs):
        asked.append((message, kwargs))
        if len(asked) == 1:
            # Closing one viewer uses Yes/No for edits; whole-app exit uses
            # its separate Save/Discard/Cancel question.
            app.after_idle(lambda: memory_result(state))
            app.update_idletasks()
            return True
        return False

    monkeypatch.setattr(tv.messagebox, "askyesno", answer)
    state._on_close()
    assert [message for message, _ in asked] == [
        tv._("There are unsaved transcript edits. Close anyway?"),
        tv._("A completed AI result has not been saved. Close anyway?"),
    ]
    assert all(kwargs == {"parent": state, "default": "no"} for _, kwargs in asked)
    assert state.winfo_exists() and not state._closing and state._dirty
    assert state._ai_pending_result.text == "completed synthetic answer"


def test_cancelled_app_exit_reasks_on_next_attempt_real_viewer(app, calls, tmp_path, monkeypatch):
    state = open_viewer(app, tmp_path)
    memory_result(state)
    asked = []
    answers = iter([True, False])
    monkeypatch.setattr(tv.messagebox, "askyesno", lambda *a, **kw: asked.append(kw["parent"]) or next(answers))
    monkeypatch.setattr(app_module, "live_save_before_exit", lambda root: False)
    app.on_exit()
    app.on_exit()
    assert asked == [state, state] and calls == []
    assert not app._closing and not app._exit_prompt_open


@pytest.mark.parametrize("same_body", [True, False])
def test_real_viewer_replacement_during_question_needs_own_approval(app, calls, tmp_path, monkeypatch, same_body):
    state = open_viewer(app, tmp_path)
    original = memory_result(state)
    asked = []

    def answer(*args, **kwargs):
        asked.append(state._ai_pending_result)
        if len(asked) == 1:
            body = original.text if same_body else "different completed answer"
            app.after_idle(lambda: memory_result(state, body))
            app.update_idletasks()
            return True
        return False

    monkeypatch.setattr(tv.messagebox, "askyesno", answer)
    app.on_exit()
    assert len(asked) == 2 and asked[0] is original
    assert asked[1] is state._ai_pending_result and asked[1] is not original
    assert state.winfo_exists() and not app._closing and calls == []


@pytest.mark.parametrize("individual_close", [False, True])
def test_real_viewer_memory_only_translation_decline_stays_open(app, calls, tmp_path, monkeypatch, individual_close):
    from core.writers.bilingual_srt import SavedBilingual

    state = open_viewer(app, tmp_path)
    pending = SavedBilingual(state.segments, ["translated first", "translated second"],
                             source_json=state.json_path, language="French", target="synthetic.srt")
    state._pending_bilingual_save = pending
    asked = []
    monkeypatch.setattr(tv.messagebox, "askyesno", lambda *a, **kw: asked.append(kw) or False)
    if individual_close:
        state._on_close()
    else:
        app.on_exit()
    assert asked == [{"parent": state, "default": "no"}]
    assert state.winfo_exists() and not state._closing and state._pending_bilingual_save is pending
    assert not app._closing and calls == []


def test_real_tk_translation_body_changed_during_question_needs_new_approval(app, calls, tmp_path, monkeypatch):
    from core.writers.bilingual_srt import SavedBilingual

    state = open_viewer(app, tmp_path)
    pending = SavedBilingual(state.segments, ["translated first", "translated second"],
                             source_json=state.json_path, language="French", target="synthetic.srt")
    state._pending_bilingual_save = pending
    asked = []

    def answer(*args, **kwargs):
        asked.append(pending.body)
        if len(asked) == 1:
            app.after_idle(lambda: setattr(pending, "body", "different completed translation"))
            app.update_idletasks()
            return True
        return False

    monkeypatch.setattr(tv.messagebox, "askyesno", answer)
    app.on_exit()
    assert len(asked) == 2 and asked[0] != asked[1]
    assert asked[1] == "different completed translation"
    assert state.winfo_exists() and not app._closing and calls == []
