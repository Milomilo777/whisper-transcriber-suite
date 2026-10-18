"""Build the website in every interface language from the English pages and per-language catalogs.

The English pages under site/ are the source. ``extract`` cuts them into segments: the text of
each block (inline tags kept as numbered placeholders such as ``<1>…</1>`` and ``<2/>``),
translatable attributes (alt, title, aria-label, meta descriptions…) and chosen JSON-LD and
``#i18n-strings`` values. A catalog per language (site-i18n/<lang>.json) maps the SHA-256 of
each English segment to its translation, so a changed English sentence only needs that one
sentence translated again. ``build`` writes site/<lang>/… for every language; a segment with no
translation stays in English. It also keeps the language menu, the hreflang links and the
sitemap entries current, the English pages included.

    python tools/site_i18n.py build              # write every language page (and English blocks)
    python tools/site_i18n.py check              # exit 1 if a built page is stale
    python tools/site_i18n.py status             # untranslated segments per language
    python tools/site_i18n.py export LANG OUT    # JSON of the segments LANG still needs
    python tools/site_i18n.py import LANG IN     # merge translated segments (validated) into the catalog

Translations come from outside this script (people or models); see docs/WEBSITE_I18N.md.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import sys
from dataclasses import dataclass, field
from urllib.parse import urljoin

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = os.path.join(ROOT, "site")
CATALOGS = os.path.join(ROOT, "site-i18n")
HOST = "https://whisper-transcriber-suite.pages.dev"
# English pages, as paths under site/ and as their URL paths.
PAGES = [
    ("index.html", "/"),
    ("youtube-to-text/index.html", "/youtube-to-text/"),
    ("video-to-srt/index.html", "/video-to-srt/"),
    ("speaker-labels/index.html", "/speaker-labels/"),
]

sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, ROOT)
from make_i18n_readmes import LANGS  # noqa: E402  (code, endonym) for the 42 app languages

RTL = {"ar", "fa", "he"}
OG_LOCALE = {
    "en": "en_US", "de": "de_DE", "fr": "fr_FR", "es": "es_ES", "it": "it_IT", "pt-BR": "pt_BR",
    "pt": "pt_PT", "nl": "nl_NL", "pl": "pl_PL", "ru": "ru_RU", "uk": "uk_UA", "tr": "tr_TR",
    "cs": "cs_CZ", "sk": "sk_SK", "hu": "hu_HU", "ro": "ro_RO", "bg": "bg_BG", "el": "el_GR",
    "sv": "sv_SE", "da": "da_DK", "nb": "nb_NO", "fi": "fi_FI", "hr": "hr_HR", "sr": "sr_RS",
    "sl": "sl_SI", "lt": "lt_LT", "zh-CN": "zh_CN", "zh-TW": "zh_TW", "ja": "ja_JP", "ko": "ko_KR",
    "vi": "vi_VN", "th": "th_TH", "id": "id_ID", "ms": "ms_MY", "hi": "hi_IN", "ar": "ar_AR",
    "fa": "fa_IR", "he": "he_IL", "lv": "lv_LV", "ca": "ca_ES", "bn": "bn_BD", "fil": "fil_PH",
}


def url_dir(code: str) -> str:
    """URL folder of a language: lower case, so /pt-br/ and /zh-cn/."""
    return code.lower()


# ---------------------------------------------------------------- tokenizing
TOKEN = re.compile(
    r"<!--.*?-->"
    r"|<![^>]*>"
    r"|</?[A-Za-z][A-Za-z0-9-]*(?:[^>\"']|\"[^\"]*\"|'[^']*')*>",
    re.S,
)
ATTR = re.compile(r"""([^\s"'>/=]+)(?:\s*=\s*("[^"]*"|'[^']*'|[^\s"'>]+))?""")
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
RAW = {"script", "style"}
# Inline tags that stay inside a segment as paired placeholders.
INLINE = {"a", "abbr", "b", "bdi", "bdo", "cite", "dfn", "em", "i", "mark", "q", "s", "small", "span",
          "strong", "sub", "sup", "u"}
# Inline elements kept whole as one atomic placeholder (never translated).
ATOMIC = {"code", "kbd", "samp", "var", "svg", "img", "br", "wbr", "time", "data"}
TRANSLATABLE_ATTRS = {"alt", "title", "aria-label", "placeholder", "data-title", "data-caption"}
META_NAMES = {"description", "twitter:title", "twitter:description", "twitter:image:alt"}
META_PROPS = {"og:title", "og:description", "og:image:alt"}
URL_ATTRS = {"href", "src", "data-still", "data-anim", "action", "poster"}
# JSON-LD keys translated everywhere, and "name" only inside these types.
JSON_TEXT_KEYS = {"text", "description", "headline", "alternativeHeadline", "abstract", "featureList"}
JSON_NAME_TYPES = {"Question", "TechArticle", "WebPage", "ListItem", "HowTo", "HowToStep"}
JSON_URL_TYPES = {"WebPage", "TechArticle", "ListItem"}
LETTER = re.compile(r"[^\W\d_]")


def parse_attrs(tag: str) -> list[tuple[str, str | None, int, int]]:
    """(name, raw value without quotes, value start, value end) for each attribute of a start tag."""
    m = re.match(r"<[A-Za-z][A-Za-z0-9-]*", tag)
    out = []
    pos = m.end() if m else 1
    for a in ATTR.finditer(tag, pos):
        name, val = a.group(1), a.group(2)
        if name in (">", "/"):
            continue
        if val is None:
            out.append((name.lower(), None, -1, -1))
            continue
        vs = a.start(2)
        if val[0] in "\"'":
            out.append((name.lower(), val[1:-1], vs + 1, a.end(2) - 1))
        else:
            out.append((name.lower(), val, vs, a.end(2)))
    return out


def tag_name(tag: str) -> str:
    m = re.match(r"</?([A-Za-z][A-Za-z0-9-]*)", tag)
    return m.group(1).lower() if m else ""


def attr_value(tag: str, name: str) -> str | None:
    for n, v, _s, _e in parse_attrs(tag):
        if n == name:
            return v
    return None


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def key_of(src: str) -> str:
    return hashlib.sha256(src.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------- segments
@dataclass
class Seg:
    kind: str                 # "text" | "attr" | "json"
    src: str                  # normalised English text shown to translators
    start: int = 0            # source span replaced by the translation (text segments)
    end: int = 0
    places: dict = field(default_factory=dict)  # placeholder number -> (open raw, close raw) or (raw, None)

    @property
    def key(self) -> str:
        return key_of(self.src)


def _skip_marked(tag: str) -> bool:
    """translate="no", data-auto (release facts) and data-i18n-skip keep an element untouched."""
    for n, v, _s, _e in parse_attrs(tag):
        if n in ("data-auto", "data-auto-href", "data-i18n-skip"):
            return True
        if n == "translate" and (v or "").lower() == "no":
            return True
    return False


def _element_end(doc: str, tokens: list[re.Match], i: int) -> int:
    """Index of the token that closes the element opened by tokens[i] (same name, nesting aware)."""
    name = tag_name(tokens[i].group(0))
    if name in VOID or tokens[i].group(0).endswith("/>"):
        return i
    depth = 0
    for j in range(i, len(tokens)):
        t = tokens[j].group(0)
        if t.startswith("<!"):
            continue
        n = tag_name(t)
        if n != name:
            continue
        if t.startswith("</"):
            depth -= 1
            if depth == 0:
                return j
        elif not t.endswith("/>"):
            depth += 1
    raise ValueError(f"unclosed <{name}> at offset {tokens[i].start()}")


def tokenize(doc: str) -> list[re.Match]:
    """Tag tokens, with the content of <script>/<style> left out (it is raw text)."""
    out: list[re.Match] = []
    pos = 0
    while True:
        m = TOKEN.search(doc, pos)
        if not m:
            return out
        out.append(m)
        pos = m.end()
        name = tag_name(m.group(0))
        if name in RAW and not m.group(0).startswith("</"):
            close = re.compile(rf"</{name}\s*>", re.I).search(doc, pos)
            if not close:
                raise ValueError(f"unclosed <{name}>")
            pos = close.start()


def _pairs(pieces: list[tuple[str, int, int, str]]) -> bool:
    """True when the first piece (an open tag) is closed by the last piece and not before."""
    depth = 0
    for idx, (kind, _s, _e, _raw) in enumerate(pieces):
        if kind == "open":
            depth += 1
        elif kind == "close":
            depth -= 1
            if depth == 0:
                return idx == len(pieces) - 1
    return False


def extract(doc: str) -> list[Seg]:
    """Every translatable segment of one English page, in document order."""
    tokens = tokenize(doc)
    segs: list[Seg] = []
    run: list[tuple[str, int, int, str]] = []  # (kind, start, end, raw text) inline pieces

    def flush() -> None:
        nonlocal run
        pieces, run = run, []
        # An inline tag whose partner lies beyond a block boundary (an <a> around a whole card)
        # is structure, not text: it splits the run instead of becoming a placeholder.
        stack: list[int] = []
        matched: dict[int, int] = {}
        for idx, (kind, _s, _e, raw) in enumerate(pieces):
            if kind == "open":
                stack.append(idx)
            elif kind == "close":
                if stack and tag_name(pieces[stack[-1]][3]) == tag_name(raw):
                    matched[stack.pop()] = idx
                else:
                    stack.clear()  # unmatched close: everything open before it is structure too
        paired = set(matched) | set(matched.values())
        sub: list[tuple[str, int, int, str]] = []
        for idx, piece in enumerate(pieces):
            if piece[0] in ("open", "close") and idx not in paired:
                emit(sub)
                sub = []
            else:
                sub.append(piece)
        emit(sub)

    def emit(pieces: list[tuple[str, int, int, str]]) -> None:
        # trim pieces that are only whitespace text at both ends
        while pieces and pieces[0][0] == "text" and not pieces[0][3].strip():
            pieces.pop(0)
        while pieces and pieces[-1][0] == "text" and not pieces[-1][3].strip():
            pieces.pop()
        # an inline pair around the whole segment (<a>Download</a>) stays outside it
        while len(pieces) >= 2 and pieces[0][0] == "open" and pieces[-1][0] == "close" and _pairs(pieces):
            pieces = pieces[1:-1]
            while pieces and pieces[0][0] == "text" and not pieces[0][3].strip():
                pieces.pop(0)
            while pieces and pieces[-1][0] == "text" and not pieces[-1][3].strip():
                pieces.pop()
        if not pieces:
            return
        text_parts = []
        places: dict = {}
        n = 0
        open_stack: list[int] = []
        has_letter = False
        for kind, _s, _e, payload in pieces:
            if kind == "text":
                plain = html.unescape(payload)
                if LETTER.search(plain):
                    has_letter = True
                text_parts.append(plain.replace("<", "&lt;"))
            elif kind == "open":
                n += 1
                places[n] = [payload, None]
                open_stack.append(n)
                text_parts.append(f"<{n}>")
            elif kind == "close":
                k = open_stack.pop()
                places[k][1] = payload
                text_parts.append(f"</{k}>")
            else:  # atomic
                n += 1
                places[n] = [payload, None]
                text_parts.append(f"<{n}/>")
        if not has_letter or open_stack:
            return
        start, end = pieces[0][1], pieces[-1][2]
        # keep the leading/trailing whitespace of the first/last text piece outside the segment
        first, last = pieces[0], pieces[-1]
        if first[0] == "text":
            start += len(first[3]) - len(first[3].lstrip())
        if last[0] == "text":
            end -= len(last[3]) - len(last[3].rstrip())
        segs.append(Seg("text", norm("".join(text_parts)), start, end,
                        {k: tuple(v) for k, v in places.items()}))

    def text_between(a: int, b: int) -> None:
        if b > a:
            run.append(("text", a, b, doc[a:b]))

    pos = 0
    i = 0
    while i < len(tokens):
        m = tokens[i]
        tag = m.group(0)
        text_between(pos, m.start())
        pos = m.end()
        name = tag_name(tag)
        if tag.startswith("<!"):
            if tag.startswith("<!--"):
                flush()
            i += 1
            continue
        closing = tag.startswith("</")
        if not closing:
            segs.extend(_attr_segs(tag))
        if not closing and name in RAW:
            flush()
            close = re.compile(rf"</{name}\s*>", re.I).search(doc, pos)
            assert close is not None  # tokenize() already checked it
            body = doc[pos:close.start()]
            typ = (attr_value(tag, "type") or "").lower()
            if typ == "application/ld+json" or (typ == "application/json" and attr_value(tag, "id") == "i18n-strings"):
                segs.extend(Seg("json", s) for s in _json_strings(json.loads(body), typ == "application/json"))
            pos = close.start()
            i += 1
            continue
        if not closing and (name in ATOMIC or (name in INLINE and _skip_marked(tag))):
            j = _element_end(doc, tokens, i)
            whole = doc[m.start():tokens[j].end()]
            # attributes inside an atomic element (an img alt, an svg title…) are still segments
            for t in tokens[i + 1:j + 1]:
                if not t.group(0).startswith("</") and not t.group(0).startswith("<!"):
                    segs.extend(_attr_segs(t.group(0)))
            run.append(("atomic", m.start(), tokens[j].end(), whole))
            pos = tokens[j].end()
            i = j + 1
            continue
        if not closing and _skip_marked(tag):
            flush()
            j = _element_end(doc, tokens, i)
            pos = tokens[j].end()
            i = j + 1
            continue
        if name in INLINE:
            run.append(("close" if closing else "open", m.start(), m.end(), tag))
        else:
            flush()
        i += 1
    text_between(pos, len(doc))
    flush()
    return segs


def _attr_segs(tag: str) -> list[Seg]:
    out = []
    attrs = parse_attrs(tag)
    name = tag_name(tag)
    names = {n: v for n, v, _s, _e in attrs}
    for n, v, _s, _e in attrs:
        if v is None:
            continue
        want = n in TRANSLATABLE_ATTRS
        if name == "meta" and n == "content":
            want = names.get("name") in META_NAMES or names.get("property") in META_PROPS
        if want:
            plain = norm(html.unescape(v))
            if LETTER.search(plain):
                out.append(Seg("attr", plain))
    return out


def _json_strings(obj, flat: bool) -> list[str]:
    """Translatable string values of a JSON-LD graph, or every value of the flat i18n-strings map."""
    out: list[str] = []
    if flat:
        return [v for v in obj.values() if isinstance(v, str) and LETTER.search(v)]

    def walk(o, typ: str | None) -> None:
        if isinstance(o, dict):
            t = o.get("@type") if isinstance(o.get("@type"), str) else typ
            for k, v in o.items():
                if isinstance(v, str) and (k in JSON_TEXT_KEYS or (k == "name" and t in JSON_NAME_TYPES)):
                    if LETTER.search(v):
                        out.append(v)
                elif isinstance(v, list) and k in JSON_TEXT_KEYS and all(isinstance(x, str) for x in v):
                    out.extend(x for x in v if LETTER.search(x))
                else:
                    walk(v, t)
        elif isinstance(o, list):
            for x in o:
                walk(x, typ)

    walk(obj, None)
    return out


# ---------------------------------------------------------------- placeholders
PLACE = re.compile(r"<(/?)(\d+)(/?)>")


def check_placeholders(src: str, tr: str) -> str | None:
    """None when tr uses exactly the placeholders of src, properly nested; else the problem."""
    def scan(s: str):
        items, stack = [], []
        for m in PLACE.finditer(s):
            closing, num, selfc = m.group(1), m.group(2), m.group(3)
            if selfc:
                items.append(f"<{num}/>")
            elif closing:
                if not stack or stack[-1] != num:
                    return None, f"unbalanced </{num}>"
                stack.pop()
                items.append(f"</{num}>")
            else:
                stack.append(num)
                items.append(f"<{num}>")
        if stack:
            return None, f"unclosed <{stack[-1]}>"
        return sorted(items), None

    a, err = scan(src)
    if err:
        return "source: " + err
    b, err = scan(tr)
    if err:
        return err
    assert a is not None and b is not None
    if a != b:
        return f"placeholders differ: {sorted(set(a) ^ set(b))}"
    if re.search(r"<(?!/?\d+/?>)[A-Za-z/!]", tr):
        return "raw HTML tag in translation"
    return None


def render_text(tr: str, places: dict) -> str:
    """Turn a translated segment back into HTML: escape the text, put the placeholders' tags back."""
    out = []
    pos = 0
    for m in PLACE.finditer(tr):
        out.append(_esc_text(tr[pos:m.start()]))
        closing, num, selfc = m.group(1), int(m.group(2)), m.group(3)
        open_raw, close_raw = places[num]
        out.append(open_raw if (selfc or not closing) else close_raw)
        pos = m.end()
    out.append(_esc_text(tr[pos:]))
    return "".join(out)


