"""Shareable interactive HTML transcript: one self-contained ``.html`` file.

The page shows the transcript with timestamps, speakers and chapters, and,
when the media file is linked, plays it: a click on a word (or a line, when
the segment has no usable word timings) seeks there and plays, the word
being spoken is highlighted, and a search box steps through matches. It
needs no install and no network: every style and script is inline and the
Content-Security-Policy allows nothing else (``default-src 'none'``; the one
page script is allowed by its SHA-256 hash, so text that somehow became a
script could not run).

Layout rules:

* The transcript is static HTML, so the page reads and prints without
  JavaScript; the script only adds seeking, highlighting and search.
* Timings live in one ``<script type="application/json">`` island whose
  ``<``, ``>``, ``&`` and line/paragraph separators are written as JSON
  escapes, so no transcript content can close the island. Segment and word
  elements carry only integer indices into it.
* Each segment's text sits in its own block with an explicit ``dir``
  (:func:`core.writers.base.is_rtl_text`), and the speaker label in its own
  ``<bdi>``, so a Latin label never flips a Persian or Arabic line.
* Word spans are used only while the words still spell the (possibly
  edited) text (:func:`core.writers.base.karaoke_tokens`); otherwise the
  line is one clickable unit and the edit is what shows.
* The media file is linked by a percent-encoded path relative to the page
  (never an absolute path, which would leak folder names); it plays while
  the two files stay together. Embedding the audio is not offered yet.

This is not a registered auto-output format (``WRITERS``): it needs the
output path for the relative link and options the frozen
``write(segments, audio_path)`` contract cannot carry. The transcript
viewer and the Last result card call :func:`write_page`.
"""
from __future__ import annotations

import base64
import hashlib
import html
import json
import os
import re
import urllib.parse
from pathlib import PurePath
from typing import Any

from .base import coerce_seconds, is_rtl_text, karaoke_tokens, normalize_text

FOOTER_URL = "https://github.com/Milomilo777/whisper-transcriber-suite"
FOOTER_TEXT = "made with Whisper Transcriber Suite"
AUDIO_MODES = ("linked", "none")

_BS = chr(92)  # a backslash, kept out of literal escapes on purpose

# C0 controls (bar tab/newline/CR, which normalise to spaces anyway), DEL and
# C1 controls: HTML calls them parse errors and browsers drop or replace them.
_CONTROL_TO_SPACE = {c: " " for c in list(range(0x00, 0x20)) + list(range(0x7F, 0xA0))}

_LANG_RE = re.compile(r"[A-Za-z]{2,3}(-[A-Za-z0-9]{1,8})*")


def clean_text(value: object) -> str:
    """*value* as text that HTML keeps as is: controls become spaces and a
    lone surrogate (only possible from a hand-made JSON) becomes U+FFFD."""
    text = "" if value is None else str(value)
    text = text.translate(_CONTROL_TO_SPACE)
    if any(0xD800 <= ord(c) <= 0xDFFF for c in text):
        text = "".join(chr(0xFFFD) if 0xD800 <= ord(c) <= 0xDFFF else c for c in text)
    return text


def _esc(text: str) -> str:
    """Escape text for an HTML text node or a double-quoted attribute."""
    return html.escape(text, quote=True)


def _text(value: object) -> str:
    return normalize_text(clean_text(value))


def json_island(value: Any) -> str:
    """JSON for a ``<script type="application/json">`` block.

    ``<`` (so ``</script>`` and ``<!--`` cannot end or hide the block), ``>``,
    ``&`` and U+2028/U+2029 are written as JSON escapes; ``JSON.parse`` reads
    them back unchanged.
    """
    body = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    for ch in ("<", ">", "&", chr(0x2028), chr(0x2029)):
        body = body.replace(ch, _BS + "u%04x" % ord(ch))
    return body


def _clock(seconds: float) -> str:
    """``m:ss`` under an hour, ``h:mm:ss`` from an hour on."""
    total = int(seconds)
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _t(value: float) -> float:
    return round(value, 3)


