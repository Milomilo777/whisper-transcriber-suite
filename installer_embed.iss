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

; Retire historical recursive-deletion records. Old-only packaged files may
; remain; preserving unknown user additions takes priority over purging them.
; https://jrsoftware.org/ishelp/topic_appendnotes.htm
UninstallLogMode=overwrite

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
; Retire this app-owned integration when an overlay upgrade deselects it.
Root: HKCR; Subkey: "*\shell\WhisperTranscriberSuiteTranscribe"; ValueType: none; Flags: deletekey; Tasks: not shellext

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
; files created after install. Only sweep the root bytecode cache;
; preserve untracked user files in application/runtime subdirectories.
; https://jrsoftware.org/ishelp/topic_uninstalldeletesection.htm
Type: filesandordirs; Name: "{app}\__pycache__"
Type: files; Name: "{app}\gui.py"
Type: files; Name: "{app}\sitecustomize.py"
Type: files; Name: "{app}\no_voice_clone.flag"
Type: dirifempty; Name: "{app}"

[InstallDelete]
; Marker written by installers from before the Video Tiling feature was removed.
Type: files; Name: "{app}\no_tiling.flag"

[Code]
// Read-only detection of an existing installation. Never invoke its
// uninstaller during an upgrade: older versions delete user-added files.
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

// --------------------------------------------------------------------
//  One-time migration from the predecessor product ("Whisper Project",
//  AppId OldAppId) to this one (the 2026-08-23 rebrand).
//  The application imports legacy settings and databases on first launch:
//  it stages settings and merges SQLite history without replacing newer rows.
//  The installer retains the old product and never copies profile files.
//  The old profile stays available for the application's retryable migration.
// --------------------------------------------------------------------

const
  OldAppId = '{734B46B9-5E70-4C4E-8833-0A7506A64376}';

// Versioned shortcut maintenance.
function ShortcutFileAttributes(PathName: String): Cardinal;
  external 'GetFileAttributesW@kernel32.dll stdcall';
function ShortcutDriveType(RootPath: String): Cardinal;
  external 'GetDriveTypeW@kernel32.dll stdcall';

function PlainShortcutFolder(Folder: String): Boolean;
var
  Current, Remaining, Part: String;
  Separator: Integer;
  Attributes: Cardinal;
begin
  Result := False;
  Folder := RemoveBackslashUnlessRoot(ExpandFileName(Folder));
  if (Length(Folder) < 4) or (Copy(Folder, 2, 2) <> ':\') then Exit;
  if ShortcutDriveType(Copy(Folder, 1, 3)) <> 3 then Exit;
  Current := Copy(Folder, 1, 3);
  Remaining := Copy(Folder, 4, Length(Folder));
  while Remaining <> '' do begin
    Separator := Pos('\', Remaining);
    if Separator = 0 then begin Part := Remaining; Remaining := ''; end
    else begin
      Part := Copy(Remaining, 1, Separator - 1);
      Remaining := Copy(Remaining, Separator + 1, Length(Remaining));
    end;
    if Part = '' then Exit;
    Current := AddBackslash(Current) + Part;
    Attributes := ShortcutFileAttributes(Current);
    if (Attributes = $FFFFFFFF) or ((Attributes and FILE_ATTRIBUTE_DIRECTORY) = 0) or
       ((Attributes and $400) <> 0) then Exit;
  end;
  Result := True;
end;

procedure CleanupVersionedShortcutFolder(Folder: String);
var
  FindRec: TFindRec;
  VersionText, LinkPath, Target, Arguments: String;
  Version, CurrentVersion: Int64;
  Shell, Shortcut: Variant;
begin
  // Retain unknown, redirected and custom links. Match both the historical
  // installer filename and its exact embedded-app target and arguments.
  if not PlainShortcutFolder(Folder) then Exit;
  if not StrToVersion('{#MyAppVersion}', CurrentVersion) then Exit;
  if FindFirst(AddBackslash(Folder) + 'Whisper Transcriber Suite *.lnk', FindRec) then begin
    try
      repeat
        if (FindRec.Attributes and (FILE_ATTRIBUTE_DIRECTORY or $400)) = 0 then begin
          VersionText := Copy(FindRec.Name, Length('Whisper Transcriber Suite ') + 1,
            Length(FindRec.Name) - Length('Whisper Transcriber Suite ') - Length('.lnk'));
          if StrToVersion(VersionText, Version) and
             (ComparePackedVersion(Version, CurrentVersion) < 0) then begin
            LinkPath := AddBackslash(Folder) + FindRec.Name;
            try
              Shell := CreateOleObject('WScript.Shell');
              Shortcut := Shell.CreateShortcut(LinkPath);
              Target := Shortcut.TargetPath;
              Arguments := Shortcut.Arguments;
              if (CompareText(ExpandFileName(Target), ExpandConstant('{app}\python\pythonw.exe')) = 0) and
                 (CompareText(Arguments, '"' + ExpandConstant('{app}\gui.py') + '"') = 0) then begin
                if not DeleteFile(LinkPath) then Log('Could not remove historical shortcut: ' + LinkPath);
              end;
            except
              Log('Retained unreadable historical shortcut: ' + LinkPath);
            end;
          end;
        end;
      until not FindNext(FindRec);
    finally
      FindClose(FindRec);
    end;
  end;
end;

procedure CleanupVersionedShortcuts();
begin
  CleanupVersionedShortcutFolder(ExpandConstant('{group}'));
  CleanupVersionedShortcutFolder(ExpandConstant('{commondesktop}'));
end;
// End versioned shortcut maintenance.

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  // Historical uninstallers recursively remove untracked user additions.
  // Upgrade in place and let the application import legacy profile data.
  Result := '';
  if GetUninstallString() <> '' then begin
    Log('Upgrade in place; existing user additions are preserved.');
    CleanupVersionedShortcuts();
  end
  else if GetUninstallStringForAppId(OldAppId) <> '' then
    Log('Previous product retained; profile migration runs on first launch.');
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
  // An unattended uninstall must not prompt to delete downloaded models.
  // Keep settings, credentials and preferences for other app copies.
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
           'Choose No to keep models for reinstalls or other copies. Other model folders are kept.';
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
