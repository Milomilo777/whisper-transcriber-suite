"""Translation wave 3: the transcript viewer, its two small dialogs and the export notices.

``capture_pure`` collects texts that need no window (the VLC hints, the AI status lines, the
export notices of Save); ``capture_viewer`` builds real viewers (a Tk root, VLC stubbed) and
drives every branch that shows a text: menus, notices, message boxes, error dialogs, the
Edit timestamp and Find and replace dialogs. The English texts were captured into
``tests/fixtures/i18n/i18n_wave_3_en.json`` BEFORE the strings went through the translation
layer; after the conversion they must stay byte-identical. Built in the qps-ploc pseudo-locale
every text the viewer owns must carry the pseudo marker.

To capture the fixture again (only when a change is meant to alter the English texts): create
``tests/fixtures/i18n/.capture_wave_3`` and run ``test_capture_english_fixture`` (it needs a Tk
root; run it where a window may open).
"""
from __future__ import annotations

import json
import os
import sys
import threading
import types
from pathlib import Path
from typing import Any, Callable

import pytest

tk = pytest.importorskip("tkinter")

from app.dialogs import transcript_viewer as tv  # noqa: E402
from app.dialogs import viewer_exports  # noqa: E402

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "i18n" / "i18n_wave_3_en.json"
CAPTURE_SENTINEL = FIXTURE.with_name(".capture_wave_3")

SEGMENTS = [
    {"start": 0.0, "end": 1.5, "text": "Hello um world", "speaker": "Speaker 00"},
    {"start": 1.5, "end": 3.0, "text": "Second segment", "speaker": "Speaker 01"},
    {"start": 3.0, "end": 5.0, "text": "Third with no speaker"},
]

Rows = list[list[str]]
States = dict[str, Rows]


class _Var:
    def __init__(self) -> None:
        self.value = ""

    def get(self) -> str:
        return self.value

    def set(self, value: str) -> None:
        self.value = value


def _llm_self(config: dict[str, Any]) -> Any:
    """A stand-in ``self`` for the viewer methods that only read the config."""
    fake = types.SimpleNamespace(_llm_runner=None, _llm_runner_cache_key=None,
                                 _ai_status_var=_Var())
    fake._app_config = lambda: config
    return fake


# --- texts that need no window ---------------------------------------------------------------

def capture_pure(mp: pytest.MonkeyPatch) -> States:
    states: States = {}
    states["vlc_hints"] = [
        ["missing:win32", tv._vlc_missing_hint("win32")],
        ["missing:darwin", tv._vlc_missing_hint("darwin")],
        ["start_failed:win32", tv._vlc_start_failed_hint("win32")],
        ["start_failed:linux", tv._vlc_start_failed_hint("linux")],
    ]
    with mp.context() as m:
        m.setattr(tv, "_locate_vlc_dir", lambda: None)
        m.setitem(sys.modules, "vlc", None)  # the import fails: python-vlc is not installed
        states["vlc_hints"].append(["load:not_installed", tv._try_load_vlc()[1]])

        def _boom(*_a: Any) -> Any:
            raise RuntimeError("no instance")

        m.setitem(sys.modules, "vlc", types.SimpleNamespace(Instance=_boom))
        states["vlc_hints"].append(["load:start_failed", tv._try_load_vlc()[1]])

    rows: Rows = []
    for name, config in (
        ("off", {}),
        ("remote_no_model", {"ai_enabled": True, "llm_provider": "remote"}),
        ("remote_model", {"ai_enabled": True, "llm_provider": "remote", "llm_remote_model": "m-1"}),
        ("local", {"ai_enabled": True}),
    ):
        fake = _llm_self(config)
        tv.TranscriptViewer._refresh_ai_status(fake)
        rows.append([f"status:{name}", fake._ai_status_var.get()])
    with mp.context() as m:
        import core.llm
        m.setattr(core.llm, "build_runner_from_config", lambda _cfg: None)
        for name, config in (
            ("off", {}),
            ("remote", {"ai_enabled": True, "llm_provider": "remote"}),
            ("local", {"ai_enabled": True}),
        ):
            rows.append([f"runner:{name}", tv.TranscriptViewer._get_llm_runner(_llm_self(config))[1]])
    states["ai_config"] = rows

    report = viewer_exports.ExportReport(
        updated=["/t/a.srt", "/t/a.vtt"], stale=["/t/a.txt"], unchecked=["/t/a.md"],
        linked=["/t/a.tsv"], raced=["/t/a.lrc"], failed=["/t/a.docx"],
        unrebuildable=["/t/a.pdf"], other=["/t/a.chapters.json"],
    )
    states["export_notices"] = [[kind, text] for text, kind in
                                viewer_exports.report_notices(report, "/t/a.json")]
    one = viewer_exports.ExportReport(updated=["/t/a.srt"])
    states["export_notices"] += [[kind, text] for text, kind in
                                 viewer_exports.report_notices(one, "/t/a.json")]
    return states


