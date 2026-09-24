; installer.iss — Inno Setup script for the WhisperTranscriberSuite
; Windows installer (Method B of the dual-deliverable plan).
;
; Build:
;   "C:\Users\Owner\AppData\Local\Programs\Inno Setup 6\ISCC.exe" installer.iss
;
; The installer packages the onedir build from
; dist_onedir\WhisperTranscriberSuite\ (produced by
; whisper_project_onedir.spec) and emits a single
; WhisperTranscriberSuite-Setup.exe under dist_installer\.

[Setup]
; Stable AppId — keeps a single, upgradable Add/Remove Programs entry
; across versions (and shared with the Standard installer, same product).
; Changed 2026-08-23 for the "Whisper Project" -> "Whisper Transcriber
; Suite" rebrand (was {734B46B9-5E70-4C4E-8833-0A7506A64376} -- see
; OldAppId in [Code] below, which drives the one-time data migration
; from the predecessor product).
AppId={{BD640ACA-1EDB-4F9F-890E-C2DC04221871}
AppName=SMTV Whisper Transcriber Suite
AppVersion=1.9.1
AppPublisher=translation-robot
AppPublisherURL=https://github.com/translation-robot
DefaultDirName={autopf}\WhisperTranscriberSuite
DefaultGroupName=Whisper Transcriber Suite
OutputBaseFilename=WhisperTranscriberSuite-v1.9.1-Setup-Compact
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
Source: "dist_onedir\WhisperTranscriberSuite\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "assets\whisper.ico"; DestDir: "{app}\assets"; Flags: ignoreversion
Source: "assets\whisper.png"; DestDir: "{app}\assets"; Flags: ignoreversion

[Icons]
Name: "{group}\Whisper Transcriber Suite"; Filename: "{app}\WhisperTranscriberSuite.exe"; IconFilename: "{app}\assets\whisper.ico"
Name: "{group}\Uninstall Whisper Transcriber Suite"; Filename: "{uninstallexe}"
Name: "{commondesktop}\Whisper Transcriber Suite"; Filename: "{app}\WhisperTranscriberSuite.exe"; IconFilename: "{app}\assets\whisper.ico"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop icon"; GroupDescription: "Shortcuts:"
Name: "shellext"; Description: "Add 'Transcribe with Whisper Transcriber Suite' to the Windows Explorer right-click menu"; GroupDescription: "Integration:"

[Registry]
; Explorer shell extension — adds a 'Transcribe with Whisper Transcriber
; Suite' verb to every file's right-click menu. Hits the CLI mode added
; in v0.7.0 (gui.py / WhisperTranscriberSuite.exe transcribe "<path>").
; The keys live under HKCR\*\shell so they apply to every file
; regardless of extension; admin install means we write them once for
; all users.
Root: HKCR; Subkey: "*\shell\WhisperTranscriberSuiteTranscribe"; ValueType: string; ValueName: ""; ValueData: "Transcribe with Whisper Transcriber Suite"; Flags: uninsdeletekey; Tasks: shellext
Root: HKCR; Subkey: "*\shell\WhisperTranscriberSuiteTranscribe"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\WhisperTranscriberSuite.exe,0"; Tasks: shellext
Root: HKCR; Subkey: "*\shell\WhisperTranscriberSuiteTranscribe\command"; ValueType: string; ValueName: ""; ValueData: """{app}\WhisperTranscriberSuite.exe"" transcribe ""%1"""; Tasks: shellext

[Run]
Filename: "{app}\WhisperTranscriberSuite.exe"; Description: "Launch Whisper Transcriber Suite"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; PyInstaller drops __pycache__ trees beside the exe on first
; launch; Inno doesn't track files created after install, so sweep
; them on uninstall. dirifempty cleans up if nothing else remains.
Type: filesandordirs; Name: "{app}\__pycache__"
Type: filesandordirs; Name: "{app}\assets"
Type: dirifempty; Name: "{app}"

[Code]
// --------------------------------------------------------------------
//  Silently uninstall a previous version before installing this one —
//  identical logic to installer_embed.iss. See that file for the full
//  rationale; this script keeps a copy so the two installers stay
//  self-contained (Inno has no [Include]).
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
//  AppId OldAppId) — identical logic to installer_embed.iss. See that
//  file for the full rationale; this script keeps a copy so the two
//  installers stay self-contained (Inno has no [Include]).
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
  // Gate on the NEW config.json specifically -- see installer_embed.iss
  // for the full rationale (a real install test on 2026-08-23 found
  // that gating on the bare folder's existence let a stray empty
  // new-name folder from an unrelated earlier run silently skip a
  // real migration). Copy only the small settings/history files
  // directly with FileCopy, not the whole tree with xcopy -- Cache\
  // can hold several GB of models and Logs\ hundreds of small debug
  // logs, and neither is needed: config.json's hub_folder value still
  // resolves to the OLD, still-on-disk model cache either way.
  if DirExists(OldDataDir) and not FileExists(NewDataDir + '\config.json') then begin
    if not DirExists(NewDataDir) then
      ForceDirectories(NewDataDir);
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
  UninstString := GetUninstallString();
  if UninstString <> '' then begin
    UninstString := RemoveQuotes(UninstString);
    if not Exec(UninstString, '/SILENT /NORESTART /SUPPRESSMSGBOXES', '',
                SW_HIDE, ewWaitUntilTerminated, ResultCode) then
      Log('Could not run the previous version''s uninstaller: ' + UninstString);
  end else begin
    MigrateOldAppData();
  end;
end;

// --------------------------------------------------------------------
//  Hub-folder uninstall prompt
//
//  The user can pick where Whisper model files live (the "hub"
//  folder). When the folder is INSIDE the install dir it goes away
//  with the rest of the install. When it is OUTSIDE (e.g. an
//  external drive the user chose during first-launch), the
//  installer asks whether to delete it too. The decision is the
//  user's; we never touch it without a Yes.
//
//  The hub_folder value lives in
//    %LOCALAPPDATA%\WhisperTranscriberSuite\config.json
//  which we parse with a tiny regex-free string search to avoid
//  pulling a JSON library into the Pascal Script side.
// --------------------------------------------------------------------

function ExtractHubFolder(): string;
var
  ConfigPath: string;
  Lines: TArrayOfString;
  i, ColonPos, StartQ, EndQ: Integer;
  Line, Key, Value: string;
begin
  Result := '';
  // platformdirs.user_config_dir("WhisperTranscriberSuite", appauthor=False)
  // on Windows resolves to %LOCALAPPDATA% (not %APPDATA% which is
  // Roaming). Inno's {localappdata} expands to the same path, so
  // config.json lives at <localappdata>\WhisperTranscriberSuite\config.json
  // — verified empirically at install time.
  ConfigPath := ExpandConstant('{localappdata}\WhisperTranscriberSuite\config.json');
  if not FileExists(ConfigPath) then
    Exit;
  if not LoadStringsFromFile(ConfigPath, Lines) then
    Exit;
  for i := 0 to GetArrayLength(Lines) - 1 do begin
    Line := Trim(Lines[i]);
    if Pos('"hub_folder"', Line) <> 1 then
      Continue;
    // Layout: "hub_folder": "C:\\path\\to\\hub", ...
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
    // Replace JSON-escaped backslashes with real ones.
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
  HubFolder, AppFolder, Msg: string;
begin
  if CurUninstallStep <> usPostUninstall then
    Exit;
  // A silent uninstall only ever happens automatically, as the
  // pre-install step above for an in-place upgrade — never ask to
  // delete a multi-GB model hub folder in that unattended path.
  if UninstallSilent() then
    Exit;
  HubFolder := ExtractHubFolder();
  if (HubFolder = '') or (not DirExists(HubFolder)) then
    Exit;
  AppFolder := ExpandConstant('{app}');
  // When the hub sat under the app dir, Inno already swept it
  // via the onedir uninstall + UninstallDelete entries; nothing
  // to do here.
  if IsPathInside(HubFolder, AppFolder) then
    Exit;
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
