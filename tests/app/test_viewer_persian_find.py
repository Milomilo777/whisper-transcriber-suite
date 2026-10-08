"""The viewer's search box and Find/Replace fold Persian spelling like the global search.

ZWNJ (the Persian half-space), Arabic kaf/yeh versus the Persian letters, vowel marks and
Arabic-Indic digits must not hide a match, and Replace must still rewrite the ORIGINAL text
exactly where it matched: folding is for matching only. Persian text is built from code
points so the file stays ASCII.
"""
from __future__ import annotations

import json
import random
import unicodedata
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


def test_an_empty_needle_never_matches():
    assert srch.find_folded_span("abc", "") is None
    assert not srch.folded_contains("abc", "")
    assert srch.replace_folded("abc", "", "x") == ("abc", 0)


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
    """For any text and any substring needle: the span folds to the needle's fold (or,
    for a needle edged by a dropped character, is that needle literally), the text before
    the span is untouched by replace, and replace is idempotent for a replacement that
    cannot match itself."""
    rng = random.Random(266)
    alphabet = ["a", "B", " ", ZWNJ, KAF_AR, KAF_FA, YEH_AR, YEH_FA, FATHA, "1", chr(0x0661),
                _u("0628"), _u("0627"), "e", chr(0x301)]
    for _ in range(400):
        text = "".join(rng.choice(alphabet) for _ in range(rng.randint(1, 14)))
        i = rng.randrange(len(text))
        j = rng.randint(i + 1, len(text))
        needle = text[i:j]
        folded_needle, _s, _e = srch.fold_with_spans(needle)
        span = srch.find_folded_span(text, needle)
        assert span is not None, (text, needle)
        s, e = span
        assert srch.fold_with_spans(text[s:e])[0] == folded_needle, (text, needle, span)
        prefix, core, suffix = srch._split_edges(unicodedata.normalize("NFC", needle), True)
        assert text[s:e].startswith(prefix) and text[s:e].endswith(suffix), (text, needle, span)
        if not core:
            assert text[s:e].casefold() == needle.casefold(), (text, needle, span)
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


def test_match_case_is_an_exact_mode_with_no_folding(root, tmp_path, monkeypatch):
    monkeypatch.setattr(tv.messagebox, "showinfo", lambda *a, **k: None)
    viewer = _viewer(root, tmp_path, ["Hello hello " + KETAB_AR + " " + MIKHAHAM_ZWNJ])
    dlg = _dialog(viewer)
    try:
        dlg.case_var.set(True)
        dlg.find_var.set("hello")
        dlg.replace_var.set("X")
        dlg.replace_all()
        assert viewer.segments[0]["text"] == "Hello X " + KETAB_AR + " " + MIKHAHAM_ZWNJ
        # Persian kaf and the half-space are literal now.
        dlg.find_var.set(KETAB_FA)
        dlg.replace_all()
        dlg.find_var.set(MIKHAHAM_PLAIN)
        dlg.replace_all()
        assert viewer.segments[0]["text"] == "Hello X " + KETAB_AR + " " + MIKHAHAM_ZWNJ
        dlg.find_var.set(KETAB_AR)
        dlg.replace_all()
        assert viewer.segments[0]["text"] == "Hello X X " + MIKHAHAM_ZWNJ
        # Find next follows the same exact rule.
        dlg.find_var.set(MIKHAHAM_PLAIN)
        assert dlg.find_next() is False
        dlg.find_var.set(MIKHAHAM_ZWNJ)
        assert dlg.find_next() is True
        # Switching Match case off brings the folding back.
        dlg.case_var.set(False)
        dlg.find_var.set(MIKHAHAM_PLAIN)
        dlg.replace_var.set("WANT")
        dlg.replace_all()
        assert viewer.segments[0]["text"] == "Hello X X WANT"
    finally:
        dlg.destroy()
        _close(viewer)


def test_the_dialog_keeps_an_edge_half_space_and_replaces_a_zwnj_only_needle(root, tmp_path, monkeypatch):
    monkeypatch.setattr(tv.messagebox, "showinfo", lambda *a, **k: None)
    mi = _u("0645 06CC")
    z = _u("0632")
    texts = [mi + ZWNJ + _u("0631 0648 0645") + " " + mi + ZWNJ + z + " " + mi + z, "a" + ZWNJ + "b"]
    viewer = _viewer(root, tmp_path, texts)
    dlg = _dialog(viewer)
    try:
        dlg.find_var.set(mi + ZWNJ)
        dlg.replace_var.set("X")
        dlg.replace_all()
        assert viewer.segments[0]["text"] == "X" + _u("0631 0648 0645") + " X" + z + " " + mi + z
        dlg.find_var.set(ZWNJ)
        dlg.replace_var.set(" ")
        dlg.replace_all()
        assert viewer.segments[1]["text"] == "a b"
    finally:
        dlg.destroy()
        _close(viewer)


