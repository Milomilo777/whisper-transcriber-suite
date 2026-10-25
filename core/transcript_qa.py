"""Grounding core of "Ask (offline)": retrieval, evidence ids and answer checks for one transcript.

The deterministic part of asking a local model about a transcript, testable without a model:

1. :func:`fold` normalises text for the INDEX only (the text shown to the user never changes).
2. :func:`make_windows` groups consecutive segments; :func:`rank_windows` scores them with BM25 on
   two channels (folded words, character 3-grams) fused by reciprocal rank.
3. :func:`select_context` sends the whole transcript when it fits the token budget, else the best
   windows in time order, capped by tokens (``count_tokens`` is the model server's tokenizer).
4. :func:`build_evidence` numbers the chosen lines ``[E1]..[En]`` for the prompt and keeps the map
   back to segment indices; the prompt never holds timestamps or real indices.
5. :func:`check_answer` keeps only evidence ids that were shown, honours :data:`ABSTAIN`, strips
   model-written timestamps and flags numbers or Latin words that the cited lines do not contain.
6. :func:`should_abstain` answers "not in this transcript" before any model call when no question
   word occurs; :func:`format_timestamp` renders the app's own ``[mm:ss]`` links.

Stdlib only; no Tk, no network, no process. A segment is a mapping with ``start`` (seconds) and
``text``, as in the app's JSON output.
"""
from __future__ import annotations

import itertools
import math
import re
import unicodedata
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

Segment = Mapping[str, Any]

#: The reply that means "the shown lines do not answer this".
ABSTAIN = "NOT_IN_TRANSCRIPT"

# Arabic-script letters folded to one form, so Arabic and Persian spellings of a word meet:
# Arabic kaf / yeh / alef maksura / yeh with hamza -> Persian kaf / yeh, teh marbuta -> heh,
# alef with hamza or madda and alef wasla -> alef, waw with hamza -> waw; ZWNJ -> space.
_FOLD_MAP: dict[int, str] = {
    0x0643: "\u06a9", 0x064A: "\u06cc", 0x0649: "\u06cc", 0x0626: "\u06cc",
    0x0629: "\u0647", 0x0623: "\u0627", 0x0625: "\u0627", 0x0622: "\u0627",
    0x0671: "\u0627", 0x0624: "\u0648", 0x200C: " ",
}
for _d in range(10):  # Persian and Arabic-Indic digits -> ASCII
    _FOLD_MAP[0x06F0 + _d] = str(_d)
    _FOLD_MAP[0x0660 + _d] = str(_d)
# Removed: tatweel and the Arabic harakat (other scripts keep their combining marks: a Hindi
# vowel sign is part of the word).
_DROP = frozenset([0x0640, 0x0670, *range(0x064B, 0x0660), *range(0x06D6, 0x06EE)])

_STOP_WORDS = """
a an the and or of to in on at for with by from is are was were be been it this that these those
what which who whom whose when where why how does do did can could would should will about as into
than then there their they he she we you i me my our your his her its not no yes
\u0648 \u062f\u0631 \u0628\u0647 \u0627\u0632 \u06a9\u0647 \u0627\u06cc\u0646 \u0622\u0646 \u0631\u0627 \u0628\u0627 \u0628\u0631\u0627\u06cc \u0627\u0633\u062a \u0647\u0633\u062a \u0628\u0648\u062f \u0634\u062f \u0645\u06cc \u06cc\u06a9 \u062a\u0627 \u0647\u0645 \u06cc\u0627 \u0627\u0645\u0627 \u0627\u06af\u0631 \u0686\u0647 \u0686\u06cc \u0686\u0631\u0627 \u06a9\u062c\u0627 \u06a9\u06cc \u06a9\u06cc\u0633\u062a
\u0686\u06cc\u0633\u062a \u0686\u0646\u062f \u0686\u06af\u0648\u0646\u0647 \u0686\u0637\u0648\u0631 \u0622\u06cc\u0627 \u0627\u0648 \u0645\u0627 \u0634\u0645\u0627 \u0622\u0646\u0647\u0627 \u0647\u0627 \u0647\u0627\u06cc \u062a\u0631 \u062a\u0631\u06cc\u0646 \u0634\u0648\u062f \u06a9\u0646\u062f \u06a9\u0631\u062f \u06a9\u0631\u062f\u0647 \u0645\u0646
\u0641\u064a \u0645\u0646 \u0639\u0644\u0649 \u0627\u0644\u0649 \u0625\u0644\u0649 \u0639\u0646 \u0645\u0627 \u0645\u0627\u0630\u0627 \u0645\u062a\u0649 \u0627\u064a\u0646 \u0623\u064a\u0646 \u0643\u064a\u0641 \u0647\u0644 \u0647\u0648 \u0647\u064a \u0647\u0630\u0627 \u0647\u0630\u0647 \u0630\u0644\u0643 \u0627\u0644\u062a\u064a \u0627\u0644\u0630\u064a \u0627\u0646 \u0623\u0646 \u0627\u0648 \u0623\u0648 \u062b\u0645 \u0643\u0645 \u0644\u0627
\u0646\u0639\u0645 \u0645\u0639 \u0643\u0627\u0646
"""

