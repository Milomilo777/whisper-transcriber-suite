"""docs/COMPARISON.md and the site's compare section must stay honest and linked.

The WTS column is checked against the code (version, engines, output formats),
every relative link in the page must resolve (file and heading anchor), every
rival fact table row must carry a source URL, the page and the site section
must carry the same check date, and neither may use superlatives.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

import core
from core.backends.availability import ENGINE_CHOICES
from core.writers import supported_formats

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
COMPARISON_MD = DOCS / "COMPARISON.md"
SITE_INDEX = ROOT / "site" / "index.html"
COMPARISON_URL = (
    "https://github.com/Milomilo777/whisper-transcriber-suite/blob/master/docs/COMPARISON.md"
)

# How each engine in the picker is named on the comparison page. A new engine
# in ENGINE_CHOICES fails the engine test until it is added here and on the page.
ENGINE_NAMES = {
    "faster_whisper": "faster-whisper",
    "whisper_cpp": "whisper.cpp",
    "nvidia_asr": "NVIDIA Parakeet",
    "cloud_stt": "Gemini API",
    "google_cloud_stt": "Google Cloud Speech-to-Text",
}

RIVALS = ("Subtitle Edit", "Vibe", "Buzz", "noScribe", "aTrain")

_SUPERLATIVES = re.compile(
    r"\b(best|fastest|easiest|cheapest|leading|unmatched|unrivall?ed|superior|"
    r"ultimate|perfect|world[- ]class|number one|"
    r"most (accurate|powerful|advanced|complete|popular|private))\b",
    re.I,
)
_LINK = re.compile(r"\]\(([^)\s]+)\)")


def _slug(heading: str) -> str:
    """GitHub's anchor for a markdown heading."""
    text = re.sub(r"[^\w\- ]", "", heading.strip().lower())
    return text.replace(" ", "-")


def _anchors(markdown: str) -> set[str]:
    return {_slug(m.group(1)) for m in re.finditer(r"^#+ (.+)$", markdown, re.M)}


def _section(markdown: str, heading: str) -> str:
    """Text under ``heading`` up to the next heading of the same or higher level."""
    lines = markdown.splitlines()
    level = len(heading) - len(heading.lstrip("#"))
    start = lines.index(heading)
    out: list[str] = []
    for line in lines[start + 1:]:
        m = re.match(r"(#+) ", line)
        if m and len(m.group(1)) <= level:
            break
        out.append(line)
    return "\n".join(out)


def _row(markdown: str, first_cell: str) -> list[str]:
    for line in markdown.splitlines():
        if line.startswith(f"| {first_cell} |"):
            return [c.strip() for c in line.strip().strip("|").split("|")]
    raise AssertionError(f"no table row {first_cell!r} in docs/COMPARISON.md")


@pytest.fixture(scope="module")
def page() -> str:
    return COMPARISON_MD.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def site_section() -> str:
    html = SITE_INDEX.read_text(encoding="utf-8")
    m = re.search(r'<section class="section compare".*?</section>', html, re.S)
    assert m, "site/index.html has no compare section"
    return m.group(0)


def test_relative_links_resolve(page):
    own = _anchors(page)
    checked = 0
    for target in _LINK.findall(page):
        if target.startswith(("http://", "https://", "mailto:")):
            continue
        path, _, anchor = target.partition("#")
        if not path:
            assert anchor in own, f"no heading for in-page link #{anchor}"
            checked += 1
            continue
        resolved = (DOCS / path).resolve()
        assert resolved.exists(), f"broken link {target} -> {resolved}"
        if anchor:
            assert resolved.suffix == ".md", f"anchor on a non-markdown target {target}"
            assert anchor in _anchors(resolved.read_text(encoding="utf-8")), (
                f"no heading #{anchor} in {path}"
            )
        checked += 1
    assert checked >= 15  # the WTS source table alone links about 20 files


def test_check_date_matches_site(page, site_section):
    m = re.search(r"^Last checked: (\d{4}-\d{2}-\d{2})$", page, re.M)
    assert m, "docs/COMPARISON.md has no 'Last checked: YYYY-MM-DD' line"
    assert f"Checked {m.group(1)}" in site_section


def test_wts_version_matches_code(page):
    glance = _row(page, "Latest stable version")
    assert glance[1].startswith(f"v{core.__version__} "), glance[1]
    assert f"| Version {core.__version__} |" in page


def test_every_engine_is_named(page):
    cell = _row(page, "Speech engines")[1]
    for _, value in ENGINE_CHOICES:
        assert value in ENGINE_NAMES, f"engine {value!r} is missing from docs/COMPARISON.md"
        assert ENGINE_NAMES[value] in cell, f"{ENGINE_NAMES[value]!r} not in the WTS cell"


def test_output_format_count_matches_code(page, site_section):
    # smtv_docx is a project-specific layout of the docx output, not a format of its own.
    count = len(set(supported_formats()) - {"smtv_docx"})
    assert f"{count} output formats" in page
    assert f"{count} output formats" in site_section


def test_every_rival_fact_row_has_a_source(page):
    header = next(line for line in page.splitlines() if line.startswith("| | "))
    cells = [c.strip() for c in header.strip().strip("|").split("|")]
    assert cells[1:] == ["Whisper Transcriber Suite", *RIVALS]
    sources = _section(page, "## Sources for the other apps")
    for rival in RIVALS:
        rows = [
            line for line in _section(sources, f"### {rival}").splitlines()
            if line.startswith("| ") and not line.startswith(("| Fact |", "|---"))
        ]
        assert len(rows) >= 4, f"too few source rows for {rival}"
        for line in rows:
            assert "https://" in line, f"{rival}: source row without a URL: {line}"


def test_no_superlatives(page, site_section):
    for name, text in (("docs/COMPARISON.md", page), ("site compare section", site_section)):
        hit = _SUPERLATIVES.search(text)
        assert hit is None, f"superlative {hit.group(0)!r} in {name}"


def test_site_and_hub_link_the_page(site_section):
    assert COMPARISON_URL in site_section
    for rival in RIVALS[:3]:
        assert f'<th scope="col">{rival}</th>' in site_section
    hub = (DOCS / "README.md").read_text(encoding="utf-8")
    assert "](COMPARISON.md)" in hub