def _esc_text(s: str) -> str:
    s = html.unescape(s)  # translators may echo &lt; or &amp;
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _esc_attr(s: str) -> str:
    return html.unescape(s).replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")


# ---------------------------------------------------------------- build
def load_catalog(code: str) -> dict:
    path = os.path.join(CATALOGS, f"{code}.json")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_catalog(code: str, cat: dict) -> None:
    os.makedirs(CATALOGS, exist_ok=True)
    path = os.path.join(CATALOGS, f"{code}.json")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(dict(sorted(cat.items())), f, ensure_ascii=False, indent=1)
        f.write("\n")


def lookup(cat: dict, src: str) -> str | None:
    e = cat.get(key_of(src))
    if e and e.get("src") == src and e.get("tr"):
        return e["tr"]
    return None


def localise_url(value: str, page_path: str, code: str) -> str:
    """Root-absolute path for a relative URL; language prefix for links to the site's own pages."""
    v = value.strip()
    if not v or v.startswith(("#", "data:", "mailto:", "tel:", "javascript:")):
        return value
    if v.startswith(HOST):
        rest = v[len(HOST):] or "/"
        return HOST + _prefix_page(rest, code)
    if re.match(r"^[a-z][a-z0-9+.-]*:", v, re.I) or v.startswith("//"):
        return value
    if not v.startswith("/"):
        v = urljoin(page_path, v)
    return _prefix_page(v, code)


