"""The seams between the translated modules: whole messages across files, stable values.

Windowless: App methods run on stubs, message boxes are recorded, nothing builds a Tk root.
"""
from __future__ import annotations

import ast
import logging
import types
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

import app.app as app_mod
from app import i18n
from app.app import App
from app.widgets import platform as plat
from tests.app.i18n_walk import is_pseudo_marked

ROOT = Path(__file__).resolve().parent.parent
APP_FILES = sorted(p for p in (ROOT / "app").rglob("*.py") if "__pycache__" not in p.parts)


@pytest.fixture(autouse=True)
def _english() -> Iterator[None]:
    i18n.set_language("en")
    yield
    i18n.set_language("en")


@pytest.fixture
def pseudo() -> Iterator[None]:
    assert i18n.set_language(i18n.PSEUDO_LOCALE) == i18n.PSEUDO_LOCALE
    yield
    i18n.set_language("en")


def _single_segment(text: str) -> bool:
    """One pseudo segment around the whole text: a whole message, nothing set into it."""
    return text.startswith("[") and text.endswith("]") and text.count(" ~") == 1


def _calls(name: str) -> Iterator[tuple[str, ast.Call]]:
    """Every call of ``name`` (a plain name or an attribute) in app/, with its file."""
    for path in APP_FILES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                called = func.id if isinstance(func, ast.Name) else (
                    func.attr if isinstance(func, ast.Attribute) else None)
                if called == name:
                    yield path.relative_to(ROOT).as_posix(), node


# ------------------------------------------------- "stop the running transcription?" prompt

def _old_backend_text(n: int, action: str, question: str) -> str:
    """The English the prompt showed before it was translated (the old f-string)."""
    return (
        f"{n} transcription{'s are' if n != 1 else ' is'} running "
        f"right now. {action} stops "
        f"{'them' if n != 1 else 'it'} immediately -- more "
        "abruptly than a normal Cancel, so more progress may be "
        f"lost.\n\n{question}"
    )


_OLD_BACKEND = {
    "engine": ("Switch transcription engine?", "Switching engines", "Switch anyway?"),
    "model": ("Change the Whisper model?", "Changing the model", "Change it anyway?"),
    "hardware": ("Apply now?", "Applying the new hardware setting now",
                 "Apply it now? Choose No to let it finish; the setting is then used after "
                 "the app is restarted."),
}


@pytest.mark.parametrize("kind", sorted(_OLD_BACKEND))
@pytest.mark.parametrize("n", [1, 2, 3])
def test_backend_switch_english_is_unchanged(kind: str, n: int) -> None:
    title, action, question = _OLD_BACKEND[kind]
    assert app_mod.backend_switch_texts(kind, n) == (title, _old_backend_text(n, action, question))


@pytest.mark.parametrize("kind", sorted(_OLD_BACKEND))
def test_backend_switch_is_one_whole_message_per_kind(pseudo: None, kind: str) -> None:
    for n in (1, 3):
        title, question = app_mod.backend_switch_texts(kind, n)
        assert _single_segment(title) and _single_segment(question), (title, question)
        assert str(n) in question


def _busy_app(busy: int) -> Any:
    svc = types.SimpleNamespace(active_workers=lambda: [{"task": object()}] * busy)
    return types.SimpleNamespace(transcription_service=svc)


def test_confirm_backend_switch_asks_with_the_kinds_text(monkeypatch: pytest.MonkeyPatch) -> None:
    asked: list[tuple[str, str]] = []
    monkeypatch.setattr("tkinter.messagebox.askyesno",
                        lambda title, message, **_k: asked.append((title, message)) or True)
    stub = _busy_app(2)
    assert App._confirm_backend_switch(stub, kind="hardware") is True  # type: ignore[arg-type]
    assert asked == [app_mod.backend_switch_texts("hardware", 2)]
    asked.clear()
    assert App._confirm_backend_switch(_busy_app(0), kind="model") is True  # type: ignore[arg-type]
    assert asked == []  # nothing running: no question


def test_confirm_backend_switch_refuses_an_unknown_kind() -> None:
    with pytest.raises(ValueError):
        App._confirm_backend_switch(_busy_app(0), kind="Changing the model")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        app_mod.backend_switch_texts("other", 1)


