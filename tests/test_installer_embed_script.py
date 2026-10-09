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


def _function(code: str, name: str) -> str:
    match = re.search(r"(?ms)^(function|procedure) %s\b.*?^end;" % re.escape(name), code)
    assert match, f"{name} missing from [Code]"
    return match.group(0)


def test_old_version_is_removed_only_after_the_wizard():
    """A cancelled wizard must leave the installed version alone: the old
    uninstaller runs from PrepareToInstall (after Install was clicked), never
    from InitializeSetup (before the first page)."""
    code = _section(_text(), "Code")
    assert "function InitializeSetup" not in code
    prepare = _function(code, "PrepareToInstall")
    assert "RunOldUninstaller(ThisAppId()" in prepare
    assert "RunOldUninstaller(OldAppId" in prepare
    assert prepare.index("MigrateOldAppData()") < prepare.index("RunOldUninstaller(OldAppId")
    # The only Exec of an uninstaller is the checked one.
    assert code.count("Exec(") == 1 and "Exec(" in _function(code, "RunOldUninstaller")


def test_upgrade_keeps_the_previous_folder_and_tasks():
    setup = _section(_text(), "Setup")
    assert re.search(r"(?m)^UsePreviousAppDir=yes$", setup)
    assert re.search(r"(?m)^UsePreviousTasks=yes$", setup)


def test_app_id_lookup_expands_the_doubled_brace():
    """SetupSetting("AppId") is the raw "{{GUID}"; without ExpandConstant the
    uninstall key name is wrong and an upgrade never finds the old version."""
    code = _section(_text(), "Code")
    assert "ExpandConstant('{#SetupSetting(\"AppId\")}')" in _function(code, "ThisAppId")
    assert "GetUninstallStringForAppId(ThisAppId())" in _function(code, "GetUninstallString")
    assert code.count('SetupSetting("AppId")') == 1


def test_old_uninstaller_result_is_checked_and_awaited():
    run = _function(_section(_text(), "Code"), "RunOldUninstaller")
    assert "ewWaitUntilTerminated" in run
    assert "if ResultCode <> 0 then" in run
    # The uninstaller relaunches itself from a temp copy: wait for its key
    # and its exe to disappear, bounded, and report a timeout.
    assert "UninstallKeyExists(AnAppId)" in run and "FileExists(UninstString)" in run
    assert "Sleep(500)" in run and "for i := 1 to 360 do" in run
    assert "did not finish within 3 minutes" in run
    # windows-installer.yml greps the setup log for this line after an upgrade.
    assert "Log('Removed ' + What);" in run
    assert "RunOldUninstaller(ThisAppId(), 'the previous version')" in _function(
        _section(_text(), "Code"), "PrepareToInstall")
    # A missing uninstaller (broken old install) does not block the install.
    assert run.index("if not FileExists(UninstString) then") < run.index("Exec(")


def test_clone_your_voice_task_and_marker_are_unchanged():
    text = _text()
    assert 'Name: "voiceclone"' in _section(text, "Tasks")
    code = _section(text, "Code")
    assert "NoVoiceCloneMarker = '{app}\\no_voice_clone.flag'" in code
    assert "WizardIsTaskSelected('voiceclone')" in code


_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _both_installers():
    for name in ("installer_embed.iss", "installer.iss"):
        with open(os.path.join(_ROOT, name), encoding="utf-8") as fh:
            yield name, fh.read()


def test_uninstall_never_deletes_the_whole_model_folder():
    """hub_folder is any folder the user picked (Documents, a drive root, ...), and
    only the model folders the app made in it are the app's to delete. A recursive
    delete of the folder itself, on a "yes", would take the user's other files too."""
    for name, text in _both_installers():
        code = _section(text, "Code")
        assert "DelTree(HubFolder" not in code, name
        cleanup = _function(code, "DeleteHubModels")
        # Only the `models--*` folders (core.hub.model_folder_for) are removed; the
        # hub folder itself goes only when that left it empty.
        assert "'models--*'" in cleanup, name
        assert "DelTree(" in cleanup and "RemoveDir(HubFolder)" in cleanup, name
        assert cleanup.index("RemoveDir(HubFolder)") > cleanup.index("DelTree("), name
        assert "DeleteHubModels(HubFolder)" in _function(code, "CurUninstallStepChanged"), name
