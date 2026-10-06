"""Per-script fonts for file names and transcript lines (app.theme.script_fonts).

Samples are CLDR autonyms and territory names (the names the languages give themselves), one or
more per writing system of the caption-language list.
"""
from __future__ import annotations

import logging
import re
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

import pytest

from app.domain.languages import SUBTITLE_LANGUAGES
from app.theme import script_fonts, tokens

ZWJ = chr(0x200D)
SRI_LANKA = "ශ්" + ZWJ + "රී ලංකාව"  # Sinhala conjunct joined by ZERO WIDTH JOINER

# (language code, sample, expected font key)
SAMPLES = [
    ("hi", "हिन्दी", "indic"),
    ("mr", "मराठी", "indic"),
    ("ne", "नेपाली", "indic"),
    ("bn", "বাংলা", "indic"),
    ("gu", "ગુજરાતી", "indic"),
    ("pa", "ਪੰਜਾਬੀ", "indic"),
    ("ta", "தமிழ்", "indic"),
    ("te", "తెలుగు", "indic"),
    ("kn", "ಕನ್ನಡ", "indic"),
    ("ml", "മലയാളം", "indic"),
    ("si", "සිංහල", "sinhala"),
    ("si", SRI_LANKA, "sinhala"),
    ("my", "မြန်မာ", "myanmar"),
    ("th", "ไทย", "thai"),
    ("lo", "ລາວ", "lao"),
    ("km", "ខ្មែរ", "khmer"),
    ("ja", "日本語", "ja"),
    ("zh-Hans,zh-CN", "中文（简体）", "zh-hans"),
    ("zh-Hant,zh-TW", "中文（繁體）", "zh-hant"),
    ("ko", "한국어", None),
    ("ru", "русский", None),
    ("el", "Ελληνικά", None),
    ("hy", "հայերեն", None),
    ("ka", "ქართული", None),
    ("am", "አማርኛ", None),
    ("ar", "العربية", None),
    ("fa", "فارسی", None),
    ("iw", "עברית", None),
    ("en", "English", None),
    ("vi", "Tiếng Việt", None),
    ("yo", "Èdè Yorùbá", None),
]


@pytest.fixture
def windows(monkeypatch: pytest.MonkeyPatch) -> set[str]:
    """Pretend to run on Windows with every family of the table installed (the set can be edited)."""
    installed = set(tokens.FONT_FAMILIES_WINDOWS.values())
    monkeypatch.setattr(script_fonts, "_on_windows", lambda: True)
    monkeypatch.setattr(script_fonts, "installed_families", lambda _w: frozenset(installed))
    monkeypatch.setattr(script_fonts, "_missing_logged", set())
    return installed


@pytest.fixture
def root():
    r = tk.Tk()
    r.withdraw()
    try:
        yield r
    finally:
        r.destroy()


# ------------------------------------------------------------------ choosing a font

@pytest.mark.parametrize(("language", "text", "key"), SAMPLES)
def test_font_key_per_writing_system(language: str, text: str, key: str | None) -> None:
    assert script_fonts.font_key(text, language) == key
    # File names wrap the name in Latin; the script still decides.
    assert script_fonts.font_key(f"interview_{text}.mp4", language) == key


def test_every_language_of_the_list_with_a_special_script_is_sampled() -> None:
    codes = {c.split(",")[0] for _name, c in SUBTITLE_LANGUAGES if c}
    special = {"hi", "mr", "ne", "bn", "gu", "pa", "ta", "te", "kn", "ml", "si", "my", "th", "lo", "km",
               "ja", "zh-Hans", "zh-Hant"}
    assert special <= codes, "the caption-language list lost a language this test covers"
    sampled = {lang.split(",")[0] for lang, _text, key in SAMPLES if key is not None}
    assert special == sampled


def test_kana_makes_han_japanese_without_a_language() -> None:
    assert script_fonts.font_key("にほんご") == "ja"
    assert script_fonts.font_key("日本語のテスト") == "ja"
    assert script_fonts.font_key("日本語のテスト", "zh") == "ja"


