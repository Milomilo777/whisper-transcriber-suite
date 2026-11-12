"""Exercise the actual editor save callback without constructing Tk widgets."""
import errno
import json
import multiprocessing
import os
from pathlib import Path
from types import SimpleNamespace

import pytest


def editor(path, label):
    from app.dialogs import transcript_viewer as viewer

    queued = []
    state = SimpleNamespace(
        _dirty=True, _disk_stamp=viewer._file_stamp(str(path)),
        json_path=str(path), segments=[{"start": 0, "end": 1, "text": label}],
        media_path="", _queue_exports=queued.append,
    )
    return state, queued


def save_in_process(path, role, first_staged, second_closed, first_done, results):
    os.environ["WTS_PROFILE_DIR"] = str(Path(path).parent / ("profile-" + role))
    from app.dialogs import transcript_viewer as viewer
    from core import _checkpoint

    errors = []
    viewer.notify = lambda *args, **kwargs: None
    viewer.show_error = lambda *args, **kwargs: errors.append(kwargs.get("detail"))
    state, queued = editor(Path(path), role)
    sync, replace = _checkpoint._flush_to_disk, viewer.os.replace

    def staged(stream):
        sync(stream)
        if role == "first":
            first_staged.set()
            assert second_closed.wait(15), "second save never reached publication"

    def publish(source, destination):
        if role == "second":
            second_closed.set()
            assert first_done.wait(15), "first save never finished"
        return replace(source, destination)

    _checkpoint._flush_to_disk = staged
    viewer.os.replace = publish
    try:
        viewer.TranscriptViewer._save_changes(state)
        results.put({
            "role": role, "dirty": state._dirty, "queued": len(queued), "errors": errors,
            "disk_text_at_return": json.loads(Path(path).read_text(encoding="utf-8"))[0]["text"],
        })
    except BaseException as error:
        results.put({"role": role, "fatal": repr(error)})
    finally:
        if role == "first":
            first_done.set()


def test_separate_app_processes_never_publish_each_others_staging(tmp_path):
    path = tmp_path / "transcript.json"
    path.write_text('[{"start":0,"end":1,"text":"original"}]', encoding="utf-8")
    context = multiprocessing.get_context("spawn")
    first_staged, second_closed, first_done = [context.Event() for _ in range(3)]
    results = context.Queue()
    processes = [context.Process(
        target=save_in_process,
        args=(str(path), role, first_staged, second_closed, first_done, results),
    ) for role in ("first", "second")]
    try:
        processes[0].start()
        assert first_staged.wait(15), "first save never reached staging"
        processes[1].start()
        observed = {item["role"]: item for item in [results.get(timeout=20), results.get(timeout=20)]}
        for process in processes:
            process.join(timeout=5)
            assert process.exitcode == 0
        for role, result in observed.items():
            assert "fatal" not in result, result
            assert result["errors"] == [] and result["dirty"] is False, result
            assert result["queued"] == 1
            assert result["disk_text_at_return"] == role, result
        assert json.loads(path.read_text(encoding="utf-8"))[0]["text"] == "second"
        assert not list(tmp_path.glob("*.part"))
    finally:
        first_done.set()
        second_closed.set()
        for process in processes:
            if process.pid is not None:
                process.join(timeout=2)
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=5)
        results.close()
        results.join_thread()


@pytest.mark.parametrize("failure", ["flush", "replace"])
def test_failed_editor_save_keeps_original_and_unsaved_edits(tmp_path, monkeypatch, failure):
    from app.dialogs import transcript_viewer as viewer
    from core import _checkpoint

    path = tmp_path / "transcript.json"
    original = b'[{"start":0,"end":1,"text":"original"}]'
    path.write_bytes(original)
    state, queued = editor(path, "unsaved edits")
    errors = []
    monkeypatch.setattr(viewer, "show_error", lambda *args, **kwargs: errors.append(kwargs))

    def fail(*args, **kwargs):
        raise OSError(errno.ENOSPC, "synthetic save failure")

    monkeypatch.setattr(_checkpoint if failure == "flush" else viewer.os,
                        "_flush_to_disk" if failure == "flush" else "replace", fail)
    viewer.TranscriptViewer._save_changes(state)
    assert state._dirty is True and state.segments[0]["text"] == "unsaved edits"
    assert path.read_bytes() == original and queued == [] and len(errors) == 1
    assert not list(tmp_path.glob("*.part"))


def test_editor_save_supports_a_long_existing_filename(tmp_path, monkeypatch):
    from app.dialogs import transcript_viewer as viewer

    path = tmp_path / ("t" * 244 + ".json")
    try:
        path.write_bytes(b'[{"start":0,"end":1,"text":"original"}]')
    except OSError:
        pytest.skip("filesystem cannot create the long source filename")
    state, queued = editor(path, "saved edits")
    errors = []
    monkeypatch.setattr(viewer, "notify", lambda *args, **kwargs: None)
    monkeypatch.setattr(viewer, "show_error", lambda *args, **kwargs: errors.append(kwargs))
    viewer.TranscriptViewer._save_changes(state)
    assert errors == [] and state._dirty is False
    assert json.loads(path.read_text(encoding="utf-8"))[0]["text"] == "saved edits"
    assert len(queued) == 1 and not list(tmp_path.glob("*.part"))


def test_staging_name_collision_never_removes_someone_elses_file(tmp_path, monkeypatch):
    from app.dialogs import viewer_exports

    target = tmp_path / "transcript.json"
    target.write_bytes(b"original")
    occupied = tmp_path / ".viewer-fixed.part"
    occupied.write_bytes(b"synthetic other writer's file")
    monkeypatch.setattr(viewer_exports.uuid, "uuid4", lambda: SimpleNamespace(hex="fixed"))
    with pytest.raises(FileExistsError):
        viewer_exports.write_atomically(str(target), b"edited")
    assert target.read_bytes() == b"original"
    assert occupied.read_bytes() == b"synthetic other writer's file"
