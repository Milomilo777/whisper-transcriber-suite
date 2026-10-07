"""Property tests: every writer/parser pair gives the text back exactly.

For each format that ``core.convert`` can read back, random segment texts
built from a pool of awkward pieces (markup characters, ASS escapes,
InqScribe-like timestamps, RTL marks, combining marks, emoji, CJK) are
written with ``core.writers`` and parsed again. The parsed text must equal
the written text (whitespace-normalised, as every writer normalises it)
and the start time must survive within the format's precision.

Stdlib ``random`` with fixed seeds keeps the runs reproducible without a
test-only dependency. The negative controls at the end swap in a broken
parser and check that the same run catches it.
"""
from __future__ import annotations

import random
import re

import pytest

from core import convert
from core.writers import WRITERS
from core.writers.base import normalize_text

BS = chr(92)
_POOL = list("abcXYZ019 .,;:!?'\"()[]{}<>&*_#/|%$@~^`=+-") + [BS] + [
    "ی", "ک", "ء", "ؤ", "ً", "‌", "‏", "‫", "é", "ñ", "ß",
    "你", "好", "こ", "😀", "👨‍👩‍👧", "́", "\t", "\n", " ",
    "-->", "[00:01]", "[1:02:03.5]", "{" + BS + "k5}", BS + "N", BS + "h",
    BS + "{", BS * 2, "&amp;", "&lt;", "&#10;", "<b>", "</i>", "<c.x>",
    "<00:00:01.000>", " ",
]
_TOKEN_POOL = [p for p in _POOL if not any(ch.isspace() for ch in p)]
_EXT = {"elan": "eaf", "inqscribe": "inqscr"}
# Start-time precision of each format, in seconds.
_PRECISION = {"srt": 0.001, "vtt": 0.001, "tsv": 0.001, "json": 1e-9,
              "ass": 0.01, "elan": 0.001, "inqscribe": 0.01}
FORMATS = sorted(_PRECISION)
RUNS = 300
# SubRip has no escape syntax: text that is itself a formatting tag is read
# back as formatting, and "-->" is written as an arrow (see
# core.writers.base.escape_cue_separator). Both are documented limits.
_SRT_TAG_TEXT = re.compile(r"</?(?:i|b|u|s)>|<font(?:\s[^<>]*)?>|</font>", re.IGNORECASE)


def _expected(fmt: str, text: str) -> str | None:
    want = normalize_text(text)
    if fmt == "srt":
        if _SRT_TAG_TEXT.search(want):
            return None
        want = want.replace("-->", "→")
    return want or None


def _random_text(rng: random.Random) -> str:
    return "".join(rng.choice(_POOL) for _ in range(rng.randint(1, 14)))


def _karaoke_segment(rng: random.Random, t0: float) -> dict:
    tokens = ["".join(rng.choice(_TOKEN_POOL) for _ in range(rng.randint(1, 3)))
              for _ in range(rng.randint(1, 5))]
    words = [{"start": t0 + 0.2 * k, "end": t0 + 0.2 * k + 0.15, "word": tok}
             for k, tok in enumerate(tokens)]
    # Words are joined with or without a space, like Latin and CJK text.
    text = tokens[0] + "".join(rng.choice(("", " ")) + tok for tok in tokens[1:])
    return {"start": t0, "end": t0 + 1.5, "text": text, "words": words}


def _roundtrip_failures(fmt: str, tmp_path, *, karaoke: bool = False,
                        seed: int = 7, runs: int = RUNS) -> list[tuple]:
    rng = random.Random(f"{seed}-{fmt}-{karaoke}")
    path = tmp_path / ("x." + _EXT.get(fmt, fmt))
    failures: list[tuple] = []
    for _ in range(runs):
        t0 = round(rng.uniform(0, 40000), 3)
        if karaoke:
            first = _karaoke_segment(rng, t0)
        else:
            first = {"start": t0, "end": t0 + 1.5, "text": _random_text(rng)}
        want = _expected(fmt, first["text"])
        if want is None:
            continue
        segs = [first, {"start": t0 + 2, "end": t0 + 3, "text": "tail"}]
        path.write_text(WRITERS[fmt](segs, "a.wav"), encoding="utf-8", newline="\n")
        try:
            back = convert.parse_to_segments(str(path))
        except Exception as e:  # noqa: BLE001 - every failure is reported
            failures.append((first["text"], "raised " + repr(e)[:80]))
            continue
        got = [normalize_text(b["text"]) for b in back]
        if got != [want, "tail"]:
            failures.append((first["text"], got))
        elif abs(back[0]["start"] - t0) > _PRECISION[fmt] + 1e-9:
            failures.append((first["text"], ("start", back[0]["start"], t0)))
    return failures


@pytest.mark.parametrize("fmt", FORMATS)
def test_text_round_trips(fmt, tmp_path):
    failures = _roundtrip_failures(fmt, tmp_path)
    assert failures == [], failures[:5]


@pytest.mark.parametrize("fmt", ["vtt", "ass", "json"])
def test_karaoke_words_round_trip(fmt, tmp_path):
    failures = _roundtrip_failures(fmt, tmp_path, karaoke=True)
    assert failures == [], failures[:5]


@pytest.mark.parametrize("fmt", ["vtt", "ass"])
def test_karaoke_is_really_written(fmt):
    seg = _karaoke_segment(random.Random(1), 0.0)
    marker = "<c>" if fmt == "vtt" else "{" + BS + "k"
    assert marker in WRITERS[fmt]([seg], "")


# ----------------------------------------------------------- negative controls
# Each swaps one parser fix for the old behaviour; the property run must
# then report failures, which shows the run can see that class of defect.

def _old_strip_ass_markup(text: str) -> str:
    out = re.sub(r"\{[^}]*\}", "", text)
    out = re.sub(BS * 2 + "[Nn]", " ", out)
    out = out.replace(BS + "h", " ")
    out = out.replace(BS + "{", "{").replace(BS + "}", "}")
    out = out.replace(BS * 2, BS)
    return " ".join(out.split())


@pytest.mark.parametrize("fmt, attr, broken", [
    ("vtt", "_decode_vtt_entities", lambda s: s),
    ("srt", "_SRT_TAG", re.compile(r"<[^>]+>")),
    ("ass", "_strip_ass_markup", _old_strip_ass_markup),
    ("inqscribe", "_unescape_inqscribe", lambda s: s),
])
def test_property_run_catches_a_broken_parser(fmt, attr, broken, tmp_path, monkeypatch):
    monkeypatch.setattr(convert, attr, broken)
    assert _roundtrip_failures(fmt, tmp_path, runs=200)
