"""Saving generated speech preserves the previous destination on I/O failure.

These exercise the save callback with synthetic files and a fake file picker;
no Tk root, model, recording or owner profile is opened.
"""
import errno
from pathlib import Path
import shutil
from types import SimpleNamespace
import wave

import pytest

from app.widgets import voice_clone_tab as tab


def previous_wav(path):
    with wave.open(str(path), "wb") as audio:
        audio.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        audio.writeframes(b"\x02\x00" * 80)
    return path.read_bytes()


@pytest.fixture
def save_case(monkeypatch, tmp_path):
    source = tmp_path / "generated.wav"
    with wave.open(str(source), "wb") as audio:
        audio.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        audio.writeframes(b"\x01\x00" * 160)
    destination = tmp_path / "saved \u0622\u0632\u0645\u0627\u06cc\u0634.wav"
    logs, errors = [], []
    app = SimpleNamespace(vc_last_output=str(source), log=logs.append)
    monkeypatch.setattr(tab.filedialog, "asksaveasfilename", lambda **kwargs: str(destination))
    monkeypatch.setattr(tab, "show_error", lambda *args, **kwargs: errors.append(args))
    return app, source, destination, logs, errors


@pytest.mark.parametrize("existing", [False, True])
def test_partial_export_keeps_previous_destination(save_case, monkeypatch, existing):
    app, source, destination, logs, errors = save_case
    original = source.read_bytes()
    previous = None
    if existing:
        previous = previous_wav(destination)

    def interrupted_copy(src, dst):
        Path(dst).write_bytes(b"partial")
        raise OSError(errno.ENOSPC, "synthetic disk full")

    monkeypatch.setattr(shutil, "copyfile", interrupted_copy)
    tab._save(app)
    assert source.read_bytes() == original
    if existing:
        assert destination.read_bytes() == previous
    else:
        assert not destination.exists()
    assert len(errors) == 1 and logs == []
    assert sorted(p.name for p in source.parent.iterdir()) == sorted(
        [source.name, destination.name] if existing else [source.name]
    )


@pytest.mark.parametrize("failure", ["sync", "replace"])
def test_export_publish_failure_preserves_both_files(save_case, monkeypatch, failure):
    app, source, destination, logs, errors = save_case
    previous = previous_wav(destination)
    original = source.read_bytes()

    def fail(*args, **kwargs):
        raise OSError(errno.EIO, "synthetic publish failure")

    monkeypatch.setattr(tab.os, "fsync" if failure == "sync" else "replace", fail)
    tab._save(app)
    assert source.read_bytes() == original and destination.read_bytes() == previous
    assert len(errors) == 1 and logs == []
    assert sorted(p.name for p in source.parent.iterdir()) == sorted([source.name, destination.name])


@pytest.mark.parametrize("existing", [False, True])
def test_successful_export_copies_complete_wav(save_case, existing):
    app, source, destination, logs, errors = save_case
    if existing:
        previous_wav(destination)
    original = source.read_bytes()
    tab._save(app)
    assert destination.read_bytes() == original == source.read_bytes()
    with wave.open(str(destination)) as audio:
        assert audio.getnframes() == 160
    assert errors == [] and len(logs) == 1 and str(destination) in logs[0]
    assert sorted(p.name for p in source.parent.iterdir()) == sorted([source.name, destination.name])


def test_cancelled_export_does_not_touch_files(save_case, monkeypatch):
    app, source, destination, logs, errors = save_case
    original = source.read_bytes()
    monkeypatch.setattr(tab.filedialog, "asksaveasfilename", lambda **kwargs: "")
    tab._save(app)
    assert source.read_bytes() == original and not destination.exists()
    assert logs == [] and errors == []


def test_destination_changes_only_after_complete_sync(save_case, monkeypatch):
    app, source, destination, logs, errors = save_case
    previous = previous_wav(destination)
    original = source.read_bytes()
    sync, replace = tab.os.fsync, tab.os.replace
    synced = []

    def observe_sync(fd):
        assert destination.read_bytes() == previous and logs == []
        sync(fd)
        synced.append(True)

    def observe_publish(staging, target):
        assert synced == [True] and Path(target) == destination
        assert Path(staging).parent == destination.parent
        assert Path(staging).read_bytes() == original
        assert destination.read_bytes() == previous and logs == []
        replace(staging, target)

    monkeypatch.setattr(tab.os, "fsync", observe_sync)
    monkeypatch.setattr(tab.os, "replace", observe_publish)
    tab._save(app)
    assert destination.read_bytes() == original
    assert len(logs) == 1 and not errors
