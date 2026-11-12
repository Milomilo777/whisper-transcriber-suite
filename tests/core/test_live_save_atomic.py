"""A failed manual live transcript save must preserve an earlier saved file."""
import builtins
import errno
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.widgets import live_tab
from core import live


@pytest.fixture
def saving(tmp_path, monkeypatch):
    exports = tmp_path / "exports"
    exports.mkdir()
    target = exports / "saved.txt"
    target.write_bytes(b"earlier irreplaceable saved transcript")
    work = tmp_path / "session"
    work.mkdir()
    session = live.LiveSession(transcribe_chunk=lambda path: "new live words", work_dir=str(work))
    session.recording_path = str(work / "live-session.wav")
    live.write_wav(session.recording_path, b"\x01\x00" * 128, 16000)
    session._consume_one((1, b"\x01\x00" * 128, 0.0, 16000))
    errors = []
    app = SimpleNamespace(
        live_session=session, live_lines=[], _live_saved_count=0, _live_saved_paths=[],
        _live_held=[(session, 1)], log=lambda value: None,
    )
    live_tab._poll_once(app)
    monkeypatch.setattr(live_tab.filedialog, "asksaveasfilename", lambda **kwargs: str(target))
    monkeypatch.setattr(live_tab, "show_error", lambda *args, **kwargs: errors.append((args, kwargs)))
    return app, session, target, errors


def fail_output(monkeypatch, folder, operation):
    real_open = builtins.open

    class InterruptedWriter:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            self.stream.__enter__()
            return self

        def __exit__(self, *args):
            self.stream.__exit__(*args)
            if operation == "close" and args[0] is None:
                raise OSError(errno.ENOSPC, "synthetic output close failure")

        def __getattr__(self, name):
            return getattr(self.stream, name)

        def write(self, text):
            if operation == "write":
                self.stream.write(text[:5])
                self.stream.flush()
                raise OSError(errno.ENOSPC, "synthetic output write failure")
            return self.stream.write(text)

    def open_output(path, mode="r", *args, **kwargs):
        stream = real_open(path, mode, *args, **kwargs)
        if Path(path).parent == folder and any(flag in mode for flag in ("w", "x")):
            return InterruptedWriter(stream)
        return stream

    monkeypatch.setattr(builtins, "open", open_output)


@pytest.mark.parametrize("operation", ["write", "close"])
def test_failed_save_preserves_previous_file_and_live_recovery(saving, monkeypatch, operation):
    app, session, target, errors = saving
    original = target.read_bytes()
    fail_output(monkeypatch, target.parent, operation)
    assert live_tab._save(app) is False
    assert target.read_bytes() == original
    assert app._live_saved_count == 0 and not app._live_saved_paths
    assert session.transcript_saved is False
    assert Path(session.journal_path).is_file() and Path(session.recording_path).is_file()
    assert errors and not list(target.parent.glob("*.part"))


def test_successful_save_releases_recovery_only_after_full_text_is_saved(saving):
    app, session, target, errors = saving
    assert live_tab._save(app) is True
    assert target.read_text(encoding="utf-8") == "new live words\n"
    assert app._live_saved_count == 1 and app._live_saved_paths == [str(target)]
    assert session.transcript_saved is True
    assert not Path(session.journal_path).exists() and not errors


def test_text_arriving_in_file_dialog_remains_unsaved(saving, monkeypatch):
    app, _session, target, _errors = saving

    def choose(**kwargs):
        app.live_lines.append("later words")
        return str(target)

    monkeypatch.setattr(live_tab.filedialog, "asksaveasfilename", choose)
    assert live_tab._save(app) is True
    assert "later words" not in target.read_text(encoding="utf-8")
    assert app._live_saved_count == 1 and live_tab.has_unsaved_transcript(app)


@pytest.mark.parametrize("operation", ["sync", "replace"])
def test_failed_publication_keeps_previous_save_and_recovery(saving, monkeypatch, operation):
    from core import _checkpoint

    app, session, target, errors = saving
    original = target.read_bytes()

    def fail(*args):
        raise OSError("synthetic publication failure")

    if operation == "sync":
        monkeypatch.setattr(_checkpoint, "_strict_sync", fail)
    else:
        monkeypatch.setattr(live_tab.os, "replace", fail)
    assert live_tab._save(app) is False
    assert target.read_bytes() == original and errors
    assert app._live_saved_count == 0 and session.transcript_saved is False
    assert Path(session.journal_path).is_file() and Path(session.recording_path).is_file()
    assert not list(target.parent.glob("*.part"))


def test_exclusive_staging_collision_keeps_foreign_file(saving, monkeypatch):
    app, _session, target, _errors = saving
    original = target.read_bytes()
    foreign = target.parent / ".live-fixed.part"
    foreign.write_bytes(b"another recoverable transcript")
    monkeypatch.setattr(live_tab.uuid, "uuid4", lambda: SimpleNamespace(hex="fixed"))
    assert live_tab._save(app) is False
    assert target.read_bytes() == original
    assert foreign.read_bytes() == b"another recoverable transcript"


def test_long_valid_output_name_remains_saveable(saving, monkeypatch):
    app, _session, target, _errors = saving
    long_target = target.with_name("s" * 245 + ".txt")
    if os.name == "nt":
        long_target = Path("\\\\?\\" + str(target.parent.resolve())) / long_target.name
    monkeypatch.setattr(live_tab.filedialog, "asksaveasfilename", lambda **kwargs: str(long_target))
    assert live_tab._save(app) is True
    assert long_target.read_text(encoding="utf-8") == "new live words\n"


def test_cleanup_error_does_not_mask_failed_replacement(saving, monkeypatch):
    app, _session, target, errors = saving
    original = target.read_bytes()

    def fail_replace(*args):
        raise PermissionError("synthetic destination lock")

    def fail_cleanup(*args):
        raise PermissionError("synthetic staging lock")

    with monkeypatch.context() as failure:
        failure.setattr(live_tab.os, "replace", fail_replace)
        failure.setattr(live_tab.os, "unlink", fail_cleanup)
        assert live_tab._save(app) is False
    assert target.read_bytes() == original
    assert "synthetic destination lock" in errors[0][1]["detail"]


@pytest.mark.parametrize("artifact", ["journal_path", "recording_path"])
def test_saving_to_a_session_hard_link_keeps_original_artifact(saving, monkeypatch, artifact):
    app, session, target, _errors = saving
    original = Path(getattr(session, artifact))
    before = original.read_bytes()
    alias = target.with_name("alias.txt")
    live_tab.os.link(original, alias)
    monkeypatch.setattr(live_tab.filedialog, "asksaveasfilename", lambda **kwargs: str(alias))
    assert live_tab._save(app) is True
    assert alias.read_text(encoding="utf-8") == "new live words\n"
    assert original.read_bytes() == before