@pytest.mark.parametrize(("language", "key"), [
    ("zh", "zh-hans"), ("zh-CN", "zh-hans"), ("zh_Hans", "zh-hans"), ("zh-Hant", "zh-hant"),
    ("zh-TW", "zh-hant"), ("zh-HK", "zh-hant"), ("yue", "zh-hant"), ("ja", "ja"), ("JA", "ja"),
    ("ko", None), ("", None), (None, None), ("auto", None),
])
def test_han_without_kana_follows_the_language(language: str | None, key: str | None) -> None:
    assert script_fonts.font_key("中文", language) == key


def test_the_script_with_most_characters_wins_and_ties_are_stable() -> None:
    assert script_fonts.text_script("ไทย ไทย မြန်") == "thai"
    assert script_fonts.text_script("ไ မ") == "myanmar"  # tie: the taller marks first
    assert script_fonts.text_script("ไ မ") == script_fonts.text_script("မ ไ")


@pytest.mark.parametrize(("cp", "script"), [
    (0x08FF, None), (0x0900, "indic"), (0x0D7F, "indic"), (0x0D80, "sinhala"), (0x0DFF, "sinhala"),
    (0x0E00, "thai"), (0x0E7F, "thai"), (0x0E80, "lao"), (0x0F00, None), (0x1000, "myanmar"),
    (0x109F, "myanmar"), (0x10A0, None), (0x1780, "khmer"), (0x3040, "kana"), (0x4E00, "han"),
    (0x9FFF, "han"), (0xAC00, None), (0x20000, "han"), (0x0041, None), (0x0627, None),
])
def test_script_of_range_edges(cp: int, script: str | None) -> None:
    assert script_fonts.script_of(chr(cp)) == script


def test_every_font_key_has_a_family_and_every_family_is_used() -> None:
    ranges = {s for _a, _b, s in script_fonts._RANGES} - {"kana", "han"}
    keys = ranges | {"ja", "zh-hans", "zh-hant"}
    assert set(tokens.FONT_FAMILIES_WINDOWS) == keys | {"ui"}


def test_family_for_on_windows(windows: set[str]) -> None:
    assert script_fonts.family_for("မြန်မာ", installed=windows) == "Myanmar Text"
    assert script_fonts.family_for(SRI_LANKA, installed=windows) == "Nirmala UI"
    assert script_fonts.family_for("中文", "zh-TW", installed=windows) == "Microsoft JhengHei UI"
    assert script_fonts.family_for("English", installed=windows) is None


def test_a_missing_font_keeps_the_default_and_is_logged_once(
        windows: set[str], caplog: pytest.LogCaptureFixture) -> None:
    windows.discard("Myanmar Text")
    with caplog.at_level(logging.INFO, logger="app.theme.script_fonts"):
        assert script_fonts.family_for("မြန်မာ", installed=windows) is None
        assert script_fonts.family_for("interview_မြန်မာ.mp4", installed=windows) is None
    assert [r.getMessage() for r in caplog.records].count(
        "Font 'Myanmar Text' is not installed; myanmar text keeps the default font") == 1
    assert script_fonts.family_for("සිංහල", installed=windows) == "Nirmala UI"


def test_other_platforms_keep_their_fonts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(script_fonts, "_on_windows", lambda: False)
    assert script_fonts.family_for("မြန်မာ", installed={"Myanmar Text"}) is None


# ------------------------------------------------------------------------- tk.Text

def _font_of_line(text: tk.Text, line: int) -> str | None:
    names = [t for t in text.tag_names(f"{line}.0") if t.startswith("script-font-")]
    return str(text.tag_cget(names[0], "font")) if names else None


