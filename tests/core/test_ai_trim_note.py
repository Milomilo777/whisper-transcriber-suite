"""The transcript viewer adds a translatable note when a remote reply used a shortened transcript."""
from __future__ import annotations

from types import SimpleNamespace

from app.dialogs.transcript_viewer import TranscriptViewer, _with_trim_note


def test_note_added_only_when_trimmed():
    assert _with_trim_note(SimpleNamespace(last_trimmed=True), "S").startswith("S\n\n(")
    assert _with_trim_note(SimpleNamespace(last_trimmed=False), "S") == "S"
    assert _with_trim_note(SimpleNamespace(), "S") == "S"
    assert _with_trim_note(SimpleNamespace(last_trimmed=True), "") == ""


def _run_viewer_task(method, runner):
    """Run a viewer AI action with the work function captured instead of started on a thread."""
    captured = []
    fake = SimpleNamespace(
        _full_transcript_text=lambda: "text", language="en",
        _ai_target_lang_var=SimpleNamespace(get=lambda: "German"),
        _run_ai_task=lambda label, work, language=None: captured.append(work))
    method(fake)
    return captured[0](runner)


def _runner(trimmed):
    return SimpleNamespace(
        last_trimmed=trimmed,
        action_items=lambda _t: ["call Bob"],
        translate=lambda _t, target_language="": "Hallo")


def test_action_items_and_translate_preview_carry_the_note_when_trimmed():
    for method, plain in ((TranscriptViewer._run_action_items, "- call Bob"),
                          (TranscriptViewer._run_translate_preview, "Hallo")):
        assert _run_viewer_task(method, _runner(False)) == plain
        noted = _run_viewer_task(method, _runner(True))
        assert noted.startswith(plain + "\n\n(") and noted != plain
