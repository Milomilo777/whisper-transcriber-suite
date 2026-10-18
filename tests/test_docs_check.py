"""tools/docs_check.py over the repo's Markdown: no broken relative links, no control characters,
and well-formed records under docs/{decisions,experiments,investigations,proposals}/.

Only tracked files count. In a git checkout the local, git-ignored layer (notes, build logs) is
filtered out with `git ls-files`; a `git archive` copy holds nothing else to begin with.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load():
    spec = importlib.util.spec_from_file_location("docs_check", ROOT / "tools" / "docs_check.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["docs_check"] = mod
    spec.loader.exec_module(mod)
    return mod


dc = _load()


def _tracked_markdown() -> set[str] | None:
    """Tracked *.md paths (forward slashes), or None when this is not a git checkout."""
    if not (ROOT / ".git").exists():
        return None
    try:
        out = subprocess.run(
            ["git", "ls-files", "-z", "--", "*.md"],
            cwd=ROOT, capture_output=True, check=True, timeout=60,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    return {p.decode("utf-8") for p in out.split(b"\0") if p}


def _problem_path(problem: str) -> str:
    return problem.split(":", 1)[0].replace("\\", "/")


def test_repo_markdown_passes_docs_check() -> None:
    problems, _ = dc.check(ROOT)
    tracked = _tracked_markdown()
    if tracked is not None:
        # record-register problems name docs/ paths, which are tracked too
        problems = [p for p in problems if _problem_path(p) in tracked]
    assert problems == []


def test_docs_check_catches_a_broken_link_and_a_control_character(tmp_path: Path) -> None:
    (tmp_path / "target.md").write_text("# Target\n", encoding="utf-8")
    (tmp_path / "good.md").write_text("[ok](target.md) and [anchor](target.md#top)\n", encoding="utf-8")
    (tmp_path / "bad.md").write_text("[gone](missing.md)\nstray\x01char\n", encoding="utf-8")
    problems, _ = dc.check(tmp_path)
    assert sorted(problems) == ["bad.md: broken link -> missing.md", "bad.md:2: control character or U+FFFD"]


def test_docs_check_ignores_links_inside_code(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("`[x](nope.md)`\n\n```\n[y](nope.md)\n```\n", encoding="utf-8")
    assert dc.check(tmp_path)[0] == []


def test_problem_path_handles_both_separators() -> None:
    assert _problem_path("docs\\BUILD.md: broken link -> x.md") == "docs/BUILD.md"
    assert _problem_path("docs/BUILD.md:12: control character or U+FFFD") == "docs/BUILD.md"