def _times(item: dict, fallback: float = 0.0) -> tuple[float, float]:
    start = max(coerce_seconds(item.get("start"), fallback), 0.0)
    end = max(coerce_seconds(item.get("end"), start), start)
    return start, end


def audio_href(media_path: str, out_path: str) -> str:
    """The media file's link from the page at *out_path*: relative, with
    ``/`` separators, every other reserved character percent-encoded
    (``#``, ``%``, ``?`` and ``:`` break an unencoded link). Media on
    another drive cannot be reached relatively; the bare file name is used,
    so the page plays once the two files are put side by side."""
    out_dir = os.path.dirname(os.path.abspath(out_path))
    media = os.path.abspath(media_path)
    try:
        rel = os.path.relpath(media, out_dir)
    except ValueError:
        rel = os.path.basename(media)
    parts = PurePath(rel).parts
    # clean_text: an unpaired surrogate (NTFS allows one in a name) would make
    # quote() raise; such a link cannot resolve anyway, so the page shows its
    # "audio not found" note instead of the export failing.
    return "/".join(urllib.parse.quote(clean_text(part), safe="") for part in parts)


def _lang(language: str | None) -> str:
    if not isinstance(language, str):
        return ""
    value = language.strip()
    return value if _LANG_RE.fullmatch(value) else ""


def _csp(script: str) -> str:
    digest = base64.b64encode(hashlib.sha256(script.encode("utf-8")).digest()).decode("ascii")
    return (
        "default-src 'none'; "
        f"script-src 'sha256-{digest}'; "
        "style-src 'unsafe-inline'; "
        "media-src 'self' file:; "
        "img-src data:; "
        "base-uri 'none'; "
        "form-action 'none'"
    )


def _segment_html(index: int, seg: dict, start: float) -> tuple[str, list[list[float]] | None]:
    """One segment's markup and its word timings (None = line-level)."""
    text = _text(seg.get("text"))
    clean = dict(seg)
    clean["text"] = text
    words = seg.get("words")
    if isinstance(words, list):
        clean["words"] = [
            {**w, "word": clean_text(w.get("word"))} if isinstance(w, dict) else w
            for w in words
        ]
    tokens = karaoke_tokens(clean)
    direction = "rtl" if is_rtl_text(text) else "ltr"
    speaker = _text(seg.get("speaker"))
    meta = f'<a class="ts" href="#s{index}">{_clock(start)}</a>'
    if speaker:
        meta += f' <bdi class="spk">{_esc(speaker)}</bdi>'
    if tokens is None:
        body = _esc(text)
        timings = None
    else:
        parts: list[str] = []
        timings = []
        for j, (w, token, space_before) in enumerate(tokens):
            if parts and space_before:
                parts.append(" ")
            parts.append(f'<span class="w" data-j="{j}">{_esc(token)}</span>')
            ws, we = _times(w, start)
            timings.append([_t(ws), _t(we)])
        body = "".join(parts)
    markup = (
        f'<p class="seg" id="s{index}" data-i="{index}">'
        f'<span class="meta" dir="{direction}">{meta}</span>'
        f'<span class="txt" dir="{direction}">{body}</span></p>'
    )
    return markup, timings