def _prefix_page(path: str, code: str) -> str:
    base, sep, frag = path.partition("#")
    if code != "en" and base in {p for _f, p in PAGES}:
        base = f"/{url_dir(code)}{base}"
    return base + sep + frag


def render_tag(tag: str, cat: dict, page_path: str, code: str) -> str:
    """One start tag with its translatable attributes translated and its URLs made language-aware."""
    attrs = parse_attrs(tag)
    if not attrs:
        return tag
    name = tag_name(tag)
    names = {n: v for n, v, _s, _e in attrs}
    edits = []
    for n, v, s, e in attrs:
        if v is None:
            continue
        new = None
        want = n in TRANSLATABLE_ATTRS
        if name == "meta" and n == "content":
            want = names.get("name") in META_NAMES or names.get("property") in META_PROPS
            if names.get("property") == "og:url":
                new = localise_url(v, page_path, code)
            if names.get("property") == "og:locale":
                new = OG_LOCALE.get(code, v)
        if want:
            tr = lookup(cat, norm(html.unescape(v)))
            if tr is not None:
                new = _esc_attr(tr)
        if code != "en" and n in URL_ATTRS and not (name == "link" and names.get("rel") == "alternate"
                                                    and names.get("hreflang")):
            u = localise_url(v, page_path, code)
            if u != v:
                new = u
        if new is not None and new != v:
            edits.append((s, e, new))
    for s, e, new in reversed(edits):
        tag = tag[:s] + new + tag[e:]
    return tag


