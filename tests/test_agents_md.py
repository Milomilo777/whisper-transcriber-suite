"""AGENTS.md is the single, tool-neutral source of the repo's agent rules.

Tool-specific files only import it, it stays short enough to read in one go,
and the guardrails that protect users and release history stay in it.
"""
from __future__ import annotations

import glob
import os

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(*parts: str) -> str:
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as fh:
        return fh.read()


AGENTS = _read("AGENTS.md")


def test_claude_md_only_imports_agents_md() -> None:
    assert _read("CLAUDE.md").strip() == "@AGENTS.md"


def test_no_separate_cursor_rules_file() -> None:
    # Cursor reads AGENTS.md itself; a second rules file drifts out of date.
    assert not os.path.exists(os.path.join(ROOT, ".cursorrules"))


def test_agents_md_stays_short() -> None:
    assert len(AGENTS.splitlines()) <= 200


def test_agents_md_is_english_only() -> None:
    assert not [ch for ch in AGENTS if 0x0590 <= ord(ch) <= 0x08FF]


@pytest.mark.parametrize("needle", [
    "pyright app core",                                     # type-check gate
    "python -m pytest tests/ --ignore=tests/smoke",         # hermetic suite
    "explicit go-ahead",                                    # releases
    "Never delete a published GitHub release",
    "`v1.0.3` and later are public",                        # published tags
    "--clobber",                                            # asset re-upload
    "delete-asset",
    "per-version download badge",
    "docs/MACOS_BUILD_NOTES.md",                            # macOS builds
    "real macOS system",
    "Persist completed work before reporting success",
    "# Adapted from <ProjectName> (<URL>)",
    "whisper_project_mac.spec",                             # spec lock-step
])
def test_agents_md_keeps_guardrail(needle: str) -> None:
    assert needle in AGENTS


def test_docs_point_to_agents_md_for_rules() -> None:
    # CLAUDE.md holds no rules any more, so a pointer to it is a dead end.
    paths = glob.glob(os.path.join(ROOT, "docs", "**", "*.md"), recursive=True)
    paths += [os.path.join(ROOT, name) for name in ("README.md", "CONTRIBUTING.md")]
    paths.append(os.path.join(ROOT, "platform", "macos", "pyinstaller",
                              "whisper_project_mac.spec"))
    stale = [
        os.path.relpath(p, ROOT) for p in paths
        if os.path.basename(p) != "CHANGELOG.md"
        and "CLAUDE.md" in _read(os.path.relpath(p, ROOT))
    ]
    assert stale == []