def test_text_box_gets_a_proportional_font_and_per_line_script_fonts(windows: set[str], root: tk.Tk) -> None:
    text = tk.Text(root)
    assert script_fonts.use_text_font(text)
    assert tkfont.Font(root=root, font=text.cget("font")).cget("family") == "Segoe UI"
    text.insert("1.0", "\n".join(["English line", "မြန်မာ", SRI_LANKA, "हिन्दी", "日本語", "ไทย"]))
    script_fonts.tag_script_lines(text, language="ja")
    assert _font_of_line(text, 1) is None
    assert "Myanmar Text" in str(_font_of_line(text, 2))
    assert "Nirmala UI" in str(_font_of_line(text, 3))
    assert "Nirmala UI" in str(_font_of_line(text, 4))
    assert "Yu Gothic UI" in str(_font_of_line(text, 5))
    assert "Leelawadee UI" in str(_font_of_line(text, 6))
    # The tag covers the whole line, so the line gets that font's height.
    tag = next(t for t in text.tag_names("2.0") if t.startswith("script-font-"))
    assert [str(i) for i in text.tag_ranges(tag)] == ["2.0", text.index("2.end")]


def test_retagging_follows_edits(windows: set[str], root: tk.Tk) -> None:
    text = tk.Text(root)
    text.insert("1.0", "မြန်မာ\nEnglish")
    script_fonts.tag_script_lines(text)
    assert _font_of_line(text, 1) is not None
    text.delete("1.0", "1.end")
    text.insert("1.0", "now Latin")
    text.insert("2.0", "ไทย ")
    script_fonts.tag_script_lines(text)
    assert _font_of_line(text, 1) is None
    assert "Leelawadee UI" in str(_font_of_line(text, 2))


def _script_tags(text: tk.Text, index: str) -> list[str]:
    return [t for t in text.tag_names(index) if t.startswith("script-font-")]


def test_retagging_drops_tags_that_typed_characters_inherited(windows: set[str], root: tk.Tk) -> None:
    text = tk.Text(root)
    text.insert("1.0", "မမ")
    script_fonts.tag_script_lines(text)
    text.insert("1.1", "abc")  # typed between tagged characters: inherits the Myanmar tag
    text.delete("1.4")
    text.delete("1.0")
    assert text.get("1.0", "1.end") == "abc" and _script_tags(text, "1.0")
    script_fonts.tag_script_lines(text)
    assert _script_tags(text, "1.0") == []
    text.delete("1.0", "end")
    text.insert("1.0", "မမ")
    script_fonts.tag_script_lines(text)
    text.insert("1.1", "ไทยไทย")  # now mostly Thai, all of it inherited the Myanmar tag
    script_fonts.tag_script_lines(text)
    assert _script_tags(text, "1.0") == ["script-font-Leelawadee_UI"]


def test_appending_tags_only_the_new_lines(windows: set[str], root: tk.Tk) -> None:
    text = tk.Text(root)
    text.insert("end", "မြန်မာ\n")
    script_fonts.tag_script_lines(text)
    start = text.index("end-1c")
    text.insert("end", "हिन्दी\n")
    script_fonts.tag_script_lines(text, start, "end")
    assert "Myanmar Text" in str(_font_of_line(text, 1))
    assert "Nirmala UI" in str(_font_of_line(text, 2))


def test_text_box_unchanged_off_windows(monkeypatch: pytest.MonkeyPatch, root: tk.Tk) -> None:
    monkeypatch.setattr(script_fonts, "_on_windows", lambda: False)
    text = tk.Text(root)
    before = str(text.cget("font"))
    assert not script_fonts.use_text_font(text)
    text.insert("1.0", "မြန်မာ")
    script_fonts.tag_script_lines(text)
    assert str(text.cget("font")) == before
    assert _font_of_line(text, 1) is None


def test_text_box_keeps_its_font_when_segoe_ui_is_missing(windows: set[str], root: tk.Tk) -> None:
    windows.discard("Segoe UI")
    text = tk.Text(root)
    before = str(text.cget("font"))
    assert not script_fonts.use_text_font(text)
    assert str(text.cget("font")) == before


# ------------------------------------------------------------------------ Treeview

