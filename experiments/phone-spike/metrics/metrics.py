"""Persian metrics; standard library only. A2 overrides R1's ZWNJ default."""
from collections import Counter
import re
import string
import unicodedata

_SMALL = dict(zip(
    "صفر یک دو سه چهار پنج شش هفت هشت نه ده یازده دوازده سیزده چهارده پانزده شانزده هفده هجده نوزده".split(),
    range(20)))
_TENS = dict(zip("بیست سی چهل پنجاه شصت هفتاد هشتاد نود".split(), range(20, 100, 10)))
_HUNDREDS = dict(zip("صد دویست سیصد چهارصد پانصد ششصد هفتصد هشتصد نهصد".split(), range(100, 1000, 100)))
_HUNDREDS["یکصد"] = 100
_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_PUNCTUATION = str.maketrans({c: " " for c in
    string.punctuation + "،؛؟«»\u2026\u2013\u2014\u2018\u2019\u201a\u201b\u201c\u201d\u066a\u066b\u066c"
    if c != "."})
_DIRECTION_MARKS = str.maketrans("", "", "\u200e\u200f\ufeff")


def _under_100(text):
    if text in _SMALL:
        return _SMALL[text]
    if text in _TENS:
        return _TENS[text]
    for word, value in _TENS.items():
        prefix = word + "و"
        rest = _SMALL.get(text[len(prefix):], -1)
        if text.startswith(prefix) and 1 <= rest <= 9:
            return value + rest
    return None


def _under_1000(text):
    small = _under_100(text)
    if small is not None:
        return small
    for word, value in _HUNDREDS.items():
        if text == word:
            return value
        if text.startswith(word + "و"):
            rest = _under_100(text[len(word) + 1:])
            if rest is not None and rest > 0:
                return value + rest
    return None


def _number(text):
    if "هزار" not in text:
        return _under_1000(text)
    if text.count("هزار") != 1:
        return None
    before, after = text.split("هزار")
    thousands = 1 if not before else _under_1000(before)
    if thousands is None or not 1 <= thousands <= 999:
        return None
    if not after:
        return thousands * 1000
    if after.startswith("و"):
        after = after[1:]
    rest = _under_1000(after)
    return thousands * 1000 + rest if rest is not None and rest > 0 else None


def words_to_digits(text):
    """Convert whole cardinal phrases 0..999999, including compact/ZWNJ forms.

    Longest grammatical match wins. Unrelated adjacent numbers are not added.
    Ordinals, negatives, decimals, colloquial spellings and larger numbers are
    outside this grammar.
    """
    words = text.split()
    out = []
    i = 0
    while i < len(words):
        for end in range(min(len(words), i + 16), i, -1):
            phrase = "".join(words[i:end]).replace("\u200c", "")
            # Do not consume any part of an adjacent thousands multiplier.
            _, unit, rest = phrase.partition("هزار")
            if unit and rest:
                following = (rest + "".join(words[end:end + 8])).replace("\u200c", "")
                multiplier, next_unit, _ = following.partition("هزار")
                value = _under_1000(multiplier.removeprefix("و"))
                if next_unit and value is not None and value > 0:
                    continue
            value = _number(phrase)
            if value is not None:
                out.append(str(value))
                i = end
                break
        else:
            out.append(words[i])
            i += 1
    return " ".join(out)


def normalize_fa(text, zwnj_to_space=False):
    if text is None:
        return ""
    text = unicodedata.normalize("NFC", text)
    text = text.translate(str.maketrans({"ي": "ی", "ى": "ی", "ك": "ک"}))
    text = re.sub(r"[\u064b-\u065f\u0670\u0640]", "", text)
    text = text.replace("\u200c", " " if zwnj_to_space else "")
    text = text.translate(_DIGITS).translate(_DIRECTION_MARKS)
    # Grouping separators join digits; decimals retain a dot on both sides of scoring.
    text = re.sub(r"(?<=[0-9])[,\u060c\u066c](?=[0-9])", "", text)
    text = re.sub(r"(?<=[0-9])\u066b(?=[0-9])", ".", text)
    text = text.translate(_PUNCTUATION)
    text = re.sub(r"(?<![0-9])\.|\.(?![0-9])", " ", text).lower()
    return " ".join(words_to_digits(text).split())


def edit_distance(ref, hyp):
    """Levenshtein distance in linear space, including for long-form CER."""
    if len(hyp) > len(ref):
        ref, hyp = hyp, ref
    previous = list(range(len(hyp) + 1))
    for i, ref_item in enumerate(ref, 1):
        current = [i]
        for j, hyp_item in enumerate(hyp, 1):
            current.append(min(current[-1] + 1, previous[j] + 1,
                               previous[j - 1] + (ref_item != hyp_item)))
        previous = current
    return previous[-1]


def _sequences(ref, hyp, characters, zwnj_to_space):
    r = normalize_fa(ref, zwnj_to_space)
    h = normalize_fa(hyp, zwnj_to_space)
    r, h = (r.replace(" ", ""), h.replace(" ", "")) if characters else (r.split(), h.split())
    if not r:
        raise ValueError("Empty reference after normalization")
    return r, h


def wer_edits(ref, hyp, zwnj_to_space=False):
    r, h = _sequences(ref, hyp, False, zwnj_to_space)
    return edit_distance(r, h), len(r)


def cer_edits(ref, hyp, zwnj_to_space=False):
    r, h = _sequences(ref, hyp, True, zwnj_to_space)
    return edit_distance(r, h), len(r)


def wer(ref, hyp, zwnj_to_space=False):
    edits, length = wer_edits(ref, hyp, zwnj_to_space)
    return edits / length


def cer(ref, hyp, zwnj_to_space=False):
    edits, length = cer_edits(ref, hyp, zwnj_to_space)
    return edits / length


def repeated_ngrams(text, n=3):
    """Occurrences beyond the first for each normalized word n-gram."""
    if n < 1:
        raise ValueError("n must be positive")
    words = normalize_fa(text).split()
    counts = Counter(tuple(words[i:i + n]) for i in range(len(words) - n + 1))
    return sum(count - 1 for count in counts.values())


def word_error_counts(ref, hyp):
    """Minimum-edit word alignment; ties prefer substitution, then deletion."""
    r, h = _sequences(ref, hyp, False, False)
    previous = [(j, 0, 0, j) for j in range(len(h) + 1)]
    for i, item in enumerate(r, 1):
        current = [(i, 0, i, 0)]
        for j, other in enumerate(h, 1):
            total, sub, delete, insert = previous[j - 1]
            diagonal = (total + (item != other), sub + (item != other), delete, insert)
            total, sub, delete, insert = previous[j]
            deletion = (total + 1, sub, delete + 1, insert)
            total, sub, delete, insert = current[-1]
            insertion = (total + 1, sub, delete, insert + 1)
            current.append(min((diagonal, deletion, insertion), key=lambda cell: cell[0]))
        previous = current
    total, sub, delete, insert = previous[-1]
    return {"edits": total, "substitutions": sub, "deletions": delete, "insertions": insert}
