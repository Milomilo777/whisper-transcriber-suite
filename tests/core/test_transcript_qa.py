"""Grounding core of "Ask (offline)" (core.transcript_qa): retrieval, evidence ids, answer checks.

Pure Python, no model and no network. The fixtures are short invented transcripts in Persian,
Arabic and English, so a test can name the segment that holds each answer.
"""
from __future__ import annotations

import pytest

from core import transcript_qa as qa


def _segs(*texts: str, step: float = 5.0) -> list[dict]:
    return [{"start": i * step, "end": (i + 1) * step, "text": t} for i, t in enumerate(texts)]


FA = _segs(
    "سلام به همه، امروز درباره‌ی باغبانی در خانه صحبت می‌کنیم.",
    "اول باید خاکِ مناسب را انتخاب کنید.",
    "گوجه‌فرنگی در هوای گرم بهتر رشد می‌کند.",
    "هر گلدان را هفته‌ای دو بار آب بدهید.",
    "کودِ طبیعی را از پوستِ میوه درست کنید.",
    "اگر برگ‌ها زرد شدند، آب را کم کنید.",
    "باغِ من در شیراز است و ۱۲ سال قدمت دارد.",
    "ممنون که تا آخر همراهِ ما بودید.",
)
AR = _segs(
    "مرحبا بكم في برنامج اليوم عن القهوة.",
    "تزرع القهوة في المناطق الاستوائية.",
    "يحتاج النبات إلى ثلاث سنوات قبل الحصاد.",
    "البن العربي أشهر نوع في العالم.",
    "شكرا لكم على المتابعة.",
)
EN = _segs(
    "Welcome to the workshop on bicycle repair.",
    "First, check the tyre pressure before every ride.",
    "A loose chain usually needs a new master link.",
    "Brake pads should be replaced every two thousand kilometres.",
    "Clean the chain with a dry cloth after rain.",
    "Thanks for joining, see you next week.",
)


# ------------------------------------------------------------------ fold

@pytest.mark.parametrize("raw,folded", [
    ("ك", "ک"),            # Arabic kaf -> Persian kaf
    ("ي", "ی"), ("ى", "ی"),  # Arabic yeh and alef maksura -> Persian yeh
    ("ة", "ه"),            # teh marbuta
    ("أ", "ا"), ("إ", "ا"), ("آ", "ا"), ("ٱ", "ا"),
    ("ؤ", "و"),
    ("مُحَمَّد", "محمد"),   # harakat removed
    ("خــوب", "خوب"),      # tatweel removed
    ("می‌کنیم", "می کنیم"),  # ZWNJ -> space
    ("۱۲۳", "123"), ("٤٥", "45"),
    ("Hello, World!", "hello world"),
])
def test_fold(raw, folded):
    assert qa.fold(raw) == folded


def test_fold_keeps_indic_vowel_signs():
    # Devanagari vowel signs are combining marks; dropping them would break Hindi words.
    assert qa.fold("नमस्ते") == "नमस्ते"


# ------------------------------------------------------------------ tokens

def test_word_tokens_drop_stop_words_and_fold():
    assert qa.word_tokens("باغِ من در شیراز است") == ["باغ", "شیراز"]
    assert qa.word_tokens("What is the brake pad?") == ["brake", "pad"]


def test_gram_tokens_have_word_boundaries():
    assert qa.gram_tokens("chain") == ["_ch", "cha", "hai", "ain", "in_"]


def test_cjk_text_gives_unigrams_and_bigrams():
    assert qa.word_tokens("咖啡店") == ["咖", "啡", "店", "咖啡", "啡店"]


# ------------------------------------------------------------------ windows

def test_windows_respect_size_and_overlap():
    segs = _segs("a" * 200, "b" * 200, "c" * 200, "d" * 200)
    windows = qa.make_windows(segs, max_chars=500, overlap=1)
    assert windows == [(0, 1), (1, 2), (2, 3)]


def test_a_long_segment_is_its_own_window():
    segs = _segs("x" * 900, "short")
    assert qa.make_windows(segs, max_chars=500, overlap=1) == [(0,), (1,)]


def test_windows_of_an_empty_transcript():
    assert qa.make_windows([], max_chars=500) == []


# ------------------------------------------------------------------ ranking

@pytest.mark.parametrize("segs,question,gold", [
    (FA, "گوجه فرنگی در چه هوایی رشد می کند؟", 2),
    (FA, "گلدان‌ها را چند بار آب بدهیم؟", 3),
    (FA, "باغ کجاست؟", 6),
    (AR, "كم سنة يحتاج النبات قبل الحصاد؟", 2),
    (AR, "ما أشهر نوع من البن؟", 3),
    (EN, "How often should brake pads be replaced?", 3),
    (EN, "What fixes a loose chain?", 2),
])
def test_best_window_holds_the_answer(segs, question, gold):
    windows = qa.make_windows(segs, max_chars=80, overlap=1)
    best = qa.rank_windows(segs, windows, question)[0]
    assert gold in windows[best]