_AR_COMMA, _AR_SEMICOLON, _AR_QUESTION = chr(0x060C), chr(0x061B), chr(0x061F)
_AR_THOUSANDS, _AR_DECIMAL = chr(0x066C), chr(0x066B)
_OPEN, _CLOSE = "[(" + chr(0x3010), "])" + chr(0x3011)  # 0x3010/0x3011: CJK lenticular brackets

# Only the app's own square-bracket form counts as a model-written timestamp; "(3:20)" stays.
_TIMESTAMP = re.compile(r"\[\s*\d{1,2}(?::\d{2}){1,2}(?:\.\d+)?\s*\]")
# A citation is a bracket group holding only evidence ids ("[E2]", "[E1, E3]", "(E4)"); a bare
# "E2" in prose ("vitamin E2", "model E1000") is never read as a citation.
_ID_GROUP = re.compile(
    f"[{re.escape(_OPEN)}]\\s*E\\d{{1,5}}(?:\\s*[,;{_AR_COMMA}]?\\s*(?:and\\s+)?E\\d{{1,5}})*\\s*"
    f"[{re.escape(_CLOSE)}]",
    re.IGNORECASE,
)
_ID_IN_GROUP = re.compile(r"E(\d{1,5})", re.IGNORECASE)
_EVIDENCE_LOOKALIKE = re.compile(f"([{re.escape(_OPEN)}]\\s*E\\d)", re.IGNORECASE)
_ZWSP = chr(0x200B)
_PUNCT_AFTER_SPACE = re.compile(f"\\s+([.,;:!?{_AR_COMMA}{_AR_SEMICOLON}{_AR_QUESTION}])")
_DIGITS_TO_ASCII = {k: v for k, v in _FOLD_MAP.items() if v.isdigit()}
# Digits are folded to ASCII first; thousands separators between digits go, a decimal mark
# becomes ".", so "1,200", "\u06f1\u066c\u06f2\u06f0\u06f0" and "1200" are the same number and "3.5" is one token.
_NUMBER = re.compile(
    f"\\d+(?:[,{_AR_THOUSANDS}{_AR_COMMA}]\\d{{3}})*(?:[.{_AR_DECIMAL}]\\d+)?"
)
# A comma between digits that is not a thousands group ("3,5", "3,50") is a
# decimal comma ("3.5"); ",ddd" stays a thousands separator ("1,200").
_DECIMAL_COMMA = re.compile(f"(\\d)[,{_AR_COMMA}](\\d{{1,2}})(?!\\d)")
_LATIN_WORD = re.compile(r"[a-z]{2,}")
_ABSTAIN_SHAPE = re.compile(r"not[\s_-]*in[\s_-]*(?:this[\s_-]*)?transcript", re.IGNORECASE)

_RRF_K = 60  # reciprocal-rank constant from Cormack et al. (2009)


def fold(text: str) -> str:
    """Index form of ``text``: NFKC, lower case, Arabic-script letters folded, harakat and
    tatweel removed, ZWNJ and punctuation turned into spaces, digits ASCII. Idempotent."""
    s = unicodedata.normalize("NFKC", text).lower()
    s = "".join(_FOLD_MAP.get(ord(ch), ch) for ch in s if ord(ch) not in _DROP)
    s = unicodedata.normalize("NFKC", s)
    s = "".join(
        ch if ch.isalnum() or unicodedata.category(ch).startswith("M") else " " for ch in s
    )
    return " ".join(s.split())


