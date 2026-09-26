; installer_embed.iss — Inno Setup script for Method C
; (Standard installer with an embeddable Python interpreter).
;
; Builds: dist_installer\WhisperTranscriberSuite-Installer-Windows-vX.Y.Z.exe
;
; Source tree expected: embed_build\ — produced by
; build_embed_installer.bat. The tree contains a self-contained
; CPython 3.11 embeddable interpreter, all dependencies under
; Lib\site-packages\, the app's source under app\ + core\, and the
; bundled bin\ binaries. Shortcuts launch pythonw.exe gui.py.

; Single version knob — drives AppVersion, the output filename, and the
; (version-stamped) shortcut name so the user can see which build is
; installed. Bump alongside core/__init__.py + pyproject.toml.
#define MyAppVersion "1.9.3"

[Setup]
; Stable AppId — keeps a single, upgradable Add/Remove Programs entry
; across versions (and shared with the Compact installer, same product).
; Changed 2026-08-23 for the "Whisper Project" -> "Whisper Transcriber
; Suite" rebrand (was {734B46B9-5E70-4C4E-8833-0A7506A64376} -- see
; OldAppId in [Code] below, which drives the one-time data migration
; from the predecessor product).
AppId={{BD640ACA-1EDB-4F9F-890E-C2DC04221871}
AppName=Whisper Transcriber Suite
AppVersion={#MyAppVersion}
AppPublisher=translation-robot
AppPublisherURL=https://github.com/translation-robot
DefaultDirName={autopf}\WhisperTranscriberSuite
DefaultGroupName=Whisper Transcriber Suite
OutputBaseFilename=WhisperTranscriberSuite-Installer-Windows-v{#MyAppVersion}
OutputDir=dist_installer
Compression=lzma2/ultra
SolidCompression=yes
PrivilegesRequired=admin
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayName=Whisper Transcriber Suite
UninstallDisplayIcon={app}\assets\whisper.ico
SetupIconFile=assets\whisper.ico

[Files]
Source: "embed_build\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "assets\whisper.ico"; DestDir: "{app}\assets"; Flags: ignoreversion
Source: "assets\whisper.png"; DestDir: "{app}\assets"; Flags: ignoreversion

[Icons]
Name: "{group}\Whisper Transcriber Suite {#MyAppVersion}"; Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\gui.py"""; WorkingDir: "{app}"; IconFilename: "{app}\assets\whisper.ico"
Name: "{group}\Uninstall Whisper Transcriber Suite"; Filename: "{uninstallexe}"
Name: "{commondesktop}\Whisper Transcriber Suite {#MyAppVersion}"; Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\gui.py"""; WorkingDir: "{app}"; IconFilename: "{app}\assets\whisper.ico"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop icon"; GroupDescription: "Shortcuts:"
Name: "shellext"; Description: "Add 'Transcribe with Whisper Transcriber Suite' to the Windows Explorer right-click menu"; GroupDescription: "Integration:"
; Video Tiling (video wall) is OFF by default (owner request, 2026-08-15):
; it's a niche multi-monitor live-stream grid most users never touch.
; Leaving this task unticked drops a no_tiling.flag marker in {app}; the
; app reads it at startup (core.hub.tiling_tab_enabled) and hides the
; Video Tiling tab. Ticking the task installs the feature normally.
Name: "tiling"; Description: "Install the Video Tiling (video wall) feature (advanced; most users don't need this)"; GroupDescription: "Optional features:"; Flags: unchecked
; Clone Your Voice / Text to Voice is OFF by default, same reasoning as
; Video Tiling above -- a niche, legally/ethically sensitive feature most
; users never touch. Leaving this task unticked drops a
; no_voice_clone.flag marker in {app}; the app reads it at startup
; (core.hub.voice_clone_tab_enabled) and hides the tab. Independent of
; the "tiling" task above -- ticking/unticking one never affects the
; other.
Name: "voiceclone"; Description: "Install the Clone Your Voice / Text to Voice feature (downloads a ~2GB speech model on first use)"; GroupDescription: "Optional features:"; Flags: unchecked

[Registry]
; Same shell-extension hook as installer.iss, but the embedded
; layout points at pythonw.exe + gui.py instead of a frozen binary.
; pythonw is the windowless launcher so the CLI run from Explorer
; doesn't pop a console.
Root: HKCR; Subkey: "*\shell\WhisperTranscriberSuiteTranscribe"; ValueType: string; ValueName: ""; ValueData: "Transcribe with Whisper Transcriber Suite"; Flags: uninsdeletekey; Tasks: shellext
Root: HKCR; Subkey: "*\shell\WhisperTranscriberSuiteTranscribe"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\python\pythonw.exe,0"; Tasks: shellext
Root: HKCR; Subkey: "*\shell\WhisperTranscriberSuiteTranscribe\command"; ValueType: string; ValueName: ""; ValueData: """{app}\python\pythonw.exe"" ""{app}\gui.py"" transcribe ""%1"""; Tasks: shellext

[Run]
Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\gui.py"""; WorkingDir: "{app}"; Description: "Launch Whisper Transcriber Suite"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Python writes __pycache__ trees at runtime; Inno doesn't track
; files created after install, so sweep them on uninstall along
; with anything else the user might have generated under {app}.
Type: filesandordirs; Name: "{app}\__pycache__"
Type: filesandordirs; Name: "{app}\app"
Type: filesandordirs; Name: "{app}\core"
Type: filesandordirs; Name: "{app}\bin"
Type: filesandordirs; Name: "{app}\assets"
Type: filesandordirs; Name: "{app}\python"
Type: filesandordirs; Name: "{app}\Lib"
Type: files; Name: "{app}\gui.py"
Type: files; Name: "{app}\sitecustomize.py"
Type: files; Name: "{app}\no_tiling.flag"
Type: files; Name: "{app}\no_voice_clone.flag"
Type: dirifempty; Name: "{app}"

[Code]
// --------------------------------------------------------------------
//  Silently uninstall a previous version before installing this one.
//
//  AppId is stable across versions, so Inno's [Files] ignoreversion
//  overwrite normally "upgrades in place" without the user uninstalling
//  first. But that only OVERWRITES files still present in the new file
//  list — a file removed between versions (a deleted module, a renamed
//  asset) is never cleaned up and lingers forever. Running the previous
//  version's own uninstaller first (silently, before any new files are
//  copied) removes that whole class of leftovers while keeping the
//  one-click "no need to uninstall first" experience intact.
// --------------------------------------------------------------------

function GetUninstallStringForAppId(AnAppId: String): String;
var
  UninstPath, UninstString: String;
begin
  UninstPath := 'Software\Microsoft\Windows\CurrentVersion\Uninstall\' + AnAppId + '_is1';
  UninstString := '';
  if not RegQueryStringValue(HKLM, UninstPath, 'UninstallString', UninstString) then
    RegQueryStringValue(HKLM32, UninstPath, 'UninstallString', UninstString);
  Result := UninstString;
end;

function GetUninstallString(): String;
begin
  Result := GetUninstallStringForAppId('{#SetupSetting("AppId")}');
end;

// --------------------------------------------------------------------
//  One-time migration from the predecessor product ("Whisper Project",
//  AppId OldAppId) to this one (the 2026-08-23 rebrand). Copies -- NEVER
//  moves -- the old per-user data folder to the new APP_NAME location,
//  then silently removes the old product via its own uninstaller: same
//  "no need to uninstall first" experience as a same-product upgrade,
//  just crossing the rename. The old %LOCALAPPDATA%\WhisperProject\
//  folder is deliberately left behind afterwards -- if the copy step
//  has a bug, the user's settings/history/model cache are never at
//  risk, just briefly duplicated. Safe to delete by hand once the new
//  app is confirmed working. Idempotent: skips the copy if the new
//  folder already exists (e.g. this ran on a previous attempt).
// --------------------------------------------------------------------

const
  OldAppId = '{734B46B9-5E70-4C4E-8833-0A7506A64376}';

procedure MigrateOldAppData();
var
  OldDataDir, NewDataDir, UninstString: String;
  DataFiles: TArrayOfString;
  i: Integer;
  ResultCode: Integer;
begin
  OldDataDir := ExpandConstant('{localappdata}\WhisperProject');
  NewDataDir := ExpandConstant('{localappdata}\WhisperTranscriberSuite');
  // Gate on the NEW config.json specifically, not just the folder's
  // existence: a bare folder (Cache\/Logs\ with no config.json) can
  // already exist from an unrelated early code path -- e.g. the
  // Portable build was run once before this installer -- and gating
  // on DirExists alone would then skip a real migration and silently
  // strand the user's actual settings/history in the old folder
  // (caught by an install test on 2026-08-23: a prior direct launch
  // had created an empty new-name folder, and the old guard treated
  // that as "already migrated").
  if DirExists(OldDataDir) and not FileExists(NewDataDir + '\config.json') then begin
    if not DirExists(NewDataDir) then
      ForceDirectories(NewDataDir);
    // Copy only the small, meaningful settings/history files directly
    // with FileCopy -- NOT the whole tree. A real install test on
    // 2026-08-23 found Cache\ can hold several GB of downloaded
    // Whisper models and Logs\ can hold hundreds of small per-run
    // worker debug logs; shelling out to xcopy for the full tree took
    // long enough to look hung. Neither is needed anyway: config.json
    // is copied as-is, so its hub_folder value (default or custom)
    // still resolves to the OLD, still-on-disk Cache\models -- the
    // model cache is transparently reused with zero copying.
    DataFiles := ['config.json', 'history.db', 'hardware.json', 'search.db'];
    for i := 0 to GetArrayLength(DataFiles) - 1 do begin
      if FileExists(OldDataDir + '\' + DataFiles[i]) then begin
        if not CopyFile(OldDataDir + '\' + DataFiles[i], NewDataDir + '\' + DataFiles[i], False) then
          Log('Could not migrate ' + DataFiles[i] + ' from ' + OldDataDir);
      end;
    end;
    Log('Migrated settings/history from ' + OldDataDir + ' to ' + NewDataDir);
  end;
  UninstString := GetUninstallStringForAppId(OldAppId);
  if UninstString = '' then
    Exit;
  UninstString := RemoveQuotes(UninstString);
  if not Exec(UninstString, '/SILENT /NORESTART /SUPPRESSMSGBOXES', '',
              SW_HIDE, ewWaitUntilTerminated, ResultCode) then
    Log('Could not run the old product''s uninstaller: ' + UninstString);
end;

function InitializeSetup(): Boolean;
var
  UninstString: String;
  ResultCode: Integer;
begin
  Result := True;
  // Same-product upgrade (a newer Whisper Transcriber Suite over an
  // older one) takes priority -- unchanged logic, now scoped to the
  // new AppId. Only when there's no same-product predecessor do we
  // check for the pre-rebrand "Whisper Project" product instead.
  UninstString := GetUninstallString();
  if UninstString <> '' then begin
    UninstString := RemoveQuotes(UninstString);
    // /SUPPRESSMSGBOXES auto-answers any Pascal MsgBox in the OLD
    // uninstaller too; CurUninstallStepChanged below skips the hub-folder
    // deletion prompt entirely when UninstallSilent() is true, so a model
    // hub OUTSIDE the install dir survives this automatic step either way.
    if not Exec(UninstString, '/SILENT /NORESTART /SUPPRESSMSGBOXES', '',
                SW_HIDE, ewWaitUntilTerminated, ResultCode) then
      Log('Could not run the previous version''s uninstaller: ' + UninstString);
  end else begin
    MigrateOldAppData();
  end;
end;

// --------------------------------------------------------------------
//  Hub-folder uninstall prompt — identical logic to installer.iss.
//  See that file for full commentary; this script keeps a copy so
//  the two installers stay self-contained (Inno has no [Include]).
// --------------------------------------------------------------------

// --------------------------------------------------------------------
//  Optional "Video Tiling" feature toggle.
//
//  Video Tiling is EXCLUDED by default (owner request, 2026-08-15) --
//  most users never touch this multi-monitor live-stream grid, so it
//  should be an opt-IN, not an opt-out. Unless the user ticks the
//  "tiling" task, we drop an empty marker file at {app}\no_tiling.flag
//  during post-install. The app reads it at startup
//  (core.hub.tiling_tab_enabled) and simply hides the Video Tiling tab
//  -- no code is removed, so the toggle is fully reversible by deleting
//  the marker. The marker is also swept on uninstall (here + in
//  [UninstallDelete]).
// --------------------------------------------------------------------

const
  NoTilingMarker = '{app}\no_tiling.flag';

// --------------------------------------------------------------------
//  Optional "Clone Your Voice / Text to Voice" feature toggle.
//
//  Same shape as Video Tiling above, own independent marker -- OFF by
//  default (public-installer opt-in; legal/ethical sensitivity + a
//  ~2GB on-demand model, see docs/SESSION_HANDOFF_NEXT.md 2026-09-12).
//  Unless the user ticks the "voiceclone" task, we drop an empty marker
//  file at {app}\no_voice_clone.flag during post-install. The app reads
//  it at startup (core.hub.voice_clone_tab_enabled) and hides the tab
//  -- no code is removed, so the toggle is fully reversible by deleting
//  the marker. Swept on uninstall (here + in [UninstallDelete]).
// --------------------------------------------------------------------

const
  NoVoiceCloneMarker = '{app}\no_voice_clone.flag';

procedure CurStepChanged(CurStep: TSetupStep);
var
  MarkerPath: string;
begin
  if CurStep <> ssPostInstall then
    Exit;
  MarkerPath := ExpandConstant(NoTilingMarker);
  if not WizardIsTaskSelected('tiling') then begin
    if not SaveStringToFile(MarkerPath, '', False) then
      Log('Could not create no_tiling.flag marker at ' + MarkerPath);
  end else begin
    // Defensive: on a reinstall/upgrade where the user previously left
    // Tiling out but now wants it, make sure a stale marker is gone.
    if FileExists(MarkerPath) then
      DeleteFile(MarkerPath);
  end;
  // Independent block, same shape, own marker -- ticking/unticking
  // "tiling" above never affects this one and vice versa.
  MarkerPath := ExpandConstant(NoVoiceCloneMarker);
  if not WizardIsTaskSelected('voiceclone') then begin
    if not SaveStringToFile(MarkerPath, '', False) then
      Log('Could not create no_voice_clone.flag marker at ' + MarkerPath);
  end else begin
    if FileExists(MarkerPath) then
      DeleteFile(MarkerPath);
  end;
end;

function ExtractHubFolder(): string;
var
  ConfigPath: string;
  Lines: TArrayOfString;
  i, ColonPos, StartQ, EndQ: Integer;
  Line, Value: string;
begin
  Result := '';
  // platformdirs.user_config_dir on Windows resolves to %LOCALAPPDATA%
  // with appauthor=False; see installer.iss for the full rationale.
  ConfigPath := ExpandConstant('{localappdata}\WhisperTranscriberSuite\config.json');
  if not FileExists(ConfigPath) then
    Exit;
  if not LoadStringsFromFile(ConfigPath, Lines) then
    Exit;
  for i := 0 to GetArrayLength(Lines) - 1 do begin
    Line := Trim(Lines[i]);
    if Pos('"hub_folder"', Line) <> 1 then
      Continue;
    ColonPos := Pos(':', Line);
    if ColonPos = 0 then
      Continue;
    Value := Trim(Copy(Line, ColonPos + 1, Length(Line) - ColonPos));
    StartQ := Pos('"', Value);
    if StartQ = 0 then
      Continue;
    EndQ := Pos('"', Copy(Value, StartQ + 1, Length(Value) - StartQ));
    if EndQ = 0 then
      Continue;
    Value := Copy(Value, StartQ + 1, EndQ - 1);
    StringChangeEx(Value, '\\', '\', True);
    Result := Value;
    Exit;
  end;
end;

function IsPathInside(Child, Parent: string): Boolean;
var
  C, P: string;
begin
  Result := False;
  if (Child = '') or (Parent = '') then
    Exit;
  C := LowerCase(AddBackslash(Child));
  P := LowerCase(AddBackslash(Parent));
  Result := Pos(P, C) = 1;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  HubFolder, AppFolder, Msg, MarkerPath, ConfigPath: string;
begin
  // Remove the optional-feature markers (created post-install when the
  // user opted out of Video Tiling / Clone Your Voice). [UninstallDelete]
  // also covers both, but delete them explicitly so a partial uninstall
  // leaves nothing behind.
  if CurUninstallStep = usUninstall then begin
    MarkerPath := ExpandConstant(NoTilingMarker);
    if FileExists(MarkerPath) then
      DeleteFile(MarkerPath);
    MarkerPath := ExpandConstant(NoVoiceCloneMarker);
    if FileExists(MarkerPath) then
      DeleteFile(MarkerPath);
  end;
  if CurUninstallStep <> usPostUninstall then
    Exit;
  // A silent uninstall only ever happens automatically, as the
  // pre-install step above for an in-place upgrade — never touch the
  // user's config.json (hub_folder, API keys, preferences) or ask to
  // delete a multi-GB model hub folder in that unattended path.
  if UninstallSilent() then
    Exit;
  // Read hub_folder out of config.json BEFORE deleting it below.
  HubFolder := ExtractHubFolder();
  AppFolder := ExpandConstant('{app}');
  if (HubFolder <> '') and DirExists(HubFolder) and not IsPathInside(HubFolder, AppFolder) then begin
    Msg := 'The Whisper model hub folder is located outside the install directory:' + #13#10 + #13#10 +
           HubFolder + #13#10 + #13#10 +
           'It may contain several gigabytes of downloaded Whisper models.' + #13#10 +
           'Do you want to delete this folder as part of the uninstall?';
    if MsgBox(Msg, mbConfirmation, MB_YESNO) = IDYES then begin
      if not DelTree(HubFolder, True, True, True) then
        MsgBox('Could not fully delete ' + HubFolder + '.' + #13#10 +
               'You can remove it manually with File Explorer.',
               mbInformation, MB_OK);
    end;
  end;
  // A real, interactive uninstall also clears the per-user config.json
  // (NOT during the silent upgrade step above, which would otherwise
  // wipe hub_folder/API keys/preferences on every single in-place
  // upgrade — see InitializeSetup).
  ConfigPath := ExpandConstant('{localappdata}\WhisperTranscriberSuite\config.json');
  if FileExists(ConfigPath) then
    DeleteFile(ConfigPath);
end;
