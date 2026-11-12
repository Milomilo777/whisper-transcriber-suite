"""Finished live words remain recoverable if the bounded UI event queue falls behind."""
import queue
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.widgets import live_tab
from core import live


@pytest.fixture
def session_app(tmp_path, monkeypatch):
    work = tmp_path / "session"
    work.mkdir()
    counter = iter(range(1, 10000))
    session = live.LiveSession(
        transcribe_chunk=lambda path: {"text": f"Finished sentence {next(counter)}"},
        work_dir=str(work),
    )
    session.recording_path = str(work / "live-session.wav")
    live.write_wav(session.recording_path, b"\x01\x00" * 512, 16000)
    logs = []
    app = SimpleNamespace(
        live_session=session, live_transcriber=None, live_lines=[],
        live_status_var=SimpleNamespace(set=lambda value: None),
        live_keep_var=SimpleNamespace(get=lambda: False),
        app_config={"download_folder": str(tmp_path)},
        download_folder_var=SimpleNamespace(get=lambda: str(tmp_path)),
        _live_saved_count=0, _live_saved_paths=[], _live_held=[],
        _live_draining=False, _live_exit_discard=False, log=logs.append,
    )
    monkeypatch.setattr(live_tab, "_set_running", lambda *args: None)
    monkeypatch.setattr(live_tab.filedialog, "asksaveasfilename", lambda **kwargs: str(tmp_path / "saved.txt"))
    return session, app, tmp_path / "saved.txt", logs


def finish_sentences(session, count):
    for number in range(1, count + 1):
        session._consume_one((number, b"\x01\x00" * 512, float(number), 16000))


def test_stop_drains_all_finished_text_before_releasing_session(session_app):
    session, app, saved, _logs = session_app
    finish_sentences(session, 70)
    live_tab._stopped(app)
    assert len(app.live_lines) == 70
    assert app.live_lines[-1] == "Finished sentence 70"
    assert session.events.empty()
    assert live_tab._save(app) is True
    assert "Finished sentence 70" in saved.read_text(encoding="utf-8")


def test_saving_visible_text_preserves_dropped_words_and_audio(session_app):
    session, app, saved, _logs = session_app
    session.events = queue.Queue(maxsize=3)
    finish_sentences(session, 5)
    live_tab._stopped(app)
    assert len(app.live_lines) == 3
    assert live_tab._save(app) is True and saved.is_file()
    journal = Path(session.journal_path)
    assert journal.is_file(), "saving visible text deleted words that never reached the UI"
    assert "Finished sentence 5" in journal.read_text(encoding="utf-8")
    assert Path(session.recording_path).is_file()
    assert session.transcript_saved is False and app._live_held


def test_all_text_events_dropped_does_not_release_session_immediately(session_app):
    session, app, _saved, _logs = session_app
    session.events = queue.Queue(maxsize=1)
    session.events.put(live.LiveEvent(kind="state", detail="started"))
    finish_sentences(session, 2)
    live_tab._stopped(app)
    assert app.live_lines == []
    assert Path(session.journal_path).is_file()
    assert Path(session.recording_path).is_file()
    assert session.transcript_saved is False and app._live_held


def test_explicit_discard_can_release_dropped_text(session_app):
    session, app, _saved, _logs = session_app
    session.events = queue.Queue(maxsize=1)
    finish_sentences(session, 2)
    live_tab._stopped(app)
    live_tab._release_all(app)
    assert not Path(session.journal_path).exists()
    assert not Path(session.recording_path).exists()


def test_exit_autosave_preserves_unreported_words(session_app):
    session, app, _saved, _logs = session_app
    session.events = queue.Queue(maxsize=3)
    finish_sentences(session, 5)
    live_tab.stop_live_session(app)
    assert Path(session.journal_path).is_file()
    assert "Finished sentence 5" in Path(session.journal_path).read_text(encoding="utf-8")
    assert Path(session.recording_path).is_file()


def test_explicit_exit_discard_releases_unreported_words(session_app):
    session, app, _saved, _logs = session_app
    session.events = queue.Queue(maxsize=1)
    finish_sentences(session, 2)
    app._live_exit_discard = True
    live_tab.stop_live_session(app)
    assert not Path(session.journal_path).exists()
    assert not Path(session.recording_path).exists()


def test_exit_keeps_held_unreported_words_after_visible_text_was_saved(session_app):
    session, app, _saved, _logs = session_app
    session.events = queue.Queue(maxsize=1)
    finish_sentences(session, 2)
    live_tab._stopped(app)
    assert live_tab._save(app) is True
    live_tab.stop_live_session(app)
    assert Path(session.journal_path).is_file()
    assert Path(session.recording_path).is_file()


def test_dropped_status_events_do_not_keep_fully_saved_text(session_app):
    session, app, _saved, _logs = session_app
    finish_sentences(session, 1)
    live_tab._poll_once(app)
    session.events = queue.Queue(maxsize=1)
    session._emit(live.LiveEvent(kind="warning", detail="status"))
    session._emit(live.LiveEvent(kind="warning", detail="another status"))
    live_tab._stopped(app)
    assert live_tab._save(app) is True
    assert not Path(session.journal_path).exists()
    assert not Path(session.recording_path).exists()


def test_failed_event_collection_preserves_pending_text(session_app, monkeypatch):
    session, app, _saved, _logs = session_app
    finish_sentences(session, 1)

    def fail():
        raise RuntimeError("synthetic event collection failure")

    monkeypatch.setattr(session, "drain_events", fail)
    live_tab._stopped(app)
    assert Path(session.journal_path).is_file()
    assert Path(session.recording_path).is_file()
    assert session.transcript_saved is False


@pytest.mark.parametrize("callback", ["status", "log"])
def test_failed_status_callback_does_not_lose_later_text(session_app, callback):
    session, app, saved, _logs = session_app
    session._emit(live.LiveEvent(kind="warning", detail="transient status"))
    finish_sentences(session, 2)

    def fail_once(value):
        app.live_status_var = SimpleNamespace(set=lambda value: None)
        app.log = lambda value: None
        raise RuntimeError("synthetic status callback failure")

    if callback == "status":
        app.live_status_var = SimpleNamespace(set=fail_once)
    else:
        app.log = fail_once
    try:
        live_tab._poll_once(app)
    except RuntimeError:
        pass
    live_tab._stopped(app)
    assert app.live_lines == ["Finished sentence 1", "Finished sentence 2"]
    assert live_tab._save(app) is True
    assert "Finished sentence 2" in saved.read_text(encoding="utf-8")


def test_failed_text_append_does_not_acknowledge_unreported_words(session_app):
    session, app, _saved, _logs = session_app

    class FailFirstAppend(list):
        failed = False

        def append(self, text):
            if not self.failed:
                self.failed = True
                raise RuntimeError("synthetic text append failure")
            super().append(text)

    app.live_lines = FailFirstAppend()
    finish_sentences(session, 2)
    live_tab._stopped(app)
    assert app.live_lines == ["Finished sentence 2"]
    assert live_tab._save(app) is True
    assert "Finished sentence 1" in Path(session.journal_path).read_text(encoding="utf-8")
    assert Path(session.recording_path).is_file()
