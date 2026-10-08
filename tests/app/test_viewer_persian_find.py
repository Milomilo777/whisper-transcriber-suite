"""The viewer's search box and Find/Replace fold Persian spelling like the global search.

ZWNJ (the Persian half-space), Arabic kaf/yeh versus the Persian letters, vowel marks and
Arabic-Indic digits must not hide a match, and Replace must still rewrite the ORIGINAL text
exactly where it matched: folding is for matching only. Persian text is built from code
points so the file stays ASCII.
"""
from __future__ import annotations

import json
import random
from typing import Any

import pytest

from core import search as srch


def _u(hex_points: str) -> str:
    """'0645 06CC' -> the string of those code points."""
    return "".join(chr(int(h, 16)) for h in hex_points.split())


ZWNJ = chr(0x200C)
FATHA = chr(0x064E)
KAF_AR, KAF_FA = chr(0x0643), chr(0x06A9)
YEH_AR, YEH_FA = chr(0x064A), chr(0x06CC)
# "mikhaham" (I want) with the half-space, and without it.
MIKHAHAM_ZWNJ = _u("0645 06CC") + ZWNJ + _u("062E 0648 0627 0647 0645")
MIKHAHAM_PLAIN = _u("0645 06CC 062E 0648 0627 0647 0645")
# "ketab" (book) with the Persian and with the Arabic kaf.
KETAB_FA = KAF_FA + _u("062A 0627 0628")
KETAB_AR = KAF_AR + _u("062A 0627 0628")


# --- core helpers ----------------------------------------------------------------------


def test_find_span_ignores_a_zwnj_and_returns_the_original_span():
    text = "x " + MIKHAHAM_ZWNJ + " y"
    start = 2
    assert srch.find_folded_span(text, MIKHAHAM_PLAIN) == (start, start + len(MIKHAHAM_ZWNJ))
    # and the other way round
    text2 = "x " + MIKHAHAM_PLAIN + " y"
    assert srch.find_folded_span(text2, MIKHAHAM_ZWNJ) == (2, 2 + len(MIKHAHAM_PLAIN))


def test_find_span_folds_arabic_kaf_and_yeh():
    assert srch.find_folded_span("a " + KETAB_AR, KETAB_FA) == (2, 2 + len(KETAB_AR))
    assert srch.find_folded_span("a " + KETAB_FA, KETAB_AR) == (2, 2 + len(KETAB_FA))
    ali_ar = _u("0639 0644") + YEH_AR
    ali_fa = _u("0639 0644") + YEH_FA
    assert srch.find_folded_span(ali_ar, ali_fa) == (0, 3)


def test_find_span_matches_arabic_indic_digits_to_ascii():
    assert srch.find_folded_span("room " + _u("0661 0662 0663"), "123") == (5, 8)


def test_a_match_swallows_the_vowel_marks_that_belong_to_its_last_letter():
    text = KAF_AR + FATHA + _u("062A 0627 0628") + FATHA + " end"
    span = srch.find_folded_span(text, KETAB_FA)
    assert span == (0, len(text) - len(" end"))


def test_a_zwnj_after_the_match_is_left_alone():
    text = KETAB_FA + ZWNJ + _u("0647 0627")  # "ketab-ha" (books)
    assert srch.find_folded_span(text, KETAB_FA) == (0, len(KETAB_FA))


def test_find_span_start_is_an_original_offset():
    text = KETAB_AR + " " + KETAB_FA
    assert srch.find_folded_span(text, KETAB_FA, 0) == (0, 4)
    assert srch.find_folded_span(text, KETAB_FA, 1) == (5, 9)
    assert srch.find_folded_span(text, KETAB_FA, 6) is None


def test_case_sensitive_find_keeps_case_but_still_folds_persian():
    assert srch.find_folded_span("Hello", "hello") == (0, 5)
    assert srch.find_folded_span("Hello", "hello", casefold=False) is None
    assert srch.find_folded_span(KETAB_AR, KETAB_FA, casefold=False) == (0, 4)


def test_empty_or_noise_only_needles_never_match():
    assert srch.find_folded_span("abc", "") is None
    assert srch.find_folded_span("a" + ZWNJ + "b", ZWNJ) is None


def test_replace_rewrites_only_the_matched_spans_of_the_original():
    text = _u("0639 0644") + YEH_AR + " " + KETAB_AR + " " + MIKHAHAM_ZWNJ + " " + KETAB_FA
    new, count = srch.replace_folded(text, KETAB_FA, "BOOK")
    assert count == 2
    assert new == _u("0639 0644") + YEH_AR + " BOOK " + MIKHAHAM_ZWNJ + " BOOK"
    new, count = srch.replace_folded(text, MIKHAHAM_PLAIN, "WANT")
    assert (new, count) == (text.replace(MIKHAHAM_ZWNJ, "WANT"), 1)