def build_page(
    segments: list[dict],
    *,
    audio_href: str | None,
    title: str = "Transcript",
    chapters: list[Any] | None = None,
    language: str | None = None,
    footer: bool = True,
) -> str:
    """The whole page as a string. *audio_href* is the already encoded link
    to the media (None = no player)."""
    shown: list[tuple[int, dict]] = [
        (i, s) for i, s in enumerate(segments)
        if isinstance(s, dict) and _text(s.get("text"))
    ]
    seg_html: list[str] = []
    island_segs: list[list[Any]] = []
    for index, (_orig, seg) in enumerate(shown):
        start, end = _times(seg)
        markup, timings = _segment_html(index, seg, start)
        seg_html.append(markup)
        if timings:
            # Aligned word times can start before or end after their segment;
            # the segment's playback range covers its words, so a click on
            # its first word lands inside it.
            start = min(start, min(w[0] for w in timings))
            end = max(end, max(w[1] for w in timings))
        island_segs.append([_t(start), _t(end), timings])

    chapter_items: list[str] = []
    chapter_starts: list[float] = []
    for chapter in chapters or []:
        if not isinstance(chapter, dict):
            continue
        c_start, _c_end = _times(chapter)
        target = _chapter_target(chapter, c_start, shown, island_segs)
        if target is None:
            continue
        c_index = len(chapter_starts)
        chapter_starts.append(_t(c_start))
        name = _text(chapter.get("title")) or f"Chapter {c_index + 1}"
        chapter_items.append(
            f'<li><a href="#s{target}" data-c="{c_index}">{_clock(c_start)}</a> '
            f'<span dir="{"rtl" if is_rtl_text(name) else "ltr"}">{_esc(name)}</span></li>'
        )

    page_title = _text(title) or "Transcript"
    lang = _lang(language)
    lang_attr = f' lang="{_esc(lang)}"' if lang else ""
    title_dir = "rtl" if is_rtl_text(page_title) else "ltr"
    island = json_island({"segments": island_segs, "chapters": chapter_starts})

    out: list[str] = [
        "<!DOCTYPE html>",
        f"<html{lang_attr}>",
        "<head>",
        '<meta charset="utf-8">',
        # Constant text plus a base64 digest: nothing to escape.
        f'<meta http-equiv="Content-Security-Policy" content="{_csp(_SCRIPT)}">',
        '<meta name="referrer" content="no-referrer">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{_esc(page_title)}</title>",
        f"<style>{_STYLE}</style>",
        "</head>",
        "<body>",
        '<header id="wts-top">',
        f'<h1 dir="{title_dir}">{_esc(page_title)}</h1>',
    ]
    if audio_href:
        out += [
            f'<audio id="wts-audio" controls preload="metadata" src="{_esc(audio_href)}"></audio>',
            '<p id="wts-missing" class="note" hidden>The audio file was not found. Keep it '
            "in the same place relative to this page (for example, both in one folder) and "
            "reload.</p>",
            '<p id="wts-hint" class="note" hidden>Click any word or line to hear it.</p>',
        ]
    out += [
        '<div id="wts-search" class="search" hidden>',
        '<input id="wts-q" type="search" placeholder="Search" aria-label="Search the transcript">',
        '<button id="wts-prev" type="button">Previous</button>',
        '<button id="wts-next" type="button">Next</button>',
        '<span id="wts-count" aria-live="polite"></span>',
    ]
    if audio_href:
        out.append('<label><input id="wts-follow" type="checkbox" checked> Follow playback</label>')
    out += ["</div>", "</header>"]
    if chapter_items:
        out += ['<nav id="wts-chapters"><h2>Chapters</h2><ol>', *chapter_items, "</ol></nav>"]
    out += ['<main id="wts-transcript">', *seg_html, "</main>"]
    if footer:
        out.append(
            f'<footer><a href="{FOOTER_URL}" rel="noopener noreferrer">{FOOTER_TEXT}</a></footer>'
        )
    out += [
        f'<script type="application/json" id="wts-data">{island}</script>',
        f"<script>{_SCRIPT}</script>",
        "</body>",
        "</html>",
        "",
    ]
    return "\n".join(out)


def _chapter_target(
    chapter: dict, c_start: float, shown: list[tuple[int, dict]], island: list[list[Any]]
) -> int | None:
    """Index of the first shown segment at or after the chapter's first
    segment (by ``segment_start`` when it is a usable int, else by time)."""
    first = chapter.get("segment_start")
    if isinstance(first, int) and not isinstance(first, bool) and first >= 0:
        for index, (orig, _seg) in enumerate(shown):
            if orig >= first:
                return index
        return None
    for index, row in enumerate(island):
        if row[1] >= c_start:
            return index
    return None


