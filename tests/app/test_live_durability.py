"""Live captions never lose words: journal, deferred cleanup, Stop debounce.

Drives the real ``live_tab`` stop/save/exit functions and a real
``core.live.LiveSession`` with a fake recorder and a fake transcriber. No
audio device, no model and no Tk root is created.
"""
from __future__ import annotations

import array
import math
import os
import threading
import time
import types

import pytest

from app.widgets import live_tab
from core import live

RATE = 16_000


def _pcm(seconds: float, amplitude: float) -> bytes:
    n = int(seconds * RATE)
    peak = int(amplitude * 32767)
    return array.array(
        "h", (int(peak * math.sin(2 * math.pi * 220.0 * i / RATE)) for i in range(n))
    ).tobytes()


def _blocks(data: bytes, block_s: float = 0.064):
    step = int(block_s * RATE) * 2
    for i in range(0, len(data), step):
        yield data[i:i + step]


class FakeRecorder:
    """Stands in for core.recorder.Recorder; writes a placeholder session WAV."""

    def __init__(self, output_path, mode="mic", device_index=None,
                 sample_rate=RATE, on_frames=None):
        self.output_path = output_path
        self.last_error = None
        self._running = False

    def start(self):
        os.makedirs(os.path.dirname(self.output_path), exist_ok=True)
        with open(self.output_path, "wb") as fh:
            fh.write(b"RIFFfake-session-recording" * 100)
        self._running = True

    def stop(self, *, timeout=5.0):
        self._running = False
        return self.output_path

    def is_running(self):
        return self._running


class FakeTranscriber:
    def __init__(self, delay=0.0, text="sentence", gate=None):
        self.delay = delay
        self.gate = gate  # when set, a chunk is not transcribed until it is set
        self.text = text
        self.stopped = threading.Event()
        self.calls = 0

    def transcribe_chunk(self, wav_path):
        self.calls += 1
        n = self.calls
        if self.gate is not None and not self.gate.wait(timeout=30):
            raise RuntimeError("gate never opened")
        if self.stopped.wait(timeout=self.delay):
            raise RuntimeError("Live session stopped.")
        return {"text": f"{self.text}-{n}", "language": "en"}

    def stop(self):
        self.stopped.set()

    def is_running(self):
        return not self.stopped.is_set()


class _Var:
    def __init__(self, value=""):
        self.v = value

    def set(self, v):
        self.v = v

    def get(self):
        return self.v


class _Widget:
    def __init__(self):
        self.opts = {}

    def configure(self, **kw):
        self.opts.update(kw)

    config = configure


class _Text:
    def yview(self):
        return (0.0, 1.0)

    def index(self, i):
        return "1.0"

    def insert(self, where, text):
        pass

    def see(self, where):
        pass


def _make_app(session, transcriber, tmp_path):
    app = types.SimpleNamespace()
    app.live_session = session
    app.live_transcriber = transcriber
    app.live_lines = []
    app._live_saved_count = 0
    app._live_held = []
    app._live_stop_reason = ""
    app.app_config = {"download_folder": str(tmp_path / "dl")}
    os.makedirs(app.app_config["download_folder"], exist_ok=True)
    for name in ("live_stop_btn", "live_start_btn", "live_source_combo", "live_lang_combo",
                 "live_device_combo", "live_model_btn", "live_model_dl_btn"):
        setattr(app, name, _Widget())
    app.live_text = _Text()
    app.live_status_var = _Var()
    app.live_source_var = _Var("Microphone")
    app.live_lang_var = _Var("English")
    app.live_keep_var = _Var(False)
    app.logged = []
    app.log = app.logged.append
    app.posted = []
    app.post_to_main = app.posted.append
    return app


@pytest.fixture(autouse=True)
def _no_real_device(monkeypatch):
    monkeypatch.setattr(live._rec, "Recorder", FakeRecorder)
    monkeypatch.setattr(live_tab.script_fonts, "tag_script_lines", lambda *a, **k: None)


def _spoken_session(tmp_path, *, delay=0.0, sentences=1, gate=None):
    t = FakeTranscriber(delay=delay, gate=gate)
    s = live.LiveSession(transcribe_chunk=t.transcribe_chunk,
                         work_dir=str(tmp_path / "live" / "run1"))
    s.start()
    for _ in range(sentences):
        for b in _blocks(_pcm(2.0, 0.5)):
            s._on_frames(b, RATE)
        for b in _blocks(_pcm(0.6, 0.0)):
            s._on_frames(b, RATE)
    return s, t


