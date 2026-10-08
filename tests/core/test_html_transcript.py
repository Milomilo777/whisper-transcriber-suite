"""Shareable interactive HTML transcript (core.writers.html_transcript).

The page is parsed back with html.parser: every segment's text must come
back exactly once and unchanged, hostile text must never add elements, the
timing island must decode to the input times, and every URL in the output
must be the linked audio, an in-page anchor or the footer link.

Property checks use seeded stdlib ``random`` (the project has no Hypothesis
dependency); each one is also run against a deliberately broken escaper to
prove it can fail.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import random
import re
import urllib.parse
from html.parser import HTMLParser
from pathlib import Path

import pytest

from core import writers
from core.writers import html_transcript as ht
from core.writers.base import normalize_text


# ---------------------------------------------------------------- page parser


class _Page(HTMLParser):
    """Collects the structure, texts, URLs and scripts of a generated page."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: list[str] = []
        self.urls: list[tuple[str, str, str]] = []
        self.attrs_by_id: dict[str, dict[str, str]] = {}
        self.metas: list[dict[str, str]] = []
        self.scripts: list[tuple[dict[str, str], str]] = []
        self.styles: list[str] = []
        self.seg_texts: list[str] = []
        self.seg_dirs: list[str] = []
        self.seg_speakers: list[str] = []
        self.words: list[list[tuple[int, str]]] = []
        self.footer_links: list[str] = []
        self._stack: list[tuple[str, dict[str, str]]] = []
        self._script: tuple[dict[str, str], list[str]] | None = None
        self._style: list[str] | None = None
        self._in_footer = False

    def _classes(self) -> set[str]:
        out: set[str] = set()
        for _tag, attrs in self._stack:
            out.update((attrs.get("class") or "").split())
        return out

    def handle_starttag(self, tag, attrs):  # type: ignore[override]
        a = {k: (v or "") for k, v in attrs}
        self.tags.append(tag)
        for key in ("href", "src", "action", "formaction", "poster", "srcset"):
            if key in a:
                self.urls.append((tag, key, a[key]))
        if "id" in a:
            self.attrs_by_id[a["id"]] = a
        if tag == "meta":
            self.metas.append(a)
        if tag == "script":
            self._script = (a, [])
        if tag == "style":
            self._style = []
        if tag == "footer":
            self._in_footer = True
        if tag == "a" and self._in_footer:
            self.footer_links.append(a.get("href", ""))
        cls = set((a.get("class") or "").split())
        if "txt" in cls:
            self.seg_texts.append("")
            self.seg_dirs.append(a.get("dir", ""))
            self.words.append([])
        if "spk" in cls:
            self.seg_speakers.append("")
        if "w" in cls:
            self.words[-1].append((int(a["data-j"]), ""))
        if tag not in ("meta", "link", "br", "input", "img", "source", "wbr"):
            self._stack.append((tag, a))

    def handle_endtag(self, tag):  # type: ignore[override]
        if tag == "script" and self._script is not None:
            self.scripts.append((self._script[0], "".join(self._script[1])))
            self._script = None
        if tag == "style" and self._style is not None:
            self.styles.append("".join(self._style))
            self._style = None
        if tag == "footer":
            self._in_footer = False
        if self._stack and self._stack[-1][0] == tag:
            self._stack.pop()

    def handle_data(self, data):  # type: ignore[override]
        if self._script is not None:
            self._script[1].append(data)
            return
        if self._style is not None:
            self._style.append(data)
            return
        cls = self._classes()
        if "txt" in cls:
            self.seg_texts[-1] += data
        if "w" in cls:
            j, t = self.words[-1][-1]
            self.words[-1][-1] = (j, t + data)
        if "spk" in cls:
            self.seg_speakers[-1] += data


def _parse(page: str) -> _Page:
    p = _Page()
    p.feed(page)
    p.close()
    return p


def _island(p: _Page) -> dict:
    blocks = [body for attrs, body in p.scripts if attrs.get("type") == "application/json"]
    assert len(blocks) == 1
    return json.loads(blocks[0])


def _expected(text: object) -> str:
    return normalize_text(ht.clean_text(text))