def write_page(
    segments: list[dict],
    audio_path: str,
    *,
    out_path: str,
    chapters: list[Any] | None = None,
    language: str | None = None,
    footer: bool = True,
    audio: str = "linked",
    title: str | None = None,
) -> str:
    """Write the page to *out_path* (UTF-8, ``\\n`` line ends, through a
    ``.part`` file and ``os.replace`` so a failure never leaves half a page)
    and return *out_path*.

    *audio*: ``"linked"`` links *audio_path* relative to the page (nothing
    when *audio_path* is empty); ``"none"`` leaves the player out.
    """
    if audio not in AUDIO_MODES:
        raise ValueError(f"audio must be one of {AUDIO_MODES}, not {audio!r}")
    href = audio_href(audio_path, out_path) if (audio == "linked" and audio_path) else None
    if title is None:
        source = audio_path or out_path
        title = os.path.splitext(os.path.basename(source))[0]
    page = build_page(
        segments, audio_href=href, title=title, chapters=chapters,
        language=language, footer=footer,
    )
    part = out_path + ".part"
    try:
        with open(part, "w", encoding="utf-8", newline="\n") as f:
            f.write(page)
        os.replace(part, out_path)
    except BaseException:
        try:
            os.remove(part)
        except OSError:
            pass
        raise
    return out_path


_STYLE = """
:root{color-scheme:light dark;--bg:#fff;--fg:#1d1d1f;--muted:#6b6b70;--line:#e3e3e8;
--word:#ffe58a;--seg:#fff8d6;--hit:#cfe3ff;--cur:#7fb0ff;--link:#0b57d0}
@media (prefers-color-scheme:dark){:root{--bg:#17181a;--fg:#e8e8ea;--muted:#a0a0a8;
--line:#2c2d31;--word:#7a6400;--seg:#2e2a14;--hit:#1f3a5c;--cur:#2f5f9e;--link:#8ab4f8}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
font:17px/1.6 system-ui,-apple-system,"Segoe UI",Roboto,"Noto Sans","Vazirmatn",Tahoma,sans-serif}
header{position:sticky;top:0;z-index:1;background:var(--bg);border-bottom:1px solid var(--line);
padding:.6rem 1rem}
header,nav,main,footer{max-width:52rem;margin-left:auto;margin-right:auto}
h1{font-size:1.25rem;margin:0 0 .4rem;overflow-wrap:anywhere}
h2{font-size:1rem;margin:.2rem 0}
audio{width:100%;display:block}
.note{margin:.3rem 0 0;color:var(--muted);font-size:.9rem}
.search{display:flex;flex-wrap:wrap;gap:.4rem;align-items:center;margin-top:.4rem;font-size:.9rem}
.search[hidden],.note[hidden]{display:none}
.search input[type=search]{flex:1 1 12rem;min-width:8rem;font:inherit;padding:.2rem .4rem}
button{font:inherit;padding:.15rem .6rem}
nav{padding:.4rem 1rem;border-bottom:1px solid var(--line)}
nav ol{margin:0;padding-inline-start:1.4rem}
main{padding:.4rem 1rem 2rem}
.seg{margin:0;padding:.35rem .5rem;border-radius:6px;scroll-margin-top:var(--top,15rem)}
.meta{display:block;font-size:.8rem;color:var(--muted)}
.meta a{color:var(--muted);text-decoration:none}
.spk{font-weight:600}
.txt{display:block;overflow-wrap:anywhere}
.playable .txt{cursor:pointer}
.w{border-radius:3px}
.seg.active{background:var(--seg)}
.w.active{background:var(--word)}
.seg.hit{box-shadow:inset 3px 0 0 var(--hit)}
.seg.cur-hit{box-shadow:inset 4px 0 0 var(--cur);background:var(--hit)}
footer{padding:1rem;font-size:.85rem;color:var(--muted);text-align:center}
footer a{color:var(--link)}
@media (max-width:600px){body{font-size:16px}header{padding:.5rem .6rem}main{padding:.3rem .4rem 2rem}}
@media print{:root{--bg:#fff;--fg:#000;--muted:#555;--line:#ccc}
header audio,.note,.search,footer{display:none}header{position:static;border:0}
.seg{break-inside:avoid}.seg.active,.w.active,.seg.hit,.seg.cur-hit{background:none;box-shadow:none}}
"""

