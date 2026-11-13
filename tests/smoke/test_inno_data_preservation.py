"""Compile the actual uninstall directives into a lowest-privilege fixture."""
import os
from pathlib import Path
import subprocess
import time
import uuid
import re

import pytest

ROOT=Path(__file__).resolve().parents[2]
COMPILER=Path(os.environ.get('WHISPER_SMOKE_INNO_COMPILER',''))
pytestmark=pytest.mark.skipif(os.name!='nt' or not COMPILER.is_file(),reason='Pinned local Inno compiler required')


def test_actual_uninstall_section_retains_user_additions(tmp_path):
    actual=(ROOT/'installer_embed.iss').read_text(encoding='utf-8')
    section=actual.split('[UninstallDelete]',1)[1].split('[InstallDelete]',1)[0]
    app=tmp_path/'app'
    (tmp_path/'tracked.txt').write_text('tracked fixture',encoding='utf-8')
    script=tmp_path/'fixture.iss'
    script.write_text(f'''[Setup]
AppId=WhisperQaFixture{uuid.uuid4().hex}
AppName=Whisper QA private uninstall fixture
AppVersion=1
DefaultDirName={app}
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
OutputDir={tmp_path}
OutputBaseFilename=fixture
Compression=none
CreateUninstallRegKey=no
[Files]
Source: "{tmp_path}/tracked.txt"; DestDir: "{{app}}/assets"
[UninstallDelete]
{section}
''',encoding='utf-8')

    def run(args):
        result=subprocess.run(args,cwd=tmp_path,capture_output=True,timeout=45,
                              creationflags=subprocess.CREATE_NO_WINDOW)
        assert result.returncode==0,(result.stdout+result.stderr).decode(errors='replace')

    run([str(COMPILER),'/Q',str(script)])
    run([str(tmp_path/'fixture.exe'),'/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART'])
    originals=[]
    for name in ('app','core','bin','assets','python','Lib'):
        path=app/name/'untracked-user-original.txt'
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(b'user-owned fixture bytes')
        originals.append(path)
    uninstaller=app/'unins000.exe'
    run([str(uninstaller),'/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART'])
    deadline=time.monotonic()+15
    while uninstaller.exists() and time.monotonic()<deadline:
        time.sleep(.1)
    assert not uninstaller.exists(),'private uninstaller did not finish'
    assert all(path.is_file() and path.read_bytes()==b'user-owned fixture bytes' for path in originals), 'uninstall destroyed untracked originals'


def test_first_upgrade_and_later_uninstall_preserve_old_user_additions(tmp_path):
    old_path=Path(os.environ.get('WHISPER_SMOKE_OLD_INSTALLER_SCRIPT',''))
    if not old_path.is_file():
        pytest.skip('Historical installer script required')
    old=old_path.read_text(encoding='utf-8')
    current=(ROOT/'installer_embed.iss').read_text(encoding='utf-8')
    app=tmp_path/'app'
    app_id='WhisperQaFixture'+uuid.uuid4().hex
    tracked=tmp_path/'tracked.txt'
    tracked.write_bytes(b'old tracked payload')
    old_exe=str(app/'unins000.exe').replace("'","''")
    prepare=re.search(r'(?ms)^function PrepareToInstall\b.*?^end;',current).group(0)
    helpers=re.search(r'(?s)// Versioned shortcut maintenance\.\n(.*?)// End versioned shortcut maintenance\.',current)
    shortcut_code=helpers.group(1) if helpers else ''
    shortcut_code=shortcut_code.replace('{group}',str(tmp_path/'private-menu')).replace('{commondesktop}',str(tmp_path/'private-desktop'))
    # The data-preservation fixture has no icons; still compile its real helper
    # dependencies, with every inspected location confined to this tmp_path.
    shortcut_code=shortcut_code.replace('{#MyAppVersion}','2.4.0')
    stubs=f'''const OldAppId = 'fixture-legacy';
function ThisAppId():String; begin Result := 'fixture-current'; end;
function GetUninstallString():String; begin Result := '{old_exe}'; end;
function GetUninstallStringForAppId(AnAppId:String):String; begin Result := ''; end;
function RunOldUninstaller(AnAppId, What:String):String;
var ExitCode:Integer;
begin
  Result := '';
  if not Exec('{old_exe}', '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART', '',
      SW_HIDE, ewWaitUntilTerminated, ExitCode) then
    Result := 'Private fixture uninstaller failed';
end;
'''

    def run(args):
        result=subprocess.run(args,cwd=tmp_path,capture_output=True,timeout=45,
                              creationflags=subprocess.CREATE_NO_WINDOW)
        assert result.returncode==0,(result.stdout+result.stderr).decode(errors='replace')

    def install(name,text,code=''):
        section=text.split('[UninstallDelete]',1)[1].split('[InstallDelete]',1)[0]
        log_mode=re.search(r'(?m)^UninstallLogMode=(\w+)',text)
        mode=log_mode.group(1) if log_mode else 'append'
        old_only=(f'Source: "{tracked}"; DestDir: "{{app}}/assets"; DestName: "old-only.txt"' if name=='old' else '')
        script=tmp_path/(name+'.iss')
        script.write_text(f'''[Setup]
AppId={app_id}
AppName=Whisper QA private upgrade fixture
AppVersion=1
DefaultDirName={app}
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
OutputDir={tmp_path}
OutputBaseFilename={name}
Compression=none
CreateUninstallRegKey=no
UninstallLogMode={mode}
[Files]
Source: "{tracked}"; DestDir: "{{app}}/assets"
{old_only}
[UninstallDelete]
{section}
[Code]
{code}
''',encoding='utf-8')
        run([str(COMPILER),'/Q',str(script)])
        run([str(tmp_path/(name+'.exe')),'/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART'])

    install('old',old)
    originals=[]
    for folder in ('app','core','bin','assets','python','Lib'):
        path=app/folder/'private-original.txt'
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(b'irreplaceable synthetic original')
        originals.append(path)
    tracked.write_bytes(b'new tracked payload')
    install('new',current,stubs+shortcut_code+prepare)
    assert all(path.is_file() and path.read_bytes()==b'irreplaceable synthetic original' for path in originals), 'first upgrade destroyed originals'
    assert (app/'assets/tracked.txt').read_bytes()==b'new tracked payload'
    run([str(app/'unins000.exe'),'/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART'])
    deadline=time.monotonic()+15
    while (app/'unins000.exe').exists() and time.monotonic()<deadline:
        time.sleep(.1)
    assert not (app/'unins000.exe').exists()
    assert all(path.is_file() and path.read_bytes()==b'irreplaceable synthetic original' for path in originals), 'old uninstall-log actions survived the upgrade'
    # Retiring an unsafe historical log deliberately retains old-only files.
    assert (app/'assets/old-only.txt').read_bytes()==b'old tracked payload'


