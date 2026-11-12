"""Simple AI actions recover when the worker thread cannot be started (no Tk)."""
from types import SimpleNamespace

import pytest

from app.dialogs import transcript_viewer as tv


def viewer():
    state = SimpleNamespace(_ai_busy=False, _closing=False,
        segments=[{"start": 0.0, "end": 1.0, "text": "synthetic transcript"}],
        statuses=[], results=[], calls=[])
    state._app_config = lambda: {"ai_enabled": True}
    state.buttons = []
    for name in ("_ai_summarise_btn", "_ai_actionitems_btn", "_ai_ask_btn",
                 "_ai_translate_btn", "_ai_bilingual_btn"):
        observed = []
        state.buttons.append(observed)
        setattr(state, name, SimpleNamespace(state=lambda flags, seen=observed: seen.append(tuple(flags))))
    actual_busy = tv.TranscriptViewer._set_ai_buttons_busy.__get__(state)
    def busy(value):
        actual_busy(value)
        state.statuses.append(value)
    state._set_ai_buttons_busy = busy
    state._set_ai_result = lambda text, language=None: state.results.append((text, language))
    state._finish_ai_task = tv.TranscriptViewer._finish_ai_task.__get__(state)
    state._get_llm_runner = lambda: (state.calls.append("runner") or object(), "")
    state._post_to_main = lambda fn: fn()
    return state


@pytest.mark.parametrize("label", ["Summarise", "Action items", "Ask", "Translate"])
@pytest.mark.parametrize("failure", [RuntimeError("synthetic thread allocation refusal"),
                                     OSError("synthetic operating system thread refusal")])
def test_thread_start_failure_restores_controls_and_shows_error(monkeypatch, label, failure):
    from core import _threads
    state = viewer()
    def fail_start(thread):
        raise failure
    monkeypatch.setattr(_threads.threading.Thread, "start", fail_start)
    tv.TranscriptViewer._run_ai_task(state, label, lambda runner: "provider result", "en")
    assert state._ai_busy is False
    assert state.statuses == [True, False]
    assert all(states == [("disabled",), ("!disabled",)] for states in state.buttons)
    assert str(failure) in state.results[-1][0]
    assert state.calls == [], "provider must not be built/called when the thread did not start"


def test_a_new_ai_action_can_finish_after_start_failure(monkeypatch):
    from core import _threads
    state = viewer()
    with monkeypatch.context() as failure:
        def fail_start(thread):
            raise RuntimeError("synthetic first start failure")
        failure.setattr(_threads.threading.Thread, "start", fail_start)
        tv.TranscriptViewer._run_ai_task(state, "Summarise", lambda runner: "must not run")
    assert state._ai_busy is False and state.calls == []
    original = _threads.safe_thread
    threads = []
    def record(target, **kwargs):
        thread = original(target, **kwargs)
        threads.append(thread)
        return thread
    monkeypatch.setattr(_threads, "safe_thread", record)
    def work(runner):
        state.calls.append("work")
        return "completed synthetic answer"
    tv.TranscriptViewer._run_ai_task(state, "Ask", work, "en")
    assert len(threads) == 1
    threads[0].join(timeout=5)
    assert not threads[0].is_alive()
    assert state.calls == ["runner", "work"]
    assert state.results[-1][1] == "en"
    assert state._ai_copy_text == "completed synthetic answer"
    assert state._ai_pending_result.saved_path in state.results[-1][0]
    assert state._ai_busy is False
    assert state.statuses == [True, False, True, False]


def test_busy_action_does_not_attempt_another_thread(monkeypatch):
    from core import _threads
    state = viewer()
    state._ai_busy = True
    attempts = []
    monkeypatch.setattr(_threads, "safe_thread", lambda *args, **kwargs: attempts.append(True))
    tv.TranscriptViewer._run_ai_task(state, "Ask", lambda runner: "must not run")
    assert attempts == [] and state.calls == []
    assert state._ai_busy is True


def test_existing_runner_build_error_still_restores_controls(monkeypatch):
    from core import _threads
    state = viewer()
    state._get_llm_runner = lambda: (None, "synthetic runner unavailable")
    monkeypatch.setattr(_threads, "safe_thread", lambda target, **kwargs: target())
    tv.TranscriptViewer._run_ai_task(state, "Translate", lambda runner: "must not run")
    assert state.results[-1][0] == "synthetic runner unavailable"
    assert state._ai_busy is False