def test_replace_treats_the_replacement_literally():
    new, count = srch.replace_folded("a cat", "CAT", r"\1\g<x>")
    assert (new, count) == ("a \\1\\g<x>", 1)


def test_folded_contains_is_the_filter_the_search_box_uses():
    assert srch.folded_contains(KETAB_AR + " x", KETAB_FA)
    assert srch.folded_contains("Hello World", "WORLD")
    assert not srch.folded_contains("Hello", "")
    assert not srch.folded_contains("Hello", "bye")


def test_the_ascii_fast_path_folds_exactly_like_the_full_pipeline():
    import unicodedata

    everything = "".join(chr(i) for i in range(128))
    full = unicodedata.normalize("NFD", unicodedata.normalize("NFKC", everything))
    full = "".join(ch for ch in full if not srch._is_search_noise(ch))
    full = unicodedata.normalize("NFC", full).translate(srch._FOLD_TABLE)
    assert srch.normalize_search_text(everything) == unicodedata.normalize("NFKC", full.casefold())
    assert srch._fold(everything, False) == unicodedata.normalize("NFKC", full)


def test_folding_by_character_equals_folding_the_whole_text_for_persian():
    text = "x " + MIKHAHAM_ZWNJ + " " + KETAB_AR + FATHA + " " + _u("0661 0662") + " Ab"
    assert srch.fold_with_spans(text)[0] == srch.normalize_search_text(text)


def test_random_texts_keep_the_matching_invariants():
    """For any text and any substring needle: the span folds to the needle's fold, the
    text outside the span is untouched by replace, and replace is idempotent for a
    replacement that cannot match itself."""
    rng = random.Random(266)
    alphabet = ["a", "B", " ", ZWNJ, KAF_AR, KAF_FA, YEH_AR, YEH_FA, FATHA, "1", chr(0x0661),
                _u("0628"), _u("0627"), "e", chr(0x301)]
    for _ in range(400):
        text = "".join(rng.choice(alphabet) for _ in range(rng.randint(1, 14)))
        i = rng.randrange(len(text))
        j = rng.randint(i + 1, len(text))
        needle = text[i:j]
        folded_needle, _s, _e = srch.fold_with_spans(needle)
        if not folded_needle:
            assert srch.find_folded_span(text, needle) is None
            continue
        span = srch.find_folded_span(text, needle)
        assert span is not None, (text, needle)
        s, e = span
        assert srch.fold_with_spans(text[s:e])[0] == folded_needle
        new, count = srch.replace_folded(text, needle, "#")
        assert count >= 1 and new.count("#") == count
        assert new[:s] == text[:s]
        again, count2 = srch.replace_folded(new, needle, "#")
        assert (again, count2) == (new, 0)


# --- the viewer ------------------------------------------------------------------------

tk = pytest.importorskip("tkinter")

from app.dialogs import transcript_viewer as tv  # noqa: E402


@pytest.fixture
def root():
    try:
        r = tk.Tk()
    except tk.TclError as e:  # pragma: no cover - no display
        pytest.skip(f"no Tk display: {e}")
    r.withdraw()
    yield r
    r.destroy()


def _viewer(root, tmp_path, texts: list[str]) -> tv.TranscriptViewer:
    path = tmp_path / "fa.json"
    segs: list[dict[str, Any]] = [
        {"start": float(i), "end": i + 1.0, "text": t} for i, t in enumerate(texts)
    ]
    path.write_text(json.dumps(segs), encoding="utf-8")
    viewer = tv.TranscriptViewer(root, str(path))
    viewer.withdraw()
    return viewer


def _close(viewer: tv.TranscriptViewer) -> None:
    viewer._dirty = False
    viewer._on_close()


def test_search_box_finds_persian_spelling_variants(root, tmp_path):
    viewer = _viewer(root, tmp_path, [
        "a " + KETAB_AR, "b " + KETAB_FA, "c " + MIKHAHAM_ZWNJ, "d other",
    ])
    try:
        viewer.search_var.set(KETAB_FA)
        assert viewer.filtered_indices == [0, 1]
        viewer.search_var.set(MIKHAHAM_PLAIN)
        assert viewer.filtered_indices == [2]
        viewer.search_var.set(MIKHAHAM_ZWNJ)
        assert viewer.filtered_indices == [2]
        viewer.search_var.set("OTHER")
        assert viewer.filtered_indices == [3]
        viewer.search_var.set("")
        assert viewer.filtered_indices == [0, 1, 2, 3]
    finally:
        _close(viewer)