# --- texts of real windows -------------------------------------------------------------------

class _Log:
    """Message boxes, notices and error dialogs, recorded instead of shown."""

    def __init__(self, tmp: Path) -> None:
        self.rows: Rows = []
        self.tmp = str(tmp)
        self.answers: dict[str, Any] = {}

    def norm(self, text: Any) -> str:
        return str(text).replace(self.tmp, "<tmp>")

    def add(self, where: str, *texts: Any) -> None:
        for i, text in enumerate(texts):
            self.rows.append([f"{where}#{i}", self.norm(text)])

    def take(self) -> Rows:
        rows, self.rows = self.rows, []
        return rows


def _widget_texts(log: _Log, w: tk.Misc) -> Rows:
    from tests.app.i18n_walk import visible_texts

    rows = [[p, log.norm(t)] for p, t in visible_texts(w)]

    def headings(widget: tk.Misc) -> None:
        if widget.winfo_class() == "Treeview":
            tree: Any = widget
            for col in tree["columns"]:
                rows.append([f"{tree}:heading:{col}", str(tree.heading(col, "text"))])
        for child in widget.winfo_children():
            headings(child)

    headings(w)
    return rows


def _patch_viewer_world(mp: pytest.MonkeyPatch, log: _Log, pending: list[Callable[[], None]]) -> None:
    mp.setattr(tv, "_try_load_vlc", lambda: (None, tv._vlc_missing_hint("win32")))
    mp.setattr(tv, "notify", lambda _w, text, kind="info", **_k: log.add(f"notify:{kind}", text))
    mp.setattr(tv, "show_error",
               lambda _p, title, message, detail=None: log.add("show_error", title, message))

    def box(name: str) -> Callable[..., Any]:
        def fake(title: str, message: str = "", **_k: Any) -> Any:
            log.add(f"messagebox.{name}", title, message)
            return log.answers.get(name)
        return fake

    for name in ("askyesno", "askyesnocancel", "showinfo", "showwarning", "showerror"):
        mp.setattr(tv.messagebox, name, box(name))

    def askstring(title: str, prompt: str, **_k: Any) -> str:
        log.add("askstring", title, prompt)
        return "Narrator"

    mp.setattr(tv.simpledialog, "askstring", askstring)

    def askopen(**kw: Any) -> str:
        log.add("askopenfilename", kw.get("title", ""), *[d for d, _p in kw.get("filetypes", [])])
        return ""

    mp.setattr(tv.filedialog, "askopenfilename", askopen)
    real_help_icon = tv.help_icon

    def help_icon(parent: tk.Misc, text: Any, **kw: Any) -> Any:
        log.add("help_icon", text() if callable(text) else text)
        return real_help_icon(parent, text, **kw)

    mp.setattr(tv, "help_icon", help_icon)
    import core._threads
    mp.setattr(core._threads, "safe_thread",
               lambda target, args=(), **_k: pending.append(lambda: target(*args)))


def _write_json(folder: Path, payload: Any) -> str:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "demo.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


