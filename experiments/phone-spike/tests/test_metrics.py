import pytest
from metrics.metrics import normalize_fa, wer, cer, words_to_digits
import string
from metrics import cer_edits, edit_distance, repeated_ngrams, wer_edits, word_error_counts

def test_normalize_fa():
    # basic tests
    assert normalize_fa("ك") == "ک"
    assert normalize_fa("ي") == "ی"
    assert normalize_fa("ى") == "ی"
    # harakat
    assert normalize_fa("مُحَمَّد") == "محمد"
    assert normalize_fa("مـحمـد") == "محمد"
    # zwnj deletion
    assert normalize_fa("می‌رود") == "میرود"
    assert normalize_fa("می‌رود", zwnj_to_space=True) == "می رود"
    # digits
    assert normalize_fa("۱۲۳") == "123"
    assert normalize_fa("١٢٣") == "123"
    # punctuation
    assert normalize_fa("سلام، خوبی؟") == "سلام خوبی"
    # collapse whitespace
    assert normalize_fa("  سلام   خوبی  ") == "سلام خوبی"

def test_words_to_digits():
    assert words_to_digits("یک") == "1"
    assert words_to_digits("صد و بیست و سه") == "123"
    assert words_to_digits("یکصد و دو") == "102"
    assert words_to_digits("سه هزار و چهارصد و پنجاه و شش") == "3456"
    assert words_to_digits("دوازده") == "12"
    assert words_to_digits("هزار و یک") == "1001"
    assert words_to_digits("من سه هزار سیب دارم") == "من 3000 سیب دارم"

def test_wer_cer():
    ref = "من یک کتاب دارم"
    hyp = "من دو کتاب دارم"
    # norm: من 1 کتاب دارم vs من 2 کتاب دارم (1 substitution)
    assert wer(ref, hyp) == 1/4
    # chars norm ref: م ن 1 ک ت ا ب د ا ر م (11)
    # chars norm hyp: م ن 2 ک ت ا ب د ا ر م (11)
    # 1 sub
    assert cer(ref, hyp) == 1/11
    
    # insertion
    assert wer("من کتاب دارم", "من یک کتاب دارم") == 1/3
    # deletion
    assert wer("من یک کتاب دارم", "من کتاب دارم") == 1/4

    with pytest.raises(ValueError):
        wer("", "test")

def test_normalize_fa_with_digits_mixed():
    assert normalize_fa("سه هزار و چهارصد و پنجاه و شش") == "3456"


@pytest.mark.parametrize("mark", [chr(i) for i in range(0x64b, 0x660)] + ["\u0670", "\u0640"])
def test_every_harakat_and_tatweel(mark):
    assert normalize_fa("ب" + mark + "ب") == "بب"


@pytest.mark.parametrize("punctuation", list(string.punctuation + "،؛؟«»"))
def test_every_punctuation(punctuation):
    assert normalize_fa("کتاب" + punctuation + "خوب") == "کتاب خوب"


@pytest.mark.parametrize("digit", range(10))
def test_every_digit_in_both_alphabets(digit):
    assert normalize_fa(chr(0x6f0 + digit)) == str(digit)
    assert normalize_fa(chr(0x660 + digit)) == str(digit)


def test_nfc_latin_case_and_all_whitespace():
    assert normalize_fa("  E\u0301COLE\tABC\n\rسلام\u00a0\u2003خوب  ") == "école abc سلام خوب"
    assert normalize_fa(None) == ""
    assert normalize_fa("") == ""


@pytest.mark.parametrize("word,value", [
    ("صفر", 0), ("یک", 1), ("دو", 2), ("سه", 3), ("چهار", 4), ("پنج", 5),
    ("شش", 6), ("هفت", 7), ("هشت", 8), ("نه", 9), ("ده", 10),
    ("یازده", 11), ("دوازده", 12), ("سیزده", 13), ("چهارده", 14), ("پانزده", 15),
    ("شانزده", 16), ("هفده", 17), ("هجده", 18), ("نوزده", 19),
    ("بیست", 20), ("سی", 30), ("چهل", 40), ("پنجاه", 50), ("شصت", 60),
    ("هفتاد", 70), ("هشتاد", 80), ("نود", 90), ("صد", 100), ("یکصد", 100),
    ("دویست", 200), ("سیصد", 300), ("چهارصد", 400), ("پانصد", 500),
    ("ششصد", 600), ("هفتصد", 700), ("هشتصد", 800), ("نهصد", 900),
    ("نود و نه", 99), ("صد و یک", 101), ("یک صد و دو", 102),
    ("نهصد و نود و نه", 999), ("هزار", 1000), ("یک هزار و یک", 1001),
    ("دو هزار سیصد و هفت", 2307), ("پنج هزار و شصت", 5060),
    ("نه هزار و نهصد و نود و نه", 9999), ("بیست‌وسه", 23),
    ("بیستوسه", 23), ("سه‌هزاروچهارصد‌وپنجاه‌وشش", 3456),
])
def test_number_grammar(word, value):
    assert words_to_digits(word) == str(value)
    assert normalize_fa(word) == str(value)
    assert wer(word, str(value)) == 0
    assert cer(str(value), word) == 0


def test_numbers_do_not_consume_unrelated_words_or_lists():
    assert words_to_digits("من سیب و دوست دارم") == "من سیب و دوست دارم"
    assert words_to_digits("یک دو سه") == "1 2 3"
    assert words_to_digits("دو و سه کتاب") == "2 و 3 کتاب"
    assert words_to_digits("ده هزار") == "10000"
    assert words_to_digits("صد و کتاب") == "100 و کتاب"
    assert normalize_fa("يک كتاب و بيست‌وسه سیب") == "1 کتاب و 23 سیب"


