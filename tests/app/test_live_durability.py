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
    def __init__(self, delay=0.0, text="sentence"):
        self.delay = delay
        self.text = text
        self.stopped = threading.Event()
        self.calls = 0

    def transcribe_chunk(self, wav_path):
        self.calls += 1
        n = self.calls
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


def _spoken_session(tmp_path, *, delay=0.0, sentences=1):
    t = FakeTranscriber(delay=delay)
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
    s, t = _spoken_session(tmp_path)
    seen: list[str] = []
    real_emit = s._emit

    def spy(event):
        if event.kind == "text":
            with open(s.journal_path, encoding="utf-8") as fh:
                seen.append(fh.read())
        real_emit(event)

    s._emit = spy  # type: ignore[method-assign]
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