# The page script. It is constant (all data comes from the JSON island), so
# the CSP hash is constant too. Arabic-script letters for the search folding
# are built from code points to keep this file ASCII.
_SCRIPT = """
(function () {
  "use strict";
  var data = JSON.parse(document.getElementById("wts-data").textContent);
  var segs = data.segments;
  var segEls = document.querySelectorAll("#wts-transcript .seg");
  var audio = document.getElementById("wts-audio");
  var activeSeg = -1, activeWord = null, pin = null;
  var follow = document.getElementById("wts-follow");
  var header = document.getElementById("wts-top");

  // Scrolled-to lines stop below the sticky header, whatever its height.
  function pad() {
    document.documentElement.style.setProperty("--top", (header.offsetHeight + 8) + "px");
  }
  pad();
  window.addEventListener("resize", pad);

  function wordEl(i, j) {
    return segEls[i] ? segEls[i].querySelector('.w[data-j="' + j + '"]') : null;
  }

  // A click pins its own word (or line) for a moment: several words can share
  // one time (zero-length words) and segments can overlap, so the time alone
  // cannot always tell which one was clicked.
  function seek(t, i, j) {
    if (!audio || !isFinite(t)) { return; }
    pin = (i === undefined) ? null : {t: t, i: i, j: j};
    try { audio.currentTime = t; } catch (e) { return; }
    var p = audio.play();
    if (p && p.catch) { p.catch(function () {}); }
    update();
  }

  function setActive(i, j) {
    if (i !== activeSeg) {
      if (activeSeg >= 0 && segEls[activeSeg]) { segEls[activeSeg].classList.remove("active"); }
      activeSeg = i;
      if (i >= 0) {
        segEls[i].classList.add("active");
        if (follow && follow.checked && audio && !audio.paused) {
          segEls[i].scrollIntoView({block: "nearest"});
        }
      }
    }
    var w = (i >= 0 && j >= 0) ? wordEl(i, j) : null;
    if (w !== activeWord) {
      if (activeWord) { activeWord.classList.remove("active"); }
      activeWord = w;
      if (w) { w.classList.add("active"); }
    }
  }

  function update() {
    if (!audio) { return; }
    // The LAST item containing t wins: where one segment ends exactly as the
    // next starts (or they overlap), a click on the next one's first word
    // highlights that word, not the end of the previous segment. EPS absorbs
    // the browser storing a seek target in whole microseconds (64.32 reads
    // back as 64.319999).
    var EPS = 0.005;
    var t = audio.currentTime, i, k, found = -1, word = -1;
    if (pin && Math.abs(t - pin.t) < 0.3) { setActive(pin.i, pin.j); return; }
    pin = null;
    for (i = 0; i < segs.length; i++) {
      if (segs[i][0] - EPS <= t && t <= segs[i][1]) { found = i; }
    }
    if (found >= 0 && segs[found][2]) {
      var ws = segs[found][2];
      for (k = 0; k < ws.length; k++) {
        if (ws[k][0] - EPS <= t && t <= ws[k][1]) { word = k; }
      }
    }
    setActive(found, word);
  }

  if (audio) {
    var missing = document.getElementById("wts-missing");
    var hint = document.getElementById("wts-hint");
    var showMissing = function () { missing.hidden = false; hint.hidden = true; };
    audio.addEventListener("error", showMissing);
    if (audio.error) { showMissing(); } else { hint.hidden = false; }
    audio.addEventListener("loadedmetadata", function () { missing.hidden = true; });
    audio.addEventListener("timeupdate", update);
    audio.addEventListener("seeked", update);
    var tick = function () { update(); if (!audio.paused) { requestAnimationFrame(tick); } };
    audio.addEventListener("play", function () { requestAnimationFrame(tick); });
    document.body.classList.add("playable");
  }

  document.getElementById("wts-transcript").addEventListener("click", function (ev) {
    if (!audio || audio.error) { return; }
    if (window.getSelection && String(window.getSelection())) { return; }
    var el = ev.target;
    while (el && el !== this) {
      if (el.classList && el.classList.contains("w")) {
        var seg = el.closest(".seg");
        var i = +seg.getAttribute("data-i"), j = +el.getAttribute("data-j");
        if (segs[i] && segs[i][2] && segs[i][2][j]) { ev.preventDefault(); seek(segs[i][2][j][0], i, j); }
        return;
      }
      if (el.classList && el.classList.contains("seg")) {
        var n = +el.getAttribute("data-i");
        if (segs[n]) { ev.preventDefault(); seek(segs[n][0], n, -1); }
        return;
      }
      el = el.parentNode;
    }
  });

  // Chapter links: scroll to the chapter and play from its start. Without
  // playable audio they stay plain in-page links.
  var nav = document.getElementById("wts-chapters");
  if (nav) {
    nav.addEventListener("click", function (ev) {
      var a = ev.target.closest ? ev.target.closest("a[data-c]") : null;
      if (!a || !audio || audio.error) { return; }
      var t = data.chapters[+a.getAttribute("data-c")];
      if (typeof t !== "number") { return; }
      ev.preventDefault();
      var target = document.getElementById(a.getAttribute("href").slice(1));
      if (target) { target.scrollIntoView({block: "start"}); }
      seek(t);
    });
  }

  // Search folding: Arabic and Persian letter variants (kaf, yeh, alef with
  // hamza or madda, teh marbuta), Arabic-Indic and Persian digits, and no
  // diacritics, zero-width non-joiner or tatweel.
  var C = String.fromCharCode, FOLD = {}, c;
  FOLD[C(0x643)] = C(0x6a9);
  FOLD[C(0x64a)] = FOLD[C(0x649)] = C(0x6cc);
  FOLD[C(0x623)] = FOLD[C(0x625)] = FOLD[C(0x622)] = FOLD[C(0x671)] = C(0x627);
  FOLD[C(0x629)] = C(0x647);
  for (c = 0; c < 10; c++) { FOLD[C(0x660 + c)] = FOLD[C(0x6f0 + c)] = String(c); }
  for (c = 0x64b; c <= 0x652; c++) { FOLD[C(c)] = ""; }
  FOLD[C(0x670)] = FOLD[C(0x640)] = FOLD[C(0x200c)] = "";
  function fold(s) {
    s = (s.normalize ? s.normalize("NFKC") : s).toLowerCase();
    var out = "";
    for (var k = 0; k < s.length; k++) {
      var ch = s.charAt(k);
      out += Object.prototype.hasOwnProperty.call(FOLD, ch) ? FOLD[ch] : ch;
    }
    return out;
  }
  var texts = [];
  for (var s = 0; s < segEls.length; s++) {
    var spk = segEls[s].querySelector(".spk");
    texts.push(fold(segEls[s].querySelector(".txt").textContent +
                    (spk ? " " + spk.textContent : "")));
  }
  var bar = document.getElementById("wts-search");
  var q = document.getElementById("wts-q");
  var count = document.getElementById("wts-count");
  var hits = [], cur = -1;
  function clearHits() {
    for (var h = 0; h < hits.length; h++) { segEls[hits[h]].classList.remove("hit", "cur-hit"); }
    hits = []; cur = -1;
  }
  function show(step) {
    if (!hits.length) { count.textContent = q.value.trim() ? "No matches" : ""; return; }
    if (cur >= 0) { segEls[hits[cur]].classList.remove("cur-hit"); }
    cur = (cur + step + hits.length) % hits.length;
    var el = segEls[hits[cur]];
    el.classList.add("cur-hit");
    el.scrollIntoView({block: "center"});
    count.textContent = (cur + 1) + " / " + hits.length;
  }
  function search() {
    clearHits();
    var needle = fold(q.value.trim());
    if (needle) {
      for (var i = 0; i < texts.length; i++) {
        if (texts[i].indexOf(needle) >= 0) { hits.push(i); segEls[i].classList.add("hit"); }
      }
    }
    show(1);
  }
  q.addEventListener("input", search);
  q.addEventListener("keydown", function (ev) {
    if (ev.key === "Enter" && !ev.isComposing) {
      ev.preventDefault();
      show(ev.shiftKey ? -1 : 1);
    }
  });
  document.getElementById("wts-next").addEventListener("click", function () { show(1); });
  document.getElementById("wts-prev").addEventListener("click", function () { show(-1); });
  bar.hidden = false;
})();
"""