def _close(viewer: Any) -> None:
    viewer._dirty = False
    viewer.vlc_player = None
    viewer._on_close()


def _run_pending(pending: list[Callable[[], None]]) -> None:
    while pending:
        pending.pop(0)()


def capture_viewer(mp: pytest.MonkeyPatch, tmp: Path) -> States:
    log = _Log(tmp)
    pending: list[Callable[[], None]] = []
    _patch_viewer_world(mp, log, pending)
    states: States = {}
    root = tk.Tk()
    root.withdraw()
    root.app_config = {}  # type: ignore[attr-defined]
    root.post_to_main = lambda fn: fn()  # type: ignore[attr-defined]
    try:
        _capture_main_viewer(mp, root, tmp, log, pending, states)
        _capture_media_viewer(mp, root, tmp, log, states)
        _capture_ai_viewer(mp, root, tmp, log, pending, states)
        _capture_load_and_open(root, tmp, log, states)
    finally:
        for viewer in list(tv._OPEN_VIEWERS.values()):
            try:
                _close(viewer)
            except tk.TclError:
                pass
        root.destroy()
    return states


def _capture_main_viewer(mp: pytest.MonkeyPatch, root: Any, tmp: Path, log: _Log,
                         pending: list[Callable[[], None]], states: States) -> None:
    viewer: Any = tv.TranscriptViewer(root, _write_json(tmp / "main", SEGMENTS))
    viewer.withdraw()
    viewer._bring_forward = lambda: None
    states["viewer"] = _widget_texts(log, viewer) + log.take()

    # Right-click menu, with and without a speaker on the row.
    menus: Rows = []

    def popup(menu: Any, *_a: Any) -> None:
        for i in range(int(menu.index("end")) + 1):
            menus.append([f"menu#{i}", str(menu.entrycget(i, "label"))])

    with mp.context() as m:
        m.setattr(tk.Menu, "tk_popup", popup)
        for row in ("0", "2"):
            m.setattr(viewer.tree, "identify_row", lambda _y, r=row: r)
            viewer._on_segment_right_click(types.SimpleNamespace(y=0, x_root=0, y_root=0))
    states["context_menu"] = menus

    viewer._rename_speaker("Speaker 00")
    viewer.language = None
    viewer._remove_fillers()
    viewer.language = "xx"
    viewer._remove_fillers()
    viewer.language = "en"
    log.answers["askyesno"] = False
    viewer._remove_fillers()
    log.answers["askyesno"] = True
    viewer._remove_fillers()
    states["edits"] = log.take()

    viewer._dirty = True
    real_stamp = viewer._disk_stamp
    viewer._disk_stamp = (0, 0)
    log.answers["askyesno"] = False
    viewer._save_changes()
    viewer._disk_stamp = real_stamp
    with mp.context() as m:
        def no_replace(*_a: Any) -> None:
            raise OSError("disk full")
        m.setattr(tv.os, "replace", no_replace)
        viewer._save_changes()
    viewer._save_changes()
    states["save"] = log.take()

    viewer._dirty = True
    log.answers["askyesno"] = False
    viewer._on_close()
    log.answers["askyesnocancel"] = None
    viewer._open_in_subtitle_edit()
    viewer._confirm_exit(False)
    viewer._confirm_exit(True)
    log.answers["askyesnocancel"] = True

    def save_fails_after_write() -> None:
        viewer._dirty = False
        raise RuntimeError("late failure")

    def save_fails() -> None:
        raise RuntimeError("write failure")

    for fake_save in (save_fails_after_write, save_fails, lambda: None):
        viewer._dirty = True
        viewer._save_changes = fake_save
        viewer._confirm_exit(False)
    del viewer._save_changes
    viewer._dirty = False
    states["close_and_exit"] = log.take()

    viewer.media_path = None
    viewer._open_in_system_player()
    with mp.context() as m:
        m.setattr(tv, "open_file", lambda _p, parent=None, error_text="": log.add("open_file", error_text))
        viewer.media_path = str(tmp / "main" / "demo.mp4")
        viewer._open_in_system_player()
        viewer.media_path = None
        m.setattr(tv, "is_darwin", lambda: False)

        def cannot_open(*_a: Any, **_k: Any) -> None:
            raise OSError("no file manager")

        m.setattr(tv, "_os_open", cannot_open)
        viewer._open_json_folder()
    with mp.context() as m:
        m.setattr(tv, "open_async", lambda _path, _parent, done: done(OSError("x")))
        tv._os_open(str(tmp), viewer)
    with mp.context() as m:
        def cannot_write(*_a: Any) -> None:
            raise OSError("read-only")
        m.setattr(tv, "_write_text_atomically", cannot_write)
        viewer._export_srt_for_subtitle_edit()
    viewer._export_srt_for_subtitle_edit()
    states["files"] = log.take()

    dialog: Any = tv.EditTimestampDialog(viewer, 0)
    dialog.withdraw()
    rows = _widget_texts(log, dialog)
    dialog.start_var.set("bad")
    dialog._save()
    rows.append(["error:invalid", dialog.error_var.get()])
    dialog.start_var.set("5")
    dialog.end_var.set("4")
    dialog._save()
    rows.append(["error:order", dialog.error_var.get()])
    dialog.destroy()
    states["edit_timestamp"] = rows

    viewer._open_find_replace()
    finder: Any = viewer._find_dialog
    finder.withdraw()
    rows = _widget_texts(log, finder)
    finder.find_var.set("zzz")
    finder.find_next()
    finder.replace_all()
    finder.find_var.set("Second")
    finder.replace_var.set("Next")
    finder.replace_all()
    states["find_replace"] = rows + log.take()
    finder.destroy()
    _close(viewer)
    _run_pending(pending)


