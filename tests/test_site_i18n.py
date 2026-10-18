"""tools/site_i18n.py: extraction, placeholders, page building, and the "/" language redirect."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import site_i18n as S  # noqa: E402

try:
    from hypothesis import given, settings, strategies as st
except ImportError:  # the property tests skip themselves without hypothesis
    given = None

PAGES = [(rel, path, open(os.path.join(S.SITE, rel), encoding="utf-8", newline="").read()) for rel, path in S.PAGES]
TAG = re.compile(r"<(/?)([A-Za-z][A-Za-z0-9-]*)")


def skeleton(doc: str) -> list[str]:
    """Tag names in order, outside <script>/<style> bodies: what a translation must never change."""
    body = re.sub(r"(<script\b[^>]*>).*?(</script>)", r"\1\2", doc, flags=re.S)
    body = re.sub(r"(<style\b[^>]*>).*?(</style>)", r"\1\2", body, flags=re.S)
    return [m.group(1) + m.group(2).lower() for m in TAG.finditer(body)]


def with_catalog(monkeypatch, translate):
    """Make every language's catalog translate each segment with translate(src)."""
    segs = S.all_segments()
    cat = {s.key: {"src": s.src, "tr": translate(s.src)} for s in segs}
    monkeypatch.setattr(S, "load_catalog", lambda code: cat)
    return cat


def test_built_pages_are_current():
    assert S.cmd_build(check=True) == 0, "run python tools/site_i18n.py build"


def test_every_page_has_segments_and_markers():
    for rel, _path, doc in PAGES:
        segs = S.extract(doc)
        assert sum(s.kind == "text" for s in segs) > 20, rel
        for a, b in S.MARK.values():
            if "hreflang" in a or rel == "index.html" or "menu" in a or "current" in a:
                assert a in doc and b in doc, (rel, a)


def test_english_build_is_unchanged():
    for _rel, path, doc in PAGES:
        assert S.build_page(doc, "en", path) == doc


def test_identity_translation_keeps_text_and_structure(monkeypatch):
    with_catalog(monkeypatch, lambda src: src)
    for rel, path, doc in PAGES:
        built = S.build_page(doc, "de", path)
        assert skeleton(built) == skeleton(doc), rel
        assert [s.src for s in S.extract(built)] == [s.src for s in S.extract(doc)], rel
        assert '<html lang="de"' in built


def test_translated_page_language_direction_and_urls(monkeypatch):
    with_catalog(monkeypatch, lambda src: "Ü " + src)
    doc = PAGES[0][2]
    built = S.build_page(doc, "fa", "/")
    assert '<html lang="fa" dir="rtl"' in built
    assert '<link rel="canonical" href="https://whisper-transcriber-suite.pages.dev/fa/">' in built
    assert 'href="/assets/logo.svg"' in built and 'href="assets/logo.svg"' not in built
    assert 'href="/fa/youtube-to-text/"' in built
    assert 'href="#features"' in built  # in-page anchors stay
    assert 'href="/?lang=en"' in built  # "View in English" is never localised
    assert '<meta property="og:locale" content="fa_IR">' in built
    assert 'as="font"' not in built and 'as="font"' in doc  # no Latin font preload for a non-Latin script
    assert 'as="font"' in S.build_page(doc, "de", "/")
    guide = S.build_page(PAGES[1][2], "fa", "/youtube-to-text/")
    assert 'href="/fa/"' in guide and 'href="/fa/#download"' in guide and 'src="/assets/logo.svg"' in guide


def test_json_ld_and_strings_are_translated(monkeypatch):
    with_catalog(monkeypatch, lambda src: "XX " + src)
    built = S.build_page(PAGES[0][2], "de", "/")
    for body in re.findall(r'<script type="application/ld\+json">(.*?)</script>', built, flags=re.S):
        data = json.loads(body)
        names = [q["name"] for q in data["@graph"] if q.get("@type") == "FAQPage" for q in q["mainEntity"]] \
            if "@graph" in data else []
        assert all(n.startswith("XX ") for n in names)
    strings = json.loads(re.search(r'<script type="application/json" id="i18n-strings">(.*?)</script>',
                                   built, flags=re.S).group(1))
    assert strings["Play animations"] == "XX Play animations"
    assert '"name": "Whisper Transcriber Suite"' in built  # brand names stay


@pytest.mark.parametrize("src,tr,ok", [
    ("<1>Star</1> and <2/>", "<2/> und <1>Stern</1>", True),
    ("<1>a <2>b</2></1>", "<1><2>b</2> a</1>", True),
    ("<1>Star</1>", "Stern", False),
    ("<1>Star</1>", "<1>Stern</1><3/>", False),
    ("<1>Star</1>", "<2>Stern</2>", False),
    ("<1>a <2>b</2></1>", "<1>a <2>b</1></2>", False),
    ("Plain", "Plain <b>bold</b>", False),
    ("<1/> text", "text", False),
])
def test_placeholder_check(src, tr, ok):
    assert (S.check_placeholders(src, tr) is None) is ok


