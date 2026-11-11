"""The active output OS error wins over an unrelated handled read error."""
from __future__ import annotations

import errno
from types import SimpleNamespace

import pytest

from core import failure_clue, transcriber as tr


@pytest.mark.parametrize("number,code,family", [
    (errno.ENOSPC, "disk_full", "OSError"),
    (errno.EACCES, "access_denied", "PermissionError"),
])
def test_output_os_error_wins_over_handled_missing_file(tmp_path, monkeypatch, number, code, family):
    monkeypatch.setitem(tr.config, "output_filename_template", "{base}.{ext}")
    monkeypatch.setattr(tr, "get_writer", lambda name: lambda *args: "hello\n")

    def failed_flush(stream):
        try:
            (tmp_path / "unrelated-missing-file").read_bytes()
        except FileNotFoundError:
            raise OSError(number, "private destination")

    monkeypatch.setattr(tr._checkpoint, "_flush_to_disk", failed_flush)
    with pytest.raises(RuntimeError) as caught:
        tr._write_outputs(str(tmp_path / "talk"), [], "input.wav", ["srt"])
    actual = caught.value.__cause__
    assert isinstance(actual, OSError) and actual.errno == number
    assert isinstance(actual.__context__, FileNotFoundError)
    clue = failure_clue.worker_clue(caught.value, SimpleNamespace(_failure_site="worker.output"), device="cpu")
    assert clue["observed_code"] == code
    assert clue["exception_family"] == family
    assert clue["os_error"] == str(number)
    assert clue["failure_site"] == "worker.output"
    assert "private" not in str(clue)
    assert list(tmp_path.iterdir()) == []
