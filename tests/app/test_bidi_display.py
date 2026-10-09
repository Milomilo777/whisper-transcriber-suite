"""Left-to-right base direction for file names on macOS (app.theme.bidi_display).

Tk on macOS (aqua) hands a label to CoreText, which takes the paragraph direction from the first
strong letter: a Persian file name followed by ".wav" is drawn as "wav.<name>", and the "• " or
"✓ " in front of it jumps to the right end. Tk on Windows always uses a left-to-right base. The
helper puts one invisible LEFT-TO-RIGHT MARK in front of such a string on macOS only; the data,
the files and the saved text are never touched.
"""
from __future__ import annotations

import os
import types
import unicodedata
from tkinter import ttk
from unittest.mock import MagicMock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app import app as appmod
from app.domain.tasks import TranscriptionTask, VideoDownloadTask
from app.theme import bidi_display
from app.theme.bidi_display import LRM, ltr_base

PERSIAN_NAME = "نمونه صدا.wav"
ARABIC_NAME = "عربي.docx"
BULLET_LINE = "• " + ARABIC_NAME + "  (36.0 KB)"


@pytest.fixture
def aqua(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bidi_display, "is_aqua", lambda: True)


@pytest.fixture
def not_aqua(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bidi_display, "is_aqua", lambda: False)


def _strong(ch: str) -> bool:
    return unicodedata.bidirectional(ch) in ("L", "R", "AL")


# --- the helper -------------------------------------------------------------------------------


def test_platform_query_follows_sys_platform(monkeypatch):
    monkeypatch.setattr(bidi_display.sys, "platform", "darwin")
    assert bidi_display.is_aqua()
    for other in ("win32", "linux"):
        monkeypatch.setattr(bidi_display.sys, "platform", other)
        assert not bidi_display.is_aqua()


def test_aqua_marks_a_name_that_starts_with_an_rtl_letter(aqua):
    assert ltr_base(PERSIAN_NAME) == LRM + PERSIAN_NAME
    assert ltr_base(ARABIC_NAME) == LRM + ARABIC_NAME


def test_aqua_marks_a_label_whose_prefix_is_neutral(aqua):
    # "bullet, space, Arabic": the first STRONG letter decides, not the bullet.
    assert ltr_base(BULLET_LINE) == LRM + BULLET_LINE
    assert ltr_base("✓ " + PERSIAN_NAME) == LRM + "✓ " + PERSIAN_NAME
    assert ltr_base("(1) " + PERSIAN_NAME) == LRM + "(1) " + PERSIAN_NAME


def test_aqua_leaves_a_string_that_already_starts_left_to_right(aqua):
    for text in ("talk.wav", "Hello " + PERSIAN_NAME, "• talk.wav", "2024 talk", "", " ", "✓ "):
        assert ltr_base(text) == text


def test_aqua_mark_is_not_added_twice(aqua):
    once = ltr_base(PERSIAN_NAME)
    assert ltr_base(once) == once
    assert once.count(LRM) == 1


def test_not_aqua_never_changes_anything(not_aqua):
    for text in (PERSIAN_NAME, BULLET_LINE, "talk.wav", ""):
        assert ltr_base(text) == text


def test_the_mark_is_the_left_to_right_mark():
    assert LRM == "\u200e"
    assert unicodedata.bidirectional(LRM) == "L"


# --- properties (Hypothesis) --------------------------------------------------------------------

# Latin, Arabic-script, digits, punctuation, the marks and joiners a file name can hold.
_ALPHABET = st.sampled_from(
    list("abcXYZ019 ._-()•✓")
    + list("ابجدهوزحطیکلمنسعفصقرشتثخذضظغپچژگ")
    + ["\u200c", "\u200d", "\u200e", "\u200f", "\u064b", "۱", "א"]
)
_TEXT = st.text(alphabet=_ALPHABET, max_size=40)


@settings(max_examples=300, deadline=None)
@given(_TEXT)
def test_property_off_aqua_is_the_identity(text):
    import app.theme.bidi_display as mod

    orig = mod.is_aqua
    mod.is_aqua = lambda: False
    try:
        assert ltr_base(text) == text
    finally:
        mod.is_aqua = orig