def _page(segments, **kw) -> str:
    kw.setdefault("audio_href", "a.mp3")
    return ht.build_page(segments, **kw)


# ---------------------------------------------------------------- hostile text

HOSTILE = [
    "<b>bold</b> & <i>x</i>",
    "</script><script>alert(1)</script>",
    "<!--<script>",
    "-->",
    "x &lt; y &amp; &#x3c;i&#x3e;",
    "AT&T a<b c>d",
    "\"double\" 'single' `back`",
    "\u2028line\u2029para",
    "\u200fRLM \u200eLRM \u202eRLO\u202c",
    "emoji \U0001F600 \U0001F469\u200d\U0001F4BB",
    "\u4f60\u597d\u4e16\u754c",
    "\u0633\u0644\u0627\u0645 \u062f\u0646\u06cc\u0627",
    "",
    "   ",
    "x" * 5000,
    "\x00nul\x07bell\x1besc\x7f",
    "\ud800 lone surrogate",
    "]]> <![CDATA[ x ]]>",
    "<style>body{display:none}</style>",
    "<a href='https://evil.example'>link</a> javascript:alert(1)",
]


def test_hostile_texts_round_trip_exactly():
    segs = [{"start": i, "end": i + 0.5, "text": t} for i, t in enumerate(HOSTILE)]
    p = _parse(_page(segs))
    kept = [_expected(t) for t in HOSTILE if _expected(t)]
    assert p.seg_texts == kept


def _structure(page: str) -> list[str]:
    return _parse(page).tags


def test_hostile_texts_never_change_the_structure():
    hostile = [{"start": i, "end": i + 1, "text": t, "speaker": t + "x"}
               for i, t in enumerate(HOSTILE) if _expected(t)]
    benign = [{"start": i, "end": i + 1, "text": "plain", "speaker": "S"}
              for i in range(len(hostile))]
    assert _structure(_page(hostile)) == _structure(_page(benign))


def test_hostile_title_chapters_and_speakers_are_escaped():
    segs = [{"start": 0, "end": 1, "text": "a", "speaker": "</bdi><script>x</script>"}]
    chapters = [{"title": "<img src=x onerror=alert(1)>", "start": 0, "segment_start": 0}]
    page = _page(segs, title="</title><script>t</script>", chapters=chapters)
    p = _parse(page)
    assert p.tags.count("script") == 2  # the island and the page script only
    assert "img" not in p.tags
    assert p.seg_speakers == ["</bdi><script>x</script>"]


# ---------------------------------------------------------------- seeded property checks

_ALPHABET = (
    list("abcXYZ019 .,;:!?'\"`<>&=/#%-_()[]{}\\")
    + ["</script>", "<!--", "-->", "<script>", "&amp;", "&#60;", "]]>", "\u2028",
       "\u200f", "\u200e", "\U0001F600", "\u4f60", "\u3042", "\u0633", "\u06cc",
       "\u0643", "\t", "\n", "\x00", "\x1f", "\ud800", "\u00a0"]
)


def _random_text(rng: random.Random) -> str:
    n = rng.choice([0, 1, 3, 10, 40, 300])
    return "".join(rng.choice(_ALPHABET) for _ in range(n))


def _random_segments(rng: random.Random) -> list[dict]:
    segs = []
    t = rng.choice([0.0, 0.125, 3599.5, 7200.25])
    for _ in range(rng.randint(1, 6)):
        text = _random_text(rng)
        seg: dict = {"start": round(t, 3), "end": round(t + 1.5, 3), "text": text}
        if rng.random() < 0.4:
            seg["speaker"] = _random_text(rng)
        if rng.random() < 0.5:
            tokens = normalize_text(ht.clean_text(text)).split(" ")
            seg["words"] = [
                {"start": round(t + k * 0.25, 3), "end": round(t + k * 0.25 + 0.2, 3), "word": tok}
                for k, tok in enumerate(tokens) if tok
            ]
        segs.append(seg)
        t += 2.0
    return segs


def _property_holds(segs: list[dict]) -> bool:
    try:
        return _check_properties(segs)
    except (AssertionError, ValueError, IndexError, KeyError):
        # A broken page can also make the parse or the island decode fail.
        return False


