"""Historical smoke fixtures must not inherit executable installer hooks."""
from pathlib import Path

import pytest

from tools.inno_sections import uninstall_delete_section


@pytest.mark.parametrize("following", ["Code", "InstallDelete", "Files", "Registry"])
@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_uninstall_fixture_excludes_every_following_section(following, newline):
    text = newline.join(["[Setup]", "AppId=synthetic-fixture", "[UninstallDelete]",
        'Type: filesandordirs; Name: "{app}\\app"', '[' + following + ']',
        "function PrepareToInstall(var N: Boolean): String;",
        "begin Exec('synthetic-uninstaller','','',0,ewWaitUntilTerminated,R); end;", ""])
    section = uninstall_delete_section(text)
    assert "filesandordirs" in section
    assert '[' + following + ']' not in section and "Exec(" not in section


def test_actual_compact_script_never_contributes_code_to_fixture():
    source = Path(__file__).resolve().parents[1] / "installer.iss"
    section = uninstall_delete_section(source.read_text(encoding="utf-8"))
    assert "Type: filesandordirs;" in section
    assert "[Code]" not in section and "PrepareToInstall" not in section


def test_indented_or_commented_following_header_still_stops_capture():
    text = '[UninstallDelete]\nType: dirifempty; Name: "{app}"\n  [Code] ; boundary\nExec(unsafe)\n'
    assert "[Code]" not in uninstall_delete_section(text)
    assert "Exec(" not in uninstall_delete_section(text)


def test_missing_uninstall_section_is_rejected():
    with pytest.raises(ValueError, match="UninstallDelete"):
        uninstall_delete_section("[Code]\nExec(unsafe)\n")