def _capture_media_viewer(mp: pytest.MonkeyPatch, root: Any, tmp: Path, log: _Log,
                          states: States) -> None:
    folder = tmp / "media"
    json_path = _write_json(folder, SEGMENTS)
    (folder / "demo.mp4").write_bytes(b"")
    (folder / "demo.chapters.json").write_text(
        json.dumps([{"start": 0.0, "title": ""}, {"start": 2.0, "title": "Intro"}]), encoding="utf-8")
    with mp.context() as m:
        m.setattr(tv, "_try_load_vlc", lambda: (None, ""))
        viewer: Any = tv.TranscriptViewer(root, json_path)
    viewer.withdraw()
    rows = _widget_texts(log, viewer) + log.take()
    for item in viewer._chapters_tree.get_children():
        rows.append([f"chapter:{item}", str(viewer._chapters_tree.item(item, "values")[1])])
    playing = {"now": False}
    viewer.vlc_player = types.SimpleNamespace(
        is_playing=lambda: playing["now"], play=lambda: None, pause=lambda: None,
        set_time=lambda _ms: None, stop=lambda: None, release=lambda: None)
    viewer._toggle_play()
    rows.append(["play:started", str(viewer.play_btn.cget("text"))])
    playing["now"] = True
    viewer._toggle_play()
    rows.append(["play:paused", str(viewer.play_btn.cget("text"))])
    playing["now"] = False
    viewer._restart()
    rows.append(["play:restart", str(viewer.play_btn.cget("text"))])
    states["media_viewer"] = rows
    _close(viewer)


