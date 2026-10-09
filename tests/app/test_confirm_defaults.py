"""A confirmation whose "Yes" destroys something must not be the default answer.

Tk's ``askyesno`` / ``askyesnocancel`` select "Yes" unless told otherwise, so pressing Return on
"Cancel transcription?" or "Discard changes?" did the destructive thing. Every such call in
``app/`` is listed here with its kind; a new Yes/No dialog fails the test until it is classified,
so the choice is made on purpose.
"""
from __future__ import annotations

import ast
import pathlib
from typing import Any

import pytest

APP = pathlib.Path(__file__).resolve().parents[2] / "app"

# "Yes" (or the dialog's first button) stops, discards, overwrites or quits: the safe answer
# must be the default. The value is what ``default=`` has to be.
DESTRUCTIVE = {
    ("app/app.py", "f'{shortcuts.quit_label()} with queued tasks'"): "no",
    ("app/app.py", "title"): "no",                    # stop running jobs to switch engine
    ("app/app.py", "'Cancel transcription?'"): "no",
    ("app/app.py", "'Cancel download?'"): "no",
    ("app/dialogs/transcript_viewer.py", "'Discard changes?'"): "no",
    ("app/dialogs/transcript_viewer.py", "'Transcript changed on disk'"): "no",   # overwrite
    ("app/services/integrations_service.py", "'Replace .otr file?'"): "cancel",   # Yes replaces
}

# "Yes" is the helpful, harmless answer (open, save, download, show, continue).
HARMLESS = {
    ("app/app.py", "'Convert transcript'"),
    ("app/app.py", "'View transcript'"),
    ("app/app.py", "'Offline mode is on'"),
    ("app/app.py", "f'{friendly} needs a download'"),
    ("app/app.py", "'Resume interrupted transcriptions?'"),
    ("app/app.py", "'Whisper model required'"),
    ("app/app.py", "'Check for updates'"),
    ("app/dialogs/model_download.py", "title"),
    ("app/dialogs/transcript_viewer.py", "'Unsaved transcript edits'"),   # Yes = save
    ("app/dialogs/transcript_viewer.py", "'Bilingual subtitle'"),
    ("app/dialogs/transcript_viewer.py", "'Unsaved edits'"),              # Yes = save
    ("app/dialogs/transcript_viewer.py", "'Remove fillers'"),             # an edit, not saved yet
    ("app/widgets/hardware_wizard.py", "'Install GPU support'"),
    ("app/widgets/live_tab.py", "'Unsaved live transcript'"),             # Yes = save
    ("app/widgets/subtitle_edit.py", "'Subtitle Edit not found'"),
}

_ASKS = ("askyesno", "askyesnocancel", "askokcancel", "askretrycancel", "askquestion")


def _calls() -> list[tuple[str, int, str, dict[str, Any]]]:
    found: list[tuple[str, int, str, dict[str, Any]]] = []
    for path in sorted(APP.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        rel = "app/" + path.relative_to(APP).as_posix()
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr in _ASKS and node.args):
                kwargs = {k.arg: ast.literal_eval(k.value) for k in node.keywords
                          if k.arg == "default" and isinstance(k.value, ast.Constant)}
                found.append((rel, node.lineno, ast.unparse(node.args[0]), kwargs))
    return found


def test_the_scan_sees_the_dialogs() -> None:
    assert len(_calls()) >= 20  # a broken scan would pass everything below


def test_every_yes_no_dialog_is_classified() -> None:
    unknown = [
        f"{rel}:{line} {title}" for rel, line, title, _k in _calls()
        if (rel, title) not in DESTRUCTIVE and (rel, title) not in HARMLESS
    ]
    assert not unknown, "classify these new Yes/No dialogs in DESTRUCTIVE or HARMLESS: " + "; ".join(unknown)


def test_the_classified_dialogs_still_exist() -> None:
    present = {(rel, title) for rel, _line, title, _k in _calls()}
    gone = sorted((set(DESTRUCTIVE) | HARMLESS) - present)
    assert not gone, f"remove from the lists: {gone}"


@pytest.mark.parametrize("rel, title", sorted(DESTRUCTIVE))
def test_a_destructive_confirmation_defaults_to_the_safe_answer(rel: str, title: str) -> None:
    sites = [(line, kwargs) for r, line, t, kwargs in _calls() if (r, t) == (rel, title)]
    assert sites
    for line, kwargs in sites:
        assert kwargs.get("default") == DESTRUCTIVE[(rel, title)], f"{rel}:{line} {title}"


def test_the_viewer_close_prompt_passes_the_default_to_tk(monkeypatch: pytest.MonkeyPatch) -> None:
    """The keyword really reaches Tk: ask the question the way the viewer does and read it back."""
    from types import SimpleNamespace

    from app.dialogs import transcript_viewer as tv

    seen: list[dict[str, Any]] = []
    monkeypatch.setattr(tv.messagebox, "askyesno",
                        lambda title, message, **kw: seen.append({"title": title, **kw}) or False)
    fake = SimpleNamespace(_dirty=True)
    tv.TranscriptViewer._on_close(fake)  # type: ignore[arg-type]
    assert seen and seen[0]["default"] == "no" and seen[0]["title"] == "Discard changes?"