@settings(max_examples=300, deadline=None)
@given(_TEXT)
def test_property_on_aqua_the_logical_text_is_recoverable(text):
    import app.theme.bidi_display as mod

    orig = mod.is_aqua
    mod.is_aqua = lambda: True
    try:
        out = ltr_base(text)
    finally:
        mod.is_aqua = orig
    assert out == text or out == LRM + text
    # Dropping the one added mark gives the original back, nothing else was edited.
    assert (out[1:] if out != text else out) == text
    assert len(out) - len(text) in (0, 1)


@settings(max_examples=300, deadline=None)
@given(_TEXT)
def test_property_on_aqua_is_idempotent_and_marks_only_rtl_first(text):
    import app.theme.bidi_display as mod

    orig = mod.is_aqua
    mod.is_aqua = lambda: True
    try:
        out = ltr_base(text)
        again = ltr_base(out)
    finally:
        mod.is_aqua = orig
    assert again == out
    first = next((c for c in text if _strong(c)), "")
    marked = out != text
    assert marked == (first != "" and unicodedata.bidirectional(first) in ("R", "AL"))


@settings(max_examples=200, deadline=None)
@given(st.text(alphabet=st.sampled_from(list("abcXYZ019 ._-()•✓\u200e")), max_size=40))
def test_property_left_to_right_only_text_is_unchanged_on_aqua(text):
    import app.theme.bidi_display as mod

    orig = mod.is_aqua
    mod.is_aqua = lambda: True
    try:
        assert ltr_base(text) == text
    finally:
        mod.is_aqua = orig


# --- call sites: only the DISPLAY string changes -------------------------------------------------


class _RecordingTree:
    """Just enough Treeview surface for refresh() and refresh_download_queue()."""

    def __init__(self) -> None:
        self.rows: list[tuple[tuple, tuple]] = []

    def get_children(self):
        return tuple(str(i) for i in range(len(self.rows)))

    def delete(self, *_iids):
        self.rows = []

    def insert(self, _parent, _index, iid=None, values=(), tags=()):
        self.rows.append((tuple(values), tuple(tags)))
        return str(len(self.rows) - 1)

    def selection(self):
        return ()

    def selection_set(self, _iids):
        pass


def _queue_app(queue):
    return types.SimpleNamespace(
        tree=_RecordingTree(), row_map={}, queue=queue,
        _row_progress_text=lambda *_a: "", fmt_time=lambda _t: "",
        _refresh_window_title=lambda: None, _ensure_animation=lambda: None,
        _selected_tasks=lambda: [], _update_queue_action_bar=lambda: None,
    )


def test_queue_row_shows_the_marked_name_but_the_task_keeps_its_path(aqua):
    path = os.path.join("media", PERSIAN_NAME)
    task = TranscriptionTask(path)
    app = _queue_app([task])
    appmod.App.refresh(app)  # type: ignore[arg-type]
    (values, _tags), = app.tree.rows
    assert values[0] == LRM + PERSIAN_NAME
    assert task.file_path == path
    assert list(app.row_map.values()) == [task]


def test_queue_row_is_unchanged_off_aqua(not_aqua):
    task = TranscriptionTask(os.path.join("media", PERSIAN_NAME))
    app = _queue_app([task])
    appmod.App.refresh(app)  # type: ignore[arg-type]
    assert app.tree.rows[0][0][0] == PERSIAN_NAME


def test_download_row_shows_the_marked_title_but_not_the_url(aqua):
    task = VideoDownloadTask(
        url="https://example.com/v", folder=".", format_label="best", format_info={},
        title=PERSIAN_NAME,
    )
    app = types.SimpleNamespace(
        download_tree=_RecordingTree(), download_row_map={}, download_queue=[task],
        _download_row_progress=lambda _t: 0, _row_progress_text=lambda *_a: "",
        fmt_time=lambda _t: "", _refresh_window_title=lambda: None,
        _ensure_animation=lambda: None, _update_download_action_bar=lambda: None,
        _selected_downloads=lambda: [],
    )
    appmod.App.refresh_download_queue(app)  # type: ignore[arg-type]
    (values, _tags), = app.download_tree.rows
    assert values[0] == LRM + PERSIAN_NAME
    assert values[1] == "https://example.com/v"
    assert task.title == PERSIAN_NAME


def _label_texts(widget):
    out = []
    for child in widget.winfo_children():
        if isinstance(child, ttk.Label):
            out.append(str(child.cget("text")))
        out.extend(_label_texts(child))
    return out


