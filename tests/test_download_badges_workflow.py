"""Exercise the workflow shell step with a fake generator and a local Git remote."""
import os
from pathlib import Path
import shutil
import subprocess
from textwrap import dedent

import pytest


WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/download-badges.yml"


def git(repo, *args):
    return subprocess.check_output(["git", *args], cwd=repo, text=True, timeout=30).strip()


@pytest.fixture
def repos(tmp_path):
    bash = shutil.which("bash")
    if os.name == "nt":
        git_bash = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Git/bin/bash.exe"
        if git_bash.is_file():
            bash = str(git_bash)
    if not bash or not shutil.which("git"):
        pytest.skip("Git and Bash are required to exercise the workflow step")

    remote = tmp_path / "remote.git"
    work = tmp_path / "work"
    git(tmp_path, "init", "--bare", "--initial-branch=master", str(remote))
    git(tmp_path, "clone", str(remote), str(work))
    git(work, "config", "user.name", "Test Author")
    git(work, "config", "user.email", "test@example.invalid")
    git(work, "commit", "--allow-empty", "-m", "Initial commit")
    git(work, "push", "origin", "master")
    return bash, work, remote


def refresh(repos, extra="", *, shell_setup=""):
    bash, work, _ = repos
    step = dedent(WORKFLOW.read_text(encoding="utf-8").split("        run: |\n", 1)[1])
    generator = dedent('''\
        python() {
          [[ "$1" == tools/download_badges.py && "$2" == test/repo && "$3" == docs/badges ]] || return 10
          mkdir -p -- "$3"
          printf '<svg/>\\n' > "$3/total.svg"
    ''') + f"  {extra}\n}}\n"
    return subprocess.run(
        [bash, "-s"], input=generator + shell_setup + "\n" + step,
        env={**os.environ, "GITHUB_REPOSITORY": "test/repo"}, cwd=work,
        text=True, capture_output=True, timeout=60,
    )


def test_workflow_pushes_badges_after_master_advances(repos, tmp_path):
    _, _, remote = repos
    concurrent = tmp_path / "concurrent"
    git(tmp_path, "clone", str(remote), str(concurrent))
    (concurrent / "unrelated.txt").write_text("concurrent change", encoding="utf-8")
    git(concurrent, "add", "unrelated.txt")
    git(concurrent, "-c", "user.name=Test Author", "-c", "user.email=test@example.invalid",
        "commit", "-m", "Concurrent change")
    git(concurrent, "push", "origin", "master")

    result = refresh(repos)
    assert result.returncode == 0, result.stderr
    assert git(remote, "rev-parse", "master^") == git(concurrent, "rev-parse", "HEAD")
    assert git(remote, "diff-tree", "--no-commit-id", "--name-only", "-r", "master") == "docs/badges/total.svg"
    assert git(remote, "log", "-1", "--format=%an %s", "master").startswith("github-actions[bot] [skip ci] ")

    latest = git(remote, "rev-parse", "master")
    noop = refresh(repos)
    assert noop.returncode == 0, noop.stderr
    assert git(remote, "rev-parse", "master") == latest


@pytest.mark.parametrize("extra", ["touch unrelated.txt", "touch unrelated.txt; git add unrelated.txt"])
def test_workflow_refuses_unrelated_changes(repos, extra):
    _, _, remote = repos
    result = refresh(repos, extra)
    assert result.returncode != 0
    assert "outside docs/badges/" in result.stderr
    assert git(remote, "log", "-1", "--format=%s", "master") == "Initial commit"


def test_workflow_does_not_publish_after_generator_failure(repos):
    _, _, remote = repos
    result = refresh(repos, "return 31")
    assert result.returncode == 31
    assert git(remote, "log", "-1", "--format=%s", "master") == "Initial commit"


def test_workflow_refuses_to_replay_a_replaced_master_history(repos):
    _, _, remote = repos
    original = git(remote, "rev-parse", "master")
    replacement = git(remote, "-c", "user.name=Test Author", "-c", "user.email=test@example.invalid",
                      "commit-tree", "master^{tree}", "-m", "Replacement history")
    git(remote, "update-ref", "refs/heads/master", replacement, original)

    result = refresh(repos)
    assert result.returncode != 0
    assert "master history changed" in result.stderr
    assert git(remote, "rev-parse", "master") == replacement


def test_workflow_limits_push_attempts(repos):
    _, _, remote = repos
    result = refresh(repos, shell_setup=dedent('''\
        git() {
          if [[ "$1" == push ]]; then
            echo 'simulated rejected push' >&2
            return 43
          fi
          command git "$@"
        }
    '''))
    assert result.returncode != 0
    assert result.stderr.count("simulated rejected push") == 3
    assert git(remote, "log", "-1", "--format=%s", "master") == "Initial commit"
