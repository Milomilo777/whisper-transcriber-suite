"""Tests for the --safe-mode CLI recovery flow."""
from __future__ import annotations

import os
from pathlib import Path
import sys

import pytest


def test_activate_safe_mode_backs_up_config(tmp_path, monkeypatch):
    """A config file should be renamed to <path>.safemode_backup-<ts>."""
    import gui as _gui
    from core import config as cfg_mod

    cfg_path = tmp_path / "config.json"
    cfg_path.write_text('{"hub_folder": "/old"}', encoding="utf-8")
    monkeypatch.setattr(cfg_mod, "config_path", lambda: str(cfg_path))

    _gui._activate_safe_mode()

    assert not cfg_path.exists(), "config.json should be renamed"
    backups = [p for p in tmp_path.iterdir()
               if p.name.startswith("config.json.safemode_backup-")]
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == '{"hub_folder": "/old"}'


def test_activate_safe_mode_is_noop_when_no_config(tmp_path, monkeypatch, capsys):
    """A profile with no config.json should NOT crash; the flag is
    still useful (e.g. as a clean-launch verification)."""
    import gui as _gui
    from core import config as cfg_mod

    cfg_path = tmp_path / "config.json"
    monkeypatch.setattr(cfg_mod, "config_path", lambda: str(cfg_path))

    _gui._activate_safe_mode()  # must not raise
    out = capsys.readouterr().out
    assert "no config to back up" in out


def test_activate_safe_mode_handles_rename_failure(tmp_path, monkeypatch, capsys):
    """When os.replace fails (permission denied, antivirus lock),
    the function must print to stderr and return — never raise.
    The user can then manually delete the file."""
    import gui as _gui
    from core import config as cfg_mod

    cfg_path = tmp_path / "config.json"
    cfg_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(cfg_mod, "config_path", lambda: str(cfg_path))

    def _boom(*_a, **_kw):
        raise OSError("simulated antivirus lock")

    monkeypatch.setattr(os, "replace", _boom)
    _gui._activate_safe_mode()  # must not raise
    err = capsys.readouterr().err
    assert "could not back up config" in err


def test_main_safe_mode_flag_stripped_before_argparse(monkeypatch, tmp_path):
    """--safe-mode must not reach argparse; otherwise the unrecognised
    arg would crash the launcher. We verify by setting sys.argv +
    asserting argparse never sees the flag."""
    import sys as _sys
    import gui as _gui
    from core import config as cfg_mod

    # Stub out app.run + _activate_safe_mode so we don't actually
    # launch Tk or rename real files.
    monkeypatch.setattr(cfg_mod, "config_path",
                        lambda: str(tmp_path / "config.json"))

    activations: list[bool] = []
    monkeypatch.setattr(_gui, "_activate_safe_mode",
                        lambda: activations.append(True))

    launches: list[bool] = []

    def _fake_run():
        launches.append(True)

    import app as _app
    monkeypatch.setattr(_app, "run", _fake_run)

    monkeypatch.setattr(_sys, "argv", ["gui.py", "--safe-mode"])
    rc = _gui.main()
    assert rc == 0
    assert activations == [True]
    assert launches == [True]


@pytest.mark.parametrize(("argv", "exit_code"), [
    (["--help"], 0),
    (["transcribe"], 2),
])
def test_safe_mode_preserves_config_when_argparse_exits(
    monkeypatch, tmp_path, argv, exit_code,
):
    import gui
    from core import config

    config_file = tmp_path / "config.json"
    saved = '{"hub_folder": "original hub"}'
    config_file.write_text(saved, encoding="utf-8")
    monkeypatch.setattr(config, "config_path", lambda: str(config_file))
    monkeypatch.setattr(sys, "argv", ["gui.py", "--safe-mode", *argv])

    with pytest.raises(SystemExit) as exc:
        gui.main()

    assert exc.value.code == exit_code
    assert config_file.read_text(encoding="utf-8") == saved
    assert not list(tmp_path.glob("config.json.safemode_backup-*"))
