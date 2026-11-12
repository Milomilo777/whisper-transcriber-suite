"""App exit must also protect a completed response with no saved file (no Tk)."""
import pytest
import threading
from core import config,llm
from app.dialogs import transcript_viewer as tv
from tests.app.test_ai_worker_startup import viewer


def test_close_decline_keeps_later_unsaved_provider_result_reachable(tmp_path, monkeypatch):
    from core import _threads
    state = viewer()
    state._dirty = False
    state._vlc_bind_id = state.vlc_seek_after = state._find_dialog = None
    state.vlc_player = state.vlc_instance = None
    destroyed = []
    state.destroy = lambda: destroyed.append(True)
    state.winfo_exists = lambda: not destroyed
    state._post_to_main = lambda callback: None
    blocked = tmp_path / "blocked-profile"
    blocked.write_bytes(b"unrelated original")
    monkeypatch.setattr(config, "user_data_dir", lambda: blocked)
    entered, release = threading.Event(), threading.Event()
    threads = []
    original = _threads.safe_thread
    def spawn(fn, **kwargs):
        thread = original(fn, **kwargs)
        threads.append(thread)
        return thread
    monkeypatch.setattr(_threads, "safe_thread", spawn)
    def work(runner):
        entered.set()
        assert release.wait(3)
        return "completed while closing, with failed storage"
    asked = []
    monkeypatch.setattr(tv.messagebox, "askyesno", lambda *a, **kw: asked.append(kw) or False)
    tv.TranscriptViewer._run_ai_task(state, "Ask", work, "en")
    assert entered.wait(1)
    try:
        tv.TranscriptViewer._on_close(state)
        closed_early = state._closing
    finally:
        release.set()
        threads[0].join(timeout=2)
    assert not threads[0].is_alive()
    assert not closed_early and not destroyed, "The owner of a running response disappeared without consent"
    assert asked == [{"parent": state, "default": "no"}]
    assert state._ai_pending_result.text == "completed while closing, with failed storage"
    assert state._ai_pending_result.save_error
    assert blocked.read_bytes() == b"unrelated original"


def test_app_exit_checks_running_provider_before_irreversible_teardown(monkeypatch):
    state = _memory_viewer()
    state._ai_pending_result = None
    state._ai_worker_state = threading.Event()
    state._ai_worker_state.set()
    App, app = _exit_environment(monkeypatch, state)
    asked = []
    monkeypatch.setattr(tv.messagebox, "askyesno", lambda *a, **kw: asked.append(kw) or False)
    App.on_exit(app)
    assert asked == [{"parent": state, "default": "no"}]
    assert not app._closing and not app._exit_prompt_open


@pytest.mark.parametrize("worker_name", ["_ai_worker_state", "_bilingual_worker_state"])
def test_active_task_discard_is_explicit_and_reused_only_for_that_task(monkeypatch, worker_name):
    state = _memory_viewer()
    state._ai_pending_result = None
    active = threading.Event()
    active.set()
    setattr(state, worker_name, active)
    App, app = _exit_environment(monkeypatch, state)
    asked = []
    monkeypatch.setattr(tv.messagebox, "askyesno", lambda *a, **kw: asked.append(kw) or True)
    with pytest.raises(_ExitReached):
        App.on_exit(app)
    assert asked == [{"parent": state, "default": "no"}]


def test_active_task_consent_does_not_cover_a_replacement_task(monkeypatch):
    state = _memory_viewer()
    state._ai_pending_result = None
    original, replacement = threading.Event(), threading.Event()
    original.set()
    replacement.set()
    state._ai_worker_state = original
    monkeypatch.setattr(tv, "_OPEN_VIEWERS", {"synthetic": state})
    asked = []
    def answer(*args, **kwargs):
        asked.append(state._ai_worker_state)
        if len(asked) == 1:
            original.clear()
            state._ai_worker_state = replacement
            return True
        return False
    monkeypatch.setattr(tv.messagebox, "askyesno", answer)
    assert tv.confirm_unsaved_before_exit() is False
    assert asked == [original, replacement]