def _check_properties(segs: list[dict]) -> bool:
    page = _page(segs, title=_random_text(random.Random(len(segs))))
    p = _parse(page)
    kept = [s for s in segs if _expected(s.get("text"))]
    if p.seg_texts != [_expected(s.get("text")) for s in kept]:
        return False
    benign = [{"start": s["start"], "end": s["end"], "text": "plain",
               **({"speaker": "S"} if normalize_text(ht.clean_text(s.get("speaker"))) else {})}
              for s in kept]
    # Word spans add one element per word; compare the line-level shape.
    stripped = [{k: v for k, v in s.items() if k != "words"} for s in kept]
    if _structure(_page(stripped, title="t")) != _structure(_page(benign, title="t")):
        return False
    island = _island(p)
    if [seg[0] for seg in island["segments"]] != [round(float(s["start"]), 3) for s in kept]:
        return False
    return True


@pytest.mark.parametrize("seed", range(300))
def test_property_random_segments(seed):
    assert _property_holds(_random_segments(random.Random(seed)))


def test_property_fails_on_a_broken_escaper(monkeypatch):
    """The property checks above catch an escaper that lets markup through."""
    monkeypatch.setattr(ht, "_esc", lambda s: s)
    failures = sum(not _property_holds(_random_segments(random.Random(seed)))
                   for seed in range(300))
    assert failures > 0


def test_property_fails_on_double_escaping(monkeypatch):
    import html as _html
    monkeypatch.setattr(ht, "_esc", lambda s: _html.escape(_html.escape(s)))
    failures = sum(not _property_holds(_random_segments(random.Random(seed)))
                   for seed in range(300))
    assert failures > 0


def test_island_escape_round_trips_and_has_no_markup():
    rng = random.Random(7)
    for _ in range(300):
        value = {"t": _random_text(rng), "n": [rng.random() for _ in range(3)]}
        body = ht.json_island(value)
        assert "<" not in body and ">" not in body and "&" not in body
        assert "\u2028" not in body and "\u2029" not in body
        assert json.loads(body) == json.loads(json.dumps(value))


def test_island_escape_check_fails_on_a_raw_dump():
    body = json.dumps({"t": "</script>"}, ensure_ascii=False)
    assert "<" in body  # the assertion above would catch an unescaped island


# ---------------------------------------------------------------- timestamps and words


def test_timestamps_with_fractions_and_hours():
    segs = [
        {"start": 0.125, "end": 1.5, "text": "first"},
        {"start": 3725.25, "end": 3727.0, "text": "after an hour",
         "words": [{"start": 3725.25, "end": 3725.5, "word": "after"},
                   {"start": 3725.75, "end": 3726.0, "word": " an"},
                   {"start": 3726.125, "end": 3727.0, "word": " hour"}]},
    ]
    page = _page(segs)
    p = _parse(page)
    island = _island(p)
    assert island["segments"][0][:2] == [0.125, 1.5]
    assert island["segments"][1][:2] == [3725.25, 3727.0]
    assert island["segments"][1][2] == [[3725.25, 3725.5], [3725.75, 3726.0], [3726.125, 3727.0]]
    assert ">1:02:05<" in page
    assert ">0:00<" in page
    assert p.words[1] == [(0, "after"), (1, "an"), (2, "hour")]


def test_malformed_times_are_clamped():
    segs = [{"start": "abc", "end": None, "text": "a"},
            {"start": float("nan"), "end": -5, "text": "b"},
            {"start": 10, "end": 2, "text": "c"}]
    island = _island(_parse(_page(segs)))
    assert [s[:2] for s in island["segments"]] == [[0.0, 0.0], [0.0, 0.0], [10.0, 10.0]]


def test_stale_words_fall_back_to_the_edited_text():
    seg = {"start": 0, "end": 2, "text": "hello brave world",
           "words": [{"start": 0, "end": 1, "word": "hello"},
                     {"start": 1, "end": 2, "word": " cruel"},
                     {"start": 1.5, "end": 2, "word": " world"}]}
    p = _parse(_page([seg]))
    assert p.seg_texts == ["hello brave world"]
    assert p.words == [[]]
    assert "cruel" not in _page([seg])
    assert _island(p)["segments"][0][2] is None