_STOP = frozenset(fold(_STOP_WORDS).split())


def _is_cjk(ch: str) -> bool:
    return ("\u4e00" <= ch <= "\u9fff" or "\u3400" <= ch <= "\u4dbf"
            or "\u3040" <= ch <= "\u30ff")


def word_tokens(text: str) -> list[str]:
    """Folded words without stop words; a run of CJK characters gives its characters and
    their bigrams (those scripts have no spaces between words), and the rest of a mixed word
    ("iphone" in "iPhone" + Chinese, "2024" before a year sign) stays a word of its own."""
    out: list[str] = []
    for word in fold(text).split():
        for is_cjk, run in itertools.groupby(word, _is_cjk):
            part = "".join(run)
            if is_cjk:
                out += list(part) + [a + b for a, b in zip(part, part[1:])]
            elif part not in _STOP:
                out.append(part)
    return out


def gram_tokens(text: str) -> list[str]:
    """Character 3-grams of each folded word, with ``_`` marking the word edges."""
    out: list[str] = []
    for word in word_tokens(text):
        padded = f"_{word}_"
        out += [padded[i:i + 3] for i in range(len(padded) - 2)]
    return out


def make_windows(segments: Sequence[Segment], max_chars: int = 500,
                 overlap: int = 1) -> list[tuple[int, ...]]:
    """Windows of consecutive segment indices, each at most ``max_chars`` of text (a longer
    segment is a window of its own); neighbouring windows share ``overlap`` segments."""
    windows: list[tuple[int, ...]] = []
    n = len(segments)
    i = 0
    while i < n:
        cur: list[int] = []
        size = 0
        j = i
        while j < n and (not cur or size + len(_segment_text(segments[j])) + 1 <= max_chars):
            cur.append(j)
            size += len(_segment_text(segments[j])) + 1
            j += 1
        windows.append(tuple(cur))
        if j >= n:
            break
        i = max(i + 1, j - overlap)
    return windows


def _bm25(docs: list[list[str]], query: list[str], k1: float = 1.5, b: float = 0.75) -> list[float]:
    """Okapi BM25 score of every document for ``query``."""
    if not docs:
        return []
    avg = sum(len(d) for d in docs) / len(docs) or 1.0
    df: Counter[str] = Counter()
    for d in docs:
        df.update(set(d))
    n = len(docs)
    terms = set(query)
    idf = {t: math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5)) for t in terms if df[t]}
    scores: list[float] = []
    for d in docs:
        tf = Counter(d)
        s = 0.0
        for t, w in idf.items():
            f = tf[t]
            if f:
                s += w * f * (k1 + 1) / (f + k1 * (1 - b + b * len(d) / avg))
        scores.append(s)
    return scores


def rank_windows(segments: Sequence[Segment], windows: Sequence[Sequence[int]],
                 question: str) -> list[int]:
    """Window numbers that match ``question``, best first: BM25 on folded words and on
    3-grams, fused by reciprocal rank. Equal scores go to the earlier window."""
    texts = [" ".join(_segment_text(segments[i]) for i in w) for w in windows]
    fused: dict[int, float] = {}
    for tokens in (word_tokens, gram_tokens):
        scores = _bm25([tokens(t) for t in texts], tokens(question))
        ranked = sorted((k for k, s in enumerate(scores) if s > 0), key=lambda k: (-scores[k], k))
        for rank, k in enumerate(ranked, 1):
            fused[k] = fused.get(k, 0.0) + 1.0 / (_RRF_K + rank)
    return sorted(fused, key=lambda k: (-fused[k], k))


@dataclass(frozen=True)
class Evidence:
    """The transcript lines shown to the model and the map back to segments."""

    prompt_lines: str
    ids: dict[int, int] = field(default_factory=dict)  # evidence number -> segment index


def _segment_text(segment: Segment) -> str:
    text = segment.get("text")
    return "" if text is None else str(text)