def test_active_task_consent_rechecks_a_result_completed_during_its_question(monkeypatch):
    state = _memory_viewer()
    state._ai_pending_result = None
    state._ai_worker_state = threading.Event()
    state._ai_worker_state.set()
    monkeypatch.setattr(tv, "_OPEN_VIEWERS", {"synthetic": state})
    asked = []
    def answer(title, message, **kwargs):
        asked.append(message)
        assert kwargs == {"parent": state, "default": "no"}
        if len(asked) == 1:
            state._ai_pending_result = llm.SavedAIResult(
                "finished during active-task question", "Ask", state.json_path, save_error="storage failure")
            state._ai_worker_state.clear()
            return True
        return False
    monkeypatch.setattr(tv.messagebox, "askyesno", answer)
    assert tv.confirm_unsaved_before_exit() is False
    assert len(asked) == 2
    assert "still running" in asked[0] and "completed AI result" in asked[1]


@pytest.mark.parametrize("already_decided_edits", [False, True])
def test_app_exit_cannot_skip_unsaved_ai_result(tmp_path, monkeypatch, already_decided_edits):
    state=viewer()
    state._dirty=False
    state.winfo_exists=lambda:True
    blocked=tmp_path / "blocked-profile"
    blocked.write_bytes(b"unrelated original")
    monkeypatch.setattr(config,"user_data_dir",lambda:blocked)
    state._ai_pending_result=llm.save_ai_result("completed answer",action="Ask",source_json="source.json")
    assert not state._ai_pending_result.saved_path and state._ai_pending_result.save_error
    monkeypatch.setattr(tv,"_OPEN_VIEWERS",{"synthetic":state})
    prompts=[]
    monkeypatch.setattr(tv.messagebox,"askyesno",lambda *args,**kwargs:prompts.append(kwargs) or False)
    skip=(state,) if already_decided_edits else ()
    assert tv.confirm_unsaved_before_exit(skip=skip) is False
    assert prompts==[{"parent":state,"default":"no"}]
    assert not state._closing and state._ai_pending_result.text=="completed answer"
    assert blocked.read_bytes()==b"unrelated original"


def test_app_exit_does_not_prompt_for_verified_ai_copy(tmp_path,monkeypatch):
    state=viewer()
    state._dirty=False
    state.winfo_exists=lambda:True
    monkeypatch.setattr(config,"user_data_dir",lambda:tmp_path)
    state._ai_pending_result=llm.save_ai_result("completed saved answer",action="Ask",source_json="source.json")
    assert llm.ai_result_is_saved(state._ai_pending_result)
    monkeypatch.setattr(tv,"_OPEN_VIEWERS",{"synthetic":state})
    prompts=[]
    monkeypatch.setattr(tv.messagebox,"askyesno",lambda *args,**kwargs:prompts.append(kwargs) or False)
    assert tv.confirm_unsaved_before_exit() is True
    assert prompts==[]


def _memory_viewer(text="completed answer"):
    state=viewer()
    state._dirty=False
    state.json_path="synthetic transcript.json"
    state.winfo_exists=lambda:True
    state._ai_pending_result=llm.SavedAIResult(text,"Ask",state.json_path,save_error="synthetic storage refusal")
    return state


def test_result_completed_in_earlier_viewer_during_later_prompt_is_rechecked(monkeypatch):
    first=_memory_viewer()
    first._ai_pending_result=None
    second=_memory_viewer("second answer")
    monkeypatch.setattr(tv,"_OPEN_VIEWERS",{"first":first,"second":second})
    asked=[]
    def answer(*args,**kwargs):
        asked.append(kwargs["parent"])
        if kwargs["parent"] is second:
            first._ai_pending_result=llm.SavedAIResult("new first answer","Ask",first.json_path,save_error="late refusal")
            return True
        return False
    monkeypatch.setattr(tv.messagebox,"askyesno",answer)
    assert tv.confirm_unsaved_before_exit() is False
    assert asked==[second,first]


def test_result_completed_during_transcript_save_prompt_is_rechecked(monkeypatch):
    state=_memory_viewer()
    state._ai_pending_result=None
    state._dirty=True
    def save_edits(show_folder=False):
        state._dirty=False
        state._ai_pending_result=llm.SavedAIResult("finished during edit prompt","Ask",state.json_path,save_error="late refusal")
        return True
    state._confirm_exit=save_edits
    monkeypatch.setattr(tv,"_OPEN_VIEWERS",{"synthetic":state})
    asked=[]
    monkeypatch.setattr(tv.messagebox,"askyesno",lambda *args,**kwargs:asked.append(kwargs["parent"]) or False)
    assert tv.confirm_unsaved_before_exit() is False
    assert asked==[state]


