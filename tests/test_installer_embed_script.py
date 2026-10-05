"""installer_embed.iss after the Video Tiling feature was removed.

The installer must not offer the old task, must not write the old marker file, and must delete
a marker left by an older install when the user upgrades.
"""

import os
import re

_ISS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "installer_embed.iss")


def _text() -> str:
    with open(_ISS, encoding="utf-8") as fh:
        return fh.read()


def _section(text: str, name: str) -> str:
    match = re.search(r"^\[%s\]\s*$(.*?)(?=^\[|\Z)" % re.escape(name), text, re.M | re.S)
    assert match, f"[{name}] section missing from installer_embed.iss"
    return match.group(1)


def test_no_tiling_task_is_offered():
    tasks = _section(_text(), "Tasks")
    assert 'Name: "tiling"' not in tasks
    assert "Tiling" not in tasks


def test_installer_code_never_writes_or_asks_for_the_tiling_marker():
    code = _section(_text(), "Code")
    assert "NoTilingMarker" not in code
    assert "WizardIsTaskSelected('tiling')" not in code
    assert "no_tiling.flag" not in code


def test_upgrade_removes_a_marker_left_by_an_older_install():
    install_delete = _section(_text(), "InstallDelete")
    assert 'Type: files; Name: "{app}\\no_tiling.flag"' in install_delete


def test_clone_your_voice_task_and_marker_are_unchanged():
    text = _text()
    assert 'Name: "voiceclone"' in _section(text, "Tasks")
    code = _section(text, "Code")
    assert "NoVoiceCloneMarker = '{app}\\no_voice_clone.flag'" in code
    assert "WizardIsTaskSelected('voiceclone')" in code
