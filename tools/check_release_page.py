"""Offline checks for the release notes, website and promo animation."""
from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
if not __package__:
    sys.path.insert(0, str(ROOT))

from core.updates import release_headline, release_highlights
from tools.check_public_release import check_release_notes, release_placeholders

LANGUAGES = "en ar bg bn ca cs da de el es fa fi fil fr he hi hr hu id it ja ko lt lv ms nb nl pl pt pt-br ro ru sk sl sr sv th tr uk vi zh-cn zh-tw".split()
SITE_VERSION = "2.5.0"
SITE_RELEASED = "2026-11-26"
FEATURES = ["audio-track", "media-recovery", "transcript-edits"]
SITE_SIZES = {
    "size-installer": "241 MB",
    "size-portable": "360 MB",
    "size-mac-arm64": "279 MB",
    "size-mac-x64": "305 MB",
}
RELEASE = "https://github.com/Milomilo777/whisper-transcriber-suite/releases/"
BADGES = "https://raw.githubusercontent.com/Milomilo777/whisper-transcriber-suite/master/docs/badges/"
SITE_DOWNLOAD = f"{RELEASE}download/v{SITE_VERSION}/WhisperTranscriberSuite-"
SITE_FILES = {
    "installer": f"Installer-Windows-v{SITE_VERSION}.exe",
    "portable": f"Portable-Windows-v{SITE_VERSION}.zip",
    "mac-arm64": f"v{SITE_VERSION}-macOS-arm64.dmg",
    "mac-x64": f"v{SITE_VERSION}-macOS-x64.dmg",
}


def check_release_artifacts(notes: str, *, allow_draft: bool = False) -> None:
    """Validate the public download table without publishing build identities."""
    check_release_notes(notes, allow_draft=allow_draft)
    rows = [line for line in notes.splitlines() if line.startswith("| [")]
    assert len(rows) == 4, "expected four release artifact rows"
    for row, kind in zip(rows, ("INSTALLER", "PORTABLE", "ARM64", "X64")):
        cells = [part.strip() for part in row.strip("|").split("|")]
        assert len(cells) == 3, "artifact row must contain file, platform and size only"
        is_size = re.fullmatch(r"[1-9][0-9]* (?:B|KB|MB|GB)", cells[2])
        assert is_size or (allow_draft and cells[2] == f"SIZE_{kind}"), "invalid artifact size"


def check_release_page_250(notes: str) -> tuple[str, ...]:
    notes = notes.replace("\r\n", "\n").replace("\r", "\n")
    check_release_artifacts(notes, allow_draft=True)
    assert len(notes) <= 5300, "release body exceeds 5,300 characters"
    assert re.search(r"^Released (?:RELEASE_DATE|\d{4}-\d{2}-\d{2})\.$", notes, re.M), "missing release date"

    headline = notes.splitlines()[0].replace("**", "")
    assert release_headline(notes) == headline and 0 < len(headline) <= 160, "headline changes in the update bar"
    section = re.search(r"^## What's new in 2\.5\n(.*?)(?=^## |\Z)", notes, re.M | re.S)
    assert section, "missing 2.5 highlights"
    bullets = re.findall(r"^(?:[-+*]|\d+[.)]) .+$", section[1], re.M)
    assert 3 <= len(bullets) <= 7 and all(re.match(r"- \*\*[^*]+\*\* .+", bullet) for bullet in bullets), "invalid highlight bullets"
    assert release_highlights(notes) == tuple(bullet[2:].replace("**", "") for bullet in bullets[:3]), "highlights change in the update bar"

    for alt, filename, target in (("downloads", "total.svg", RELEASE.rstrip("/")),
                                  ("v2.5.0 downloads", "v2.5.0-this-version.svg", RELEASE + "tag/v2.5.0")):
        assert f"[![{alt}]({BADGES}{filename})]({target})" in notes, f"missing badge: {filename}"
    files = ("Installer-Windows-v2.5.0.exe", "Portable-Windows-v2.5.0.zip",
             "v2.5.0-macOS-arm64.dmg", "v2.5.0-macOS-x64.dmg")
    for row, filename in zip((line for line in notes.splitlines() if line.startswith("| [")), files):
        assert f"]({RELEASE}download/v2.5.0/WhisperTranscriberSuite-{filename})" in row, f"invalid download: {filename}"
    return release_placeholders(notes)