def translate_json(body: str, cat: dict, page_path: str, code: str, flat: bool) -> str:
    obj = json.loads(body)
    changed = False

    def tr(s: str) -> str:
        nonlocal changed
        t = lookup(cat, s)
        if t is not None and t != s:
            changed = True
            return t
        return s

    if flat:
        obj = {k: (tr(v) if isinstance(v, str) else v) for k, v in obj.items()}
    else:
        def walk(o, typ):
            nonlocal changed
            if isinstance(o, dict):
                t = o.get("@type") if isinstance(o.get("@type"), str) else typ
                for k, v in list(o.items()):
                    if isinstance(v, str) and (k in JSON_TEXT_KEYS or (k == "name" and t in JSON_NAME_TYPES)):
                        o[k] = tr(v)
                    elif isinstance(v, list) and k in JSON_TEXT_KEYS and all(isinstance(x, str) for x in v):
                        o[k] = [tr(x) for x in v]
                    elif isinstance(v, str) and k in ("url", "@id", "item") and t in JSON_URL_TYPES and code != "en":
                        nv = localise_url(v, page_path, code)
                        if nv != v:
                            o[k] = nv
                            changed = True
                    elif k == "inLanguage" and isinstance(v, str) and code != "en":
                        o[k] = code
                        changed = True
                    else:
                        walk(v, t)
            elif isinstance(o, list):
                for x in o:
                    walk(x, typ)
        walk(obj, None)
    if not changed:
        return body
    return "\n" + json.dumps(obj, ensure_ascii=False, indent=2) + "\n"