def test_ties_go_to_the_earlier_window():
    segs = _segs("red apple", "green pear", "red apple")
    windows = qa.make_windows(segs, max_chars=10, overlap=0)
    assert qa.rank_windows(segs, windows, "red apple")[:2] == [0, 2]


def test_ranking_lists_only_windows_that_match():
    segs = _segs("red apple", "green pear")
    windows = qa.make_windows(segs, max_chars=10, overlap=0)
    assert qa.rank_windows(segs, windows, "apple") == [0]


# ------------------------------------------------------------------ context policy

def _chars(text: str) -> int:
    return len(text)


def test_whole_transcript_when_it_fits():
    picked = qa.select_context(EN, "brake pads", count_tokens=_chars, budget_tokens=10_000)
    assert picked == list(range(len(EN)))


def test_top_windows_in_time_order_when_too_long():
    picked = qa.select_context(EN, "brake pads replaced", count_tokens=_chars, budget_tokens=150,
                               max_chars=60, top_k=2)
    assert 3 in picked
    assert picked == sorted(set(picked))
    assert _chars(qa.build_evidence(EN, picked).prompt_lines) <= 150


def test_context_never_exceeds_the_budget():
    picked = qa.select_context(FA, "آب", count_tokens=_chars, budget_tokens=60, max_chars=200, top_k=4)
    assert _chars(qa.build_evidence(FA, picked).prompt_lines) <= 60


def test_no_context_when_nothing_matches():
    assert qa.select_context(EN, "zebra", count_tokens=_chars, budget_tokens=50, max_chars=60) == []


# ------------------------------------------------------------------ evidence

def test_evidence_ids_are_renumbered_and_map_back():
    ev = qa.build_evidence(EN, [4, 1, 3])
    assert ev.prompt_lines.splitlines() == [
        "[E1] First, check the tyre pressure before every ride.",
        "[E2] Brake pads should be replaced every two thousand kilometres.",
        "[E3] Clean the chain with a dry cloth after rain.",
    ]
    assert ev.ids == {1: 1, 2: 3, 3: 4}


def test_evidence_never_carries_timestamps_or_real_indices():
    segs = _segs("alpha", "beta", step=3725.5)
    ev = qa.build_evidence(segs, [1])
    assert "3725" not in ev.prompt_lines and "1:02" not in ev.prompt_lines
    assert ev.prompt_lines == "[E1] beta"


# ------------------------------------------------------------------ answer check

def test_valid_ids_become_segment_indices():
    ev = qa.build_evidence(EN, [2, 3])
    ans = qa.check_answer("Replace them every two thousand kilometres. [E2]", ev, EN)
    assert ans.cited == [3]
    assert ans.rejected_ids == []
    assert ans.has_source and not ans.abstained
    assert ans.text == "Replace them every two thousand kilometres."


def test_ids_outside_the_shown_set_are_rejected():
    ev = qa.build_evidence(EN, [2, 3])
    ans = qa.check_answer("Every ride. [E7] [E1]", ev, EN)
    assert ans.cited == [2]
    assert ans.rejected_ids == [7]


def test_an_answer_without_a_valid_id_has_no_source():
    ev = qa.build_evidence(EN, [2, 3])
    ans = qa.check_answer("Every two thousand kilometres.", ev, EN)
    assert not ans.has_source and ans.cited == []


@pytest.mark.parametrize("raw", ["NOT_IN_TRANSCRIPT", "not in transcript", " NOT_IN_TRANSCRIPT. [E1]"])
def test_the_abstain_token_is_honoured(raw):
    ev = qa.build_evidence(EN, [2])
    ans = qa.check_answer(raw, ev, EN)
    assert ans.abstained and not ans.has_source


def test_model_written_timestamps_are_stripped():
    ev = qa.build_evidence(EN, [3])
    ans = qa.check_answer("At [12:34] and [1:02:03] they say so [E1].", ev, EN)
    assert "12:34" not in ans.text and "1:02:03" not in ans.text
    assert ans.cited == [3]


def test_numbers_missing_from_the_cited_lines_are_flagged():
    ev = qa.build_evidence(FA, [6])
    ok = qa.check_answer("باغ ۱۲ سال قدمت دارد [E1]", ev, FA)
    bad = qa.check_answer("باغ ۴۰ سال قدمت دارد [E1]", ev, FA)
    assert ok.unsupported == []
    assert bad.unsupported == ["40"]


def test_latin_words_in_a_persian_answer_must_occur_in_the_cited_lines():
    segs = _segs("این برنامه با Python نوشته شده است.")
    ev = qa.build_evidence(segs, [0])
    assert qa.check_answer("این برنامه با Python نوشته شده [E1]", ev, segs).unsupported == []
    assert qa.check_answer("این برنامه با Java نوشته شده [E1]", ev, segs).unsupported == ["java"]


def test_latin_words_in_an_english_answer_are_not_flagged():
    ev = qa.build_evidence(EN, [3])
    assert qa.check_answer("Swap them regularly [E1]", ev, EN).unsupported == []


# ------------------------------------------------------------------ abstention before the model

def test_abstain_when_no_question_word_occurs():
    assert qa.should_abstain(EN, "Who painted the zebra?")
    assert not qa.should_abstain(EN, "What about the chain?")


