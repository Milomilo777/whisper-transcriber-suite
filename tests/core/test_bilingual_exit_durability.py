"""Keep completed translations alive when both native save paths fail."""
from types import SimpleNamespace

import pytest

from app.dialogs import transcript_viewer as viewer
from core import config
from core.writers import bilingual_srt


class _ExitViewer(SimpleNamespace):
    _keep_open_for_cue_draft = viewer.TranscriptViewer._keep_open_for_cue_draft


def _failed_result(tmp_path, monkeypatch):
    blocked = tmp_path / "existing-file"
    blocked.write_bytes(b"keep this unrelated file")
    monkeypatch.setattr(config, "user_data_dir", lambda: blocked)
    result = bilingual_srt.save_result(
        [{"start": 0, "end": 1, "text": "source"}], ["completed translation"],
        source_json=str(tmp_path / "source.json"), language="French",
        target=str(blocked / "out.srt"))
    assert result.saved_path is None and result.recovery_path is None
    assert result.error and result.recovery_error
    assert blocked.read_bytes() == b"keep this unrelated file"
    return result


@pytest.mark.parametrize("dirty,skip", [(False, False), (True, False), (False, True), (True, True)])
def test_app_exit_keeps_completed_translation_until_explicit_discard(tmp_path, monkeypatch, dirty, skip):
    pending = _failed_result(tmp_path, monkeypatch)
    fake = _ExitViewer(_closing=False, _dirty=dirty, winfo_exists=lambda: True,
        _pending_bilingual_save=pending, json_path="source.json", _confirm_exit=lambda *_: True)
    monkeypatch.setattr(viewer, "_OPEN_VIEWERS", {"source": fake})
    calls = []
    monkeypatch.setattr(viewer.messagebox, "askyesno", lambda *a, **kw: calls.append(kw) or False)
    assert viewer.confirm_unsaved_before_exit([fake] if skip else []) is False
    assert len(calls) == 1 and calls[0]["default"] == "no"
    assert fake._pending_bilingual_save is pending and "completed translation" in pending.body
    monkeypatch.setattr(viewer.messagebox, "askyesno", lambda *a, **kw: True)
    assert viewer.confirm_unsaved_before_exit([fake] if skip else []) is True


def test_final_exit_recheck_catches_translation_completed_during_other_prompts(tmp_path, monkeypatch):
    fake = _ExitViewer(_closing=False, _dirty=False, winfo_exists=lambda: True,
        _pending_bilingual_save=None, json_path="source.json", _confirm_exit=lambda *_: True)
    monkeypatch.setattr(viewer, "_OPEN_VIEWERS", {"source": fake})
    assert viewer.confirm_unsaved_before_exit() is True
    fake._pending_bilingual_save = _failed_result(tmp_path, monkeypatch)
    monkeypatch.setattr(viewer.messagebox, "askyesno", lambda *a, **kw: False)
    assert viewer.confirm_unsaved_before_exit([fake]) is False


def test_valid_recovery_allows_exit_but_corrupt_recovery_keeps_memory(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "user_data_dir", lambda: tmp_path / "profile")
    blocked = tmp_path / "blocked"
    blocked.write_bytes(b"original")
    pending = bilingual_srt.save_result(
        [{"start": 0, "end": 1, "text": "source"}], ["completed translation"],
        source_json=str(tmp_path / "source.json"), language="French",
        target=str(blocked / "out.srt"))
    assert pending.saved_path is None and pending.recovery_path
    fake = _ExitViewer(_closing=False, _dirty=False, winfo_exists=lambda: True,
        _pending_bilingual_save=pending, json_path="source.json", _confirm_exit=lambda *_: True)
    monkeypatch.setattr(viewer, "_OPEN_VIEWERS", {"source": fake})
    calls = []
    monkeypatch.setattr(viewer.messagebox, "askyesno", lambda *a, **kw: calls.append(True) or False)
    assert viewer.confirm_unsaved_before_exit() is True
    assert calls == []
    from pathlib import Path
    Path(pending.recovery_path).write_bytes(b"damaged archive")
    assert viewer.confirm_unsaved_before_exit() is False
    assert calls == [True]