MARK = {
    "hreflang": ("<!-- i18n:hreflang:start -->", "<!-- i18n:hreflang:end -->"),
    "menu": ("<!-- i18n:menu:start -->", "<!-- i18n:menu:end -->"),
    "current": ("<!-- i18n:current:start -->", "<!-- i18n:current:end -->"),
}


def _replace_block(doc: str, which: str, inner: str) -> str:
    a, b = MARK[which]
    i, j = doc.find(a), doc.find(b)
    if i == -1 or j == -1:
        return doc
    return doc[:i + len(a)] + inner + doc[j:]


# A language is published only once this share of the English segments is translated, so no page
# carries a language tag over mostly English text.
PUBLISH_SHARE = 0.9
_ACTIVE: list[tuple[str, str]] | None = None


def active_langs() -> list[tuple[str, str]]:
    """English plus every language whose catalog covers PUBLISH_SHARE of the segments, in LANGS order."""
    global _ACTIVE
    if _ACTIVE is None:
        segs = all_segments()
        active = [LANGS[0]]
        for c, n in LANGS[1:]:
            cat = load_catalog(c)
            done = sum(1 for s in segs if lookup(cat, s.src) is not None)
            if segs and done / len(segs) >= PUBLISH_SHARE:
                active.append((c, n))
        _ACTIVE = active
    return _ACTIVE


