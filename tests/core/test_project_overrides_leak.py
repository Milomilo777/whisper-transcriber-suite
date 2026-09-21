"""Per-folder ``.whisperproject.json`` overrides must not leak.

Audit P0-6: ``_apply_runtime_overrides`` mutates the module-level
``core.transcriber.config`` dict in place. The worker subprocess is
long-lived and transcribes many files in sequence, so without a
snapshot/restore wrapper a project override applied to file A in
folder /A silently persisted into file B in folder /B.

The fix is ``_runtime_overrides_scope`` — a context manager that
snapshots the keys an override is about to write and restores them
on exit. These tests pin that contract.
"""
from __future__ import annotations

import json
import sys
import types

import pytest


@pytest.fixture
def transcriber(monkeypatch):
    """Import ``core.transcriber`` with ``faster_whisper`` stubbed.

    Mirrors the fixture in ``test_transcriber_helpers.py``: the real
    import triggers a model probe we don't want in unit tests.
    """
    if "core.transcriber" not in sys.modules:
        fake_fw = types.ModuleType("faster_whisper")
        fake_fw.WhisperModel = object  # type: ignore[attr-defined]
        sys.modules.setdefault("faster_whisper", fake_fw)
    import core.transcriber as t
    return t


def _write_project_file(folder, payload: dict) -> None:
    from core.config import PROJECT_FILE_NAME
    (folder / PROJECT_FILE_NAME).write_text(
        json.dumps(payload), encoding="utf-8",
    )


class _StubTask:
    """Minimal stand-in for ``core.task.TranscriptionTask``.

    ``_runtime_overrides_scope`` only reads ``file_path``, so we
    don't need the full dataclass.
    """

    def __init__(self, file_path: str) -> None:
        self.file_path = file_path


def test_scope_applies_override_inside(transcriber, tmp_path, monkeypatch):
    """Inside the scope, the override must take effect on
    ``transcriber.config`` — the value the actual transcribe loop
    reads from. This is the "did anything happen" guard."""
    _write_project_file(tmp_path, {"diarization_enabled": True})
    monkeypatch.setattr(
        transcriber, "config", {"diarization_enabled": False},
    )
    task = _StubTask(str(tmp_path / "show.mp4"))

    with transcriber._runtime_overrides_scope(task):
        assert transcriber.config["diarization_enabled"] is True


def test_scope_restores_after_exit(transcriber, tmp_path, monkeypatch):
    """Once the scope exits, ``config`` must look exactly as it did
    before the override was applied — pre-existing key restored to
    its previous value."""
    _write_project_file(tmp_path, {"diarization_enabled": True})
    monkeypatch.setattr(
        transcriber, "config", {"diarization_enabled": False},
    )
    task = _StubTask(str(tmp_path / "show.mp4"))

    with transcriber._runtime_overrides_scope(task):
        pass

    assert transcriber.config["diarization_enabled"] is False


def test_scope_no_leak_between_files(transcriber, tmp_path, monkeypatch):
    """End-to-end shape of the P0-6 bug: file A in folder /A has an
    override that enables diarisation, file B in folder /B has no
    override. After the scope around file A exits, the scope around
    file B must NOT inherit diarisation."""
    folder_a = tmp_path / "A"
    folder_a.mkdir()
    _write_project_file(folder_a, {"diarization_enabled": True})

    folder_b = tmp_path / "B"
    folder_b.mkdir()
    # Intentionally no project file in B.

    monkeypatch.setattr(
        transcriber, "config", {"diarization_enabled": False},
    )

    task_a = _StubTask(str(folder_a / "a.mp4"))
    task_b = _StubTask(str(folder_b / "b.mp4"))

    # File A: diarisation visible while inside.
    with transcriber._runtime_overrides_scope(task_a):
        assert transcriber.config["diarization_enabled"] is True
    # After exit: back to False.
    assert transcriber.config["diarization_enabled"] is False

    # File B: must still see diarisation OFF inside its scope
    # because B has no project file.
    with transcriber._runtime_overrides_scope(task_b):
        assert transcriber.config["diarization_enabled"] is False
    assert transcriber.config["diarization_enabled"] is False


