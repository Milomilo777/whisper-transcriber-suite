"""The repo hygiene gate refuses deny-listed paths and an oversized root, and accepts this repo."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "tools" / "check_repo_hygiene.py"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _run(repo: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(SCRIPT), str(repo)], capture_output=True, text=True)


def _make_repo(tmp_path: Path, files: list[str]) -> Path:
    _git(tmp_path, "init", "-q")
    for rel in files:
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x\n", encoding="utf-8")
    _git(tmp_path, "add", "-f", "--", *files)
    return tmp_path


def test_clean_scratch_repo_passes(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path, ["README.md", "app/x.py", "docs/INSTALL.md"])
    assert _run(repo).returncode == 0


@pytest.mark.parametrize("bad", [
    "OPENCODE_HANDOFF_1.md",
    "INTEGRATION_SUMMARY.md",
    "PROJECT_INDEX.md",
    ".project_index.json",
    ".cursorrules",
    "docs/history/old.md",
    "docs/roadmap/plan.md",
    "docs/reports/r.md",
    "docs/release-notes/v1.md",
    "docs/SESSION_LOG.md",
    "_local/notes.md",
    "CLAUDE.local.md",
    "docs/notes.local.md",
    ".claude/settings.json",
])
def test_deny_listed_path_is_refused(tmp_path: Path, bad: str) -> None:
    repo = _make_repo(tmp_path, ["README.md", bad])
    res = _run(repo)
    assert res.returncode == 1
    assert bad in res.stderr


def test_allowed_look_alikes_pass(tmp_path: Path) -> None:
    # Same words in other places or other extensions are fine.
    repo = _make_repo(tmp_path, [
        "docs/ROADMAP.md", "docs/integrations/README.md", "tests/core/test_session_log.py",
        "docs/history.md",
    ])
    assert _run(repo).returncode == 0


def test_oversized_root_is_refused(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path, [f"f{i}.txt" for i in range(25)])
    res = _run(repo)
    assert res.returncode == 1
    assert "root holds 25" in res.stderr


def test_root_at_the_limit_passes(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path, [f"f{i}.txt" for i in range(24)])
    assert _run(repo).returncode == 0


def test_gitlink_is_refused(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path, ["README.md"])
    sha = "1" * 40
    _git(repo, "update-index", "--add", "--cacheinfo", f"160000,{sha},vendor/lib")
    res = _run(repo)
    assert res.returncode == 1
    assert "gitlink" in res.stderr


def test_this_repo_passes() -> None:
    if not (ROOT / ".git").exists():
        pytest.skip("not a git checkout")
    res = _run(ROOT)
    assert res.returncode == 0, res.stderr


def test_ci_runs_the_hygiene_job() -> None:
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "tools/check_repo_hygiene.py" in text
    assert os.path.exists(SCRIPT)