def test_search_box_with_only_a_zwnj_lists_the_rows_that_have_one(root, tmp_path):
    viewer = _viewer(root, tmp_path, ["a" + ZWNJ + "b", "ab", KAF_AR + FATHA])
    try:
        viewer.search_var.set(ZWNJ)
        assert viewer.filtered_indices == [0]
        viewer.search_var.set(FATHA)
        assert viewer.filtered_indices == [2]
    finally:
        _close(viewer)


# --- needles made of (or edged by) characters that fold to nothing ---------------------


def test_a_needle_of_only_foldable_away_characters_matches_literally():
    assert srch.find_folded_span("a" + ZWNJ + "b", ZWNJ) == (1, 2)
    assert srch.replace_folded("a" + ZWNJ + "b" + ZWNJ, ZWNJ, " ") == ("a b ", 2)
    assert srch.replace_folded("ab", ZWNJ, " ") == ("ab", 0)
    tatweel = chr(0x0640)
    assert srch.replace_folded(KAF_AR + tatweel * 2 + _u("062A 0627 0628"), tatweel, "") == (
        KAF_AR + _u("062A 0627 0628"), 2)
    word = KAF_AR + FATHA + _u("062A") + FATHA
    assert srch.replace_folded(word, FATHA, "") == (KAF_AR + _u("062A"), 2)
    assert srch.replace_folded("e" + chr(0x301), chr(0x301), "!") == ("e!", 1)


def test_an_edge_zwnj_is_part_of_the_match_not_dropped():
    mi = _u("0645 06CC")
    text = mi + ZWNJ + _u("0631 0648 0645") + " " + mi + ZWNJ + _u("0632") + " " + mi + _u("0632")
    new, count = srch.replace_folded(text, mi + ZWNJ, "X")
    assert count == 2
    assert new == "X" + _u("0631 0648 0645") + " X" + _u("0632") + " " + mi + _u("0632")
    # leading half-space: the suffix "-ha" only where the half-space really is
    ha = _u("0647 0627")
    two = KETAB_FA + ZWNJ + ha + " " + KETAB_FA + ha
    assert srch.replace_folded(two, ZWNJ + ha, "#") == (KETAB_FA + "# " + KETAB_FA + ha, 1)


def test_an_edge_noise_needle_still_ignores_case_unless_asked():
    assert srch.find_folded_span("xA" + ZWNJ, "a" + ZWNJ) == (1, 3)
    assert srch.find_folded_span("xA" + ZWNJ, "a" + ZWNJ, casefold=False) is None


def test_the_filter_treats_such_needles_literally_too():
    assert srch.folded_contains("a" + ZWNJ + "b", ZWNJ)
    assert not srch.folded_contains("ab", ZWNJ)
    assert srch.folded_contains(KAF_AR + FATHA, FATHA)
    assert not srch.folded_contains(KAF_AR, FATHA)


def test_zwnj_in_the_middle_of_a_needle_is_still_forgiving():
    assert srch.find_folded_span("x " + MIKHAHAM_PLAIN, MIKHAHAM_ZWNJ) == (2, 2 + len(MIKHAHAM_PLAIN))


def test_an_edge_noise_needle_still_folds_its_core():
    """The core of the needle folds as usual; only the edge characters are literal."""
    ar_mi = _u("0645 064A") + ZWNJ  # Arabic yeh + half-space
    assert srch.find_folded_span(_u("0645 06CC") + ZWNJ + _u("0631 0648 0645"), ar_mi) == (0, 3)
    assert srch.find_folded_span(ZWNJ + KAF_FA, ZWNJ + KAF_AR) == (0, 2)
    assert srch.find_folded_span(ZWNJ + _u("06F1 06F2"), ZWNJ + "12") == (0, 3)
    assert srch.find_folded_span(KETAB_FA + FATHA, KETAB_AR + FATHA) == (0, 5)
    # a mark that follows another mark is not adjacent to the letter: no match
    assert srch.find_folded_span(KETAB_FA + chr(0x0651) + FATHA, KETAB_AR + FATHA) is None


def test_an_nfd_paste_finds_precomposed_text():
    nfd = "f" + "e" + chr(0x301)
    assert srch.find_folded_span("caf" + chr(0xE9), nfd) == (2, 4)
    assert srch.replace_folded("caf" + chr(0xE9) + " cafe", nfd, "X") == ("caX caX", 2)
    # and the other way round
    assert srch.find_folded_span("cafe" + chr(0x301), "caf" + chr(0xE9)) == (0, 5)


def test_the_needle_as_typed_still_matches_when_nfc_would_change_it():
    marks = chr(0x0323) + chr(0x0651)  # NFC reorders these two combining marks
    assert srch.find_folded_span("a" + marks, marks) == (1, 3)
    jamo = "".join(chr(c) for c in (0x1112, 0x1161, 0x11AB))  # decomposed Hangul
    assert srch.find_folded_span(jamo, jamo[:2]) == (0, 2)
    # a precomposed syllable in the text is found by its decomposed needle too
    assert srch.find_folded_span(chr(0xD55C), jamo) == (0, 1)
    assert srch.folded_contains(chr(0xD55C), jamo)  # the search-box filter agrees
    assert srch.folded_contains("caf" + chr(0xE9), "fe" + chr(0x301))