@pytest.fixture()
def tk_root():
    import tkinter as tk

    try:
        root = tk.Tk()
    except tk.TclError:  # pragma: no cover - headless box
        pytest.skip("no display")
    root.withdraw()
    yield root
    root.destroy()


def _last_result_texts(root, tmp_path):
    media = tmp_path / PERSIAN_NAME
    media.write_bytes(b"x")
    out = tmp_path / "نمونه صدا.srt"
    out.write_text("1\n", encoding="utf-8")
    task = types.SimpleNamespace(
        file_path=str(media), output_paths=[str(out)], language="fa", detected_language="fa",
        no_speech=False, word_count=0, audio_duration=0.0, whisper_task=None,
    )
    fake = types.SimpleNamespace(
        last_result_frame=ttk.Frame(root), last_result_empty_label=MagicMock(),
        last_result_body=ttk.Frame(root), tray=None, log=MagicMock(), nb=MagicMock(),
        t1=object(), app_config={}, chime_on_complete_var=None,
        _open_file=MagicMock(), _open_folder=MagicMock(),
        open_transcript_viewer_for=MagicMock(), _save_shareable_page_for=MagicMock(),
    )
    appmod.App.show_last_result(fake, task)  # type: ignore[arg-type]
    return _label_texts(fake.last_result_body)


def test_last_result_card_marks_the_name_lines_on_aqua(aqua, tk_root, tmp_path):
    texts = _last_result_texts(tk_root, tmp_path)
    assert LRM + "✓ " + PERSIAN_NAME in texts
    assert any(t.startswith(LRM + "• نمونه صدا.srt") for t in texts)


def test_last_result_card_is_unchanged_off_aqua(not_aqua, tk_root, tmp_path):
    texts = _last_result_texts(tk_root, tmp_path)
    assert "✓ " + PERSIAN_NAME in texts
    assert not any(LRM in t for t in texts)


# --- search dialog and voice-clone sample list -----------------------------------------------------


def _search_rows(monkeypatch):
    from app.dialogs import search_dialog

    monkeypatch.setattr(search_dialog.script_fonts, "tree_row_tags", lambda *_a, **_k: ())
    hit = types.SimpleNamespace(
        json_path=os.path.join("media", "نمونه صدا.json"),
        start_seconds=1.0, text=PERSIAN_NAME,
    )
    fake = types.SimpleNamespace(
        _closing=False, _search_seq=1, status_var=MagicMock(), tree=_RecordingTree(), _hits=[],
    )
    search_dialog.SearchDialog._finish_search(fake, [hit], None, 1)  # type: ignore[arg-type]
    return fake, hit


def test_search_result_marks_the_file_name_column_but_not_the_hit_text(aqua, monkeypatch):
    fake, hit = _search_rows(monkeypatch)
    (values, _tags), = fake.tree.rows
    assert values[0] == LRM + os.path.basename(hit.json_path)
    assert values[2] == PERSIAN_NAME  # transcript text keeps the first-strong direction
    assert fake._hits == [hit] and hit.json_path.endswith(".json")


def test_search_result_is_unchanged_off_aqua(not_aqua, monkeypatch):
    fake, hit = _search_rows(monkeypatch)
    assert fake.tree.rows[0][0][0] == os.path.basename(hit.json_path)


def _sample_names(root, paths):
    import tkinter as tk

    from app.widgets import voice_clone_tab

    box = tk.Listbox(root)
    fake = types.SimpleNamespace(vc_samples_listbox=box, vc_samples=list(paths))
    voice_clone_tab._refresh_samples_listbox(fake)
    return list(box.get(0, "end")), fake


def test_voice_clone_sample_list_marks_names_on_aqua(aqua, tk_root):
    names, fake = _sample_names(tk_root, [os.path.join("a", PERSIAN_NAME), os.path.join("a", "x.wav")])
    assert names == [LRM + PERSIAN_NAME, "x.wav"]
    assert fake.vc_samples[0] == os.path.join("a", PERSIAN_NAME)  # the stored path is not marked


def test_voice_clone_sample_list_is_unchanged_off_aqua(not_aqua, tk_root):
    names, _fake = _sample_names(tk_root, [os.path.join("a", PERSIAN_NAME)])
    assert names == [PERSIAN_NAME]
