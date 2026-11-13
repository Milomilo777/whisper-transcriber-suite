"""Pre-existing backup scratch names must not own unrelated files."""
from pathlib import Path

import os
import pytest
from core import config


@pytest.mark.parametrize("alias", [False, True], ids=["regular", "hardlink"])
def test_backup_keeps_preexisting_stage(tmp_path, alias):
    source = tmp_path / "config.json"
    source.write_bytes(b'{"telemetry_opt_in": false}\n')
    original = tmp_path / "earlier-transcript.txt"
    original.write_bytes(b"irreplaceable earlier transcript\n")
    stage = Path(str(source) + ".bak.tmp")
    if alias:
        os.link(original, stage)
    else:
        stage.write_bytes(original.read_bytes())
    before = original.read_bytes()

    assert config._back_up_config(str(source)) is True

    assert original.read_bytes() == before
    assert stage.read_bytes() == before
    assert Path(str(source) + ".bak").read_bytes() == source.read_bytes()


def test_backup_copy_failure_keeps_unowned_stage(tmp_path, monkeypatch):
    source = tmp_path / "config.json"
    source.write_bytes(b'{"telemetry_opt_in": false}\n')
    stage = Path(str(source) + ".bak.tmp")
    stage.write_bytes(b"earlier partial backup data\n")

    def fail(*args, **kwargs):
        raise OSError("synthetic copy failure before creating a stage")

    monkeypatch.setattr(config.shutil, "copy2", fail)
    assert config._back_up_config(str(source)) is False
    assert stage.read_bytes() == b"earlier partial backup data\n"


def test_corrupt_recovery_keeps_preexisting_stage_alias(tmp_path):
    source = tmp_path / "config.json"
    source.write_bytes(b"{invalid JSON")
    Path(str(source) + ".bak").write_bytes(b'{"telemetry_opt_in": false}\n')
    original = tmp_path / "earlier-transcript.txt"
    original.write_bytes(b"irreplaceable earlier transcript\n")
    stage = Path(str(source) + ".corrupt.tmp")
    os.link(original, stage)

    with config._SAVE_LOCK:
        status, _, _ = config._recover_locked(str(source))

    assert status == "ok"
    assert original.read_bytes() == b"irreplaceable earlier transcript\n"
    assert stage.read_bytes() == b"irreplaceable earlier transcript\n"
    assert Path(str(source) + ".corrupt").read_bytes() == b"{invalid JSON"


@pytest.mark.parametrize("operation", ["backup", "recovery"])
@pytest.mark.parametrize("failure", ["copy", "publish"])
def test_failed_copy_preserves_existing_output_and_cleans_only_owned_stage(tmp_path, monkeypatch, operation, failure):
    source = tmp_path / "config.json"
    source.write_bytes(b'{"telemetry_opt_in": false}\n' if operation == "backup" else b"{invalid JSON")
    Path(str(source) + ".bak").write_bytes(b'{"telemetry_opt_in": false, "prior": true}\n')
    Path(str(source) + ".corrupt").write_bytes(b"earlier corrupt data")
    Path(str(source) + ".bak.tmp").write_bytes(b"unowned backup stage")
    Path(str(source) + ".corrupt.tmp").write_bytes(b"unowned recovery stage")
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}

    def fail(*args, **kwargs):
        raise OSError("synthetic copy or publication failure")

    if failure == "copy":
        monkeypatch.setattr(config.shutil, "copy2", fail)
    else:
        monkeypatch.setattr(config.os, "replace", fail)
    if operation == "backup":
        assert config._back_up_config(str(source)) is False
    else:
        with config._SAVE_LOCK:
            status, _, closed = config._recover_locked(str(source))
        assert status == "corrupt" and closed is True
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before