def test_cjk_words_keep_no_spaces():
    seg = {"start": 0, "end": 2, "text": "\u4f60\u597d\u4e16\u754c",
           "words": [{"start": 0, "end": 1, "word": "\u4f60\u597d"},
                     {"start": 1, "end": 2, "word": "\u4e16\u754c"}]}
    p = _parse(_page([seg]))
    assert p.seg_texts == ["\u4f60\u597d\u4e16\u754c"]
    assert [t for _j, t in p.words[0]] == ["\u4f60\u597d", "\u4e16\u754c"]


def test_word_spans_match_the_island_order():
    seg = {"start": 5, "end": 8, "text": "one two three",
           "words": [{"start": 5, "end": 6, "word": "one"}, {"start": 6, "end": 7, "word": "two"},
                     {"start": 7, "end": 8, "word": "three"}]}
    p = _parse(_page([seg]))
    assert [j for j, _t in p.words[0]] == [0, 1, 2]
    assert _island(p)["segments"][0][2] == [[5.0, 6.0], [6.0, 7.0], [7.0, 8.0]]


def test_empty_segments_are_skipped_consistently():
    segs = [{"start": 0, "end": 1, "text": "a"}, {"start": 1, "end": 2, "text": "  "},
            {"start": 2, "end": 3, "text": "b"}]
    p = _parse(_page(segs))
    assert p.seg_texts == ["a", "b"]
    assert [s[0] for s in _island(p)["segments"]] == [0.0, 2.0]
    assert "s1" in p.attrs_by_id and "s2" not in p.attrs_by_id


# ---------------------------------------------------------------- direction, speakers, language


def test_direction_per_paragraph_and_speaker_in_its_own_element():
    segs = [{"start": 0, "end": 1, "text": "\u0633\u0644\u0627\u0645 \u062f\u0646\u06cc\u0627 Google", "speaker": "Speaker 1"},
            {"start": 1, "end": 2, "text": "Hello \u0633\u0644\u0627\u0645"},
            {"start": 2, "end": 3, "text": "123 ..."}]
    p = _parse(_page(segs))
    assert p.seg_dirs == ["rtl", "ltr", "ltr"]
    assert p.seg_speakers == ["Speaker 1"]
    assert p.seg_texts[0].endswith(" Google")


@pytest.mark.parametrize("lang,expected", [
    ("fa", "fa"), ("en-US", "en-US"), ("zh_Hans", None), ("Persian", None),
    ("\"><script>", None), (None, None), ("", None),
])
def test_html_lang_attribute(lang, expected):
    page = _page([{"start": 0, "end": 1, "text": "a"}], language=lang)
    m = re.search(r"<html([^>]*)>", page)
    assert m is not None
    attrs = m.group(1)
    if expected is None:
        assert "lang=" not in attrs
    else:
        assert f'lang="{expected}"' in attrs


# ---------------------------------------------------------------- CSP, URLs, offline


def _csp(p: _Page) -> str:
    metas = [m for m in p.metas if m.get("http-equiv", "").lower() == "content-security-policy"]
    assert len(metas) == 1
    return metas[0]["content"]


def test_csp_hash_matches_the_page_script():
    p = _parse(_page([{"start": 0, "end": 1, "text": "a"}]))
    code = [body for attrs, body in p.scripts if not attrs.get("type")]
    assert len(code) == 1
    digest = base64.b64encode(hashlib.sha256(code[0].encode("utf-8")).digest()).decode()
    csp = _csp(p)
    assert f"script-src 'sha256-{digest}'" in csp
    assert "default-src 'none'" in csp
    assert "unsafe-inline" not in csp.split("script-src")[1].split(";")[0]
    assert "'unsafe-eval'" not in csp


