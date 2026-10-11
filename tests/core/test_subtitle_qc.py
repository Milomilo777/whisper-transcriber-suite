import math
from copy import deepcopy

import hypothesis.strategies as st
from hypothesis import given, settings

from core import subtitle_qc
from core.subtitle_qc import QcLimits, QcIssue


def test_qc_limits_defaults():
    limits = QcLimits()
    assert limits.max_cps == 20.0
    assert limits.max_line_chars == 42
    assert limits.max_lines == 2
    assert limits.min_duration == 0.833
    assert limits.max_duration == 7.0
    assert limits.min_gap == 0.083


def test_limits_for_language():
    assert subtitle_qc.limits_for_language(None) == QcLimits()
    assert subtitle_qc.limits_for_language("en") == QcLimits()

    cjk_limits = QcLimits(max_cps=9.0, max_line_chars=16)
    assert subtitle_qc.limits_for_language("zh") == cjk_limits
    assert subtitle_qc.limits_for_language("ja") == cjk_limits
    assert subtitle_qc.limits_for_language("ko") == cjk_limits
    assert subtitle_qc.limits_for_language("zh-TW") == cjk_limits
    assert subtitle_qc.limits_for_language("zh-Hant") == cjk_limits
    assert subtitle_qc.limits_for_language("ja-JP") == cjk_limits
    assert subtitle_qc.limits_for_language("zh_TW") == cjk_limits
    assert subtitle_qc.limits_for_language("yue") == cjk_limits


def test_visible_length():
    assert subtitle_qc.visible_length("abc") == 3
    assert subtitle_qc.visible_length("a\nb\rc") == 3
    assert subtitle_qc.visible_length("a\u200bb\u200cc") == 3 # ZWSP, ZWNJ
    assert subtitle_qc.visible_length("a\u200db\u200ec") == 3 # ZWJ, LRM
    assert subtitle_qc.visible_length("a\u200fb\u202ac") == 3 # RLM, LRE
    assert subtitle_qc.visible_length("a\u202bb\u202cc") == 3 # RLE, PDF
    assert subtitle_qc.visible_length("a\u202db\u202ec") == 3 # LRO, RLO
    assert subtitle_qc.visible_length("a\u2066b\u2067c") == 3 # LRI, RLI
    assert subtitle_qc.visible_length("a\u2068b\u2069c") == 3 # FSI, PDI
    assert subtitle_qc.visible_length("a\ufeffb") == 2 # BOM

    # Combining marks
    assert subtitle_qc.visible_length("a\u0301") == 1 # a + acute
    assert subtitle_qc.visible_length("é") == 1 # NFC normalized length is 1, even if input is NFD e + acute
    assert subtitle_qc.visible_length("e\u0301") == 1

    # Arabic with harakat
    assert subtitle_qc.visible_length("بِسْمِ") == 3 # b + kasra + s + sukun + m + kasra -> 3 base chars

    # Persian text with ZWNJ
    assert subtitle_qc.visible_length("می\u200cروم") == 5 # m y r w m


def test_suggest_line_break():
    assert subtitle_qc.suggest_line_break("short text", 42, 2) is None
    assert subtitle_qc.suggest_line_break("a" * 43, 42, 2) is None

    # Exceeds max possible for 2 lines
    assert subtitle_qc.suggest_line_break("a" * 86, 42, 2) is None
    assert subtitle_qc.suggest_line_break("a" * 42 + " " + "a" * 43, 42, 2) is None

    # break at space, most balanced, shorter first line
    # "a" * 15 + " " + "a" * 16 -> total 32.
    res = subtitle_qc.suggest_line_break("hello world this is a long text", 16, 2)
    # only "hello world this" (16) / "is a long text" (14) keeps both lines within 16
    assert res == ["hello world this", "is a long text"]

    # 15 five-letter words (89 chars) fit in one 90-char line: no break needed
    text_30 ="A" * 5 + " " + "B" * 5 + " " + "C" * 5 + " " + "D" * 5 + " " + "E" * 5 + " " + "F" * 5 + " " + "G" * 5 + " " + "H" * 5 + " " + "I" * 5 + " " + "J" * 5 + " " + "K" * 5 + " " + "L" * 5 + " " + "M" * 5 + " " + "N" * 5 + " " + "O" * 5
    # That's 15 words, length 15 * 6 - 1 = 89
    res_30 = subtitle_qc.suggest_line_break(text_30, 90, 2)
    assert res_30 is None  # Fits in 90!

    text_long = "One Two Three Four Five Six Seven Eight Nine Ten " * 3
    # 15 words per "One ... Ten " = 49 chars. *3 = 147 chars.
    res_long = subtitle_qc.suggest_line_break(text_long.strip(), 90, 2)
    # the most balanced cut (72 / 73 characters), the shorter line first
    assert res_long == ["One Two Three Four Five Six Seven Eight Nine Ten One Two Three Four Five",
                        "Six Seven Eight Nine Ten One Two Three Four Five Six Seven Eight Nine Ten"]

    # max_lines < 2
    assert subtitle_qc.suggest_line_break("hello world", 5, 1) is None

    # CJK text without spaces
    cjk_text = "こんにちは世界、これは長いテキストです" # 19 chars
    res2 = subtitle_qc.suggest_line_break(cjk_text, 10, 2)
    assert res2 == ['こんにちは世界、こ', 'れは長いテキストです']  # 9 and 10 (shorter first line on tie)

    # Mixed Latin and CJK
    assert subtitle_qc.suggest_line_break("Hello世界", 4, 2) is None # 'Hello' is 5 chars, cannot split
    res3 = subtitle_qc.suggest_line_break("Hello 世界", 5, 2)
    assert res3 == ["Hello", "世界"]

    res4 = subtitle_qc.suggest_line_break("世界Hello", 5, 2)
    assert res4 is None # cannot break between CJK and Latin




