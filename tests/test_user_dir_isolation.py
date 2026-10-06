"""Guard: no test may resolve the real per-user app folders.

The autouse ``_isolate_user_dirs`` fixture in ``tests/conftest.py`` redirects every
platformdirs per-user folder to a temp tree. These tests fail if that redirect is
removed or bypassed, so a test run can never again write log lines, history rows,
job folders or ``save_config()`` output into the developer's real folders.
"""
from __future__ import annotations

from pathlib import Path

import platformdirs
import pytest

from core import config as cfg
from tests.conftest import REAL_PLATFORMDIRS

_CORE_ACCESSORS = ("user_config_dir", "user_cache_dir", "user_log_dir", "user_data_dir")


def _real(kind: str, appname: str) -> Path:
    return Path(REAL_PLATFORMDIRS[kind](appname, cfg.APP_AUTHOR))


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


@pytest.mark.parametrize("accessor", _CORE_ACCESSORS)
def test_core_user_dirs_are_not_the_real_folders(accessor):
    resolved = getattr(cfg, accessor)()
    real = _real(accessor, cfg.APP_NAME)
    assert not _inside(resolved, real), f"{accessor}() points at the real folder {real}"
    assert resolved != real


def test_config_path_is_not_the_real_config_file():
    real = _real("user_config_dir", cfg.APP_NAME) / "config.json"
    assert Path(cfg.config_path()) != real
    assert not _inside(Path(cfg.config_path()), real.parent)


@pytest.mark.parametrize("kind", ("user_config_dir", "user_data_dir", "user_cache_dir"))
def test_legacy_app_name_folders_are_not_the_real_ones(kind):
    # core.config reads the legacy-name folders during migration; they must be
    # redirected too, or a migration test would move the developer's real files.
    resolved = Path(getattr(platformdirs, kind)(cfg.LEGACY_APP_NAME, cfg.APP_AUTHOR))
    assert not _inside(resolved, _real(kind, cfg.LEGACY_APP_NAME))


def test_each_test_gets_an_empty_tree(tmp_path):
    # Check before writing: if the redirect is broken this must fail, not litter
    # the real folder.
    assert not _inside(cfg.user_data_dir(), _real("user_data_dir", cfg.APP_NAME))
    marker = cfg.user_data_dir() / "marker.txt"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("x", encoding="utf-8")
    assert marker.is_file()
    # tmp_path itself is untouched, so tests that assert on it stay valid.
    assert list(tmp_path.iterdir()) == []
