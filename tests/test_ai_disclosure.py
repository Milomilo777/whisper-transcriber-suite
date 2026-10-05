"""The AI-assistance disclosure stays true, and .mailmap keeps one identity per person.

README and CONTRIBUTING say how the project is built; these tests tie each claim to the file
that makes it true (the CI workflow, the release checklist, AGENTS.md), so the text cannot
drift into a promise the repo no longer keeps.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

TRAILER_RULE = "Assisted-by: <model name> (<vendor>)"
NOREPLY = re.compile(r"^\d+\+[A-Za-z0-9-]+@users\.noreply\.github\.com$")
MAINTAINER_ALIAS = "Milomilo777 <117558067+Milomilo777@users.noreply.github.com>"


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _mailmap_lines() -> list[str]:
    lines = []
    for raw in _read(".mailmap").splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            lines.append(line)
    return lines


def test_agents_md_states_the_trailer_rule() -> None:
    agents = " ".join(_read("AGENTS.md").split())
    assert TRAILER_RULE in agents
    assert "No `Co-Authored-By:` line for an AI" in agents


@pytest.mark.parametrize("rel", ["README.md", "CONTRIBUTING.md"])
def test_disclosure_is_present(rel: str) -> None:
    text = " ".join(_read(rel).split())
    assert "heavy help from AI coding assistants" in text
    assert "`Assisted-by:`" in text
    # CI runs on the pushed commit; claiming it runs before the push would be false.
    assert "CI runs them again on Windows and Linux after every push" in text
    assert "docs/RELEASE_PROCESS.md" in text


def test_ci_claim_matches_the_workflow() -> None:
    ci = _read(".github/workflows/ci.yml")
    on_push = re.search(r"^on:\s*\n\s+push:\s*\n\s+branches:\s*\[([^\]]*)\]", ci, re.MULTILINE)
    assert on_push and "master" in on_push.group(1), "ci.yml no longer runs on a push to master"
    matrix = re.search(r"^\s+os:\s*\[([^\]]*)\]", ci, re.MULTILINE)
    assert matrix, "ci.yml lost its OS matrix"
    oses = {o.strip() for o in matrix.group(1).split(",")}
    assert {"windows-latest", "ubuntu-latest"} <= oses
    assert "python -m pyright app core" in ci
    assert "pytest tests/ --ignore=tests/smoke" in ci


def test_release_checklist_has_a_manual_install_test() -> None:
    assert re.search(r"^## Step \d+ — Manual install", _read("docs/RELEASE_PROCESS.md"), re.MULTILINE)


def test_mailmap_holds_only_github_noreply_addresses() -> None:
    # Tracked files carry no personal email address; GitHub no-reply addresses are public by design.
    addresses = [a for line in _mailmap_lines() for a in re.findall(r"<([^>]*)>", line)]
    assert addresses
    assert [a for a in addresses if not NOREPLY.match(a)] == []


def test_mailmap_maps_to_the_license_holder() -> None:
    holder = re.search(r"^Copyright \(c\) \d{4} (\S+)", _read("LICENSE"), re.MULTILINE)
    assert holder
    for line in _mailmap_lines():
        assert line.startswith(f"{holder.group(1)} <"), line


def test_git_merges_the_maintainer_alias() -> None:
    git = shutil.which("git")
    if git is None or not (ROOT / ".git").exists():
        pytest.skip("not a git checkout")
    out = subprocess.run(
        [git, "-C", str(ROOT), "check-mailmap", MAINTAINER_ALIAS],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert out == "translation-robot <105587847+translation-robot@users.noreply.github.com>"
