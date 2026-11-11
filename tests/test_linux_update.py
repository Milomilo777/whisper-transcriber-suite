"""Run the Linux updater with fake Git and virtualenv commands only."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess

import pytest


def _bash() -> str:
    if os.name == "nt":
        git = shutil.which("git")
        if git:
            # Git for Windows exposes git.exe from cmd/, bin/ or ucrt64/bin/.
            for parent in Path(git).parents:
                candidate = parent / "bin" / "bash.exe"
                if candidate.is_file():
                    return str(candidate)
        pytest.skip("Git Bash is required to exercise the Linux updater on Windows")
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("Bash is required to exercise the Linux updater")
    return bash


def _shell_path(path: Path) -> str:
    value = path.as_posix()
    if os.name == "nt":
        return f"/{value[0].lower()}{value[2:]}"
    return value


def _write_script(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    path.chmod(0o755)


@pytest.fixture
def run_update(tmp_path):
    bash = _bash()
    root = tmp_path / "checkout with spaces"
    script = root / "platform" / "linux" / "update.sh"
    source = Path(__file__).resolve().parents[1] / "platform/linux/update.sh"
    _write_script(script, source.read_text(encoding="utf-8"))
    (root / "requirements.txt").write_text("", encoding="utf-8")
    trace = tmp_path / "trace.txt"
    fake_bin = tmp_path / "fake-bin"
    _write_script(fake_bin / "git", """#!/bin/bash
printf 'git:%s\\n' "$*" >> "$TRACE_FILE"
exit "$GIT_RESULT"
""")
    python = root / ".venv/bin/python"
    _write_script(python, """#!/bin/bash
printf 'python:%s\\n' "$*" >> "$TRACE_FILE"
if [ "$PIP_FAIL_AT" = wheel ] && [ "${*: -1}" = wheel ]; then exit 23; fi
if [ "$PIP_FAIL_AT" = requirements ] && [ "${*: -1}" = yt-dlp ]; then exit 23; fi
""")
    _write_script(root / ".venv/bin/activate", """printf 'activate\\n' >> "$TRACE_FILE"
export PATH="$FAKE_VENV_BIN:$PATH"
deactivate() { printf 'deactivate\\n' >> "$TRACE_FILE"; }
""")
    startup = tmp_path / "fake-commands.sh"
    _write_script(startup, """git() { "$FAKE_GIT" "$@"; }
python() { "$FAKE_PYTHON" "$@"; }
""")

    def run(*, checkout="directory", git_result=0, venv=True, pip_fail_at="none"):
        if checkout == "directory":
            (root / ".git").mkdir()
        elif checkout == "file":
            (root / ".git").write_text("gitdir: unused\n", encoding="utf-8")
        if not venv:
            python.unlink()
        env = {
            **os.environ,
            "PATH": f"{_shell_path(fake_bin)}:/usr/bin:/bin",
            "TRACE_FILE": _shell_path(trace),
            "FAKE_VENV_BIN": _shell_path(python.parent),
            "FAKE_GIT": _shell_path(fake_bin / "git"),
            "FAKE_PYTHON": _shell_path(python),
            "GIT_RESULT": str(git_result),
            "PIP_FAIL_AT": pip_fail_at,
            # Bind exact fake commands, independent of Git Bash's PATH setup.
            "BASH_ENV": _shell_path(startup),
            "ENV": "",
        }
        result = subprocess.run(
            [bash, "--noprofile", "--norc", _shell_path(script)],
            cwd=tmp_path, env=env, capture_output=True, text=True,
            encoding="utf-8", timeout=10,
        )
        events = trace.read_text(encoding="utf-8").splitlines() if trace.exists() else []
        return result, events

    return run


@pytest.mark.parametrize("checkout", ["directory", "file"])
def test_failed_pull_stops_before_virtualenv_activation(run_update, checkout):
    result, events = run_update(checkout=checkout, git_result=37)
    assert result.returncode == 37
    assert events == ["git:pull --ff-only"]
    assert "dependencies updated" not in result.stdout


@pytest.mark.parametrize("checkout", ["directory", "file", "none"])
def test_successful_update_preserves_dependency_steps(run_update, checkout):
    result, events = run_update(checkout=checkout)
    assert result.returncode == 0, result.stderr
    if checkout != "none":
        assert events.pop(0) == "git:pull --ff-only"
    assert events[0:2] == ["activate", "python:-m pip install --upgrade pip wheel"]
    assert events[2].startswith("python:-m pip install --upgrade -r ")
    assert events[2].endswith("/requirements.txt yt-dlp")
    assert events[3:] == ["deactivate"]
    assert "dependencies updated" in result.stdout


def test_missing_virtualenv_retains_failure(run_update):
    result, events = run_update(venv=False)
    assert result.returncode == 1
    assert events == ["git:pull --ff-only"]
    assert "no virtualenv found" in result.stderr


@pytest.mark.parametrize("pip_fail_at", ["wheel", "requirements"])
def test_dependency_failure_retains_exit_status(run_update, pip_fail_at):
    result, events = run_update(pip_fail_at=pip_fail_at)
    assert result.returncode == 23
    assert events[:2] == ["git:pull --ff-only", "activate"]
    assert len(events) == (3 if pip_fail_at == "wheel" else 4)
    assert all(event.startswith("python:-m pip install --upgrade ") for event in events[2:])
    assert "dependencies updated" not in result.stdout