def test_a_suffix_may_follow_the_letters_own_hamza_mark():
    alef_hamza = _u("0627 0654")  # alef + combining hamza, decomposed
    assert srch.find_folded_span("e" + alef_hamza + ZWNJ + "e", _u("0627") + ZWNJ) == (1, 4)


def test_edge_characters_must_be_literally_adjacent_to_the_core():
    mi = _u("0645 06CC")
    assert srch.find_folded_span(mi + " " + _u("0631"), mi + ZWNJ) is None
    assert srch.find_folded_span(mi + _u("0632"), mi + ZWNJ) is None
    ha = _u("0647 0627")
    assert srch.find_folded_span(KETAB_FA + ha, ZWNJ + ha) is None
    # the second occurrence is the adjacent one
    assert srch.find_folded_span(mi + _u("0632") + " " + mi + ZWNJ, mi + ZWNJ) == (4, 7)
    assert srch.find_folded_span("x" + mi + ZWNJ, mi + ZWNJ, 2) is None  # start inside the match
    assert srch.replace_folded(ZWNJ + KAF_AR + " " + ZWNJ + KAF_FA, ZWNJ + KAF_FA, "#") == ("# #", 2)
    assert srch.folded_contains(_u("0645 06CC") + ZWNJ, _u("0645 064A") + ZWNJ)
    assert not srch.folded_contains(_u("0645 06CC 0632"), _u("0645 064A") + ZWNJ)


# --- a match must not start or end inside an expanded character ------------------------

FI = chr(0xFB01)  # the "fi" ligature
LAM_ALEF = chr(0xFEFB)  # lam + alef ligature, common in PDF-pasted Persian
SHARP_S = chr(0x00DF)
ALLAH = chr(0xFDF2)


def test_a_match_never_splits_a_compatibility_expansion():
    assert srch.replace_folded(FI + "sh", "f", "g") == (FI + "sh", 0)
    assert srch.replace_folded(FI + "sh", "i", "g") == (FI + "sh", 0)
    assert srch.replace_folded(FI + "sh", "fi", "X") == ("Xsh", 1)
    assert srch.replace_folded(FI + "sh", "sh", "Y") == (FI + "Y", 1)
    assert srch.replace_folded(LAM_ALEF, _u("0627"), "x") == (LAM_ALEF, 0)
    assert srch.replace_folded(LAM_ALEF, _u("0644"), "x") == (LAM_ALEF, 0)
    assert srch.replace_folded(LAM_ALEF, _u("0644 0627"), "x") == ("x", 1)
    assert srch.replace_folded("a" + SHARP_S + "b", "s", "x") == ("a" + SHARP_S + "b", 0)
    assert srch.replace_folded("a" + SHARP_S + "b", "ss", "x") == ("axb", 1)
    assert srch.replace_folded(ALLAH, _u("0627 0644"), "x") == (ALLAH, 0)
    assert srch.find_folded_span(FI + "sh", "f") is None
    # an unsplit match later in the same text is still found
    assert srch.replace_folded(FI + " f", "f", "g") == (FI + " g", 1)


def test_random_compat_texts_only_match_what_they_refold_to():
    rng = random.Random(267)
    alphabet = ["a", "f", "i", "s", " ", ZWNJ, FI, LAM_ALEF, SHARP_S, ALLAH, KAF_AR, KAF_FA,
                _u("0644"), _u("0627"), FATHA]
    seen = 0
    for _ in range(800):
        text = "".join(rng.choice(alphabet) for _ in range(rng.randint(1, 12)))
        needle = "".join(rng.choice(alphabet) for _ in range(rng.randint(1, 3)))
        span = srch.find_folded_span(text, needle)
        if span is None:
            continue
        seen += 1
        s, e = span
        edge_noise = not srch.fold_with_spans(needle[:1])[0] or not srch.fold_with_spans(needle[-1:])[0]
        if edge_noise:
            assert text[s:e].casefold() == needle.casefold(), (text, needle, span)
        else:
            assert srch.fold_with_spans(text[s:e])[0] == srch.fold_with_spans(needle)[0], (text, needle, span)
    assert seen > 50


# --- exact mode ------------------------------------------------------------------------


def test_exact_mode_is_a_plain_literal_search():
    assert srch.find_folded_span("a" + KETAB_AR, KETAB_FA, exact=True) is None
    assert srch.find_folded_span("a" + KETAB_AR, KETAB_AR, exact=True) == (1, 5)
    assert srch.find_folded_span("Hello", "hello", exact=True) is None
    assert srch.find_folded_span("x" + MIKHAHAM_ZWNJ, MIKHAHAM_PLAIN, exact=True) is None
    assert srch.replace_folded("ab" + ZWNJ + "ab", "ab", "#", exact=True) == ("#" + ZWNJ + "#", 2)
    assert srch.replace_folded(FI + "sh", "f", "g", exact=True) == (FI + "sh", 0)


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