def test_scope_removes_keys_that_did_not_exist(transcriber, tmp_path, monkeypatch):
    """If the override adds a key that wasn't in ``config`` before
    (uncommon but possible — e.g. a forward-compat key), the scope
    must pop it on exit, not leave it set to the override value."""
    # ``hotwords`` ships in DEFAULT_CONFIG so it's a known key but
    # we can clear it from the stubbed config to simulate "absent".
    _write_project_file(tmp_path, {"hotwords": "Anthropic"})
    monkeypatch.setattr(transcriber, "config", {})  # no hotwords key
    task = _StubTask(str(tmp_path / "show.mp4"))

    with transcriber._runtime_overrides_scope(task):
        assert transcriber.config["hotwords"] == "Anthropic"
    assert "hotwords" not in transcriber.config


def test_scope_restores_string_keys(transcriber, tmp_path, monkeypatch):
    """Cover a non-bool key shape too — output_formats list, language
    string — to confirm the snapshot/restore is type-agnostic."""
    _write_project_file(
        tmp_path,
        {"output_formats": ["srt", "txt"], "transcribe_language": "fa"},
    )
    monkeypatch.setattr(
        transcriber, "config",
        {"output_formats": ["srt", "json"], "transcribe_language": "Auto"},
    )
    task = _StubTask(str(tmp_path / "show.mp4"))

    with transcriber._runtime_overrides_scope(task):
        assert transcriber.config["output_formats"] == ["srt", "txt"]
        assert transcriber.config["transcribe_language"] == "fa"

    assert transcriber.config["output_formats"] == ["srt", "json"]
    assert transcriber.config["transcribe_language"] == "Auto"


def test_scope_restores_on_exception(transcriber, tmp_path, monkeypatch):
    """If the wrapped block raises, the override must STILL be
    restored. This is the whole reason we picked a context manager
    over Option B (mechanical snapshot at every call site) — a
    transcribe-time raise must not leave ``config`` poisoned for
    the next file."""
    _write_project_file(tmp_path, {"diarization_enabled": True})
    monkeypatch.setattr(
        transcriber, "config", {"diarization_enabled": False},
    )
    task = _StubTask(str(tmp_path / "show.mp4"))

    with pytest.raises(RuntimeError, match="boom"):
        with transcriber._runtime_overrides_scope(task):
            assert transcriber.config["diarization_enabled"] is True
            raise RuntimeError("boom")

    assert transcriber.config["diarization_enabled"] is False


def test_scope_no_project_file_is_noop(transcriber, tmp_path, monkeypatch):
    """When there's no nearest project file, the scope must be a
    no-op: nothing snapshotted, nothing changed, ``config`` left
    exactly as it was."""
    monkeypatch.setattr(
        transcriber, "config",
        {"diarization_enabled": False, "hotwords": "kept"},
    )
    task = _StubTask(str(tmp_path / "show.mp4"))

    before = dict(transcriber.config)
    with transcriber._runtime_overrides_scope(task):
        # _apply_runtime_overrides still writes its unconditional
        # diarisation-default block, so we only assert that the keys
        # we care about are unchanged (no accidental override
        # leaking in from a stray project file).
        assert transcriber.config["hotwords"] == "kept"
    assert transcriber.config["hotwords"] == before["hotwords"]


def test_scope_null_override_does_not_break_runtime_coercions(
    transcriber, tmp_path, monkeypatch,
):
    """A ``null`` in a project file must not reach the int()/float()
    coercions at the tail of ``_apply_runtime_overrides``.

    Regression: ``_validate_overrides`` let ``None`` through for known keys,
    so a folder whose ``.whisperproject.json`` had
    ``{"diarization_num_speakers": null}`` raised TypeError inside the scope
    — every transcription under that folder failed until the file was fixed
    by hand."""
    _write_project_file(
        tmp_path,
        {"diarization_num_speakers": None, "diarization_cluster_threshold": None},
    )
    monkeypatch.setattr(transcriber, "load_config", lambda **kw: {})
    monkeypatch.setattr(
        transcriber, "config",
        {
            "diarization_enabled": False,
            "diarization_num_speakers": -1,
            "diarization_cluster_threshold": 0.5,
            "alignment": "none",
        },
    )
    task = _StubTask(str(tmp_path / "show.mp4"))

    with transcriber._runtime_overrides_scope(task):
        assert transcriber.config["diarization_num_speakers"] == -1
        assert transcriber.config["diarization_cluster_threshold"] == 0.5