def test_boundaries():
    # max_cps
    limits = QcLimits(max_cps=20.0, max_line_chars=42, max_lines=2, min_duration=1.0, max_duration=5.0, min_gap=0.1)

    # Exactly max_cps
    assert not subtitle_qc.check_segments([{"start": 0.0, "end": 1.0, "text": "a" * 20}], limits)
    # Just above max_cps
    issues = subtitle_qc.check_segments([{"start": 0.0, "end": 1.0, "text": "a" * 21}], limits)
    assert [(iss.index, iss.code) for iss in issues] == [(0, 'reading_speed')]

    # Exactly max_line_chars
    assert not subtitle_qc.check_segments([{"start": 0.0, "end": 3.0, "text": "a" * 42}], limits)
    # Just above
    issues = subtitle_qc.check_segments([{"start": 0.0, "end": 3.0, "text": "a" * 43}], limits)
    assert [(iss.index, iss.code) for iss in issues] == [(0, 'line_too_long')]

    # max_lines
    assert not subtitle_qc.check_segments([{"start": 0.0, "end": 3.0, "text": "a\nb"}], limits)
    issues = subtitle_qc.check_segments([{"start": 0.0, "end": 3.0, "text": "a\nb\nc"}], limits)
    assert [(iss.index, iss.code) for iss in issues] == [(0, 'too_many_lines')]

    # exactly min_duration
    assert not subtitle_qc.check_segments([{"start": 0.0, "end": 1.0, "text": "a"}], limits)
    # exactly max_duration
    assert not subtitle_qc.check_segments([{"start": 0.0, "end": 5.0, "text": "a"}], limits)

    # exactly min_gap
    assert not subtitle_qc.check_segments([{"start": 0.0, "end": 1.0, "text": "a"}, {"start": 1.1, "end": 3.0, "text": "b"}], limits)

    # overlap tolerance 0.001
    assert not subtitle_qc.check_segments([{"start": 0.0, "end": 1.0, "text": "a"}, {"start": 0.999, "end": 3.0, "text": "b"}], limits)
    # just over tolerance
    issues = subtitle_qc.check_segments([{"start": 0.0, "end": 1.0, "text": "a"}, {"start": 0.998, "end": 3.0, "text": "b"}], limits)
    assert [(iss.index, iss.code) for iss in issues] == [(1, 'overlap')]

    # CRLF text
    assert not subtitle_qc.check_segments([{"start": 0.0, "end": 3.0, "text": "a\r\nb"}], limits)

    # Various timings
    issues = subtitle_qc.check_segments([{"start": "1.5", "end": 3, "text": "a"}], limits)
    assert len(issues) == 0
    issues = subtitle_qc.check_segments([{"start": None, "end": 3.0, "text": "a"}], limits)
    assert [(iss.index, iss.code) for iss in issues] == [(0, 'bad_timing')]
    issues = subtitle_qc.check_segments([{"start": -1.0, "end": 3.0, "text": "a"}], limits)
    assert [(iss.index, iss.code) for iss in issues] == [(0, 'bad_timing')]

    # CJK limits applied
    issues = subtitle_qc.check_segments([{"start": 0.0, "end": 1.0, "text": "a" * 10}], language='zh')
    assert [(iss.index, iss.code) for iss in issues] == [(0, 'reading_speed')] # cps = 10 > 9.0

    # Arabic/Persian
    issues = subtitle_qc.check_segments([{"start": 0.0, "end": 1.0, "text": "بِسْمِ"}])
    assert not issues # length 3, cps 3 < 20



