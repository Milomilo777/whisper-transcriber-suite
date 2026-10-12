"""Report a problem: the texts a person sees stay byte-identical in English, in every state.

The fixture ``tests/fixtures/i18n/problem_report_texts.json`` was captured from the dialog
BEFORE its strings went through the translation layer (app/i18n.py), with the windowless fake
widgets in ``tests/app/fake_tk.py``. Every later edit to the dialog must keep these English
texts unless the change is meant to alter them (then regenerate with ``capture_states()``).
No Tk root is created here.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

import pytest

from app.dialogs import problem_report as dialog
from core import problem_report as pr
from tests.app import fake_tk

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "i18n" / "problem_report_texts.json"
SYSTEM = "Whisper Transcriber Suite 9.9.9 on Windows 10 (AMD64)"
LIMIT = 50


def _patch(mp: pytest.MonkeyPatch, worker_calls: list[tuple[Callable[..., Any], tuple[Any, ...]]]) -> None:
    mp.setattr(dialog, "tk", fake_tk.fake_tk)
    mp.setattr(dialog, "ttk", fake_tk.fake_ttk)
    mp.setattr(dialog, "place_over", lambda *_a, **_k: None)
    mp.setattr(dialog, "_take_grab", lambda *_a, **_k: None)
    mp.setattr(dialog, "safe_thread", lambda target, args=(), **_k: worker_calls.append((target, args)))
    mp.setattr(pr, "system_summary", lambda: SYSTEM)
    mp.setattr(pr, "MAX_CHARS", LIMIT)


def _open() -> tuple[Any, Any, Any]:
    fake_tk.RECORDER.reset()
    parent = fake_tk.Toplevel()
    fake_tk.RECORDER.reset()
    dlg = dialog.open_problem_report(parent, {"stats_url": ""}, "https://example.invalid/new")
    widgets = fake_tk.RECORDER.widgets
    text = next(w for w in widgets if w.kind == "Text")
    send = next(w for w in widgets if w.kind == "Button")  # Send is created before Cancel
    return dlg, text, send


def _type(text: Any, chars: str) -> None:
    text.insert("end", chars)
    text.fire("<<Modified>>")


def _finish_worker(calls: list[tuple[Callable[..., Any], tuple[Any, ...]]]) -> None:
    target, args = calls.pop()
    target(*args)
    fake_tk.RECORDER.run_after_calls()


def capture_states(mp: pytest.MonkeyPatch) -> dict[str, list[list[str]]]:
    """The visible texts after each step a person can take in the dialog."""
    calls: list[tuple[Callable[..., Any], tuple[Any, ...]]] = []
    _patch(mp, calls)
    states: dict[str, list[list[str]]] = {}
    snap = fake_tk.RECORDER.visible_texts

    _dlg, text, send = _open()
    states["empty"] = snap()
    send.invoke()  # Send with no text: the core's "describe the problem" message
    states["empty_send"] = snap()

    _dlg, text, send = _open()
    _type(text, "It froze")
    states["typed"] = snap()
    _type(text, " and" * 20)
    states["over_limit"] = snap()

    def _fail(_config: Any, _message: str) -> None:
        raise RuntimeError("boom")

    mp.setattr(pr, "send", _fail)
    send.invoke()
    states["sending"] = snap()
    _finish_worker(calls)
    states["failed_unexpected"] = snap()

    def _refuse(_config: Any, _message: str) -> None:
        raise pr.ProblemReportError("The server refused the report (HTTP 500).")

    mp.setattr(pr, "send", _refuse)
    send.invoke()
    _finish_worker(calls)
    states["failed_refused"] = snap()

    mp.setattr(pr, "send", lambda _config, _message: None)
    send.invoke()
    _finish_worker(calls)
    states["sent"] = snap()
    return states


def test_english_texts_match_the_capture_made_before_translation(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert capture_states(monkeypatch) == expected
