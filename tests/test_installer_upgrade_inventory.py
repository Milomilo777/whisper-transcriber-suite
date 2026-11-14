"""The overlay installer must not silently orphan removed packaged source."""
import os
from pathlib import Path
import subprocess
import sys

import pytest

TOOL = Path(__file__).resolve().parents[1] / "tools/check_installer_upgrade_files.py"


def git(repo, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    result = subprocess.run(["git", "-C", str(repo), *args], env=env,
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    return result.stdout


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-q")
    for name in ("app/old.py", "core/old.py", "gui.py", "sitecustomize.py", "docs/old.md"):
        file = tmp_path / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text("old payload\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
        "commit", "-qm", "Release fixture")
    git(tmp_path, "tag", "v2.3.1")
    return tmp_path


def check(repo):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    return subprocess.run([sys.executable, str(TOOL), "--repo", str(repo)],
                          capture_output=True, text=True, env=env, timeout=20)


@pytest.mark.parametrize("name", ["app/old.py", "core/old.py", "gui.py", "sitecustomize.py"])
def test_removed_packaged_file_blocks_overlay_upgrade(repo, name):
    (repo / name).unlink()
    result = check(repo)
    assert result.returncode == 1
    assert name in result.stdout
    assert "retired-file cleanup" in result.stdout


def test_renamed_packaged_file_still_leaves_old_destination(repo):
    (repo / "app/old.py").rename(repo / "app/new.py")
    git(repo, "add", "-A")
    result = check(repo)
    assert result.returncode == 1 and "app/old.py" in result.stdout


def test_additions_and_removed_documentation_do_not_block(repo):
    (repo / "docs/old.md").unlink()
    (repo / "app/new.py").write_text("new payload\n")
    result = check(repo)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "v2.3.1" in result.stdout


def test_newest_numeric_release_is_the_baseline(repo):
    (repo / "app/old.py").unlink()
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
        "commit", "-qm", "Later release fixture")
    git(repo, "tag", "v2.10.0")
    git(repo, "tag", "v9.0.0-preview")
    result = check(repo)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "v2.10.0" in result.stdout


def test_missing_release_history_fails_closed(repo):
    git(repo, "tag", "-d", "v2.3.1")
    result = check(repo)
    assert result.returncode == 2
    assert "release tags" in result.stderr