def page_url(code: str, path: str) -> str:
    return HOST + (path if code == "en" else f"/{url_dir(code)}{path}")


def generated_blocks(doc: str, code: str, path: str, nl: str) -> str:
    """Fill the hreflang links, the language menu and the current-language label."""
    ind = "\n"
    langs = active_langs()
    links = [f'<link rel="alternate" hreflang="{c}" href="{page_url(c, path)}">' for c, _n in langs]
    links.append(f'<link rel="alternate" hreflang="x-default" href="{page_url("en", path)}">')
    doc = _replace_block(doc, "hreflang", ind + ind.join(links) + ind)
    items = []
    for c, n in langs:
        href = path if c == "en" else f"/{url_dir(c)}{path}"
        cur = ' aria-current="true"' if c == code else ""
        rtl = ' dir="rtl"' if c in RTL else ""
        items.append(f'<li><a href="{href}" hreflang="{c}" lang="{c}"{rtl} data-lang-pick="{c}"{cur}>{html.escape(n)}</a></li>')
    doc = _replace_block(doc, "menu", ind + ind.join(items) + ind)
    name = dict(LANGS)[code]
    doc = _replace_block(doc, "current", html.escape(name))
    return doc.replace("\n", nl) if nl != "\n" else doc


def build_page(doc: str, code: str, path: str) -> str:
    """The page in language code, built from the English source doc."""
    nl = "\r\n" if "\r\n" in doc else "\n"
    src = doc.replace("\r\n", "\n")
    cat = load_catalog(code) if code != "en" else {}
    out = src
    if code != "en":
        # 1) text segments, from the end so earlier offsets stay valid
        for seg in sorted((s for s in extract(src) if s.kind == "text"), key=lambda s: s.start, reverse=True):
            tr = lookup(cat, seg.src)
            if tr is None or check_placeholders(seg.src, tr):
                continue
            out = out[:seg.start] + render_text(tr, seg.places) + out[seg.end:]
        # 2) JSON blocks
        def json_sub(m: re.Match) -> str:
            typ = (attr_value(m.group(1), "type") or "").lower()
            flat = typ == "application/json" and attr_value(m.group(1), "id") == "i18n-strings"
            if typ != "application/ld+json" and not flat:
                return m.group(0)
            return m.group(1) + translate_json(m.group(2), cat, path, code, flat) + m.group(3)
        out = re.sub(r"(<script\b[^>]*>)(.*?)(</script>)", json_sub, out, flags=re.S)
        # 3) start tags: attributes and URLs (never inside <script>/<style> bodies)
        parts = re.split(r"(<script\b.*?</script>|<style\b.*?</style>)", out, flags=re.S)
        for k in range(0, len(parts), 2):
            parts[k] = re.sub(r"<[A-Za-z][A-Za-z0-9-]*(?:[^>\"']|\"[^\"]*\"|'[^']*')*>",
                              lambda m: render_tag(m.group(0), cat, path, code), parts[k])
        for k in range(1, len(parts), 2):  # the opening tag of a script (src=…) still needs its URL
            parts[k] = re.sub(r"^<script\b[^>]*>", lambda m: render_tag(m.group(0), cat, path, code), parts[k])
        out = "".join(parts)
        # 4) document language, direction, canonical
        lang_attr = f'lang="{code}"' + (' dir="rtl"' if code in RTL else "")
        out = re.sub(r'<html lang="en"', f"<html {lang_attr}", out, count=1)
        out = re.sub(r'(<link rel="canonical" href=")([^"]*)(")',
                     lambda m: m.group(1) + localise_url(m.group(2), path, code) + m.group(3), out, count=1)
    out = generated_blocks(out, code, path, "\n")
    return out.replace("\n", nl) if nl != "\n" else out