class _ExitReached(Exception):
    pass


class _ExitApp:
    def __init__(self):
        self._closing=False
        self._exit_prompt_open=False
        self._exit_from_tray=True
        self.app_config={}
        self.tray=None
        self.queue=[]
        self.download_queue=[]
    def __setattr__(self,name,value):
        if name=="_closing" and value is True:
            raise _ExitReached("stopped before any real teardown")
        object.__setattr__(self,name,value)


def _exit_environment(monkeypatch,state,live=lambda app:True):
    from app import app as app_module
    from app.app import App
    monkeypatch.setattr(tv,"_OPEN_VIEWERS",{"synthetic":state})
    monkeypatch.setattr(App,"active_server_jobs",lambda app:False)
    monkeypatch.setattr(app_module,"live_save_before_exit",live)
    monkeypatch.setattr(app_module,"_dirty_viewers_now",lambda:[])
    monkeypatch.setattr(app_module,"_finish_viewer_exports",lambda app:None)
    return App,_ExitApp()


def test_actual_app_exit_asks_once_for_unchanged_response_across_both_passes(monkeypatch):
    state=_memory_viewer()
    App,app=_exit_environment(monkeypatch,state)
    asked=[]
    monkeypatch.setattr(tv.messagebox,"askyesno",lambda *args,**kwargs:asked.append(kwargs["parent"]) or True)
    with pytest.raises(_ExitReached):
        App.on_exit(app)
    assert asked==[state]


def test_cancelled_exit_does_not_approve_discard_for_a_later_attempt(monkeypatch):
    state=_memory_viewer()
    App,app=_exit_environment(monkeypatch,state,live=lambda app:False)
    answers=iter([True,False])
    asked=[]
    def answer(*args,**kwargs):
        asked.append(kwargs["parent"])
        return next(answers)
    monkeypatch.setattr(tv.messagebox,"askyesno",answer)
    App.on_exit(app)
    assert not app._closing and not app._exit_prompt_open
    App.on_exit(app)
    assert asked==[state,state]
    assert not app._closing and not app._exit_prompt_open


@pytest.mark.parametrize("replacement_body", ["same answer", "new answer"])
def test_approval_does_not_cover_response_replaced_during_question(monkeypatch, replacement_body):
    state = _memory_viewer("same answer")
    original = state._ai_pending_result
    monkeypatch.setattr(tv, "_OPEN_VIEWERS", {"synthetic": state})
    asked = []

    def answer(*args, **kwargs):
        asked.append(state._ai_pending_result)
        if len(asked) == 1:
            state._ai_pending_result = llm.SavedAIResult(
                replacement_body, "Ask", state.json_path, save_error="new storage refusal"
            )
            return True
        return False

    monkeypatch.setattr(tv.messagebox, "askyesno", answer)
    assert tv.confirm_unsaved_before_exit() is False
    assert len(asked) == 2 and asked[0] is original
    assert asked[1] is state._ai_pending_result and asked[1] is not original
    assert asked[1].text == replacement_body


@pytest.mark.parametrize("arriving_kind", ["ai", "bilingual"])
def test_other_result_kind_completed_during_question_is_rechecked(monkeypatch, arriving_kind):
    from types import SimpleNamespace
    from core.writers import bilingual_srt

    state = _memory_viewer()
    state._pending_bilingual_save = None
    translation = SimpleNamespace(saved_path=None, body="completed translation")
    if arriving_kind == "ai":
        state._ai_pending_result = None
        state._pending_bilingual_save = translation
    monkeypatch.setattr(tv, "_OPEN_VIEWERS", {"synthetic": state})
    monkeypatch.setattr(bilingual_srt, "_valid_recovery", lambda result: False)
    asked = []

    def answer(title, message, **kwargs):
        asked.append(message)
        if len(asked) == 1:
            if arriving_kind == "ai":
                state._ai_pending_result = llm.SavedAIResult(
                    "new answer", "Ask", state.json_path, save_error="late storage refusal"
                )
            else:
                state._pending_bilingual_save = translation
            return True
        return False

    monkeypatch.setattr(tv.messagebox, "askyesno", answer)
    assert tv.confirm_unsaved_before_exit() is False
    assert len(asked) == 2
    assert ("AI result" in asked[1]) == (arriving_kind == "ai")
    assert state._pending_bilingual_save is translation