def _rowheight(style: ttk.Style, name: str) -> int:
    return int(str(style.lookup(name, "rowheight") or 0))


def test_tree_row_gets_the_script_font_and_only_that_tree_grows(windows: set[str], root: tk.Tk) -> None:
    style = ttk.Style(root)
    style.configure("Treeview", rowheight=21)
    tree = ttk.Treeview(root, columns=("file",), show="headings")
    other = ttk.Treeview(root, columns=("file",), show="headings")
    assert script_fonts.tree_row_tags(tree, "interview_2026.mp4") == ()
    assert str(tree.cget("style")) == ""
    tags = script_fonts.tree_row_tags(tree, "interview_မြန်မာ.mp4")
    assert tags == ("script-font-Myanmar_Text",)
    assert "Myanmar Text" in str(tree.tag_configure(tags[0], "font"))
    name = str(tree.cget("style"))
    line = tkfont.Font(root=root, font=tree.tag_configure(tags[0], "font")).metrics("linespace")
    if line + 3 > 21:
        assert re.fullmatch(r"WtsRows\d+\.Treeview", name)
        assert _rowheight(style, name) == line + 3
    else:  # the font's lines fit the rows already: the tree keeps its style
        assert name == ""
    assert str(other.cget("style")) == ""
    assert _rowheight(style, "Treeview") == 21
    # Rows insert with the tag; a second Myanmar row reuses tag and style.
    tree.insert("", "end", values=("x",), tags=tags)
    assert script_fonts.tree_row_tags(tree, "မြန်မာ") == tags
    assert str(tree.cget("style")) == name


def test_tree_rows_only_grow(windows: set[str], root: tk.Tk) -> None:
    style = ttk.Style(root)
    style.configure("Treeview", rowheight=10)  # every font below needs more
    tree = ttk.Treeview(root, columns=("file",), show="headings")
    script_fonts.tree_row_tags(tree, "हिन्दी")
    first = _rowheight(style, str(tree.cget("style")))
    script_fonts.tree_row_tags(tree, "မြန်မာ")
    tall = _rowheight(style, str(tree.cget("style")))
    script_fonts.tree_row_tags(tree, "ไทย")
    assert 10 < first <= tall == _rowheight(style, str(tree.cget("style")))


def test_tree_rows_change_no_style_once_the_theme_is_prepared(windows: set[str], root: tk.Tk) -> None:
    # Setting a ttk style option sends <<ThemeChanged>> to every widget, and sv_ttk then resets
    # each Entry / Combobox font: rows that need taller lines must only switch the tree's style.
    style = ttk.Style(root)
    style.configure("Treeview", rowheight=10)
    entry = ttk.Entry(root)
    seen: list[int] = []
    entry.bind("<<ThemeChanged>>", lambda _e: seen.append(1), add="+")
    script_fonts.apply_theme_fonts(root)
    root.update()
    assert seen, "control: setting a style option does send <<ThemeChanged>>"
    seen.clear()
    tree = ttk.Treeview(root, columns=("file",), show="headings")
    for text in ("မြန်မာ.mp3", "हिन्दी.mp3", "中文.mp3", "ไทย.mp3"):
        assert script_fonts.tree_row_tags(tree, text, language="zh")
    root.update()
    assert str(tree.cget("style")).startswith("WtsRows")
    assert seen == []


def test_tree_row_keeps_the_default_when_the_font_is_missing(windows: set[str], root: tk.Tk) -> None:
    windows.discard("Nirmala UI")
    tree = ttk.Treeview(root, columns=("file",), show="headings")
    assert script_fonts.tree_row_tags(tree, "हिन्दी.mp3") == ()
    assert str(tree.cget("style")) == ""