@pytest.mark.parametrize('installer',['installer_embed.iss','installer.iss'])
def test_deselecting_shell_integration_retires_previous_registration(tmp_path,installer):
    import winreg
    text=(ROOT/installer).read_text(encoding='utf-8')
    registry=re.search(r'(?ms)^\[Registry\]\s*$(.*?)(?=^\[|\Z)',text).group(1)
    key='Software\\WhisperQA\\Fixture\\'+uuid.uuid4().hex+'\\ShellIntegration'
    assert key.startswith('Software\\WhisperQA\\Fixture\\')
    registry=registry.replace('Root: HKCR;','Root: HKCU;').replace('*\\shell\\WhisperTranscriberSuiteTranscribe',key)
    assert all('Root: HKCU;' in line for line in registry.splitlines() if line.startswith('Root:'))
    app=tmp_path/'app'
    appid='WhisperQaShell'+uuid.uuid4().hex
    (tmp_path/'payload.txt').write_bytes(b'tracked fixture payload')
    mode_match=re.search(r'(?m)^UninstallLogMode=(\w+)',text)
    mode=mode_match.group(1) if mode_match else 'append'

    def exists():
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,key,0,winreg.KEY_READ|winreg.KEY_WOW64_32KEY):return True
        except FileNotFoundError:return False

    def cleanup(path):
        assert path==key or path.startswith(key+'\\')
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,path,0,winreg.KEY_READ|winreg.KEY_WOW64_32KEY) as handle:
                children=[]
                index=0
                while True:
                    try:children.append(winreg.EnumKey(handle,index));index+=1
                    except OSError:break
            for child in children:cleanup(path+'\\'+child)
            winreg.DeleteKeyEx(winreg.HKEY_CURRENT_USER,path,winreg.KEY_WOW64_32KEY)
        except FileNotFoundError:pass

    def run(args):
        result=subprocess.run(args,cwd=tmp_path,capture_output=True,timeout=45,
                              creationflags=subprocess.CREATE_NO_WINDOW)
        assert result.returncode==0,(result.stdout+result.stderr).decode(errors='replace')

    def install(name,tasks):
        script=tmp_path/(name+'.iss')
        script.write_text(f'''[Setup]
AppId={appid}
AppName=Whisper QA private integration fixture
AppVersion=1
DefaultDirName={app}
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
OutputDir={tmp_path}
OutputBaseFilename={name}
Compression=none
CreateUninstallRegKey=no
UninstallLogMode={mode}
[Tasks]
Name: "shellext"; Description: "Private fixture integration"; Flags: unchecked
[Files]
Source: "{tmp_path}/payload.txt"; DestDir: "{{app}}"
[Registry]
{registry}
''',encoding='utf-8')
        run([str(COMPILER),'/Q',str(script)])
        run([str(tmp_path/(name+'.exe')),'/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/TASKS='+tasks])

    assert not exists(),'fixture namespace was not fresh'
    try:
        install('on','shellext')
        assert exists(),'positive-control installation did not register the private integration'
        install('off','')
        present_after_deselect=exists()
        uninstaller=app/'unins000.exe'
        run([str(uninstaller),'/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART'])
        deadline=time.monotonic()+15
        while uninstaller.exists() and time.monotonic()<deadline:time.sleep(.1)
        assert not uninstaller.exists()
        present_after_uninstall=exists()
        assert not present_after_deselect,'deselected shell integration retained its old registration'
        assert not present_after_uninstall,'uninstall retained stale integration registration'
    finally:
        cleanup(key)
