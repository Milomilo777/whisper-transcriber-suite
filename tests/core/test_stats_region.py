"""Region lookup of ``core.stats`` when the macOS preferences file is damaged.

``plistlib`` raises ``ExpatError`` (not a ``ValueError``) for malformed XML.
That must count as "AppleLocale not readable": the lookup then falls back
to the locale environment instead of giving up with no country at all.
Hermetic: the home folder and the environment are redirected.
"""
from __future__ import annotations

import plistlib
from pathlib import Path

import pytest

from core import stats

_BAD_XML = b"<plist><dict><key>a</key><string>b</string></dict></plist"


def _prefs_file(home: Path, content: bytes) -> Path:
    path = home / "Library" / "Preferences" / ".GlobalPreferences.plist"
    path.parent.mkdir(parents=True)
    path.write_bytes(content)
    return path


@pytest.fixture
def mac_home(tmp_path, monkeypatch):
    monkeypatch.setattr(stats.Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.delenv("LC_ALL", raising=False)
    monkeypatch.setenv("LANG", "de_DE.UTF-8")
    return tmp_path


def test_a_valid_locale_preference_gives_its_region(tmp_path):
    prefs = _prefs_file(tmp_path, plistlib.dumps({"AppleLocale": "fr_CA"}))
    assert stats._macos_region(prefs) == "CA"


@pytest.mark.parametrize(
    "content",
    [_BAD_XML, b"", b"not a plist at all", plistlib.dumps({"AppleLocale": 5})],
)
def test_an_unreadable_preference_file_gives_no_region(tmp_path, content):
    assert stats._macos_region(_prefs_file(tmp_path, content)) == ""


def test_a_damaged_preference_file_falls_back_to_the_environment(mac_home):
    _prefs_file(mac_home, _BAD_XML)
    assert stats._region_for("darwin") == "DE"


def test_a_missing_preference_file_falls_back_to_the_environment(mac_home):
    assert stats._region_for("darwin") == "DE"