def sitemap(xml: str) -> str:
    """English <url> entries kept; language entries generated after them, all with hreflang alternates."""
    nl = "\r\n" if "\r\n" in xml else "\n"
    x = xml.replace("\r\n", "\n")
    x = re.sub(r"\n  <!-- i18n:sitemap:start -->.*?<!-- i18n:sitemap:end -->", "", x, flags=re.S)
    x = re.sub(r"\n    <xhtml:link [^>]*/>", "", x)
    if "xmlns:xhtml" not in x:
        x = x.replace("<urlset ", '<urlset xmlns:xhtml="http://www.w3.org/1999/xhtml" ', 1)
    lastmod = {}
    for path in (p for _f, p in PAGES):
        m = re.search(rf"<loc>{re.escape(HOST + path)}</loc>\s*<lastmod>([^<]+)</lastmod>", x)
        lastmod[path] = m.group(1) if m else None

    def alts(path: str) -> str:
        rows = [f'\n    <xhtml:link rel="alternate" hreflang="{c}" href="{page_url(c, path)}"/>' for c, _n in active_langs()]
        rows.append(f'\n    <xhtml:link rel="alternate" hreflang="x-default" href="{page_url("en", path)}"/>')
        return "".join(rows)

    for path in (p for _f, p in PAGES):
        x = re.sub(rf"(<loc>{re.escape(HOST + path)}</loc>)", lambda m: m.group(1) + alts(path), x, count=1)
    entries = []
    for c, _n in active_langs()[1:]:
        for path in (p for _f, p in PAGES):
            lm = f"\n    <lastmod>{lastmod[path]}</lastmod>" if lastmod[path] else ""
            entries.append(f"  <url>\n    <loc>{page_url(c, path)}</loc>{alts(path)}{lm}\n  </url>")
    block = "\n  <!-- i18n:sitemap:start -->\n" + "\n".join(entries) + "\n  <!-- i18n:sitemap:end -->"
    x = x.replace("\n</urlset>", block + "\n</urlset>", 1)
    return x.replace("\n", nl) if nl != "\n" else x


