"""Word counts for spaced and unspaced scripts (core.text_metrics) and the callers that use them."""
from core import chapters as ch
from core import stats
from core.llm import LLMConfig, LLMRunner
from core.text_metrics import count_words


def _s(*codes: int) -> str:
    # Built from code points so the source holds no combining marks or invisible joiners.
    return "".join(map(chr, codes))


# "Hello, my name is Jules" in Thai: 21 code points, 7 of them marks (category M) -> 14 graphemes.
_THAI_HELLO = _s(0x0E2A, 0x0E27, 0x0E31, 0x0E2A, 0x0E14, 0x0E35, 0x0E04, 0x0E23, 0x0E31, 0x0E1A, 0x0E1C,
                 0x0E21, 0x0E0A, 0x0E37, 0x0E48, 0x0E2D, 0x0E08, 0x0E39, 0x0E25, 0x0E2A, 0x0E4C)
# Persian "mi-ravad" with a zero-width non-joiner after the prefix: one word.
_PERSIAN_ZWNJ = _s(0x0645, 0x06CC, 0x200C, 0x0631, 0x0648, 0x062F)


def test_cjk_and_kana_count_one_word_per_character():
    assert count_words("これはテストです") == 8
    assert count_words("測試文本") == 4


def test_cjk_punctuation_is_not_a_word():
    assert count_words("これはテストです。") == 8
    assert count_words("你好" + chr(0xFF0C) + "世界" + chr(0xFF01)) == 4  # fullwidth comma and exclamation mark
    assert count_words("abc - def") == 3  # ASCII keeps the old whitespace count


def test_mixed_spaced_and_unspaced_text():
    assert count_words("This is a テスト") == 6


def test_thai_counts_graphemes_divided_by_four():
    assert count_words(_THAI_HELLO) == 14 // 4


def test_thai_vowel_signs_with_combining_class_zero_are_not_graphemes():
    # U+0E34 and U+0E35 are category Mn with combining class 0: 2 letters + 2 marks per word.
    assert count_words(_s(0x0E01, 0x0E34, 0x0E19, 0x0E35) * 4) == 8 // 4


def test_spaced_scripts_split_on_whitespace():
    assert count_words("이것은 테스트 입니다") == 3
    assert count_words(_PERSIAN_ZWNJ) == 1


def test_empty_text_counts_zero():
    assert count_words("") == 0
    assert count_words(None) == 0


def test_heuristic_title_cuts_cjk_by_characters_and_english_by_words():
    b = ch.ChapterBoundary(start=0.0, end=5.0, segment_start=0, segment_end=0)
    cjk = "今天我们来讨论一下人工智能在医疗领域的应用以及未来的发展趋势和挑战还有很多很多内容"
    title_cjk = ch.heuristic_title([{"start": 0.0, "end": 5.0, "text": cjk}], b)
    assert title_cjk.endswith("…")
    assert len(title_cjk) <= 31

    english = ("This is a really long english title sentence that should be truncated cleanly by the "
               "max words variable limits rather than max characters limits.")
    title_en = ch.heuristic_title([{"start": 0.0, "end": 5.0, "text": english}], b, max_words=10)
    assert title_en.endswith("…")
    assert len(title_en.split()) == 10


def test_history_word_count_counts_japanese_characters():
    segs = [{"text": "これはテストです"}, {"text": "もう一つのテスト"}]
    assert stats.count_words_in_segments(segs) == 16


def test_translate_token_budget_grows_with_cjk_text(monkeypatch):
    captured = {}

    def fake_chat(self, messages, **kwargs):
        captured.update(kwargs)
        return "fake"

    monkeypatch.setattr(LLMRunner, "_chat", fake_chat)
    LLMRunner(LLMConfig(model_path="dummy")).translate("测" * 400)
    assert captured.get("max_tokens") == 600
