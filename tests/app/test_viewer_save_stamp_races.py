"""Pure save methods preserve synthetic external edits before/after publication."""
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.dialogs import transcript_viewer as tv, viewer_exports as ve
from core.writers import json_writer


def segments(text):
    return [{"start": 0.0, "end": 1.0, "text": text}]


@pytest.fixture
def saved_viewer(tmp_path, monkeypatch):
    path = tmp_path / "talk.json"
    path.write_text(json_writer.write(segments("original")), encoding="utf-8")
    prompts, errors, queued, notices = [], [], [], []
    viewer = SimpleNamespace(
        json_path=str(path), media_path="", segments=segments("edit A"),
        _disk_stamp=ve.file_stamp(str(path)), _dirty=True, _queue_exports=queued.append,
    )
    monkeypatch.setattr(tv, "notify", lambda *a, **k: notices.append(a))
    monkeypatch.setattr(tv, "show_error", lambda *a, **k: errors.append(a))
    monkeypatch.setattr(tv.messagebox, "askyesno", lambda *a, **k: prompts.append(a) or False)
    return viewer, path, prompts, errors, queued


def test_external_sibling_edit_after_replace_is_never_adopted(tmp_path, monkeypatch):
    json_path = str(tmp_path / "talk.json")
    sibling = str(tmp_path / "talk.srt")
    Path(sibling).write_bytes(ve.render_bytes("srt", segments("original"), ""))
    scan = ve.scan_exports(json_path, segments("original"), "")
    replace = os.replace
    sentinel = b"external subtitle original, keep byte for byte\n"
    fired = []

    def external_after_publish(src, dst):
        replace(src, dst)
        if os.fspath(dst) == sibling and not fired:
            fired.append(True)
            Path(sibling).write_bytes(sentinel)

    monkeypatch.setattr(ve.os, "replace", external_after_publish)
    ve.update_exports(json_path, segments("edit A"), scan)
    report = ve.update_exports(json_path, segments("edit B"), scan)
    assert Path(sibling).read_bytes() == sentinel
    assert report.stale == [sibling] and report.updated == []


def test_external_json_edit_during_render_keeps_dirty_revision(saved_viewer, monkeypatch):
    viewer, path, _prompts, errors, queued = saved_viewer
    render = json_writer.write
    sentinel = b'{"external":"written during render"}\n'

    def external_while_building(*args, **kwargs):
        result = render(*args, **kwargs)
        path.write_bytes(sentinel)
        return result

    monkeypatch.setattr(json_writer, "write", external_while_building)
    tv.TranscriptViewer._save_changes(viewer)
    assert path.read_bytes() == sentinel
    assert viewer._dirty and queued == [] and errors


def test_external_json_edit_after_replace_requires_next_save_confirmation(saved_viewer, monkeypatch):
    viewer, path, prompts, _errors, queued = saved_viewer
    replace = os.replace
    sentinel = b'{"external":"written after publication"}\n'
    fired = []

    def external_after_publish(src, dst):
        replace(src, dst)
        if os.fspath(dst) == str(path) and not fired:
            fired.append(True)
            path.write_bytes(sentinel)

    monkeypatch.setattr(ve.os, "replace", external_after_publish)
    tv.TranscriptViewer._save_changes(viewer)
    viewer.segments = segments("edit B")
    viewer._dirty = True
    tv.TranscriptViewer._save_changes(viewer)
    assert path.read_bytes() == sentinel
    assert viewer._dirty and len(prompts) == 1 and len(queued) == 1


def test_approved_external_revision_can_be_overwritten(saved_viewer, monkeypatch):
    viewer, path, _prompts, errors, queued = saved_viewer
    path.write_bytes(b'{"external":"approved replacement"}')
    monkeypatch.setattr(tv.messagebox, "askyesno", lambda *a, **k: True)
    tv.TranscriptViewer._save_changes(viewer)
    assert json.loads(path.read_bytes()) == viewer.segments
    assert not viewer._dirty and len(queued) == 1 and errors == []


def test_file_created_during_render_after_approved_deletion_is_preserved(saved_viewer, monkeypatch):
    viewer, path, _prompts, errors, queued = saved_viewer
    path.unlink()
    monkeypatch.setattr(tv.messagebox, "askyesno", lambda *a, **k: True)
    render = json_writer.write
    sentinel = b'{"external":"recreated during render"}'

    def recreate(*args, **kwargs):
        result = render(*args, **kwargs)
        path.write_bytes(sentinel)
        return result

    monkeypatch.setattr(json_writer, "write", recreate)
    tv.TranscriptViewer._save_changes(viewer)
    assert path.read_bytes() == sentinel
    assert viewer._dirty and queued == [] and errors


def test_atomic_publication_returns_its_own_stamp_not_later_path_contents(tmp_path, monkeypatch):
    path = tmp_path / "talk.srt"
    replace = os.replace

    def external_after_publish(src, dst):
        replace(src, dst)
        Path(dst).write_bytes(b"foreign, much longer subtitle bytes")

    monkeypatch.setattr(ve.os, "replace", external_after_publish)
    stamp = ve.write_atomically(str(path), b"ours")
    assert stamp is not None and stamp != ve.file_stamp(str(path))
    assert stamp[1] == 4