def test_check_segments_text_none():
    issues = subtitle_qc.check_segments([{"start": 0.0, "end": 2.0, "text": None}])
    assert [(iss.index, iss.code) for iss in issues] == [(0, "empty_text")]

    issues2 = subtitle_qc.check_segments([{"start": 0.0, "end": 2.0, "text": 12345}])
    assert len(issues2) == 0  # 12345 is 5 chars, cps 2.5 <= 20.0, no issues



def test_boundaries_and_types():
    limits = QcLimits(max_cps=20.0, max_line_chars=42, max_lines=2, min_duration=1.0, max_duration=5.0, min_gap=0.1)

    # a) bool timing and int/str
    issues = subtitle_qc.check_segments([{"start": True, "end": "3.0", "text": "a"}])
    # True -> 1.0, end 3.0. duration 2.0. ok.
    assert len(issues) == 0

    # b) Persian text ZWNJ length diff
    # "می‌روم" is length 5 visible, len() is 6.
    # Segment limit 5. If using len(), it would be 6 and trigger line_too_long.
    # Since we use visible_length, it should pass.
    limits_persian = QcLimits(max_line_chars=5)
    issues = subtitle_qc.check_segments([{"start": 0.0, "end": 2.0, "text": "می‌روم"}], limits_persian)
    assert len(issues) == 0

    # Reverse: segment exceeds visible length limit
    issues = subtitle_qc.check_segments([{"start": 0.0, "end": 2.0, "text": "می‌روم"}], QcLimits(max_line_chars=4))
    assert [(iss.index, iss.code, iss.severity) for iss in issues] == [(0, "line_too_long", "warning")]

    # c) Arabic harakat at max_cps boundary
    # "بِسْمِ" is 3 visible chars. duration 0.15s. cps = 3 / 0.15 = 20.0. Exactly at limit -> no issue.
    issues = subtitle_qc.check_segments([{"start": 0.0, "end": 0.15, "text": "بِسْمِ"}])
    assert not any(i.code == 'reading_speed' for i in issues)
    # Just above limit -> duration 0.14s, cps = 3 / 0.14 = 21.4 > 20.0
    issues = subtitle_qc.check_segments([{"start": 0.0, "end": 0.14, "text": "بِسْمِ"}])
    assert [(iss.index, iss.code, iss.severity) for iss in issues if iss.code == 'reading_speed'] == [(0, "reading_speed", "warning")]

    # d) just-below/above min/max duration
    issues = subtitle_qc.check_segments([{"start": 0.0, "end": 0.99, "text": "a"}], limits)
    assert [(iss.index, iss.code, iss.severity) for iss in issues if iss.code == 'too_short'] == [(0, "too_short", "warning")]
    issues = subtitle_qc.check_segments([{"start": 0.0, "end": 5.01, "text": "a"}], limits)
    assert [(iss.index, iss.code, iss.severity) for iss in issues if iss.code == 'too_long'] == [(0, "too_long", "warning")]

    # e) message part ' (a 2-line break fits)'
    # Fits:
    issues = subtitle_qc.check_segments([{"start": 0.0, "end": 3.0, "text": "a" * 25 + " " + "b" * 25}], limits)
    assert " (a 2-line break fits)" in issues[0].message

    # Doesn't fit:
    issues = subtitle_qc.check_segments([{"start": 0.0, "end": 3.0, "text": "a" * 86}], limits)
    assert " (a 2-line break fits)" not in issues[0].message

    # f) CJK with space
    res = subtitle_qc.suggest_line_break("こんにちは 世界これ", 8, 2)
    # total 9 chars. max 8. break at space: "こんにちは", "世界これ". length 5 and 4.
    assert res == ["こんにちは", "世界これ"]

    # Never breaks before combining mark
    # Latin text without spaces gives None; CJK followed by combining marks may be cut, but never before a mark
    res_cjk_comb = subtitle_qc.suggest_line_break("你́" * 15, 10, 2)
    assert res_cjk_comb is not None
    # ensure it doesn't split between char and combining mark
    for c in res_cjk_comb:
        assert not c.startswith("́")



def test_check_segments_bad_timing():
    segments = [
        {"start": "abc", "end": 2.0, "text": "hello 1"},
        {"start": 1.0, "end": float('inf'), "text": "world"},
        {"start": float('nan'), "end": 3.0, "text": "test"}
    ]
    issues = subtitle_qc.check_segments(segments)
    assert len(issues) == 3
    assert all(iss.code == "bad_timing" for iss in issues)


