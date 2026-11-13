"""Exercise real Inno shortcuts without touching an installed application."""
import os
from pathlib import Path
import re
import subprocess
import time
import uuid

import pytest

ROOT = Path(__file__).resolve().parents[2]
COMPILER = Path(os.environ.get("WHISPER_SMOKE_INNO_COMPILER", ""))
pytestmark = pytest.mark.skipif(os.name != "nt" or not COMPILER.is_file(),
                                reason="Pinned local Inno compiler required")


@pytest.mark.parametrize("script_name", ["installer_embed.iss", "installer.iss"])
def test_upgrade_retires_only_matching_versioned_shortcuts(tmp_path, script_name):
    text = (ROOT / script_name).read_text(encoding="utf-8")
    app, menu, desktop = [tmp_path / n for n in ("app", "menu", "desktop")]
    for folder in (app / "python", menu, desktop):
        folder.mkdir(parents=True)
    (app / "python/pythonw.exe").write_bytes(b"synthetic target, never executed")
    (app / "gui.py").write_bytes(b"synthetic entry point, never executed")
    source = tmp_path / "payload.txt"
    source.write_bytes(b"tracked fixture")
    icons = text.split("[Icons]", 1)[1].split("[Tasks]", 1)[0]
    prepare = re.search(r"(?ms)^function PrepareToInstall\b.*?^end;", text).group(0)
    match = re.search(r"(?s)// Versioned shortcut maintenance\.\n(.*?)// End versioned shortcut maintenance\.", text)
    cleanup = match.group(1) if match else ""
    def mapped(value):
        return value.replace("{group}", str(menu)).replace("{commondesktop}", str(desktop))
    code = """const OldAppId = 'fixture-legacy';
function GetUninstallString(): String; begin Result := 'existing fixture'; end;
function GetUninstallStringForAppId(AnAppId: String): String; begin Result := ''; end;
""" + mapped(cleanup) + prepare
    seed = r"""procedure InitializeWizard();
var Folder, Link: String; i: Integer;
begin
  for i := 0 to 1 do begin
    if i = 0 then Folder := 'MENU' else Folder := 'DESKTOP';
    Link := CreateShellLink(Folder + '\Whisper Transcriber Suite 2.3.1.lnk', '',
      ExpandConstant('{app}\python\pythonw.exe'), '"' + ExpandConstant('{app}\gui.py') + '"', '', '', 0, SW_SHOWNORMAL);
    Link := CreateShellLink(Folder + '\Whisper Transcriber Suite 2.2.0.lnk', '',
      ExpandConstant('{app}\python\pythonw.exe'), '"' + ExpandConstant('{app}\gui.py') + '"', '', '', 0, SW_SHOWNORMAL);
    Link := CreateShellLink(Folder + '\My custom Whisper link.lnk', '',
      ExpandConstant('{app}\python\pythonw.exe'), '"' + ExpandConstant('{app}\gui.py') + '"', '', '', 0, SW_SHOWNORMAL);
    Link := CreateShellLink(Folder + '\Whisper Transcriber Suite 1.9.0.lnk', '',
      ExpandConstant('{app}\python\pythonw.exe'), '--custom-option', '', '', 0, SW_SHOWNORMAL);
    Link := CreateShellLink(Folder + '\Whisper Transcriber Suite 1.8.0.lnk', '',
      ExpandConstant('{app}\other.exe'), '', '', '', 0, SW_SHOWNORMAL);
    Link := CreateShellLink(Folder + '\Whisper Transcriber Suite custom.lnk', '',
      ExpandConstant('{app}\python\pythonw.exe'), '"' + ExpandConstant('{app}\gui.py') + '"', '', '', 0, SW_SHOWNORMAL);
  end;
end;
""".replace('MENU', str(menu)).replace('DESKTOP', str(desktop)).replace('{app}', str(app))
    script = tmp_path / "fixture.iss"
    script.write_text(f'''#define MyAppVersion "2.4.0"
[Setup]
AppId=WhisperShortcutFixture{uuid.uuid4().hex}
AppName=Whisper shortcut private fixture
AppVersion=2.4.0
DefaultDirName={app}
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
OutputDir={tmp_path}
OutputBaseFilename=fixture
Compression=none
CreateUninstallRegKey=no
UninstallLogMode=overwrite
[Files]
Source: "{source}"; DestDir: "{{app}}"
[Icons]
{mapped(icons)}
[Tasks]
Name: "desktopicon"; Description: "Private desktop fixture"
[Code]
{code}
{seed}
''', encoding="utf-8")
    def run(args):
        setup_log = tmp_path / "setup.log"
        if Path(args[0]).name == "fixture.exe":
            args = args + ["/LOG=" + str(setup_log)]
        result = subprocess.run(args, cwd=tmp_path, capture_output=True, timeout=45,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        detail = (result.stdout + result.stderr).decode(errors="replace")
        if result.returncode and setup_log.exists():
            detail += setup_log.read_text(encoding="utf-8-sig", errors="replace")
        assert result.returncode == 0, detail
    run([str(COMPILER), "/Q", str(script)])
    run([str(tmp_path / "fixture.exe"), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/TASKS=desktopicon"])
    for folder in (menu, desktop):
        for version in ("2.3.1", "2.2.0"):
            assert not (folder / f"Whisper Transcriber Suite {version}.lnk").exists(), "old installer-owned shortcut remains"
        for name in ("My custom Whisper link", "Whisper Transcriber Suite 1.9.0",
                     "Whisper Transcriber Suite 1.8.0", "Whisper Transcriber Suite custom"):
            assert (folder / (name + ".lnk")).is_file(), "custom shortcut was removed"
    current = "Whisper Transcriber Suite" + (" 2.4.0" if script_name == "installer_embed.iss" else "")
    assert (menu / (current + ".lnk")).is_file()
    assert (desktop / (current + ".lnk")).is_file()
    run([str(app / "unins000.exe"), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"])
    deadline = time.monotonic() + 15
    while (app / "unins000.exe").exists() and time.monotonic() < deadline:
        time.sleep(.1)
    assert not (app / "unins000.exe").exists(), "private uninstaller did not finish"
    for folder in (menu, desktop):
        assert not (folder / (current + ".lnk")).exists()
        assert (folder / "My custom Whisper link.lnk").is_file()
