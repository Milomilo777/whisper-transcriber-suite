"""installer_embed.iss after the Video Tiling feature was removed.

The installer must not offer the old task, must not write the old marker file, and must delete
a marker left by an older install when the user upgrades.
"""

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

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


def test_upgrade_never_runs_a_historical_uninstaller():
    """A previous uninstall log can recursively delete user-added content."""
    code = _section(_text(), "Code")
    assert "function InitializeSetup" not in code
    prepare = _function(code, "PrepareToInstall")
    assert "Result := '';" in prepare
    assert "GetUninstallString()" in prepare
    assert "GetUninstallStringForAppId(OldAppId)" in prepare
    assert "MigrateOldAppData" not in prepare
    assert "Exec(" not in code


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


def test_upgrade_retires_historical_recursive_delete_records():
    """An in-place upgrade must not append old destructive uninstall actions."""
    assert "UninstallLogMode=overwrite" in _section(_text(), "Setup")
    section = _section(_text(), "UninstallDelete")
    recursive = [line for line in section.splitlines() if line.startswith("Type: filesandordirs;")]
    assert recursive == ['Type: filesandordirs; Name: "{app}\\__pycache__"']


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


@pytest.mark.parametrize("name,text", list(_both_installers()), ids=["installer_embed.iss", "installer.iss"])
def test_installers_leave_profile_import_to_application(name, text):
    """Raw installer copies can overwrite newer databases and omit WAL rows.

    The application owns staged settings copies and SQLite history merging;
    installation must not bypass that path when config.json is missing.
    """
    code = _section(text, "Code")
    assert "CopyFile(" not in code, name
    assert "MigrateOldAppData" not in code, name


@pytest.mark.parametrize("name,text", list(_both_installers()), ids=["installer_embed.iss", "installer.iss"])
def test_uninstall_preserves_profile_settings(name, text):
    code = _section(text, "Code")
    uninstall = _function(code, "CurUninstallStepChanged")
    assert not re.search(r"DeleteFile\(\s*ConfigPath\s*\)", uninstall, re.I), name
    assert not re.search(r"(?im)^.*(?:Name:|Source:).*\{localappdata\}.*config\.json", text), name


@pytest.mark.parametrize("name,text", list(_both_installers()), ids=["installer_embed.iss", "installer.iss"])
def test_model_cleanup_rechecks_private_cache_before_any_deletion(name, text):
    code = _section(text, "Code")
    cleanup = _function(code, "DeleteHubModels")
    assert "CanDeletePrivateHub(HubFolder, PrivateCache)" in cleanup, name
    assert cleanup.index("CanDeletePrivateHub") < cleanup.index("FindFirst("), name
    assert cleanup.index("CanDeletePrivateHub") < cleanup.index("DelTree("), name


@pytest.mark.parametrize("name,text", list(_both_installers()), ids=["installer_embed.iss", "installer.iss"])
def test_uninstall_never_offers_custom_hub_deletion(name, text):
    code = _section(text, "Code")
    uninstall = _function(code, "CurUninstallStepChanged")
    assert "PrivateCache := ExpandConstant('{localappdata}\\WhisperTranscriberSuite\\Cache\\models')" in uninstall, name
    assert "CanDeletePrivateHub(HubFolder, PrivateCache)" in uninstall, name
    assert uninstall.index("CanDeletePrivateHub") < uninstall.index("MsgBox("), name
    assert "DeleteHubModels(HubFolder, PrivateCache)" in uninstall, name


@pytest.mark.parametrize("name,text", list(_both_installers()), ids=["installer_embed.iss", "installer.iss"])
def test_model_deletion_question_defaults_to_keep(name, text):
    uninstall = _function(_section(text, "Code"), "CurUninstallStepChanged")
    assert "MB_YESNO or MB_DEFBUTTON2" in uninstall, name


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
        assert "DeleteHubModels(HubFolder, PrivateCache)" in _function(code, "CurUninstallStepChanged"), name


def test_build_script_parses_gui_py_independent_of_the_windows_code_page():
    """`open(path).read()` decodes with the Windows ANSI code page, so the same gui.py
    passes on one PC and fails the build on another. Reading bytes lets Python apply
    its own source rule (UTF-8)."""
    with open(os.path.join(_ROOT, "build_embed_installer.bat"), encoding="utf-8") as fh:
        lines = [ln for ln in fh.read().splitlines() if "ast.parse" in ln]
    assert len(lines) == 1
    assert re.search(r",\s*'rb'\)", lines[0])