def test_every_caller_passes_a_known_kind_and_no_text() -> None:
    seen: list[str] = []
    calls = list(_calls("_confirm_backend_switch")) + [
        (w, c) for w, c in _calls("confirm")
        if w in ("app/dialogs/advanced.py", "app/widgets/hardware_wizard.py")]
    assert len(calls) >= 4
    for where, call in calls:
        keys = {k.arg for k in call.keywords}
        assert not keys & {"title", "action", "question"}, where
        for k in call.keywords:
            if k.arg == "kind":
                if isinstance(k.value, ast.Constant):
                    assert k.value.value in app_mod._BACKEND_SWITCH_KINDS, where
                    seen.append(k.value.value)
                else:
                    assert isinstance(k.value, ast.Name) and k.value.id.startswith(
                        "BACKEND_SWITCH_"), where
                    seen.append(getattr(app_mod, k.value.id))
    assert sorted(set(seen)) == ["hardware", "model"]  # "engine" is the default


# ------------------------------------------------------------------ Work offline question

_OLD_OFFLINE = ("{action} needs the internet, and Work offline is on, so the app makes no "
                "network connection.\n\nTurn Work offline off now?")


@pytest.mark.parametrize("what", app_mod.OFFLINE_ACTIONS)
def test_offline_question_english_is_unchanged(what: str) -> None:
    assert app_mod.offline_question(what) == _OLD_OFFLINE.format(action=what)


@pytest.mark.parametrize("what", app_mod.OFFLINE_ACTIONS)
def test_offline_question_is_one_whole_message(pseudo: None, what: str) -> None:
    assert _single_segment(app_mod.offline_question(what))


def test_offline_question_for_an_unknown_action_names_no_english_phrase(
        pseudo: None, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger=app_mod.logger.name):
        text = app_mod.offline_question("Doing something new")
    assert _single_segment(text) and "Doing" not in text
    assert any("Doing something new" in r.getMessage() for r in caplog.records)


def test_ensure_online_asks_the_whole_question_and_logs_english(
        pseudo: None, monkeypatch: pytest.MonkeyPatch) -> None:
    from core import offline

    asked: list[tuple[str, str]] = []
    logs: list[str] = []
    monkeypatch.setattr("tkinter.messagebox.askyesno",
                        lambda title, message, **_k: asked.append((title, message)) or False)
    monkeypatch.setattr(offline, "is_offline", lambda: True)
    stub = types.SimpleNamespace(log=logs.append)
    assert App.ensure_online(stub, "Downloading this link") is False  # type: ignore[arg-type]
    assert len(asked) == 1 and all(_single_segment(t) for t in asked[0])
    assert asked[0][1] == app_mod.offline_question("Downloading this link")
    assert logs and "downloading this link" in logs[0]  # the log line stays English


def test_every_ensure_online_caller_names_a_known_action() -> None:
    found: list[str] = []
    for name, index in (("ensure_online", 0), ("_may_go_online", 1)):
        for where, call in _calls(name):
            if len(call.args) <= index:
                continue  # the definition's own forwarding call: ensure(what)
            arg = call.args[index]
            if isinstance(arg, ast.Name):
                continue  # forwarding a parameter (download_service._may_go_online)
            assert isinstance(arg, ast.Constant) and isinstance(arg.value, str), where
            assert arg.value in app_mod.OFFLINE_ACTIONS, (where, arg.value)
            found.append(arg.value)
    assert sorted(set(found)) == sorted(app_mod.OFFLINE_ACTIONS)


# ------------------------------------------------------------------ Finder wording (macOS)

@pytest.fixture
def darwin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(plat, "sys", types.SimpleNamespace(platform="darwin"))


def test_finder_labels_on_macos_in_english(darwin: None) -> None:
    assert plat.folder_label("Open log folder", "Open Log Folder in Finder") == \
        "Open Log Folder in Finder"
    assert plat.folder_label("Open folder") == "Open Folder in Finder"
    assert plat.reveal_label("Open JSON folder") == "Reveal in Finder"
    assert plat.folder_action_label("x", "Open Output Folder in Finder", None) == \
        "Open Output Folder in Finder"


def test_finder_labels_on_macos_are_whole_translated_labels(pseudo: None, darwin: None) -> None:
    assert _single_segment(plat.folder_label(i18n._("Open log folder")))
    assert _single_segment(plat.reveal_label(i18n._("Open JSON folder")))
    assert plat.folder_label("default", i18n._("Open Log Folder in Finder")) == \
        i18n.pseudo_translate("Open Log Folder in Finder")


def test_finder_label_callers_pass_two_translated_labels() -> None:
    n = 0
    for name, label_args in (("folder_label", 2), ("folder_action_label", 2)):
        for where, call in _calls(name):
            if where == "app/widgets/platform.py":
                continue  # folder_action_label forwarding its own arguments
            n += 1
            assert len(call.args) >= label_args, where
            for arg in call.args[:label_args]:
                assert isinstance(arg, ast.Call) and isinstance(arg.func, ast.Name) and \
                    arg.func.id == "_", (where, ast.unparse(arg))
    assert n >= 5