def test_check_segments_non_positive_duration():
    segments = [
        {"start": 2.0, "end": 1.0, "text": "hello 1"},
        {"start": 2.0, "end": 2.0, "text": "world"}
    ]
    issues = subtitle_qc.check_segments(segments)
    assert len(issues) == 2
    assert all(iss.code == "non_positive_duration" for iss in issues)


def test_check_segments_empty_text():
    segments = [{"start": 1.0, "end": 2.0, "text": "   \n\r  "}]
    issues = subtitle_qc.check_segments(segments)
    assert len(issues) == 1
    assert issues[0].code == "empty_text"


def test_check_segments_reading_speed():
    segments = [{"start": 1.0, "end": 2.0, "text": "a" * 21}]
    issues = subtitle_qc.check_segments(segments)
    assert len(issues) == 1
    assert issues[0].code == "reading_speed"
    assert issues[0].value == 21.0


def test_check_segments_line_too_long():
    segments = [{"start": 0.0, "end": 3.0, "text": "a" * 43}]
    issues = subtitle_qc.check_segments(segments)
    assert len(issues) == 1
    assert issues[0].code == "line_too_long"
    assert issues[0].value == 43


def test_check_segments_too_many_lines():
    segments = [{"start": 1.0, "end": 2.0, "text": "a\nb\nc"}]
    issues = subtitle_qc.check_segments(segments)
    assert len(issues) == 1
    assert issues[0].code == "too_many_lines"

    # Ignore empty lines
    segments2 = [{"start": 1.0, "end": 2.0, "text": "a\n\nb"}]
    issues2 = subtitle_qc.check_segments(segments2)
    assert len(issues2) == 0


def test_check_segments_duration():
    limits = QcLimits()
    segments = [
        {"start": 1.0, "end": 1.0 + limits.min_duration - 0.01, "text": "test 1"},
        {"start": 3.0, "end": 3.0 + limits.max_duration + 0.1, "text": "test 2"}
    ]
    issues = subtitle_qc.check_segments(segments)
    assert len(issues) == 2
    assert issues[0].code == "too_short"
    assert issues[1].code == "too_long"


def test_check_segments_pairwise():
    segments = [
        {"start": 1.0, "end": 2.0, "text": "a"},
        {"start": 0.5, "end": 3.0, "text": "b"}, # out_of_order
        {"start": 3.0, "end": 4.0, "text": "c"},
        {"start": 3.5, "end": 5.0, "text": "d"}, # overlap
        {"start": 5.0, "end": 6.0, "text": "e"},
        {"start": 6.0, "end": 7.0, "text": "f"} # gap_too_small (gap is 0.0)
    ]
    issues = subtitle_qc.check_segments(segments)
    assert [(iss.index, iss.code, iss.severity) for iss in issues] == [
        (1, 'out_of_order', 'error'),
        (1, 'overlap', 'error'),
        (2, 'gap_too_small', 'warning'),
        (3, 'overlap', 'error'),
        (4, 'gap_too_small', 'warning'),
        (5, 'gap_too_small', 'warning')
    ]


def test_check_segments_repeated():
    segments = [
        {"start": 1.0, "end": 2.0, "text": "Hello, World!"},
        {"start": 3.0, "end": 4.0, "text": "hello world"}
    ]
    issues = subtitle_qc.check_segments(segments)
    assert len(issues) == 1
    assert issues[0].code == "repeated"


def test_summarize():
    issues = [
        QcIssue(0, "repeated", "warning", "", None, None),
        QcIssue(1, "bad_timing", "error", "", None, None),
        QcIssue(2, "repeated", "warning", "", None, None)
    ]
    counts = subtitle_qc.summarize(issues)
    assert list(counts.keys()) == ["bad_timing", "repeated"]
    assert counts["bad_timing"] == 1
    assert counts["repeated"] == 2


def test_suggest_line_break_performance(monkeypatch):
    call_count = 0
    orig_vis = subtitle_qc.visible_length

    def wrapped_vis(text):
        nonlocal call_count
        call_count += 1
        return orig_vis(text)

    monkeypatch.setattr(subtitle_qc, "visible_length", wrapped_vis)

    # a: 6000 CJK
    assert subtitle_qc.suggest_line_break('你' * 6000, 42) is None
    assert call_count <= 3

    # a: 3000 words
    call_count = 0
    assert subtitle_qc.suggest_line_break('word ' * 3000, 42) is None
    assert call_count <= 3

    # b: 50000 character text
    call_count = 0
    assert subtitle_qc.suggest_line_break('a ' * 25000, 42) is None
    assert call_count <= 3