def _prompt_line(text: str) -> str:
    """A segment's text as one evidence line: whitespace (newlines too) collapsed, and an
    id-like "[E2]" or "(E2)" in the speech broken with a zero-width space, so the transcript
    can neither start a line of its own nor hand the model a citation to copy."""
    return _EVIDENCE_LOOKALIKE.sub(lambda m: m.group(1)[:-1] + _ZWSP + m.group(1)[-1],
                                   " ".join(text.split()))


def build_evidence(segments: Sequence[Segment], indices: Sequence[int]) -> Evidence:
    """Lines ``[E1]..[En]`` in time order for the given segment indices (duplicates and
    segments without text dropped)."""
    ordered = [i for i in sorted(set(indices)) if _segment_text(segments[i]).strip()]
    lines = [f"[E{n}] {_prompt_line(_segment_text(segments[i]))}" for n, i in enumerate(ordered, 1)]
    return Evidence("\n".join(lines), {n: i for n, i in enumerate(ordered, 1)})


def select_context(segments: Sequence[Segment], question: str, *,
                   count_tokens: Callable[[str], int], budget_tokens: int,
                   max_chars: int = 500, top_k: int = 4, overlap: int = 1) -> list[int]:
    """Segment indices to show for ``question``, in time order.

    The whole transcript when its evidence lines fit ``budget_tokens``; else the union of the
    best ``top_k`` windows, skipping a window that would overflow the budget. When even the best
    window is too big, its first segments that fit. Empty when no window matches.
    """
    everything = list(range(len(segments)))
    if count_tokens(build_evidence(segments, everything).prompt_lines) <= budget_tokens:
        return everything
    windows = make_windows(segments, max_chars, overlap)
    picked: set[int] = set()
    taken = 0
    # Each trial costs a tokenizer call to the model server, so only the best few are tried.
    for k in rank_windows(segments, windows, question)[: top_k * 3]:
        if taken == top_k:
            break
        trial = picked | set(windows[k])
        if count_tokens(build_evidence(segments, sorted(trial)).prompt_lines) <= budget_tokens:
            picked = trial
            taken += 1
        elif not picked:
            for i in windows[k]:
                if count_tokens(build_evidence(segments, sorted(picked | {i})).prompt_lines) > budget_tokens:
                    break
                picked.add(i)
            taken += 1
    return sorted(picked)


@dataclass(frozen=True)
class CheckedAnswer:
    """A model answer after the app's checks."""

    text: str                 # the answer without evidence ids and model-written timestamps
    cited: list[int]          # segment indices of the valid evidence ids, in citation order
    rejected_ids: list[int]   # evidence numbers that were not shown to the model
    abstained: bool           # the model said the lines do not hold the answer
    unsupported: list[str]    # numbers / Latin words absent from the cited lines (a weak flag)

    @property
    def has_source(self) -> bool:
        return bool(self.cited) and not self.abstained


def check_answer(answer: str, evidence: Evidence, segments: Sequence[Segment]) -> CheckedAnswer:
    """Validate a model ``answer`` against the ``evidence`` it was shown.

    Citations are read only from bracket groups of evidence ids. The answer counts as an
    abstention when it is the abstain phrase alone (ids and punctuation aside) or starts with
    it; a sentence that merely contains the words keeps its sources.
    """
    cited: list[int] = []
    rejected: list[int] = []
    for group in _ID_GROUP.finditer(answer):
        for match in _ID_IN_GROUP.finditer(group.group(0)):
            n = int(match.group(1))
            index = evidence.ids.get(n)
            if index is None:
                if n not in rejected:
                    rejected.append(n)
            elif index not in cited:
                cited.append(index)
    text = " ".join(_TIMESTAMP.sub(" ", _ID_GROUP.sub(" ", answer)).split())
    phrase = _ABSTAIN_SHAPE.search(text)
    abstained = False
    if phrase is not None:
        rest = _ABSTAIN_SHAPE.sub(" ", text)
        abstained = (not re.sub(r"[\W_]+", "", rest)
                     or not re.sub(r"[\W_]+", "", text[: phrase.start()]))
        if abstained:
            text = " ".join(rest.split())
    text = _PUNCT_AFTER_SPACE.sub(r"\1", text).strip()
    unsupported: list[str] = []
    if cited and not abstained:
        source_raw = " ".join(_segment_text(segments[i]) for i in cited)
        source_numbers = set(_numbers(source_raw))
        source_words = set(fold(source_raw).split())
        answer_folded = fold(text)
        letters = [c for c in answer_folded if c.isalpha()]
        latin_share = sum(c.isascii() for c in letters) / len(letters) if letters else 1.0
        for number in _numbers(text):
            if number not in source_numbers and number not in unsupported:
                unsupported.append(number)
        if latin_share < 0.5:  # Latin words in a mostly non-Latin answer: names, terms
            for word in _LATIN_WORD.findall(answer_folded):
                if word not in source_words and word not in unsupported:
                    unsupported.append(word)
    return CheckedAnswer(text, cited, rejected, abstained, unsupported)


