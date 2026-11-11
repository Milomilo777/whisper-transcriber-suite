"""A failed ffmpeg slice retains its process result and removes partial audio."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from core import failure_clue, transcriber as tr


@pytest.mark.parametrize("returncode,stderr", [(1, b"private input failed"), (-9, b""), (28, None)])
def test_nonzero_slice_keeps_process_cause(monkeypatch, tmp_path, returncode, stderr):
    seen = {}

    def run(cmd, **kwargs):
        seen["cmd"] = cmd
        Path(cmd[-1]).write_bytes(b"unfinished audio")
        return subprocess.CompletedProcess(cmd, returncode, b"private stdout", stderr)

    monkeypatch.setattr(tr.subprocess, "run", run)
    destination = tmp_path / "partials"
    with pytest.raises(RuntimeError, match="ffmpeg slice failed") as caught:
        tr._slice_audio_from(str(tmp_path / "private source.wav"), 12.0, destination)

    cause = caught.value.__cause__
    assert isinstance(cause, subprocess.CalledProcessError)
    assert cause.returncode == returncode
    assert cause.cmd == seen["cmd"]
    assert cause.output == b"private stdout"
    assert cause.stderr == stderr
    clue = failure_clue.worker_clue(caught.value, site="worker.prepare")
    assert clue["exception_family"] == "subprocess.CalledProcessError"
    assert clue["failure_site"] == "worker.prepare"
    assert "private" not in str(clue)
    assert not list(destination.iterdir())


@pytest.mark.parametrize("kind", ["timeout", "launch"])
def test_slice_launch_failures_keep_cause_and_cleanup(monkeypatch, tmp_path, kind):
    error = (subprocess.TimeoutExpired(["ffmpeg"], 600) if kind == "timeout"
             else PermissionError(13, "private denied"))

    def run(cmd, **kwargs):
        Path(cmd[-1]).write_bytes(b"unfinished audio")
        raise error

    monkeypatch.setattr(tr.subprocess, "run", run)
    destination = tmp_path / "partials"
    with pytest.raises(RuntimeError) as caught:
        tr._slice_audio_from("source.wav", 0.0, destination)
    assert caught.value.__cause__ is error
    assert not list(destination.iterdir())


def test_successful_slice_preserves_audio_and_bounded_command(monkeypatch, tmp_path):
    def run(cmd, **kwargs):
        assert cmd[cmd.index("-ss") + 1] == "12.000"
        assert cmd[cmd.index("-t") + 1] == "3.000"
        assert kwargs["stdin"] is subprocess.DEVNULL
        Path(cmd[-1]).write_bytes(b"completed audio")
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    monkeypatch.setattr(tr.subprocess, "run", run)
    output = tr._slice_audio_from("source.wav", 12.0, tmp_path / "partials", end_seconds=15.0)
    assert Path(output).read_bytes() == b"completed audio"