def test_every_url_is_local_or_the_footer_link():
    segs = [{"start": 0, "end": 1, "text": "see https://example.com"}]
    chapters = [{"title": "Intro", "start": 0, "segment_start": 0}]
    page = _page(segs, audio_href="sub/a%23b.mp3", chapters=chapters)
    p = _parse(page)
    for tag, key, url in p.urls:
        ok = (url.startswith("#") or (tag == "audio" and url == "sub/a%23b.mp3")
              or url == ht.FOOTER_URL)
        assert ok, (tag, key, url)
    assert p.footer_links == [ht.FOOTER_URL]
    for css in p.styles:
        assert "url(" not in css and "@import" not in css
    # No remote reference anywhere except the footer link and the visible text.
    rest = page.replace(ht.FOOTER_URL, "").replace("see https://example.com", "")
    assert "http://" not in rest and "https://" not in rest
    assert "://" not in "".join(body for _a, body in p.scripts)


def test_footer_can_be_removed():
    page = _page([{"start": 0, "end": 1, "text": "a"}], footer=False)
    assert "http://" not in page and "https://" not in page
    assert _parse(page).footer_links == []


def test_page_without_audio_has_no_player():
    p = _parse(_page([{"start": 0, "end": 1, "text": "a"}], audio_href=None))
    assert "audio" not in p.tags
    assert not any(tag == "audio" for tag, _k, _u in p.urls)


def test_script_and_style_are_constant():
    a = _parse(_page([{"start": 0, "end": 1, "text": "a"}]))
    b = _parse(_page([{"start": 5, "end": 9, "text": "</script>zz"}], title="other"))
    assert [s for at, s in a.scripts if not at.get("type")] == \
        [s for at, s in b.scripts if not at.get("type")]
    assert a.styles == b.styles


def test_not_registered_as_an_auto_output_format():
    assert "html" not in writers.supported_formats()
    assert "html" not in writers.WRITERS


# ---------------------------------------------------------------- chapters


def test_chapters_link_to_their_segment():
    segs = [{"start": i * 10, "end": i * 10 + 5, "text": f"s{i}"} for i in range(5)]
    segs[1]["text"] = ""  # skipped: chapter on it moves to the next shown one
    chapters = [{"title": "Intro", "start": 0, "segment_start": 0},
                {"title": "Second", "start": 10, "segment_start": 1},
                {"title": "Late", "start": 41, "segment_start": "bad"},
                "not a dict"]
    page = _page(segs, chapters=chapters)
    p = _parse(page)
    links = [u for tag, _k, u in p.urls if tag == "a" and u.startswith("#s")]
    # Shown segments are numbered s0..s3 (the empty one is not shown).
    assert links[:3] == ["#s0", "#s1", "#s3"]  # the chapter list comes first
    assert _island(p)["chapters"] == [0.0, 10.0, 41.0]


# ---------------------------------------------------------------- linked audio href


@pytest.mark.parametrize("name", [
    "a.mp3", "sp ace.mp3", "a#1.mp3", "a%41.mp3", "q?x.mp3", "\u0635\u062f\u0627.mp3",
    # ":" names a stream on Windows, so only other systems can have it in a file name.
    *([] if os.name == "nt" else ["a:b.mp3"]),
])
def test_audio_href_is_relative_and_percent_encoded(tmp_path, name):
    media = tmp_path / "media" / name
    out = tmp_path / "pages" / "t.html"
    href = ht.audio_href(str(media), str(out))
    assert href == "../media/" + urllib.parse.quote(name, safe="")
    assert "#" not in href and "?" not in href and ":" not in href
    assert urllib.parse.unquote(href) == "../media/" + name


def test_audio_href_same_folder(tmp_path):
    assert ht.audio_href(str(tmp_path / "x y.wav"), str(tmp_path / "x y.html")) == "x%20y.wav"


def test_audio_href_across_drives_uses_the_file_name(tmp_path, monkeypatch):
    def boom(*_a, **_k):
        raise ValueError("path is on mount 'E:', start on mount 'C:'")
    monkeypatch.setattr(ht.os.path, "relpath", boom)
    assert ht.audio_href(str(tmp_path / "a b.mp3"), str(tmp_path / "t.html")) == "a%20b.mp3"


def test_audio_href_never_absolute(tmp_path):
    href = ht.audio_href(str(tmp_path / "a.mp3"), str(tmp_path / "deep" / "er" / "t.html"))
    assert href == "../../a.mp3"
    assert str(tmp_path).replace("\\", "/") not in href