def test_render_text_escapes_and_restores_tags():
    places = {1: ('<a href="#x">', "</a>"), 2: ("<br>", None)}
    assert S.render_text("Tom & <1>Jerry</1> <2/> a<b", places) == 'Tom &amp; <a href="#x">Jerry</a> <br> a&lt;b'


def test_bad_translation_falls_back_to_english(monkeypatch):
    with_catalog(monkeypatch, lambda src: "broken" if "<1>" in src else "Ü " + src)
    for rel, path, doc in PAGES:
        assert skeleton(S.build_page(doc, "de", path)) == skeleton(doc), rel


def test_import_rejects_bad_placeholders(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "CATALOGS", str(tmp_path))
    seg = next(s for s in S.all_segments() if "<1>" in s.src)
    plain = next(s for s in S.all_segments() if "<" not in s.src)
    f = tmp_path / "in.json"
    f.write_text(json.dumps({seg.key: "no tags", plain.key: "übersetzt", "0" * 16: "x"}), encoding="utf-8")
    assert S.cmd_import("de", str(f), "test") == 2
    cat = json.loads((tmp_path / "de.json").read_text(encoding="utf-8"))
    assert list(cat) == [plain.key] and cat[plain.key]["tr"] == "übersetzt"


def test_unpublished_languages_are_not_built(monkeypatch):
    monkeypatch.setattr(S, "_ACTIVE", None)
    monkeypatch.setattr(S, "load_catalog", lambda code: {})
    assert S.active_langs() == [S.LANGS[0]]
    monkeypatch.setattr(S, "_ACTIVE", None)


def test_staged_rollout_limits_published_languages(monkeypatch):
    with_catalog(monkeypatch, lambda src: "Ü " + src)
    monkeypatch.setenv("SITE_I18N_ONLY", "fa, de")
    monkeypatch.setattr(S, "_ACTIVE", None)
    assert [c for c, _n in S.active_langs()] == ["en", "de", "fa"]
    monkeypatch.setattr(S, "_ACTIVE", None)


if given is not None:
    TEXT = [s for s in S.extract(PAGES[0][2]) if s.kind == "text"]
    words = st.text(alphabet="abcdefghijklmnopqrstuvwxyzäöüßçé &<>\"'", min_size=1, max_size=12)

    @settings(max_examples=40, deadline=None)
    @given(st.lists(words, min_size=len(TEXT), max_size=len(TEXT)))
    def test_random_translations_keep_structure(fill):
        # each segment becomes random words with its placeholders kept in their original order
        cat = {}
        for seg, w in zip(TEXT, fill):
            marks = S.PLACE.findall(seg.src)
            tr = w + "".join(f"<{c}{n}{sc}>" + (w if not c and not sc else "") for c, n, sc in marks)
            cat[seg.key] = {"src": seg.src, "tr": tr}
        original = S.load_catalog
        S.load_catalog = lambda code: cat
        try:
            built = S.build_page(PAGES[0][2], "de", "/")
        finally:
            S.load_catalog = original
        assert skeleton(built) == skeleton(PAGES[0][2])
        assert "<script>" not in built.split("</head>")[1].lower()  # no injected markup


def test_country_table_is_current():
    r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "site_country_lang.py"), "--check"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_language_redirect_rules():
    fn = os.path.join(S.SITE, "functions", "index.js").replace("\\", "/")
    script = f"""
import('file:///{fn.lstrip('/')}').then(m => {{
  const table = {{IR: ['fa'], IN: ['hi', 'en'], CH: ['de', 'en', 'fr', 'it'], BR: ['pt-BR'], TW: ['zh-TW']}};
  const P = ['en', 'fa', 'hi', 'de', 'fr', 'pt-BR', 'zh-TW'];
  const ua = 'Mozilla/5.0 (Windows NT 10.0) Chrome/130';
  const c = (o) => m.pickLanguage({{published: P, table, userAgent: ua, ...o}});
  console.log(JSON.stringify([
    c({{country: 'IR', acceptLanguage: 'en-US,en;q=0.9'}}),
    c({{country: 'IN', acceptLanguage: 'en-IN,en;q=0.9'}}),
    c({{country: 'IN', acceptLanguage: 'hi-IN'}}),
    c({{country: 'CH', acceptLanguage: 'fr-CH,fr;q=0.9,en;q=0.5'}}),
    c({{country: 'CH'}}),
    c({{country: 'BR', acceptLanguage: 'pt'}}),
    c({{country: 'TW', acceptLanguage: 'zh-Hant-TW'}}),
    c({{country: 'IR', cookie: 'en'}}),
    c({{country: 'US', cookie: 'fa'}}),
    c({{country: 'IR', userAgent: 'Mozilla/5.0 (compatible; Googlebot/2.1)'}}),
    c({{country: 'IR', userAgent: ''}}),
    c({{country: 'XX'}}),
    c({{country: null}}),
    c({{country: 'IR', published: ['en']}}),
    c({{country: 'IR', cookie: 'xx'}}),
  ]));
}});
"""
    r = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout.strip().splitlines()[-1]) == [
        "fa", "en", "hi", "fr", "de", "pt-BR", "zh-TW", "en", "fa", "en", "en", "en", "en", "en", "fa"]