def animation_timing(svg: str) -> dict:
    """Read each property's holds, including steps(1,end) jumps, in CSS order."""
    declarations = re.findall(r"(?<![\w-])animation\s*:\s*([^;{}]+)", svg)
    durations = {float(v) for declaration in declarations
                 for v in re.findall(r"\b([\d.]+)s\b", declaration)}
    assert len(durations) == 1, f"inconsistent animation cycles: {durations}"
    cycle = durations.pop()
    result = {}
    for match in re.finditer(r"@keyframes\s+(\w+)\s*\{", svg):
        start, depth, end = match.end(), 1, match.end()
        while depth:
            assert end < len(svg), "unterminated keyframes"
            depth += (svg[end] == "{") - (svg[end] == "}")
            end += 1
        tracks = {}
        for frame in re.finditer(r"([^{}]+)\{([^{}]*)\}", svg[start:end - 1]):
            props = dict(re.findall(r"([\w-]+)\s*:\s*([^;]+)", frame[2]))
            step = bool(re.search(r"steps\(1,\s*end\)", props.pop("animation-timing-function", "")))
            for percent in re.findall(r"([\d.]+)%", frame[1]):
                for prop, value in props.items():
                    tracks.setdefault(prop, []).append((float(percent), value.strip(), step))
        for prop, frames in tracks.items():
            frames.sort(key=lambda f: f[0])
            holds = []
            for left, right in zip(frames, frames[1:]):
                if left[1] == right[1] or left[2]:
                    holds.append({"start": left[0], "end": right[0],
                                  "seconds": (right[0] - left[0]) * cycle / 100})
            result[f"{match[1]}/{prop}"] = holds
    assert result, "no animation tracks found"
    return {"cycle": cycle, "tracks": result}


def check_svg(svg: str, baseline: dict) -> None:
    root = ET.fromstring(svg)
    assert len(svg.encode("utf-8")) < 90000, "SVG size exceeds 90 KB"
    assert root.tag == "{http://www.w3.org/2000/svg}svg"
    assert "prefers-reduced-motion: reduce" in svg
    assert not any(el.tag.rsplit("}", 1)[-1] in {"script", "foreignObject", "image"} for el in root.iter())
    for url in re.findall(r"url\((.*?)\)", svg):
        assert url.startswith(("#", "data:")), f"external resource: {url}"
    for el in root.iter():
        for attr, value in el.attrib.items():
            assert not attr.lower().startswith("on"), "event handler in SVG"
            if attr.rsplit("}", 1)[-1] == "href":
                assert value.startswith(("#", "data:")), "external SVG href"
    current = animation_timing(svg)
    assert current["cycle"] >= max(33.6, baseline["cycle"]), "cycle is shorter"
    assert current["tracks"].keys() == baseline["tracks"].keys(), "animation tracks changed"
    for name, old in baseline["tracks"].items():
        new = current["tracks"][name]
        assert len(new) == len(old), f"hold count changed: {name}"
        for index, (before, after) in enumerate(zip(old, new)):
            assert after["seconds"] + 1e-8 >= before["seconds"], f"shortened hold: {name}[{index}]"