@pytest.mark.parametrize("metric", [wer, cer, wer_edits, cer_edits])
@pytest.mark.parametrize("empty", ["", "  \t\n", "،!؛", "\u200c\u0640\u064b"])
def test_empty_normalized_reference_raises(metric, empty):
    with pytest.raises(ValueError, match="reference"):
        metric(empty, "کتاب")


@pytest.mark.parametrize("ref,hyp,w,c", [
    ("ab cd", "ab ef", 1/2, 2/4),
    ("ab cd", "ab x cd", 1/2, 1/4),
    ("ab cd", "ab", 1/2, 2/4),
    ("ab cd", "", 1, 1),
    ("a", "a b c", 2, 2),
    ("ab cd", "abcd", 1, 0),
    ("می‌رود ۲۳", "میرود بیست و سه", 0, 0),
    ("١٢٣", "۱۲۳", 0, 0),
    ("kitten", "sitting", 1, 3/6),
])
def test_hand_computed_word_and_character_edits(ref, hyp, w, c):
    assert wer(ref, hyp) == w
    assert cer(ref, hyp) == c
    we, wn = wer_edits(ref, hyp)
    ce, cn = cer_edits(ref, hyp)
    assert we / wn == w
    assert ce / cn == c


def test_zwnj_sensitivity_changes_word_denominator():
    assert wer_edits("می‌رود خانه", "میرود خانه") == (0, 2)
    assert wer_edits("می‌رود خانه", "میرود خانه", True) == (2, 3)
    assert wer("می‌رود خانه", "میرود خانه", True) == 2/3
    assert cer("می‌رود خانه", "میرود خانه", True) == 0


def test_edit_distance_and_long_form_diagnostics():
    assert edit_distance("", "abc") == 3
    assert edit_distance("kitten", "sitting") == 3
    assert repeated_ngrams("a b c a b c a b c") == 4
    assert repeated_ngrams("a b") == 0
    assert word_error_counts("a b c", "a c") == {
        "edits": 1, "substitutions": 0, "deletions": 1, "insertions": 0}


@pytest.mark.parametrize("punctuation", list("\u2026\u2013\u2014\u2018\u2019\u201a\u201b\u201c\u201d\u066a"))
def test_unicode_punctuation_does_not_glue_words(punctuation):
    assert normalize_fa("کتاب" + punctuation + "خوب") == "کتاب خوب"
    assert wer("کتاب" + punctuation + "خوب", "کتاب خوب") == 0
    assert cer("کتاب خوب", "کتاب" + punctuation + "خوب") == 0


@pytest.mark.parametrize("mark", ["\u200e", "\u200f", "\ufeff"])
def test_direction_marks_and_bom_are_deleted(mark):
    assert normalize_fa("س" + mark + "لام دنیا") == "سلام دنیا"
    assert wer("سلام" + mark + " دنیا", "سلام دنیا") == 0
    assert cer("سلام دنیا", "سلام" + mark + " دنیا") == 0


@pytest.mark.parametrize("text,expected", [
    ("سلام…", "سلام"), ("تهران–شیراز", "تهران شیراز"),
    ("۱٬۲۰۰", "1200"), ("١٬٢٠٠", "1200"), ("1,200", "1200"),
    ("۱،۲۰۰", "1200"), ("1,234,567", "1234567"),
    ("۳٫۵", "3.5"), ("٣٫٥", "3.5"), ("3.5", "3.5"),
    ("۱٬۲۳۴٫۵۶", "1234.56"), ("۱۲٪", "12"),
    ("۱۲٬ کتاب", "12 کتاب"), ("کتاب٫خوب", "کتاب خوب"),
])
def test_unicode_numeric_normalization_on_reference_and_hypothesis(text, expected):
    assert normalize_fa(text) == expected
    assert wer(text, expected) == wer(expected, text) == 0
    assert cer(text, expected) == cer(expected, text) == 0


@pytest.mark.parametrize("word,value", [
    ("ده هزار", 10000), ("بیست و پنج هزار", 25000),
    ("بیست و پنج هزار و یک", 25001), ("نود و نه هزار و نهصد و نود و نه", 99999),
    ("صد هزار", 100000), ("یک صد و نود و نه هزار و یک صد و نود و نه", 199199),
    ("دویست و سی و چهار هزار پانصد و شصت و هفت", 234567),
    ("نهصد و نود و نه هزار و نهصد و نود و نه", 999999),
    ("بیست‌وپنج‌هزار", 25000), ("نهصدونودونههزارونهصدونودونه", 999999),
])
def test_number_grammar_through_999999(word, value):
    assert words_to_digits(word) == str(value)
    assert normalize_fa(word) == str(value)
    assert wer(word, str(value)) == wer(str(value), word) == 0
    assert cer(word, str(value)) == cer(str(value), word) == 0
    assert words_to_digits("من " + word + " کتاب دارم") == f"من {value} کتاب دارم"


def test_number_extension_keeps_cardinal_boundaries_and_standard_spellings():
    assert words_to_digits("بیست و پنج هزار دو هزار") == "25000 2000"
    assert words_to_digits("بیست و پنج هزار بیست و پنج هزار") == "25000 25000"
    assert words_to_digits("هزار هزار") == "1000 1000"
    assert words_to_digits("صد هزار و کتاب") == "100000 و کتاب"
    assert words_to_digits("صفر هزار") == "0 1000"
    # A2 specifies cardinals, without a colloquial spelling expansion.
    assert words_to_digits("هیجده پونصد") == "هیجده پونصد"
