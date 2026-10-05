"""docs/CODE_SIGNING.md keeps what the SignPath Foundation terms require, and stays true.

The terms (https://signpath.org/terms.html, "Conditions for the website / repository") ask for a
page headed "Code signing policy" that carries one fixed sentence, the team roles and a privacy
policy, linked by that name from the home page and the download/release pages. These tests pin
each of those, check that every link on the page resolves, and tie the page's claims to the files
that make them true (the installer name in installer_embed.iss, the "not signed yet" status that
README states too).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
POLICY = ROOT / "docs" / "CODE_SIGNING.md"
POLICY_URL = "https://github.com/Milomilo777/whisper-transcriber-suite/blob/master/docs/CODE_SIGNING.md"

REQUIRED_SENTENCE = "Free code signing provided by SignPath.io, certificate by SignPath Foundation"
_LINK = re.compile(r"\]\(([^)\s]+)\)")
_MD_LINK = re.compile(r"\[([^\]]+)\]\([^)\s]+\)")
_GITHUB_USER = re.compile(r"\[@[A-Za-z0-9-]+\]\(https://github\.com/[A-Za-z0-9-]+\)")


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _rendered(markdown: str) -> str:
    """The page text as a reader sees it: link targets dropped, whitespace collapsed."""
    return " ".join(_MD_LINK.sub(r"\1", markdown).split())


def _slug(heading: str) -> str:
    """GitHub's anchor for a markdown heading."""
    text = re.sub(r"[^\w\- ]", "", heading.strip().lower())
    return text.replace(" ", "-")


def _anchors(markdown: str) -> set[str]:
    return {_slug(m.group(1)) for m in re.finditer(r"^#+ (.+)$", markdown, re.M)}


def _section(markdown: str, heading: str) -> str:
    match = re.search(rf"^## {re.escape(heading)}\n(.*?)(?=^## |\Z)", markdown, re.M | re.S)
    assert match, f"no '## {heading}' section"
    return match.group(1)


@pytest.fixture(scope="module")
def page() -> str:
    return POLICY.read_text(encoding="utf-8")


def test_page_is_headed_code_signing_policy(page):
    assert re.search(r"^# Code signing policy$", page, re.M)


def test_required_sentence_is_present_verbatim(page):
    assert REQUIRED_SENTENCE in _rendered(page)


def test_team_roles_name_github_members(page):
    roles = _section(page, "Team roles")
    for role in ("Committers and reviewers:", "Approvers:"):
        line = next((ln for ln in roles.splitlines() if role in ln), "")
        assert _GITHUB_USER.search(line), f"'{role}' names no GitHub member"


def test_privacy_section_links_the_network_and_statistics_docs(page):
    privacy = _section(page, "Privacy policy")
    assert "CONFIG.md#network-use" in privacy
    assert "CONFIG.md#usage-statistics-p4-4" in privacy


def test_relative_links_resolve(page):
    own = _anchors(page)
    for target in _LINK.findall(page):
        if target.startswith(("http://", "https://", "mailto:")):
            continue
        path, _, anchor = target.partition("#")
        if not path:
            assert anchor in own, f"no heading for in-page link #{anchor}"
            continue
        resolved = (POLICY.parent / path).resolve()
        assert resolved.exists(), f"broken link {target}"
        if anchor:
            assert anchor in _anchors(resolved.read_text(encoding="utf-8")), (
                f"no heading #{anchor} in {path}"
            )


def test_signed_installer_name_matches_the_inno_script(page):
    base = re.search(r"^OutputBaseFilename=(.+)$", _read("installer_embed.iss"), re.M)
    assert base, "installer_embed.iss has no OutputBaseFilename"
    expected = base.group(1).strip().replace("{#MyAppVersion}", "X.Y.Z") + ".exe"
    assert f"`{expected}`" in _section(page, "What is signed")


def test_unsigned_status_agrees_with_readme(page):
    page_says_unsigned = "not code-signed yet" in _rendered(page)
    readme_says_unsigned = "The Windows builds are not code-signed" in " ".join(
        _read("README.md").split()
    )
    assert page_says_unsigned == readme_says_unsigned


def test_home_download_and_release_pages_link_the_policy():
    assert "[Code signing policy](docs/CODE_SIGNING.md)" in _read("README.md")
    site = _read("site/index.html")
    download = site[site.index('id="download"'):site.index('id="compare"')]
    assert f'<a href="{POLICY_URL}" rel="noopener">Code signing policy</a>' in download
    release_notes = _section(_read("docs/RELEASE_PROCESS.md"), "Step 3 — Write release notes")
    assert "Code signing policy" in release_notes and "CODE_SIGNING.md" in release_notes
    assert "(CODE_SIGNING.md)" in _read("docs/README.md")