class Page(HTMLParser):
    """Parse HTML, collecting release structure and offline link targets."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.features = []
        self.links = []
        self.downloads = {}
        self.ids = []
        self.tags = []
        self.blocks = 0
        self.lang = None
        self.stack = []
        self.release_depth = None
        self.article_depth = None
        self.headings = []
        self.release_headings = 0
        self.whats_new_depth = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        self.tags.append(tag)
        void = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
        if tag not in void:
            self.stack.append(tag)
        if tag == "html":
            self.lang = a.get("lang", "").lower()
        if "id" in a:
            self.ids.append(a["id"])
        if tag == "section" and a.get("id") == "whats-new":
            self.whats_new_depth = len(self.stack)
        if a.get("data-release") == SITE_VERSION:
            assert self.whats_new_depth is not None, "release block outside whats-new section"
            self.blocks += 1
            self.release_depth = len(self.stack)
        if "data-release-feature" in a:
            assert self.release_depth is not None and tag == "article", "feature outside release section"
            self.features.append(a["data-release-feature"])
            self.headings.append(0)
            self.article_depth = len(self.stack)
        if self.release_depth is not None and tag == "h2":
            self.release_headings += 1
        if self.article_depth is not None and tag == "h3":
            self.headings[-1] += 1
        if tag == "a" and "data-auto-href" in a:
            self.downloads.setdefault(a["data-auto-href"], []).append(a.get("href"))
        for key in ("href", "src", "data-still", "data-anim", "poster"):
            if a.get(key):
                self.links.append(a[key])

    def handle_endtag(self, tag):
        if tag in self.stack:
            depth = len(self.stack) - self.stack[::-1].index(tag)
            if self.article_depth is not None and depth <= self.article_depth:
                self.article_depth = None
            if self.release_depth is not None and depth <= self.release_depth:
                self.release_depth = None
            if self.whats_new_depth is not None and depth <= self.whats_new_depth:
                self.whats_new_depth = None
            del self.stack[depth - 1:]


def check_page(html: str, lang: str, site: Path, relative: Path) -> None:
    page = Page()
    page.feed(html)
    page.close()
    assert not page.stack, f"unclosed HTML elements: {lang}"
    assert page.lang == lang, f"wrong HTML language: {lang}"
    assert page.tags.count("html") == 1 and page.tags.count("body") == 1
    assert len(page.ids) == len(set(page.ids)), f"duplicate IDs: {lang}"
    assert page.blocks == 1 and page.features == FEATURES, f"missing {SITE_VERSION} feature block: {lang}"
    assert page.release_headings == 1 and page.headings == [1, 1, 1], f"release structure differs: {lang}"
    assert f'<h2 id="new-title">{SITE_VERSION}</h2>' in html, f"wrong release heading: {lang}"
    assert f'"softwareVersion": "{SITE_VERSION}"' in html, f"wrong structured version: {lang}"
    assert f'"dateModified": "{SITE_RELEASED}"' in html, f"wrong structured release date: {lang}"
    assert "macOS 12 or later (Intel build) or macOS 14 or later (Apple Silicon build)" in html
    expected = {"version": f"v{SITE_VERSION}", "released": SITE_RELEASED, **SITE_SIZES}
    for key, value in expected.items():
        matches = re.findall(rf'data-auto="{key}"[^>]*>([^<]*)', html)
        values = [" ".join(unescape(match).split()).removeprefix("~") for match in matches]
        assert values == [value] * (2 if key == "version" else 1), f"unverified {key}: {lang}"
    command = re.search(r'data-auto="mac-oneliner"[^>]*>([^<]*)', html)
    assert command and SITE_DOWNLOAD + f"v{SITE_VERSION}-macOS-$A.dmg" in command[1], f"wrong Mac command: {lang}"
    assert page.downloads == {
        key: [SITE_DOWNLOAD + name] * (2 if key == "installer" else 1) for key, name in SITE_FILES.items()
    }, f"wrong download markers: {lang}"
    assert "2.3.1" not in html and "2.4.0" not in html, f"old current version: {lang}"
    for link in page.links:
        u = urlsplit(link)
        if u.netloc == "whisper-transcriber-suite.com":
            target = site / unquote(u.path).lstrip("/")
            if target.is_dir():
                target /= "index.html"
            assert target.is_file(), f"missing site URL: {link} ({lang})"
            continue
        if link.startswith("https://github.com/Milomilo777/whisper-transcriber-suite/blob/master/"):
            target = site.parent / unquote(u.path.split("/blob/master/", 1)[1])
            assert target.is_file(), f"missing repository document: {link} ({lang})"
            continue
        if u.scheme or u.netloc:
            if link.startswith(RELEASE + "download/"):
                assert link in {SITE_DOWNLOAD + name for name in SITE_FILES.values()}, f"wrong download: {link}"
            continue
        if not u.path:
            assert not u.fragment or u.fragment in page.ids, f"missing anchor: {link} ({lang})"
            continue
        target = site / unquote(u.path).lstrip("/") if u.path.startswith("/") else site / relative.parent / unquote(u.path)
        if target.is_dir():
            target /= "index.html"
        assert target.is_file(), f"missing local target: {link} ({lang})"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--baseline-svg", type=Path,
                        help="parse an original SVG instead of the hermetic timing fixture")
    args = parser.parse_args()
    root = args.root
    check_release_artifacts((root / "docs/releases/2.4.0.md").read_text(encoding="utf-8"))
    placeholders = check_release_page_250((root / "docs/releases/2.5.0.md").read_text(encoding="utf-8"))
    if placeholders:
        print(f"Draft 2.5.0 has unfilled release placeholders: {', '.join(placeholders)}")
    if args.baseline_svg:
        old_svg = args.baseline_svg.read_text(encoding="utf-8")
        ET.fromstring(old_svg)
        baseline = animation_timing(old_svg)
    else:
        baseline = json.loads((root / "tests/fixtures/promo-release-timing-2.3.1.json").read_text())
    check_svg((root / "docs/img/promo-release.svg").read_text(encoding="utf-8"), baseline)
    for lang in LANGUAGES:
        relative = Path("index.html") if lang == "en" else Path(lang) / "index.html"
        check_page((root / "site" / relative).read_text(encoding="utf-8"), lang, root / "site", relative)
    print(f"PASS: SVG ({sum(map(len, baseline['tracks'].values()))} holds), {len(LANGUAGES)} language home pages")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
