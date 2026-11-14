"""Keep physical-path fixture coverage when Windows denies symlink privilege."""
from pathlib import Path
from types import SimpleNamespace

import pytest
from tests import mac_path_alias as aliases


def denied_link(self, target, target_is_directory=False):
    error = OSError("fixture: symlink privilege unavailable")
    error.winerror = 1314
    raise error


def test_privilege_denial_keeps_real_directory_alias_coverage(tmp_path, monkeypatch):
    original_link = Path.symlink_to
    target = tmp_path / "target & data"; target.mkdir()
    alias = tmp_path / "alias & data"
    (target / "sentinel").write_text("fixture bytes")
    monkeypatch.setattr(Path, "symlink_to", denied_link)
    if not aliases.WINDOWS:
        monkeypatch.setattr(aliases, "WINDOWS", True)
        def controlled_junction(command, **kwargs):
            assert "$env:WTS_TEST_ALIAS" in command[-1]
            assert str(alias) not in command[-1]
            assert kwargs["env"]["WTS_TEST_ALIAS"] == str(alias.absolute())
            original_link(alias, target, target_is_directory=True)
            return SimpleNamespace(returncode=0)
        monkeypatch.setattr(aliases.subprocess, "run", controlled_junction)
    aliases.directory_alias(alias, target)
    assert alias.resolve() == target.resolve()
    assert (alias / "sentinel").read_text() == "fixture bytes"


def test_other_alias_errors_are_not_hidden(tmp_path, monkeypatch):
    error = OSError("fixture: different filesystem error"); error.winerror = 5
    def fail(*args, **kwargs): raise error
    monkeypatch.setattr(Path, "symlink_to", fail)
    with pytest.raises(OSError, match="different filesystem error"):
        aliases.directory_alias(tmp_path / "alias", tmp_path / "target")


def test_failed_junction_remains_a_test_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "symlink_to", denied_link)
    monkeypatch.setattr(aliases, "WINDOWS", True)
    monkeypatch.setattr(aliases.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=1))
    with pytest.raises(OSError, match="Could not create"):
        aliases.directory_alias(tmp_path / "alias", tmp_path / "target")