def _wait(cond, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return cond()


def _run_stop(app):
    """Press Stop once and run the posted callbacks like the Tk thread."""
    live_tab._stop(app)
    assert _wait(lambda: any("_stopped" in f.__code__.co_names for f in app.posted))
    for fn in list(app.posted):
        fn()
    app.posted.clear()


# ------------------------------------------------------------ the journal


def test_text_reaches_the_journal_before_it_is_shown(tmp_path):
    gate = threading.Event()  # no chunk is transcribed before the spy is installed
    s, t = _spoken_session(tmp_path, gate=gate)
    seen: list[str] = []
    real_emit = s._emit

    def spy(event):
        if event.kind == "text":
            with open(s.journal_path, encoding="utf-8") as fh:
                seen.append(fh.read())
        real_emit(event)

    s._emit = spy  # type: ignore[method-assign]
    gate.set()
    s.stop_capture()
    assert s.wait_drained(timeout=10)
    assert seen and "sentence-1" in seen[0], "journal must hold the text when the event is sent"


def test_journal_is_one_utf8_line_per_sentence(tmp_path):
    s = live.LiveSession(transcribe_chunk=lambda p: "", work_dir=str(tmp_path / "w"))
    os.makedirs(s.work_dir)
    s._journal("Hello\nworld")
    s._journal("سلام دنیا")
    with open(s.journal_path, encoding="utf-8", newline="") as fh:
        assert fh.read() == "Hello world\nسلام دنیا\n"


def test_journal_failure_does_not_stop_the_session(tmp_path):
    s = live.LiveSession(transcribe_chunk=lambda p: "", work_dir=str(tmp_path / "missing" / "w"))
    s._journal("no folder, no crash")  # OSError is logged, not raised


# ------------------------------------------- audio stays until text is safe


def test_stop_keeps_audio_and_journal_until_the_text_is_saved(tmp_path):
    s, t = _spoken_session(tmp_path)
    app = _make_app(s, t, tmp_path)
    _run_stop(app)
    assert app.live_lines, "the sentence reached the window"
    assert os.path.isfile(s.recording_path), "session audio must survive Stop"
    assert os.path.isfile(s.journal_path), "journal must survive Stop"
    assert len(app._live_held) == 1


def test_autosave_then_releases_audio_and_journal(tmp_path):
    s, t = _spoken_session(tmp_path)
    app = _make_app(s, t, tmp_path)
    _run_stop(app)
    folder = s.work_dir
    assert live_tab.autosave_unsaved_transcript(app)
    assert app._live_held == []
    assert not os.path.exists(folder), "saved text: the folder may go"


def test_save_dialog_releases_the_session_files(tmp_path, monkeypatch):
    s, t = _spoken_session(tmp_path)
    app = _make_app(s, t, tmp_path)
    _run_stop(app)
    target = tmp_path / "out.txt"
    monkeypatch.setattr(live_tab.filedialog, "asksaveasfilename", lambda **kw: str(target))
    assert live_tab._save(app)
    assert "sentence-1" in target.read_text(encoding="utf-8")
    assert not os.path.exists(s.work_dir)


def test_clear_does_not_delete_unsaved_session_files(tmp_path):
    s, t = _spoken_session(tmp_path)
    app = _make_app(s, t, tmp_path)
    _run_stop(app)
    live_tab._clear(app)
    assert os.path.isfile(s.journal_path) and os.path.isfile(s.recording_path)


def test_stop_with_no_speech_still_cleans_up(tmp_path):
    t = FakeTranscriber()
    s = live.LiveSession(transcribe_chunk=t.transcribe_chunk,
                         work_dir=str(tmp_path / "live" / "empty"))
    s.start()
    app = _make_app(s, t, tmp_path)
    _run_stop(app)
    assert not os.path.exists(s.work_dir)
    assert app._live_held == []


def test_exit_without_a_saved_transcript_keeps_files_but_saves_text(tmp_path):
    s, t = _spoken_session(tmp_path)
    app = _make_app(s, t, tmp_path)
    s.stop_capture()
    s.wait_drained(timeout=10)
    live_tab.stop_live_session(app)
    saved = list((tmp_path / "dl").glob("live-transcript-*.txt"))
    assert saved and "sentence-1" in saved[0].read_text(encoding="utf-8")
    assert not os.path.exists(s.work_dir), "text autosaved: the files may go"


def test_exit_keeps_the_files_when_the_autosave_fails(tmp_path, monkeypatch):
    s, t = _spoken_session(tmp_path)
    app = _make_app(s, t, tmp_path)
    s.stop_capture()
    s.wait_drained(timeout=10)
    monkeypatch.setattr(live_tab, "autosave_unsaved_transcript", lambda a: "")
    live_tab.stop_live_session(app)
    assert os.path.isfile(s.journal_path) and os.path.isfile(s.recording_path)


def test_exit_discard_choice_releases_the_files(tmp_path):
    s, t = _spoken_session(tmp_path)
    app = _make_app(s, t, tmp_path)
    app._live_exit_discard = True
    s.stop_capture()
    s.wait_drained(timeout=10)
    live_tab.stop_live_session(app)
    assert not os.path.exists(s.work_dir)


# --------------------------------------------------------- leftover scan


def test_leftover_sessions_are_listed_and_never_deleted(tmp_path):
    root = tmp_path / "live"
    has_text = root / "a-has-text"
    empty = root / "b-empty-journal"
    nojournal = root / "c-old-wav-only"
    mine = root / "d-mine"
    for d in (has_text, empty, nojournal, mine):
        d.mkdir(parents=True)
        (d / "live-session.wav").write_bytes(b"RIFF")
    (has_text / live.JOURNAL_NAME).write_text("words\n", encoding="utf-8")
    (empty / live.JOURNAL_NAME).write_text("  \n", encoding="utf-8")
    (mine / live.JOURNAL_NAME).write_text("held\n", encoding="utf-8")
    found = live.find_leftover_sessions(str(root), exclude=(str(mine),))
    assert found == [str(has_text)]
    assert all((d / "live-session.wav").exists() for d in (has_text, empty, nojournal, mine))
    assert live.find_leftover_sessions(str(tmp_path / "nope")) == []


def test_start_logs_leftover_folders(tmp_path, monkeypatch):
    left = tmp_path / "live" / "old"
    left.mkdir(parents=True)
    (left / live.JOURNAL_NAME).write_text("lost words\n", encoding="utf-8")
    import core.config as cfg

    monkeypatch.setattr(cfg, "user_cache_dir", lambda: tmp_path)
    app = _make_app(None, None, tmp_path)
    live_tab._report_leftover_sessions(app)
    assert any(str(left) in line for line in app.logged)
    assert (left / live.JOURNAL_NAME).exists()


# ------------------------------------------------------- Stop double-click


def test_double_click_on_stop_does_not_discard_the_last_sentence(tmp_path):
    s, t = _spoken_session(tmp_path, delay=0.8)
    app = _make_app(s, t, tmp_path)
    live_tab._stop(app)
    assert app._live_draining
    live_tab._stop(app)  # the second click of a double-click, a few ms later
    assert not s._discard.is_set(), "the second press must be ignored"
    assert app.live_stop_btn.opts.get("state") != "disabled"
    assert _wait(lambda: any("_stopped" in f.__code__.co_names for f in app.posted))
    for fn in list(app.posted):
        fn()
    assert app.live_lines == ["sentence-1"], "the last sentence must survive"


def test_a_later_second_press_still_discards(tmp_path):
    s, t = _spoken_session(tmp_path, delay=5.0)
    app = _make_app(s, t, tmp_path)
    live_tab._stop(app)
    app._live_stop_at -= live_tab._STOP_DEBOUNCE_S + 1.0  # the user waited
    live_tab._stop(app)
    assert _wait(s._discard.is_set)
    assert _wait(lambda: any("_stopped" in f.__code__.co_names for f in app.posted))
    for fn in list(app.posted):
        fn()
    assert any("Discard rest" in line and "discarded" in line for line in app.logged)


# ----------------------------------------- audio kept when words are missing


def _plain_session(tmp_path):
    s = live.LiveSession(transcribe_chunk=lambda p: "", work_dir=str(tmp_path / "w"))
    os.makedirs(s.work_dir)
    s.recording_path = os.path.join(s.work_dir, "live-session.wav")
    with open(s.recording_path, "wb") as fh:
        fh.write(b"RIFF")
    return s


def test_complete_session_audio_is_still_deleted(tmp_path):
    s = _plain_session(tmp_path)
    assert s.incomplete_reason == ""
    assert s.finish_recording() == ""
    assert not os.path.exists(s.work_dir)


@pytest.mark.parametrize("attr, value, word", [
    ("dropped_chunks", 2, "skipped"),
    ("_failed_chunks", 1, "failed"),
    ("_discarded_chunks", 3, "discarded"),
    ("_queued", 1, "not transcribed"),
])
def test_audio_is_kept_when_words_are_missing(tmp_path, attr, value, word):
    s = _plain_session(tmp_path)
    setattr(s, attr, value)
    assert word in s.incomplete_reason
    assert s.finish_recording() == s.recording_path
    assert os.path.isfile(s.recording_path)


def test_a_failed_chunk_marks_the_session_incomplete(tmp_path):
    def boom(path):
        raise RuntimeError("worker died")

    s = live.LiveSession(transcribe_chunk=boom, work_dir=str(tmp_path / "live" / "f"),
                         max_consecutive_errors=99)
    s.start()
    for b in _blocks(_pcm(2.0, 0.5)):
        s._on_frames(b, RATE)
    for b in _blocks(_pcm(0.6, 0.0)):
        s._on_frames(b, RATE)
    s.stop_capture()
    assert s.wait_drained(timeout=10)
    assert "failed" in s.incomplete_reason
    assert s.finish_recording() == s.recording_path


def test_discard_rest_keeps_the_session_audio(tmp_path):
    s, t = _spoken_session(tmp_path, delay=5.0)
    app = _make_app(s, t, tmp_path)
    live_tab._stop(app)
    app._live_stop_at -= live_tab._STOP_DEBOUNCE_S + 1.0
    live_tab._stop(app)
    assert _wait(lambda: any("_stopped" in f.__code__.co_names for f in app.posted))
    for fn in list(app.posted):
        fn()
    assert os.path.isfile(s.recording_path), "discarded words: the audio is the only copy"
    assert any("discarded" in line and "kept at" in line for line in app.logged)


def test_exit_with_a_backlog_never_deletes_the_audio(tmp_path):
    s, t = _spoken_session(tmp_path, delay=3.0, sentences=2)
    app = _make_app(s, t, tmp_path)
    live_tab.stop_live_session(app)  # stop(timeout=3.0) cannot drain 2 slow chunks
    assert os.path.isfile(s.recording_path)
    t.stop()  # the slow chunks now fail, the threads end, the deferred cleanup runs
    assert _wait(lambda: not s._threads_alive())
    assert _wait(lambda: not any(th.name == "live-cleanup" for th in threading.enumerate()))
    assert os.path.isfile(s.recording_path), "lost chunks: the audio must outlive the cleanup too"


def test_exit_with_a_late_event_does_not_release_the_session(tmp_path):
    gate = threading.Event()
    s, t = _spoken_session(tmp_path, gate=gate)
    app = _make_app(s, types.SimpleNamespace(stop=lambda: None), tmp_path)  # the model finishes anyway
    app.live_lines = ["earlier line"]  # something to autosave
    live_tab.stop_live_session(app)  # the chunk is still in the model: not settled
    assert s.transcript_saved is False
    gate.set()  # the final sentence arrives AFTER the autosave
    assert _wait(lambda: not s._threads_alive())
    assert _wait(lambda: not any(th.name == "live-cleanup" for th in threading.enumerate()))
    with open(s.journal_path, encoding="utf-8") as fh:
        assert "sentence-1" in fh.read(), "the late sentence must stay in the journal"
    assert os.path.isfile(s.recording_path)
    saved = list((tmp_path / "dl").glob("live-transcript-*.txt"))
    assert saved and "sentence-1" not in saved[0].read_text(encoding="utf-8")


# ------------------------------- saving onto the session's own files (R2)


def test_saving_onto_the_journal_itself_never_deletes_it(tmp_path, monkeypatch):
    s, t = _spoken_session(tmp_path)
    app = _make_app(s, t, tmp_path)
    _run_stop(app)
    monkeypatch.setattr(live_tab.filedialog, "asksaveasfilename", lambda **kw: s.journal_path)
    assert live_tab._save(app)
    with open(s.journal_path, encoding="utf-8") as fh:
        assert "sentence-1" in fh.read(), "the saved file must survive the release"
    assert app._live_held == []


def test_saving_onto_a_hard_link_of_the_journal_never_deletes_it(tmp_path, monkeypatch):
    s, t = _spoken_session(tmp_path)
    app = _make_app(s, t, tmp_path)
    _run_stop(app)
    alias = tmp_path / "alias.txt"
    try:
        os.link(s.journal_path, alias)
    except OSError:
        pytest.skip("hard links are not available here")
    monkeypatch.setattr(live_tab.filedialog, "asksaveasfilename", lambda **kw: str(alias))
    assert live_tab._save(app)
    assert os.path.isfile(s.journal_path) and alias.is_file()


def test_saving_inside_the_session_folder_keeps_the_saved_file(tmp_path, monkeypatch):
    s, t = _spoken_session(tmp_path)
    app = _make_app(s, t, tmp_path)
    _run_stop(app)
    target = os.path.join(s.work_dir, "my-notes.txt")
    monkeypatch.setattr(live_tab.filedialog, "asksaveasfilename", lambda **kw: target)
    assert live_tab._save(app)
    with open(target, encoding="utf-8") as fh:
        assert "sentence-1" in fh.read()


# ------------------------------------------- cleanup waits for a stuck thread


def test_cleanup_outlives_the_deferral_and_runs_when_the_thread_ends(tmp_path):
    s = _plain_session(tmp_path)
    s.defer_s = 0.2
    running = {"value": True}
    s._recorder = types.SimpleNamespace(  # type: ignore[assignment]
        is_running=lambda: running["value"], last_error=None)
    s.finish_recording()
    time.sleep(0.8)  # well past the deferral: still nothing is touched
    assert os.path.isfile(s.recording_path)
    running["value"] = False  # the capture thread finally ends
    assert _wait(lambda: not os.path.exists(s.work_dir), timeout=5)
