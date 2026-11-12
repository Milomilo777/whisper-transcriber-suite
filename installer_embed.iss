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
#define MyAppVersion "2.4.0"

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
; An upgrade keeps the folder and the task choices of the installed version
; (Inno's defaults, stated because PrepareToInstall relies on them).
UsePreviousAppDir=yes
UsePreviousTasks=yes
; The app holds these mutexes while it runs (gui.py, _hold_app_mutex; the
; Global one covers a copy in another user session); Setup and the
; uninstaller ask the user to close it first. Versions up to 1.9.3 did not
; create them.
AppMutex=WhisperTranscriberSuiteRunning,Global\WhisperTranscriberSuiteRunning

[Files]
; embed_build\ already holds assets\ (icon, toolbar icons, sample clip), so
; the installer and the Portable ZIP ship the same files.
Source: "embed_build\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Whisper Transcriber Suite {#MyAppVersion}"; Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\gui.py"""; WorkingDir: "{app}"; IconFilename: "{app}\assets\whisper.ico"
Name: "{group}\Uninstall Whisper Transcriber Suite"; Filename: "{uninstallexe}"
Name: "{commondesktop}\Whisper Transcriber Suite {#MyAppVersion}"; Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\gui.py"""; WorkingDir: "{app}"; IconFilename: "{app}\assets\whisper.ico"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop icon"; GroupDescription: "Shortcuts:"
Name: "shellext"; Description: "Add 'Transcribe with Whisper Transcriber Suite' to the Windows Explorer right-click menu"; GroupDescription: "Integration:"
; Clone Your Voice / Text to Voice is OFF by default -- a niche,
; legally/ethically sensitive feature most users never touch. Leaving
; this task unticked drops a no_voice_clone.flag marker in {app}; the app
; reads it at startup (core.hub.voice_clone_tab_enabled) and hides the tab.
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
Type: files; Name: "{app}\no_voice_clone.flag"
Type: dirifempty; Name: "{app}"

[InstallDelete]
; Marker written by installers from before the Video Tiling feature was removed.
Type: files; Name: "{app}\no_tiling.flag"

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
//
//  It runs in PrepareToInstall, after the user clicked Install: a
//  cancelled wizard leaves the old version untouched. By then the
//  wizard has read the previous folder and task choices from the old
//  uninstall key (UsePreviousAppDir / UsePreviousTasks), so removing
//  that key no longer resets them.
// --------------------------------------------------------------------

function UninstallKeyPath(AnAppId: String): String;
begin
  Result := 'Software\Microsoft\Windows\CurrentVersion\Uninstall\' + AnAppId + '_is1';
end;

function GetUninstallStringForAppId(AnAppId: String): String;
var
  UninstString: String;
begin
  UninstString := '';
  if not RegQueryStringValue(HKLM, UninstallKeyPath(AnAppId), 'UninstallString', UninstString) then
    RegQueryStringValue(HKLM32, UninstallKeyPath(AnAppId), 'UninstallString', UninstString);
  Result := UninstString;
end;

function UninstallKeyExists(AnAppId: String): Boolean;
begin
  Result := RegKeyExists(HKLM, UninstallKeyPath(AnAppId)) or
            RegKeyExists(HKLM32, UninstallKeyPath(AnAppId));
end;

// The AppId as Windows stores it: SetupSetting returns the directive's raw
// text with the doubled brace ("{{GUID}"); ExpandConstant turns it into
// "{GUID}", the name of the real uninstall key.
function ThisAppId(): String;
begin
  Result := ExpandConstant('{#SetupSetting("AppId")}');
end;

function GetUninstallString(): String;
begin
  Result := GetUninstallStringForAppId(ThisAppId());
end;

// Runs the uninstaller registered for AnAppId silently and returns '' when
// it finished, else the reason (shown by PrepareToInstall, which then stops
// before any file is copied). An Inno uninstaller relaunches itself from a
// temp copy and the first process exits at once, so ewWaitUntilTerminated
// alone returns while files are still being deleted: wait until the
// uninstall key and the uninstaller itself are gone (at most 3 minutes).
function RunOldUninstaller(AnAppId, What: String): String;
var
  UninstString: String;
  ResultCode, i: Integer;
begin
  Result := '';
  UninstString := RemoveQuotes(GetUninstallStringForAppId(AnAppId));
  if UninstString = '' then
    Exit;
  if not FileExists(UninstString) then begin
    // A broken old install (uninstaller deleted by hand): install over it.
    Log('Uninstaller of ' + What + ' not found: ' + UninstString);
    Exit;
  end;
  if not Exec(UninstString, '/SILENT /NORESTART /SUPPRESSMSGBOXES', '',
              SW_HIDE, ewWaitUntilTerminated, ResultCode) then begin
    Result := 'Setup could not start the uninstaller of ' + What + ': ' +
              SysErrorMessage(ResultCode);
    Exit;
  end;
  if ResultCode <> 0 then begin
    Result := 'Removing ' + What + ' failed (exit code ' + IntToStr(ResultCode) + ').';
    Exit;
  end;
  for i := 1 to 360 do begin
    if not UninstallKeyExists(AnAppId) and not FileExists(UninstString) then begin
      Log('Removed ' + What);
      Exit;
    end;
    Sleep(500);
  end;
  Result := 'Removing ' + What + ' did not finish within 3 minutes. ' +
            'Restart Windows and run Setup again.';
end;

// --------------------------------------------------------------------
//  One-time migration from the predecessor product ("Whisper Project",
//  AppId OldAppId) to this one (the 2026-08-23 rebrand).
//  The application imports legacy settings and databases on first launch:
//  it stages settings and merges SQLite history without replacing newer rows.
//  The installer only removes the old product; it never copies profile files.
//  The old profile stays available for the application's retryable migration.
// --------------------------------------------------------------------

const
  OldAppId = '{734B46B9-5E70-4C4E-8833-0A7506A64376}';

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  // Same-product upgrade (a newer Whisper Transcriber Suite over an
  // older one) takes priority. Only when there's no same-product
  // predecessor do we check for the pre-rebrand "Whisper Project"
  // product instead.
  // /SUPPRESSMSGBOXES auto-answers any Pascal MsgBox in the OLD
  // uninstaller too; CurUninstallStepChanged below skips the hub-folder
  // deletion prompt entirely when UninstallSilent() is true, so a model
  // hub OUTSIDE the install dir survives this automatic step either way.
  if GetUninstallString() <> '' then
    Result := RunOldUninstaller(ThisAppId(), 'the previous version')
  else begin
    Result := RunOldUninstaller(OldAppId, 'the old Whisper Project app');
  end;
end;

// --------------------------------------------------------------------
//  Hub-folder uninstall prompt — identical logic to installer.iss.
//  See that file for full commentary; this script keeps a copy so
//  the two installers stay self-contained (Inno has no [Include]).
// --------------------------------------------------------------------

// --------------------------------------------------------------------
//  Optional "Clone Your Voice / Text to Voice" feature toggle.
//
//  OFF by default (public-installer opt-in; legal/ethical sensitivity
//  + a ~2GB on-demand model).
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

// Native attributes identify links before descending through an ancestor.
function HubCacheAttributes(PathName: string): Cardinal;
  external 'GetFileAttributesW@kernel32.dll stdcall';
function HubCacheDriveType(RootPath: string): Cardinal;
  external 'GetDriveTypeW@kernel32.dll stdcall';

function CanDeletePrivateHub(HubFolder, PrivateCache: string): Boolean;
var
  Hub, Expected, Current, Remaining, Part: string;
  Separator: Integer;
  Attributes: Cardinal;
begin
  Result := False;
  if (Trim(HubFolder) = '') or (Trim(PrivateCache) = '') then
    Exit;
  try
    Hub := RemoveBackslashUnlessRoot(ExpandFileName(HubFolder));
    Expected := RemoveBackslashUnlessRoot(ExpandFileName(PrivateCache));
    if CompareText(Hub, Expected) <> 0 then
      Exit;
    if (Length(Hub) < 4) or (Copy(Hub, 2, 2) <> ':\') then
      Exit;
    // A mapped/network/removable drive is not an app-owned local cache.
    if HubCacheDriveType(Copy(Hub, 1, 3)) <> 3 then
      Exit;
    Current := Copy(Hub, 1, 3);
    Remaining := Copy(Hub, 4, Length(Hub));
    // Check top-down so a redirected parent is rejected before its target
    // is traversed. Unknown attributes always keep the directory.
    while Remaining <> '' do begin
      Separator := Pos('\', Remaining);
      if Separator = 0 then begin
        Part := Remaining;
        Remaining := '';
      end else begin
        Part := Copy(Remaining, 1, Separator - 1);
        Remaining := Copy(Remaining, Separator + 1, Length(Remaining));
      end;
      if Part = '' then
        Exit;
      Current := AddBackslash(Current) + Part;
      Attributes := HubCacheAttributes(Current);
      if (Attributes = $FFFFFFFF) or
         ((Attributes and FILE_ATTRIBUTE_DIRECTORY) = 0) or
         ((Attributes and $400) <> 0) then
        Exit;
    end;
    Result := True;
  except
    Result := False;
  end;
end;

// Delete only models in the verified private application cache, after an
// explicit interactive Yes. Custom hubs and redirected caches are retained.
// Inno DelTree does not recurse into nested reparse-point directories.
function DeleteHubModels(HubFolder, PrivateCache: string): Boolean;
var
  FindRec: TFindRec;
  Root: string;
begin
  Result := False;
  if not CanDeletePrivateHub(HubFolder, PrivateCache) then
    Exit;
  Result := True;
  Root := AddBackslash(HubFolder);
  if FindFirst(Root + 'models--*', FindRec) then begin
    try
      repeat
        // $400 = FILE_ATTRIBUTE_REPARSE_POINT
        if ((FindRec.Attributes and FILE_ATTRIBUTE_DIRECTORY) <> 0) and
           ((FindRec.Attributes and $400) = 0) then begin
          if not DelTree(Root + FindRec.Name, True, True, True) then
            Result := False;
        end;
      until not FindNext(FindRec);
    finally
      FindClose(FindRec);
    end;
  end;
  // RemoveDir only removes an empty folder.
  RemoveDir(HubFolder);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  HubFolder, PrivateCache, AppFolder, Msg, MarkerPath: string;
begin
  // Remove the optional-feature marker (created post-install when the
  // user opted out of Clone Your Voice). [UninstallDelete] also covers
  // it, but delete it explicitly so a partial uninstall leaves nothing
  // behind.
  if CurUninstallStep = usUninstall then begin
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
  // Read the saved hub location; settings remain available after uninstall.
  HubFolder := ExtractHubFolder();
  PrivateCache := ExpandConstant('{localappdata}\WhisperTranscriberSuite\Cache\models');
  if not CanDeletePrivateHub(HubFolder, PrivateCache) then begin
    Log('Skipped optional model-hub cleanup: ' + HubFolder);
    Exit;
  end;
  AppFolder := ExpandConstant('{app}');
  if not IsPathInside(HubFolder, AppFolder) then begin
    Msg := 'The app''s local model cache is located at:' + #13#10 + #13#10 +
           HubFolder + #13#10 + #13#10 +
           'It may contain several gigabytes of downloaded Whisper models.' + #13#10 +
           'Do you want to delete the downloaded models in it as part of the uninstall?' + #13#10 +
           'Choose No to keep models for reinstalls or other copies. Hubs outside the install folder are kept.';
    if MsgBox(Msg, mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then begin
      if not DeleteHubModels(HubFolder, PrivateCache) then
        MsgBox('Could not fully delete the models in ' + HubFolder + '.' + #13#10 +
               'You can remove them manually with File Explorer.',
               mbInformation, MB_OK);
    end;
  end;
  // Keep settings and history for reinstalls and Portable installations.
  // Profile migration belongs to the application, never the installer.
end;
