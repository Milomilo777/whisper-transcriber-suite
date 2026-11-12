"""Live chunk names and cleanup must not replace or delete a saved transcript."""
from pathlib import Path
from types import SimpleNamespace
import builtins
from concurrent.futures import ThreadPoolExecutor
import threading
import wave

import pytest

from app.widgets import live_tab
from core import live


def make_session(tmp_path, transcribe):
    work = tmp_path / "session"
    work.mkdir()
    session = live.LiveSession(transcribe_chunk=transcribe, work_dir=str(work))
    session.recording_path = str(work / "live-session.wav")
    live.write_wav(session.recording_path, b"\x01\x00" * 512, 16000)
    return session


def make_app(session, monkeypatch):
    app = SimpleNamespace(
        live_session=session, live_lines=[], _live_held=[],
        _live_saved_count=0, _live_saved_paths=[], log=lambda value: None,
    )
    monkeypatch.setattr(live_tab, "show_error", lambda *args, **kwargs: pytest.fail("save failed"))
    return app


def test_successful_save_with_chunk_filename_survives_session_cleanup(tmp_path, monkeypatch):
    session = make_session(tmp_path, lambda path: "finished live words")
    session._consume_one((1, b"\x01\x00" * 512, 0.0, 16000))
    app = make_app(session, monkeypatch)
    live_tab._poll_once(app)
    app.live_session = None
    app._live_held = [(session, len(app.live_lines))]
    target = Path(session.work_dir) / "chunk-999999.wav"
    monkeypatch.setattr(live_tab.filedialog, "asksaveasfilename", lambda **kwargs: str(target))
    assert live_tab._save(app) is True
    assert target.read_text(encoding="utf-8") == "finished live words\n"


@pytest.mark.parametrize("alias", [False, True])
def test_final_cleanup_respects_protected_chunk_or_hard_link(tmp_path, alias):
    session = make_session(tmp_path, lambda path: "")
    target = Path(session.work_dir) / "chunk-000001.wav"
    target.write_bytes(b"saved transcript with a chosen WAV filename")
    protected = tmp_path / "saved-alias.txt" if alias else target
    if alias:
        live.os.link(target, protected)
    session.protect_path(str(protected))
    session.finish_recording()
    assert target.read_bytes() == b"saved transcript with a chosen WAV filename"


def test_next_chunk_does_not_overwrite_preexisting_saved_filename(tmp_path):
    decoded = []

    def transcribe(path):
        with wave.open(path, "rb") as audio:
            decoded.append(audio.getnframes())
        return ""

    session = make_session(tmp_path, transcribe)
    target = Path(session.work_dir) / "chunk-000001.wav"
    target.write_bytes(b"previous saved words")
    session.protect_path(str(target))
    session._consume_one((1, b"\x01\x00" * 512, 0.0, 16000))
    assert decoded == [512]
    assert target.read_bytes() == b"previous saved words"


@pytest.mark.parametrize("backend_fails", [False, True])
@pytest.mark.parametrize("same_size", [False, True])
def test_save_onto_active_chunk_survives_chunk_and_final_cleanup(tmp_path, monkeypatch, backend_fails, same_size):
    saved = []
    session = make_session(tmp_path, lambda path: "")
    app = make_app(session, monkeypatch)
    app.live_lines = ["already displayed live words"]

    def transcribe(path):
        with wave.open(path, "rb") as audio:
            assert audio.getnframes() == 512
        if same_size:
            newline_bytes = 2 if live.os.name == "nt" else 1
            app.live_lines = ["s" * (Path(path).stat().st_size - newline_bytes)]
        monkeypatch.setattr(live_tab.filedialog, "asksaveasfilename", lambda **kwargs: path)
        assert live_tab._save(app) is True
        saved.append(Path(path))
        if backend_fails:
            raise RuntimeError("synthetic backend failure after successful save")
        return ""

    session.transcribe_chunk = transcribe
    session._consume_one((1, b"\x01\x00" * 512, 0.0, 16000))
    expected = app.live_lines[0] + "\n"
    assert saved[0].read_text(encoding="utf-8") == expected
    session.finish_recording()
    assert saved[0].read_text(encoding="utf-8") == expected


def test_unchanged_owned_chunk_is_still_removed(tmp_path):
    paths = []
    session = make_session(tmp_path, lambda path: paths.append(Path(path)) or "")
    session._consume_one((1, b"\x01\x00" * 512, 0.0, 16000))
    assert paths and not paths[0].exists()


def test_replacement_before_transcription_preserves_new_file(tmp_path, monkeypatch):
    calls = []
    session = make_session(tmp_path, lambda path: calls.append(path) or "")
    stat = live.os.stat
    replaced = []

    def replace_before_stat(path, *args, **kwargs):
        target = Path(path)
        if target.name.startswith("chunk-") and not replaced:
            saved = target.with_suffix(".saved")
            saved.write_bytes(b"successfully saved replacement")
            live.os.replace(saved, target)
            replaced.append(target)
        return stat(path, *args, **kwargs)

    monkeypatch.setattr(live.os, "stat", replace_before_stat)
    session._consume_one((1, b"\x01\x00" * 512, 0.0, 16000))
    assert not calls and session._failed_chunks == 1
    session.finish_recording()
    assert replaced[0].read_bytes() == b"successfully saved replacement"