def _numbers(text: str) -> list[str]:
    """Whole numbers in ``text`` in one spelling: ASCII digits, no thousands separators,
    "." as the decimal mark."""
    s = text.translate(_DIGITS_TO_ASCII)
    s = _DECIMAL_COMMA.sub(r"\1.\2", s)
    out: list[str] = []
    for match in _NUMBER.finditer(s):
        value = match.group(0).replace(_AR_DECIMAL, ".")
        for sep in ("," , _AR_THOUSANDS, _AR_COMMA):
            value = value.replace(sep, "")
        out.append(value)
    return out


# Arabic article and prefixed prepositions, in folded spelling (longest first): wa-al, bi-al,
# fa-al, ka-al, li-l, al.
_AR_PREFIXES = tuple("".join(map(chr, cps)) for cps in (
    (0x0648, 0x0627, 0x0644), (0x0628, 0x0627, 0x0644), (0x0641, 0x0627, 0x0644),
    (0x06A9, 0x0627, 0x0644), (0x0644, 0x0644), (0x0627, 0x0644),
))
_EN_SUFFIXES = (("ies", "y"), ("ied", "y"), ("ing", ""), ("es", ""), ("ed", ""), ("s", ""))


def _variants(word: str) -> set[str]:
    """``word`` plus light stems: without an Arabic article or prefix, without a common
    English ending. Only used to avoid a wrong "not in this transcript"."""
    out = {word}
    for prefix in _AR_PREFIXES:
        if word.startswith(prefix) and len(word) - len(prefix) >= 2:
            out.add(word[len(prefix):])
            break
    if word.isascii():
        for suffix, repl in _EN_SUFFIXES:
            if word.endswith(suffix) and len(word) - len(suffix) >= 3:
                out.add(word[: -len(suffix)] + repl)
    return out


def _stems_meet(a: str, b: str) -> bool:
    if a == b:
        return True
    short, long_ = sorted((a, b), key=len)
    return len(short) >= 3 and long_.startswith(short)


def _scripts(text: str) -> set[str]:
    """First word of the Unicode names of the letters in ``text`` ("LATIN", "ARABIC", ...)."""
    return {unicodedata.name(c, "?").split()[0] for c in set(text) if c.isalpha()}


def should_abstain(segments: Sequence[Segment], question: str) -> bool:
    """True when no question word (after stop words) occurs in the transcript, not even as
    a light stem (an Arabic article, a Persian or English inflection): answer "not in this
    transcript" without asking the model. Never true when the question and the transcript
    share no script (a question in another language is the model's call). A later quality
    gate may add a score floor."""
    query = set(word_tokens(question))
    if not query:
        return False  # only stop words: let the model decide
    transcript = " ".join(_segment_text(s) for s in segments)
    if not _scripts(fold(question)) & _scripts(fold(transcript)):
        return False
    words = {v for w in word_tokens(transcript) for v in _variants(w)}
    return not any(_stems_meet(q, w) for word in query for q in _variants(word) for w in words)


def format_timestamp(seconds: float) -> str:
    """``[mm:ss]``, or ``[h:mm:ss]`` from one hour, rounded half up to the nearest second
    (an unusable value shows as ``[00:00]``)."""
    try:
        value = float(seconds)
    except (TypeError, ValueError):
        value = 0.0
    if not math.isfinite(value):
        value = 0.0
    total = max(0, math.floor(value + 0.5))
    h, rest = divmod(total, 3600)
    m, s = divmod(rest, 60)
    return f"[{h}:{m:02d}:{s:02d}]" if h else f"[{m:02d}:{s:02d}]"
