"""The transcript viewer adds a translatable note when a remote reply used a shortened transcript."""
from __future__ import annotations

from types import SimpleNamespace

from app.dialogs.transcript_viewer import _with_trim_note


def test_note_added_only_when_trimmed():
    assert _with_trim_note(SimpleNamespace(last_trimmed=True), "S").startswith("S\n\n(")
    assert _with_trim_note(SimpleNamespace(last_trimmed=False), "S") == "S"
    assert _with_trim_note(SimpleNamespace(), "S") == "S"
    assert _with_trim_note(SimpleNamespace(last_trimmed=True), "") == ""