def _run_batch(path, *, cwd, env=None):
    cmd = os.environ.get("COMSPEC", r"C:\Windows\System32\cmd.exe")
    return subprocess.run(
        f'"{cmd}" /d /s /c ""{path}""', cwd=cwd, env=env,
        capture_output=True, text=True, timeout=30,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


@pytest.mark.skipif(os.name != "nt", reason="runs Windows batch code")
@pytest.mark.parametrize("folder", ["Checkout !", "Author's checkout"])
def test_embed_builder_keeps_literal_checkout_paths(tmp_path, folder):
    text = Path(_ROOT, "build_embed_installer.bat").read_text(encoding="utf-8")
    # Run the real path setup and syntax probe, with no extraction, downloads or cleanup.
    prefix, _ = text.split('\nif exist "%BUILD%" rmdir ', 1)
    probe_line = next(line for line in text.splitlines() if "ast.parse" in line)
    probe_line = probe_line.replace(r'"%BUILD%\python\python.exe"', f'"{sys.executable}"')
    project = tmp_path / folder
    build = project / "embed_build"
    build.mkdir(parents=True)
    (build / "gui.py").write_text('sample = "مرحبا"\n', encoding="utf-8")
    probe = project / "path_probe.bat"
    probe.write_text(f'{prefix}\nset BUILD\n{probe_line}\nexit /b %errorlevel%\n', encoding="utf-8")

    result = _run_batch(probe, cwd=tmp_path)
    assert f"BUILD={build}" in result.stdout.splitlines(), result.stdout + result.stderr
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(os.name != "nt", reason="runs Windows batch code")
def test_windows_portable_launcher_finds_its_files_on_a_unc_share(tmp_path):
    drive, relative = os.path.splitdrive(str(tmp_path))
    if not re.fullmatch(r"[a-zA-Z]:", drive):
        pytest.skip("the test needs a local temporary drive")
    share = Path(f"\\\\localhost\\{drive[0]}$\\" + relative.lstrip("\\"))
    try:
        share_available = share.is_dir()
    except PermissionError:
        share_available = False
    if not share_available:
        pytest.skip("local administrative share is unavailable")
    text = Path(_ROOT, "build_embed_installer.bat").read_text(encoding="utf-8")
    commands = [line for line in text.splitlines() if 'Run Whisper Transcriber Suite.bat" echo ' in line]
    assert commands
    tree = tmp_path / "Portable files"
    interpreter = tree / "python"
    interpreter.mkdir(parents=True)
    (tree / "gui.py").write_text(
        'import os\nfrom pathlib import Path\n'
        'Path(os.environ["WTS_LAUNCH_RECEIPT"]).write_text(os.getcwd(), encoding="utf-8")\n',
        encoding="ascii",
    )
    receipt = tmp_path / "launched.txt"
    base_exe = Path(sys._base_executable)
    shutil.copyfile(base_exe, interpreter / "pythonw.exe")
    for dll in base_exe.parent.glob("*.dll"):
        shutil.copyfile(dll, interpreter / dll.name)
    # Catch the old relative launch without letting START open a missing-file dialog.
    fallback = tmp_path / "python"
    shutil.copytree(interpreter, fallback)
    (tmp_path / "gui.py").write_text("raise SystemExit(1)\n", encoding="ascii")
    generator = tmp_path / "generate.bat"
    lines = [line.replace('start "" ', 'start "" /b /wait ') for line in commands]
    generator.write_text(f'@echo off\nset "BUILD={tree}"\n' + "\n".join(lines) + "\n", encoding="utf-8")
    generated = _run_batch(generator, cwd=tmp_path)
    assert generated.returncode == 0, generated.stdout + generated.stderr
    unc_launcher = share / tree.name / "Run Whisper Transcriber Suite.bat"
    result = _run_batch(unc_launcher, cwd=tmp_path, env={
        **os.environ, "PYTHONHOME": sys.base_prefix, "WTS_LAUNCH_RECEIPT": str(receipt),
    })
    assert receipt.is_file(), result.stdout + result.stderr
    assert tree.samefile(receipt.read_text(encoding="utf-8"))