def test_uncertain_chunk_metadata_is_preserved(tmp_path, monkeypatch):
    paths = []
    session = make_session(tmp_path, lambda path: paths.append(Path(path)) or "")
    stat = live.os.stat

    def deny_after_transcription(path, *args, **kwargs):
        if paths and Path(path) == paths[0]:
            raise PermissionError("synthetic temporary metadata denial")
        return stat(path, *args, **kwargs)

    with monkeypatch.context() as failure:
        failure.setattr(live.os, "stat", deny_after_transcription)
        session._consume_one((1, b"\x01\x00" * 512, 0.0, 16000))
    session.finish_recording()
    assert paths[0].is_file()


def test_chunk_creation_failure_preserves_session_audio(tmp_path, monkeypatch):
    calls = []
    session = make_session(tmp_path, lambda path: calls.append(path) or "")

    def fail_create(*args, **kwargs):
        raise OSError("synthetic chunk creation failure")

    monkeypatch.setattr(live.tempfile, "mkstemp", fail_create)
    session._consume_one((1, b"\x01\x00" * 512, 0.0, 16000))
    assert not calls and session._failed_chunks == 1
    assert session.finish_recording() == session.recording_path


def test_cleanup_between_save_and_registration_keeps_saved_text(tmp_path, monkeypatch):
    session = make_session(tmp_path, lambda path: "")
    app = make_app(session, monkeypatch)
    app.live_lines = ["successfully saved words"]
    target = Path(session.work_dir) / "chunk-999998.wav"
    note_saved = live_tab._note_saved_path

    def cleanup_then_note(app, path):
        session._remove_own(path)
        note_saved(app, path)

    monkeypatch.setattr(live_tab, "_note_saved_path", cleanup_then_note)
    monkeypatch.setattr(live_tab.filedialog, "asksaveasfilename", lambda **kwargs: str(target))
    assert live_tab._save(app) is True
    assert target.read_text(encoding="utf-8") == "successfully saved words\n"


@pytest.mark.parametrize("already_protected", [False, True])
def test_failed_save_releases_only_its_new_reservation(tmp_path, monkeypatch, already_protected):
    paths = []
    errors = []
    session = make_session(tmp_path, lambda path: "")
    app = make_app(session, monkeypatch)
    app.live_lines = ["words that cannot be saved"]
    monkeypatch.setattr(live_tab, "show_error", lambda *args, **kwargs: errors.append(kwargs))

    def transcribe(path):
        paths.append(Path(path))
        if already_protected:
            session.protect_path(path)
        monkeypatch.setattr(live_tab.filedialog, "asksaveasfilename", lambda **kwargs: path)
        original_open = builtins.open

        def deny_save(candidate, mode="r", *args, **kwargs):
            if Path(candidate).parent == Path(path).parent and any(flag in mode for flag in ("w", "x")):
                raise OSError("synthetic Save creation failure")
            return original_open(candidate, mode, *args, **kwargs)

        with monkeypatch.context() as failure:
            failure.setattr(builtins, "open", deny_save)
            assert live_tab._save(app) is False
        assert app._live_saved_count == 0 and not app._live_saved_paths
        return ""

    session.transcribe_chunk = transcribe
    session._consume_one((1, b"\x01\x00" * 512, 0.0, 16000))
    assert errors and paths[0].exists() is already_protected


def test_save_during_initial_chunk_write_survives_the_later_writer(tmp_path, monkeypatch):
    session = make_session(tmp_path, lambda path: "")
    app = make_app(session, monkeypatch)
    app.live_lines = ["successfully saved during chunk construction"]
    opened = threading.Event()
    dialog_ready = threading.Event()
    resume_writer = threading.Event()
    save_done = threading.Event()
    paths = []
    create = live.tempfile.mkstemp
    write = live._write_pcm_wav

    def record_created(*args, **kwargs):
        fd, path = create(*args, **kwargs)
        paths.append(Path(path))
        return fd, path

    def pause_writer(target, pcm, rate):
        opened.set()
        assert resume_writer.wait(10), "chunk writer was not released"
        write(target, pcm, rate)

    def choose(**kwargs):
        dialog_ready.set()
        return str(paths[0])

    def save():
        try:
            return live_tab._save(app)
        finally:
            save_done.set()

    monkeypatch.setattr(live.tempfile, "mkstemp", record_created)
    monkeypatch.setattr(live, "_write_pcm_wav", pause_writer)
    monkeypatch.setattr(live_tab.filedialog, "asksaveasfilename", choose)
    with ThreadPoolExecutor(max_workers=2) as pool:
        consumer = pool.submit(session._consume_one, (1, b"\x01\x00" * 512, 0.0, 16000))
        try:
            assert opened.wait(10)
            saver = pool.submit(save)
            assert dialog_ready.wait(10)
            # If Save finishes while initialization is paused, the old writer
            # must still never replace that completed result afterward.
            save_done.wait(0.2)
        finally:
            resume_writer.set()
        consumer.result(timeout=10)
        assert saver.result(timeout=10) is True
    assert paths[0].read_text(encoding="utf-8") == app.live_lines[0] + "\n"
    session.finish_recording()
    assert paths[0].read_text(encoding="utf-8") == app.live_lines[0] + "\n"
