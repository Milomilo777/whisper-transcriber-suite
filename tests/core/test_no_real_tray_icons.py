"""The suite never creates a real system-tray icon (tests/conftest.py, two guards).

A real pystray icon whose test process ends stays in the Windows notification area as a dead
icon until the mouse passes over it; GUI runs once left dozens there. The stand-in replaces
``pystray.Icon``; behind it, the real class refuses to be built during the tests.
"""
from __future__ import annotations

import sys

import pytest

pystray = pytest.importorskip("pystray")


def test_the_app_side_gets_the_stand_in():
    assert getattr(pystray.Icon, "no_os_tray", False) is True


def test_the_real_icon_class_is_refused_and_reported():
    from pystray import _base

    conftest = next(m for n, m in sys.modules.items()
                    if n.endswith("conftest") and hasattr(m, "REAL_TRAY_ICON_ATTEMPTS"))

    before = len(conftest.REAL_TRAY_ICON_ATTEMPTS)
    with pytest.raises(RuntimeError, match="real system-tray icon"):
        _base.Icon("guard-check")
    assert len(conftest.REAL_TRAY_ICON_ATTEMPTS) == before + 1
    # this test asked for it on purpose: take its entry back so the per-test check passes
    del conftest.REAL_TRAY_ICON_ATTEMPTS[before:]