def _capture_ai_viewer(mp: pytest.MonkeyPatch, root: Any, tmp: Path, log: _Log,
                       pending: list[Callable[[], None]], states: States) -> None:
    viewer: Any = tv.TranscriptViewer(root, _write_json(tmp / "ai", SEGMENTS))
    viewer.withdraw()
    log.take()

    def result() -> str:
        return log.norm(viewer._ai_result_text.get("1.0", "end-1c"))

    rows: Rows = []
    viewer._run_summarise()  # the AI Layer is off
    viewer._run_bilingual_translate()
    root.app_config = {"ai_enabled": True}
    saved = viewer.segments
    viewer.segments = []
    viewer._run_summarise()
    viewer._run_bilingual_translate()
    viewer.segments = saved

    class Runner:
        def summarise(self, _text: str) -> str:
            raise RuntimeError("boom")

        def action_items(self, _text: str) -> list[str]:
            return []

        def ask(self, _text: str, _question: str) -> str:
            return "an answer"

        def translate(self, _text: str, target_language: str) -> str:
            return "translated"

    mp.setattr(viewer, "_get_llm_runner", lambda: (Runner(), ""))
    for name, run in (("summarise", viewer._run_summarise),
                      ("action_items", viewer._run_action_items),
                      ("translate", viewer._run_translate_preview)):
        run()
        rows.append([f"busy:{name}", result()])
        _run_pending(pending)
        rows.append([f"done:{name}", result()])
    viewer._run_ask()  # no question typed
    viewer._ai_question_var.set("Who spoke?")
    viewer._run_ask()
    rows.append(["busy:ask", result()])
    _run_pending(pending)
    rows += log.take()
    states["ai_tasks"] = rows

    import core.llm

    rows = []
    log.answers["askyesno"] = False
    viewer._run_bilingual_translate()
    log.answers["askyesno"] = True
    progress: Rows = []

    def translate_segments(_runner: Any, segments: list[Any], target_language: str,
                           progress_cb: Any, cancel_event: Any) -> list[str]:
        progress.append(["progress:start", viewer._ai_progress_var.get()])
        progress_cb(1, len(segments))
        progress.append(["progress:step", viewer._ai_progress_var.get()])
        return ["eins", "", "drei"]

    mp.setattr(core.llm, "translate_segments", translate_segments)
    viewer._ai_target_lang_var.set("German")
    viewer._run_bilingual_translate()
    rows.append(["progress:loading", viewer._ai_progress_var.get()])
    _run_pending(pending)  # one segment came back empty: saved with gaps
    mp.setattr(core.llm, "translate_segments", lambda *_a, **_k: ["eins", "zwei", "drei"])
    viewer._run_bilingual_translate()
    _run_pending(pending)
    viewer._bilingual_cancel = threading.Event()
    viewer._cancel_bilingual_translate()
    rows.append(["progress:cancelling", viewer._ai_progress_var.get()])
    viewer._finish_bilingual_translate(viewer.segments, ["a", "b", "c"], "German", None)
    viewer._finish_bilingual_translate(viewer.segments, None, "German", "The provider said no.")
    from core.writers import bilingual_srt
    with mp.context() as m:
        def bad_build(*_a: Any) -> str:
            raise ValueError("mismatch")
        m.setattr(bilingual_srt, "write", bad_build)
        viewer._finish_bilingual_translate(viewer.segments, ["a", "b", "c"], "German", None)
    with mp.context() as m:
        def no_replace(*_a: Any) -> None:
            raise OSError("disk full")
        m.setattr(tv.os, "replace", no_replace)
        viewer._finish_bilingual_translate(viewer.segments, ["a", "b", "c"], "German", None)
    states["bilingual"] = progress + rows + log.take()
    root.app_config = {}
    _close(viewer)


def _capture_load_and_open(root: Any, tmp: Path, log: _Log, states: States) -> None:
    rows: Rows = []
    for name, payload in (("dict", {"token": "x"}), ("numbers", [1, 2, 3])):
        viewer: Any = tv.TranscriptViewer(root, _write_json(tmp / name, payload))
        viewer.withdraw()
        log.rows = [r for r in log.rows if not r[0].startswith("help_icon")]
        rows += log.take()
        _close(viewer)
    tv.open_viewer(root, None)
    tv.open_viewer(root, str(tmp / "nowhere.json"))
    rows += log.take()
    states["load_and_open"] = rows


def capture_states(mp: pytest.MonkeyPatch, tmp: Path) -> States:
    return {**capture_pure(mp), **capture_viewer(mp, tmp)}


def _fixture() -> States:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