def test_tree_rows_survive_a_theme_switch(windows: set[str], root: tk.Tk) -> None:
    style = ttk.Style(root)
    style.configure("Treeview", rowheight=10)
    tree = ttk.Treeview(root, columns=("file",), show="headings")
    assert script_fonts.tree_row_tags(tree, "မြန်မာ")
    name = str(tree.cget("style"))
    need = _rowheight(style, name)
    style.theme_use("alt" if style.theme_use() != "alt" else "clam")
    style.configure("Treeview", rowheight=10)
    assert _rowheight(style, name) < need  # the new theme knows nothing of the taller style
    script_fonts.apply_theme_fonts(root)  # what the app runs after every theme switch
    assert _rowheight(style, name) == need


# ------------------------------------------------------------- Treeview on Windows 10

def test_tree_font_fix_replaces_a_missing_theme_font(windows: set[str], root: tk.Tk) -> None:
    style = ttk.Style(root)
    root.tk.call("font", "create", "FakeThemeFont", "-family", "No Such Font C242", "-size", -14)
    style.configure("Treeview", font="FakeThemeFont", rowheight=21)
    assert script_fonts.fix_tree_font(root)
    assert str(style.lookup("Treeview", "font")) == script_fonts.TREE_FONT
    fixed = tkfont.nametofont(script_fonts.TREE_FONT, root=root)
    assert fixed.cget("family") == "Segoe UI" and fixed.cget("size") == -14
    assert _rowheight(style, "Treeview") >= max(21, int(fixed.metrics("linespace")) + 3)
    assert script_fonts.fix_tree_font(root)  # again (a theme switch): nothing breaks


def test_tree_font_fix_leaves_an_installed_theme_font(windows: set[str], root: tk.Tk) -> None:
    style = ttk.Style(root)
    family = tkfont.nametofont("TkDefaultFont", root=root).actual("family")
    root.tk.call("font", "create", "RealThemeFont", "-family", family, "-size", -14)
    style.configure("Treeview", font="RealThemeFont")
    assert not script_fonts.fix_tree_font(root)
    assert str(style.lookup("Treeview", "font")) == "RealThemeFont"


def test_tree_font_fix_off_windows(monkeypatch: pytest.MonkeyPatch, root: tk.Tk) -> None:
    monkeypatch.setattr(script_fonts, "_on_windows", lambda: False)
    style = ttk.Style(root)
    root.tk.call("font", "create", "FakeThemeFont2", "-family", "No Such Font C242", "-size", -14)
    style.configure("Treeview", font="FakeThemeFont2")
    assert not script_fonts.fix_tree_font(root)
    assert str(style.lookup("Treeview", "font")) == "FakeThemeFont2"


# ------------------------------------------------------------------ the app's widgets

def test_viewer_rows_carry_the_script_font_next_to_the_colours(
        windows: set[str], root: tk.Tk, tmp_path) -> None:
    import json

    from app.dialogs.transcript_viewer import TranscriptViewer

    segs = [
        {"start": 0.0, "end": 1.0, "text": "English",
         "words": [{"start": 0.0, "end": 1.0, "word": "English", "probability": 0.95}]},
        {"start": 1.0, "end": 2.0, "text": "မြန်မာ",
         "words": [{"start": 1.0, "end": 2.0, "word": "မြန်မာ", "probability": 0.3}]},
    ]
    p = tmp_path / "scripts.json"
    p.write_text(json.dumps(segs, ensure_ascii=False), encoding="utf-8")
    viewer = TranscriptViewer(root, str(p))
    viewer.withdraw()
    try:
        first, second = viewer.tree.get_children()
        assert tuple(viewer.tree.item(first, "tags")) == ("conf_high",)
        assert tuple(viewer.tree.item(second, "tags")) == ("conf_low", "script-font-Myanmar_Text")
        viewer._set_active_segment(1)
        assert tuple(viewer.tree.item(second, "tags")) == (
            "active", "conf_low", "script-font-Myanmar_Text")
        viewer._set_ai_result("English\nသတင်း")
        assert "Myanmar Text" in str(_font_of_line(viewer._ai_result_text, 2))
        assert _font_of_line(viewer._ai_result_text, 1) is None
    finally:
        viewer._on_close()