def test_performance(monkeypatch):
    # c: extend test_performance with spaces and lines that do have breaks
    segments = []
    for i in range(50000):
        if i % 10 == 0:
            # Over-long WITH spaces, length ~96
            text = "word " * 10 + "a" * 40 + " " + "b" * 5
        elif i % 10 == 1:
            # ~60 chars, has 2-line break
            text = "word " * 6 + "hello world this is long enough to break " + str(i)
        else:
            text = f"hello {i}"
        segments.append({"start": float(i), "end": float(i) + 0.9, "text": text})

    call_count = 0
    orig_vis = subtitle_qc.visible_length

    def wrapped_vis(text):
        nonlocal call_count
        call_count += 1
        return orig_vis(text)

    monkeypatch.setattr(subtitle_qc, "visible_length", wrapped_vis)

    subtitle_qc.check_segments(segments)
    assert call_count <= len(segments) * 6


# INVARIANTS

@given(st.lists(st.dictionaries(
    keys=st.sampled_from(["start", "end", "text"]),
    values=st.one_of(st.floats(allow_nan=True), st.text(), st.none())
)))
@settings(max_examples=200, derandomize=True, deadline=None, database=None)
def test_invariant_no_mutation(segments):
    valid_segments = [{"start": s.get("start", 0), "end": s.get("end", 0), "text": s.get("text", "")} for s in segments]
    original = deepcopy(valid_segments)
    subtitle_qc.check_segments(valid_segments)
    assert valid_segments == original


@given(st.lists(st.dictionaries(
    keys=st.sampled_from(["start", "end", "text"]),
    values=st.one_of(st.floats(allow_nan=True), st.text(), st.none())
)))
@settings(max_examples=200, derandomize=True, deadline=None, database=None)
def test_invariant_index_range(segments):
    valid_segments = [{"start": s.get("start", 0), "end": s.get("end", 0), "text": s.get("text", "")} for s in segments]
    issues = subtitle_qc.check_segments(valid_segments)
    for iss in issues:
        assert 0 <= iss.index < len(valid_segments)


@given(st.text(alphabet=st.characters(categories=["Lu", "Ll", "Zs"])))
@settings(max_examples=200, derandomize=True, deadline=None, database=None)
def test_invariant_line_break_rejoin(text):
    res = subtitle_qc.suggest_line_break(text, max_line_chars=10, max_lines=2)
    if res is not None:
        rejoined = " ".join(res)
        assert " ".join(text.split()) == " ".join(rejoined.split())


@given(st.text())
@settings(max_examples=200, derandomize=True, deadline=None, database=None)
def test_invariant_visible_length_zwnj(text):
    assert subtitle_qc.visible_length(text + '\u200c') == subtitle_qc.visible_length(text)


@given(st.lists(st.dictionaries(
    keys=st.sampled_from(["start", "end", "text"]),
    values=st.one_of(st.floats(allow_nan=True), st.text(), st.none())
)))
@settings(max_examples=200, derandomize=True, deadline=None, database=None)
def test_invariant_same_input(segments):
    valid_segments = [{"start": s.get("start", 0), "end": s.get("end", 0), "text": s.get("text", "")} for s in segments]
    issues1 = subtitle_qc.check_segments(valid_segments)
    issues2 = subtitle_qc.check_segments(valid_segments)
    assert issues1 == issues2


def test_invariant_empty_gives_empty():
    assert subtitle_qc.check_segments([]) == []


@given(st.lists(st.dictionaries(
    keys=st.sampled_from(["text"]),
    values=st.text(min_size=1, max_size=10, alphabet=st.characters(whitelist_categories=["Lu", "Ll"]))
), min_size=1, max_size=10))
@settings(max_examples=200, derandomize=True, deadline=None, database=None)
def test_invariant_good_segments_no_issues(segments):
    limits = QcLimits()
    # Construct a valid sequence that satisfies every limit
    valid_segments = []
    current_time = 0.0
    for i, s in enumerate(segments):
        duration = limits.min_duration + 0.1
        start = current_time
        end = start + duration
        text = s.get("text", "A")
        # prevent too long or reading speed issue
        text = text[:int(duration * limits.max_cps) - 1]
        if not text:
            text = "A"
        # prevent repeated text issue
        text = f"{text} {i}"
        valid_segments.append({"start": start, "end": end, "text": text})
        current_time = end + limits.min_gap + 0.01

    issues = subtitle_qc.check_segments(valid_segments)
    assert len(issues) == 0