# --- tests -----------------------------------------------------------------------------------

@pytest.fixture
def english() -> Any:
    from app import i18n
    i18n.set_language("en")
    yield
    i18n.set_language("en")


@pytest.fixture
def pseudo() -> Any:
    from app import i18n
    assert i18n.set_language(i18n.PSEUDO_LOCALE) == i18n.PSEUDO_LOCALE
    try:
        yield
    finally:
        i18n.set_language("en")


@pytest.mark.skipif(not CAPTURE_SENTINEL.exists(), reason="capture mode is off")
def test_capture_english_fixture(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, english: Any) -> None:
    states = capture_states(monkeypatch, tmp_path)
    FIXTURE.write_text(json.dumps(states, indent=1, ensure_ascii=False) + "\n", encoding="utf-8",
                       newline="\n")


# Texts that are not the viewer's own: data from the transcript or the test, and messages that
# come from outside the viewer (core, the AI provider), which are not translated here.
DATA_TEXTS = {"Intro", "The provider said no.", "translated"}


def _untranslated(states: States) -> list[tuple[str, str, str]]:
    from tests.app.i18n_walk import is_pseudo_marked
    return [(state, where, text) for state, rows in states.items() for where, text in rows
            if text not in DATA_TEXTS and not is_pseudo_marked(text)]


def _shape(states: States) -> dict[str, list[str]]:
    return {state: [where for where, _text in rows] for state, rows in states.items()}


def test_pure_texts_match_the_english_capture(monkeypatch: pytest.MonkeyPatch, english: Any) -> None:
    expected = _fixture()
    got = capture_pure(monkeypatch)
    assert got == {k: expected[k] for k in got}


def test_pure_texts_are_translated_in_the_pseudo_locale(
        monkeypatch: pytest.MonkeyPatch, pseudo: Any) -> None:
    got = capture_pure(monkeypatch)
    assert _untranslated(got) == []
    expected = _fixture()
    assert _shape(got) == {k: [w for w, _t in expected[k]] for k in got}


def test_viewer_texts_match_the_english_capture(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path, english: Any) -> None:
    got = capture_viewer(monkeypatch, tmp_path)
    expected = _fixture()
    assert got == {k: expected[k] for k in got}
    assert set(got) | set(capture_pure(monkeypatch)) == set(expected)


def test_viewer_texts_are_translated_in_the_pseudo_locale(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path, pseudo: Any) -> None:
    got = capture_viewer(monkeypatch, tmp_path)
    assert _untranslated(got) == []
    # The same branches ran: one text per English text, in the same places.
    expected = _fixture()
    assert _shape(got) == {k: [w for w, _t in expected[k]] for k in got}
    # Nothing the viewer wrote takes a translated word: file names and the saved JSON.
    written = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file())
    assert written == WRITTEN_FILES
    saved = json.loads((tmp_path / "main" / "demo.json").read_text(encoding="utf-8"))
    assert [s.get("speaker") for s in saved] == ["Narrator", "Speaker 01", None]
    assert [s["text"] for s in saved] == ["Hello world", "Second segment", "Third with no speaker"]


# Every file capture_viewer leaves behind, the same in every interface language.
WRITTEN_FILES = [
    "ai/demo.bilingual.german.srt", "ai/demo.json", "dict/demo.json",
    "main/demo.json", "main/demo.srt",
    "media/demo.chapters.json", "media/demo.json", "media/demo.mp4", "numbers/demo.json",
]


def test_placeholder_values_survive_in_the_pseudo_locale(
        monkeypatch: pytest.MonkeyPatch, pseudo: Any) -> None:
    got = capture_pure(monkeypatch)
    notices = " ".join(t for _w, t in got["export_notices"])
    for name in ("a.srt, a.vtt", "a.json", "a.docx", "a.lrc", "a.tsv", "a.md", "a.txt", "a.pdf",
                 "a.chapters.json"):
        assert name in notices
    assert "m-1" in dict(got["ai_config"])["status:remote_model"]