# ---------------------------------------- N_() constants of one module shown by another

_SHOWN_CONSTANTS = {
    "app/dialogs/share_page.py": ("BUTTON_TEXT",),
    "app/widgets/subtitle_edit.py": ("BUTTON_TEXT", "HELP_TEXT"),
}


def test_marked_constants_are_translated_wherever_they_are_shown() -> None:
    names = {n for group in _SHOWN_CONSTANTS.values() for n in group}
    uses = 0
    for path in APP_FILES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in names and \
                    isinstance(node.ctx, ast.Load):
                uses += 1
                parent = parents[node]
                assert isinstance(parent, ast.Call) and isinstance(parent.func, ast.Name) and \
                    parent.func.id in ("translate", "lazy"), \
                    f"{path.relative_to(ROOT)}:{node.lineno} shows {node.attr} untranslated"
    assert uses >= 5


# ------------------------------------------------------------- English-only model reasons

def test_english_only_prompt_shows_the_language_name_translated(
        pseudo: None, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.dialogs import english_only_model as dlg

    prompts: list[Any] = []
    monkeypatch.setattr(dlg, "ask_english_only", lambda _w, p: prompts.append(p) or dlg.CHOICE_CANCEL)
    import core.model_manager as mm

    monkeypatch.setattr(mm, "english_only_mismatch", lambda *_a: True)
    monkeypatch.setattr(mm, "multilingual_counterpart", lambda *_a: "small")
    monkeypatch.setattr(mm, "approx_download_size_text", lambda *_a: "")
    monkeypatch.setattr(mm, "model_downloaded", lambda *_a: True)
    logs: list[str] = []
    stub = types.SimpleNamespace(
        app_config={"whisper_model": "base.en"},
        transcribe_lang_var=types.SimpleNamespace(get=lambda: "German"),
        _selected_transcribe_language=lambda: "de",
        _engine_uses_whisper_model=lambda: True,
        log=logs.append,
    )
    assert App._confirm_english_only_model(stub) is False  # type: ignore[arg-type]
    assert len(prompts) == 1
    prompt = prompts[0]
    assert prompt.language == i18n.pseudo_translate("German")
    for text in (prompt.headline(), prompt.problem(), prompt.recommendation(), prompt.reason):
        assert is_pseudo_marked(text), text


@pytest.mark.parametrize("device", ["cpu", "cuda"])
def test_live_english_only_prompt_shows_the_language_name_translated(
        pseudo: None, monkeypatch: pytest.MonkeyPatch, device: str) -> None:
    import core.model_manager as mm
    from app.widgets import live_tab
    from core.live_model import LIVE_MAIN

    monkeypatch.setattr(mm, "approx_download_size_text", lambda *_a: "")
    monkeypatch.setattr(mm, "model_downloaded", lambda *_a: False)
    for value in ("German", "Auto"):
        app = types.SimpleNamespace(app_config={},
                                    live_lang_var=types.SimpleNamespace(get=lambda v=value: v))
        for alt in (LIVE_MAIN, "small"):
            prompt = live_tab._english_only_prompt(app, "tiny.en", alt, "small", device)
            assert prompt.language == ("" if value == "Auto" else i18n.pseudo_translate("German"))
            for text in (prompt.problem(), prompt.recommendation(), prompt.reason):
                assert is_pseudo_marked(text), text


# -------------------------------------------------- the same text, the same msgid / context

def test_web_access_off_uses_one_context_everywhere() -> None:
    contexts = set()
    for where, call in _calls("pgettext"):
        if len(call.args) == 2 and isinstance(call.args[1], ast.Constant) and \
                call.args[1].value == "Off" and isinstance(call.args[0], ast.Constant):
            if where in ("app/app.py", "app/widgets/tabs.py"):
                contexts.add(call.args[0].value)
    assert contexts == {"web access status"}


def test_texts_set_by_two_files_are_the_same_msgid() -> None:
    def literals(where: str) -> set[str]:
        return {c.args[0].value for w, c in _calls("_") if w == where and c.args
                and isinstance(c.args[0], ast.Constant)}

    app_py, tabs_py = literals("app/app.py"), literals("app/widgets/tabs.py")
    fmt_py = literals("app/services/format_service.py")
    assert {"Start web access", "Stop web access"} <= app_py
    assert "Start web access" in tabs_py
    assert "Paste a video link above to load its formats" in tabs_py & fmt_py
