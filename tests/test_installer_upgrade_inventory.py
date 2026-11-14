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


@pytest.mark.parametrize("later_tag", ["v2.10.0", "v2.4.0"])
def test_older_release_retirements_survive_newer_or_current_version_tag(repo, later_tag):
    (repo / "app/old.py").unlink()
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
        "commit", "-qm", "Later release fixture")
    git(repo, "tag", later_tag)
    git(repo, "tag", "v9.0.0-preview")
    result = check(repo)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "v2.3.1" in result.stdout
    assert "app/old.py" in result.stdout


def test_missing_release_history_fails_closed(repo):
    git(repo, "tag", "-d", "v2.3.1")
    result = check(repo)
    assert result.returncode == 2
    assert "release tags" in result.stderr


@pytest.mark.parametrize("name", ["core/backends/parakeet.py", "core/monitors.py", "core/tiling.py"])
def test_historical_retired_modules_ship_inert_overlay_replacements(name):
    """Retired code must be replaced without deleting user additions."""
    import ast
    file = TOOL.parents[1] / name
    assert file.is_file(), f"An upgrade would leave the historical implementation at {name}"
    tree = ast.parse(file.read_text(encoding="utf-8"))
    # These compatibility slots must not revive removed engines, windows,
    # dependency imports or subprocesses when an old consumer imports them.
    assert all(isinstance(node, (ast.Expr, ast.AnnAssign)) for node in tree.body)
    assert not any(isinstance(node, (ast.Call, ast.Import, ast.ImportFrom)) for node in ast.walk(tree))


@pytest.mark.parametrize("name", ["core/backends/parakeet.py", "core/monitors.py", "core/tiling.py"])
@pytest.mark.parametrize("cache_mode", ["TIMESTAMP", "CHECKED_HASH"])
def test_retired_cached_implementation_cannot_run_after_overlay(tmp_path, name, cache_mode):
    import importlib.util
    import py_compile
    replacement = TOOL.parents[1] / name
    installed = tmp_path / Path(name).name
    installed.write_text('raise RuntimeError("retired implementation executed")\n', encoding="utf-8")
    old = installed.stat()
    py_compile.compile(str(installed), doraise=True,
                       invalidation_mode=getattr(py_compile.PycInvalidationMode, cache_mode))
    installed.write_bytes(replacement.read_bytes())
    # Simulate an overlay preserving the old timestamp to the same second.
    os.utime(installed, ns=(old.st_atime_ns, old.st_mtime_ns))
    spec = importlib.util.spec_from_file_location("retired_overlay_fixture", installed)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.__all__ == ()
