"""Transient hardware settings I/O failures are not evidence of corrupt JSON."""
import builtins
import errno
from pathlib import Path

import pytest

from core import hardware as hw


@pytest.fixture
def target(tmp_path, monkeypatch):
    path = tmp_path / "hardware.json"
    monkeypatch.setattr(hw, "hardware_json_path", lambda: path)
    return path


@pytest.mark.parametrize("error_number", [errno.EACCES, errno.EIO, errno.ETIMEDOUT])
def test_unreadable_hardware_choice_is_retained_for_next_read(target, monkeypatch, error_number):
    original = b'{"device":"cpu","compute_type":"int8"}'
    target.write_bytes(original)
    prior_recovery = Path(str(target) + ".corrupt")
    prior_recovery.write_bytes(b"previous retained recovery")
    open_file = builtins.open

    def temporary_failure(file, *args, **kwargs):
        if Path(file) == target:
            raise OSError(error_number, "synthetic transient hardware read error")
        return open_file(file, *args, **kwargs)

    with monkeypatch.context() as fault:
        fault.setattr(builtins, "open", temporary_failure)
        assert hw.load_hardware_choice() is None
    assert target.read_bytes() == original
    assert prior_recovery.read_bytes() == b"previous retained recovery"
    assert hw.load_hardware_choice() == {"device": "cpu", "compute_type": "int8"}


@pytest.mark.parametrize("malformed", [b'{"device":', b'[]', b'null', b'\xff'])
def test_actual_invalid_hardware_data_keeps_existing_recovery_behavior(target, malformed):
    target.write_bytes(malformed)
    assert hw.load_hardware_choice() is None
    assert not target.exists()
    assert Path(str(target) + ".corrupt").read_bytes() == malformed


def test_missing_hardware_file_remains_a_normal_empty_choice(target):
    assert hw.load_hardware_choice() is None
    assert not target.exists() and not Path(str(target) + ".corrupt").exists()