def test_search_box_matches_the_speaker_column_too(root, tmp_path):
    path = tmp_path / "sp.json"
    path.write_text(json.dumps([
        {"start": 0.0, "end": 1.0, "text": "x", "speaker": KETAB_AR},
        {"start": 1.0, "end": 2.0, "text": "y", "speaker": "S2"},
    ]), encoding="utf-8")
    viewer = tv.TranscriptViewer(root, str(path))
    viewer.withdraw()
    try:
        viewer.search_var.set(KETAB_FA)
        assert viewer.filtered_indices == [0]
    finally:
        _close(viewer)


def _dialog(viewer: tv.TranscriptViewer) -> tv.FindReplaceDialog:
    dlg = tv.FindReplaceDialog(viewer)
    dlg.withdraw()
    return dlg


def test_find_next_and_replace_current_work_across_zwnj_and_kaf(root, tmp_path, monkeypatch):
    monkeypatch.setattr(tv.messagebox, "showinfo", lambda *a, **k: None)
    first = "q " + MIKHAHAM_ZWNJ + " " + KETAB_AR
    viewer = _viewer(root, tmp_path, [first, KETAB_FA])
    dlg = _dialog(viewer)
    try:
        dlg.find_var.set(KETAB_FA)
        dlg.replace_var.set("BOOK")
        assert dlg.find_next()
        assert (dlg.last_match_idx, dlg.last_match_pos) == (0, len(first) - len(KETAB_AR))
        dlg.replace_current()
        # Only the matched Arabic-kaf word changed; the half-space word is intact.
        assert viewer.segments[0]["text"] == "q " + MIKHAHAM_ZWNJ + " BOOK"
        assert (dlg.last_match_idx, dlg.last_match_pos) == (1, 0)
        dlg.replace_current()
        assert viewer.segments[1]["text"] == "BOOK"
    finally:
        dlg.destroy()
        _close(viewer)


def test_replace_all_rewrites_the_original_spans_exactly(root, tmp_path, monkeypatch):
    monkeypatch.setattr(tv.messagebox, "showinfo", lambda *a, **k: None)
    ali = _u("0639 0644") + YEH_AR
    texts = [ali + " " + KETAB_AR, MIKHAHAM_ZWNJ, KETAB_FA + ZWNJ + _u("0647 0627"), "none"]
    viewer = _viewer(root, tmp_path, texts)
    dlg = _dialog(viewer)
    try:
        dlg.find_var.set(KETAB_FA)
        dlg.replace_var.set("BOOK")
        dlg.replace_all()
        assert [s["text"] for s in viewer.segments] == [
            ali + " BOOK", MIKHAHAM_ZWNJ, "BOOK" + ZWNJ + _u("0647 0627"), "none",
        ]
        assert viewer._dirty is True
        # half-space needle written without it finds the half-space word
        dlg.find_var.set(MIKHAHAM_PLAIN)
        dlg.replace_var.set("WANT")
        dlg.replace_all()
        assert viewer.segments[1]["text"] == "WANT"
    finally:
        dlg.destroy()
        _close(viewer)


def test_match_case_still_separates_latin_case_but_folds_persian(root, tmp_path, monkeypatch):
    monkeypatch.setattr(tv.messagebox, "showinfo", lambda *a, **k: None)
    viewer = _viewer(root, tmp_path, ["Hello hello " + KETAB_AR])
    dlg = _dialog(viewer)
    try:
        dlg.case_var.set(True)
        dlg.find_var.set("hello")
        dlg.replace_var.set("X")
        dlg.replace_all()
        assert viewer.segments[0]["text"] == "Hello X " + KETAB_AR
        dlg.find_var.set(KETAB_FA)
        dlg.replace_all()
        assert viewer.segments[0]["text"] == "Hello X X"
    finally:
        dlg.destroy()
        _close(viewer)


# --- the shared media list -------------------------------------------------------------


def test_the_viewer_pairs_every_media_type_the_watcher_accepts(tmp_path):
    from core import watcher

    for ext in sorted(watcher._MEDIA_EXTENSIONS):
        folder = tmp_path / ext.lstrip(".")
        folder.mkdir()
        media = folder / ("clip" + ext)
        media.write_bytes(b"x")
        (folder / "clip.json").write_text("[]", encoding="utf-8")
        assert tv._find_media_next_to(str(folder / "clip.json")) == str(media), ext