def outputs() -> dict[str, str]:
    """Every file build writes: path -> content."""
    out = {}
    for rel, path in PAGES:
        with open(os.path.join(SITE, rel), encoding="utf-8", newline="") as f:
            doc = f.read()
        for code, _n in active_langs():
            target = rel if code == "en" else os.path.join(url_dir(code), rel)
            out[os.path.join(SITE, target)] = build_page(doc, code, path)
    sm = os.path.join(SITE, "sitemap.xml")
    with open(sm, encoding="utf-8", newline="") as f:
        out[sm] = sitemap(f.read())
    # the "/" redirect (functions/index.js) may only send visitors to published languages
    fn = os.path.join(SITE, "functions", "index.js")
    with open(fn, encoding="utf-8", newline="") as f:
        js = f.read()
    codes = ", ".join(f"'{c}'" for c, _n in active_langs())
    out[fn] = re.sub(r"(// published:start[^\n]*\n)const PUBLISHED = \[[^\]]*\];",
                     lambda m: m.group(1) + f"const PUBLISHED = [{codes}];", js, count=1)
    return out


def cmd_build(check: bool) -> int:
    stale = []
    for path, content in outputs().items():
        old = None
        if os.path.exists(path):
            with open(path, encoding="utf-8", newline="") as f:
                old = f.read()
        if old == content:
            continue
        stale.append(os.path.relpath(path, ROOT))
        if not check:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(content)
    if check:
        if stale:
            print(f"stale ({len(stale)}): run python tools/site_i18n.py build")
            for s in stale[:20]:
                print("  " + s)
            return 1
        print("current")
        return 0
    print(f"wrote {len(stale)} file(s)")
    return 0


def all_segments() -> list[Seg]:
    segs, seen = [], set()
    for rel, _path in PAGES:
        with open(os.path.join(SITE, rel), encoding="utf-8") as f:
            for s in extract(f.read()):
                if s.src not in seen:
                    seen.add(s.src)
                    segs.append(s)
    return segs


def cmd_status() -> int:
    segs = all_segments()
    words = sum(len(PLACE.sub(" ", s.src).split()) for s in segs)
    print(f"{len(segs)} segments, {words} words")
    for code, _n in LANGS[1:]:
        cat = load_catalog(code)
        missing = sum(1 for s in segs if lookup(cat, s.src) is None)
        print(f"{code:6} {len(segs) - missing:4}/{len(segs)} translated")
    return 0


def cmd_export(code: str, dst: str) -> int:
    cat = load_catalog(code)
    todo = {s.key: s.src for s in all_segments() if lookup(cat, s.src) is None}
    with open(dst, "w", encoding="utf-8", newline="\n") as f:
        json.dump(todo, f, ensure_ascii=False, indent=1)
    print(f"{code}: {len(todo)} segment(s) -> {dst}")
    return 0


def cmd_import(code: str, src_file: str, by: str) -> int:
    with open(src_file, encoding="utf-8") as f:
        incoming = json.load(f)
    sources = {s.key: s.src for s in all_segments()}
    cat = load_catalog(code)
    ok, bad = 0, []
    for k, tr in incoming.items():
        if k not in sources:
            bad.append((k, "unknown key"))
            continue
        if not isinstance(tr, str) or not tr.strip():
            bad.append((k, "empty"))
            continue
        problem = check_placeholders(sources[k], tr)
        if problem:
            bad.append((k, problem))
            continue
        cat[k] = {"src": sources[k], "tr": tr.strip(), "by": by}
        ok += 1
    save_catalog(code, cat)
    print(f"{code}: imported {ok}, rejected {len(bad)}")
    for k, why in bad[:30]:
        print(f"  {k}: {why}")
    return 0 if not bad else 2


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build")
    sub.add_parser("check")
    sub.add_parser("status")
    e = sub.add_parser("export")
    e.add_argument("lang")
    e.add_argument("out")
    i = sub.add_parser("import")
    i.add_argument("lang")
    i.add_argument("infile")
    i.add_argument("--by", default="unknown")
    a = ap.parse_args(argv)
    codes = {c for c, _n in LANGS}
    if hasattr(a, "lang") and a.lang not in codes - {"en"}:
        ap.error(f"unknown language {a.lang!r}")
    if a.cmd in ("build", "check"):
        return cmd_build(a.cmd == "check")
    if a.cmd == "status":
        return cmd_status()
    if a.cmd == "export":
        return cmd_export(a.lang, a.out)
    return cmd_import(a.lang, a.infile, a.by)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