# ---------------------------------------------------------------- write_page


def test_write_page_writes_atomically_in_utf8(tmp_path):
    media = tmp_path / "talk.mp3"
    media.write_bytes(b"")
    out = tmp_path / "talk.html"
    segs = [{"start": 0, "end": 1, "text": "\u0633\u0644\u0627\u0645\r\nworld"}]
    result = ht.write_page(segs, str(media), out_path=str(out), language="fa")
    assert result == str(out)
    raw = out.read_bytes()
    assert b"\r\n" not in raw
    page = raw.decode("utf-8")
    assert 'src="talk.mp3"' in page
    assert "<title>talk</title>" in page
    assert not list(tmp_path.glob("*.part"))
    assert str(tmp_path) not in page and str(tmp_path).replace("\\", "/") not in page


def test_write_page_without_audio(tmp_path):
    out = tmp_path / "t.html"
    ht.write_page([{"start": 0, "end": 1, "text": "a"}], "", out_path=str(out))
    assert "<audio" not in out.read_text(encoding="utf-8")
    out2 = tmp_path / "t2.html"
    ht.write_page([{"start": 0, "end": 1, "text": "a"}], str(tmp_path / "a.mp3"),
                  out_path=str(out2), audio="none")
    assert "<audio" not in out2.read_text(encoding="utf-8")


def test_write_page_rejects_unknown_audio_mode(tmp_path):
    with pytest.raises(ValueError):
        ht.write_page([], "a.mp3", out_path=str(tmp_path / "t.html"), audio="embedded")


def test_write_page_failure_leaves_no_partial_file(tmp_path, monkeypatch):
    out = tmp_path / "t.html"
    out.write_text("old page", encoding="utf-8")

    def boom(*_a, **_k):
        raise OSError("disk full")
    monkeypatch.setattr(ht.os, "replace", boom)
    with pytest.raises(OSError):
        ht.write_page([{"start": 0, "end": 1, "text": "a"}], "", out_path=str(out))
    assert out.read_text(encoding="utf-8") == "old page"
    assert not list(tmp_path.glob("*.part"))


def test_empty_transcript_still_makes_a_valid_page():
    p = _parse(_page([]))
    assert p.seg_texts == []
    assert _island(p)["segments"] == []


def test_default_page_title_from_media(tmp_path):
    out = tmp_path / "x.html"
    ht.write_page([{"start": 0, "end": 1, "text": "a"}], str(tmp_path / "My <talk>.mp3"),
                  out_path=str(out))
    assert "<title>My &lt;talk&gt;</title>" in out.read_text(encoding="utf-8")


def test_template_has_no_remote_reference_outside_the_footer():
    src = Path(ht.__file__).read_text(encoding="utf-8")
    urls = re.findall(r"https?://[^\s\"'<>)]+", src)
    assert set(urls) <= {ht.FOOTER_URL}, urls
    assert os.path.basename(ht.__file__) == "html_transcript.py"


def test_audio_href_survives_a_lone_surrogate_in_the_file_name(tmp_path):
    # NTFS allows unpaired UTF-16 in names; quote() cannot encode it.
    href = ht.audio_href(str(tmp_path / "a\ud800b.mp3"), str(tmp_path / "t.html"))
    assert href == "a%EF%BF%BDb.mp3"


def test_segment_range_covers_its_words():
    # Aligned words can stick out of their segment; a click on the first word
    # must land inside the segment's range.
    seg = {"start": 36.44, "end": 44.98, "text": "We go",
           "words": [{"start": 36.14, "end": 36.62, "word": "We"},
                     {"start": 44.5, "end": 45.2, "word": " go"}]}
    island = _island(_parse(_page([seg])))
    assert island["segments"][0][:2] == [36.14, 45.2]
    assert ">0:36<" in _page([seg])


def test_meta_line_follows_the_text_direction():
    page = _page([{"start": 0, "end": 1, "text": "\u0633\u0644\u0627\u0645", "speaker": "S"}])
    assert '<span class="meta" dir="rtl">' in page