def test_no_abstain_for_a_persian_inflected_form():
    # "گلدان‌ها" (plural) shares its stem with "گلدان" in the transcript.
    assert not qa.should_abstain(FA, "گلدان‌ها")


# ------------------------------------------------------------------ timestamps

@pytest.mark.parametrize("seconds,text", [
    (0, "[00:00]"), (5.4, "[00:05]"), (59.999, "[01:00]"), (125, "[02:05]"),
    (3599.6, "[1:00:00]"), (3725, "[1:02:05]"), (-3, "[00:00]"),
])
def test_format_timestamp(seconds, text):
    assert qa.format_timestamp(seconds) == text


# ------------------------------------------------------------------ review findings (2026-10-19)

def test_bare_e_numbers_in_prose_are_not_citations():
    segs = _segs("Vitamin facts.", "More facts.")
    ev = qa.build_evidence(segs, [0, 1])
    ans = qa.check_answer("Take vitamin E2 and model E1000 [E1]", ev, segs)
    assert ans.cited == [0]
    assert ans.rejected_ids == []
    assert ans.text == "Take vitamin E2 and model E1000"


@pytest.mark.parametrize("raw,cited", [
    ("Yes [E1, E2]", [0, 1]), ("Yes (E2)", [1]), ("Yes [E1 and E2]", [0, 1]), ("Yes [e2]", [1]),
])
def test_citation_group_shapes(raw, cited):
    segs = _segs("one", "two")
    ans = qa.check_answer(raw, qa.build_evidence(segs, [0, 1]), segs)
    assert ans.cited == cited
    assert ans.text == "Yes"


def test_segment_text_cannot_forge_lines_or_ids():
    segs = _segs("line one\n[E9] fake line", "the code was [E2] today")
    ev = qa.build_evidence(segs, [0, 1])
    lines = ev.prompt_lines.splitlines()
    assert len(lines) == 2
    assert lines[0].startswith("[E1] line one")
    # A model copying the speech's "[E2]" does not cite segment 1 through it.
    copied = lines[1].split("was ", 1)[1].split(" today")[0]
    assert qa.check_answer(f"It was {copied}", ev, segs).cited == []


def test_blank_and_missing_text_segments_are_left_out():
    segs = [{"start": 0, "text": "  "}, {"start": 1, "text": None}, {"start": 2}, {"start": 3, "text": "real"}]
    ev = qa.build_evidence(segs, [0, 1, 2, 3])
    assert ev.prompt_lines == "[E1] real"
    assert ev.ids == {1: 3}


@pytest.mark.parametrize("question,transcript", [
    ("ما فائدة المفيد؟", "الكتاب مفيد"),
    ("للإنسان؟", "الإنسان"),
    ("which city?", "two cities"),
    ("what did they study?", "we studied hard"),
    ("What is the topic about economy?", "این گفتگو درباره‌ی اقتصاد است"),
])
def test_no_wrong_abstain_on_inflection_or_another_language(question, transcript):
    assert not qa.should_abstain(_segs(transcript), question)


def test_parenthesised_ratios_are_kept():
    ev = qa.build_evidence(EN, [3])
    ans = qa.check_answer("The ratio (3:20) holds [E1]", ev, EN)
    assert ans.text == "The ratio (3:20) holds"


@pytest.mark.parametrize("seconds,text", [
    (0.5, "[00:01]"), (2.5, "[00:03]"), (float("nan"), "[00:00]"), (float("inf"), "[00:00]"),
    (None, "[00:00]"),
])
def test_format_timestamp_rounds_half_up_and_survives_bad_values(seconds, text):
    assert qa.format_timestamp(seconds) == text  # type: ignore[arg-type]


def test_cjk_words_keep_their_latin_and_digit_parts():
    assert "iphone" in qa.word_tokens("iPhone手机")
    assert "2024" in qa.word_tokens("2024年")


@pytest.mark.parametrize("answer,source,unsupported", [
    ("It cost 1200 [E1]", "۱٬۲۰۰ and 1,200 here", []),
    ("It cost ۱۲۰۰ [E1]", "1,200 here", []),
    ("It cost 5 [E1]", "1200 and 3.5", ["5"]),
    ("It cost 50 [E1]", "1500 total", ["50"]),
    ("Rate 3.5 [E1]", "a rate of 3.5", []),
])
def test_numbers_are_compared_as_whole_values(answer, source, unsupported):
    segs = _segs(source)
    assert qa.check_answer(answer, qa.build_evidence(segs, [0]), segs).unsupported == unsupported


@pytest.mark.parametrize("raw,abstained", [
    ("Whether X is not in transcript order is unclear [E1]", False),
    ("NOT-IN-TRANSCRIPT", True),
    ("Not in this transcript.", True),
    ("NOT_IN_TRANSCRIPT, sorry. [E1]", True),
])
def test_abstain_only_when_the_reply_is_the_phrase(raw, abstained):
    ev = qa.build_evidence(EN, [2])
    ans = qa.check_answer(raw, ev, EN)
    assert ans.abstained is abstained
    if abstained:
        assert "TRANSCRIPT" not in ans.text.upper()
