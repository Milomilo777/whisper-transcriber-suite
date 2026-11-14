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

#define MyAppVersion "2.4.0"

[Setup]
; Stable AppId — keeps a single, upgradable Add/Remove Programs entry
; across versions (and shared with the Standard installer, same product).
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
OutputBaseFilename=WhisperTranscriberSuite-v{#MyAppVersion}-Setup-Compact
OutputDir=dist_installer
Compression=lzma2/ultra
SolidCompression=yes
PrivilegesRequired=admin
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayName=Whisper Transcriber Suite
UninstallDisplayIcon={app}\assets\whisper.ico
SetupIconFile=assets\whisper.ico

; Retire historical recursive-deletion records. Old-only packaged files may
; remain; preserving unknown user additions takes priority over purging them.
; https://jrsoftware.org/ishelp/topic_appendnotes.htm
UninstallLogMode=overwrite

[Files]
Source: "dist_onedir\WhisperTranscriberSuite\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "assets\whisper.ico"; DestDir: "{app}\assets"; Flags: ignoreversion
Source: "assets\whisper.png"; DestDir: "{app}\assets"; Flags: ignoreversion
Source: "assets\sample_clip.mp3"; DestDir: "{app}\assets"; Flags: ignoreversion
Source: "assets\icons\*"; DestDir: "{app}\assets\icons"; Flags: ignoreversion

[Icons]
Name: "{group}\Whisper Transcriber Suite"; Filename: "{app}\WhisperTranscriberSuite.exe"; IconFilename: "{app}\assets\whisper.ico"
Name: "{group}\Uninstall Whisper Transcriber Suite"; Filename: "{uninstallexe}"
Name: "{commondesktop}\Whisper Transcriber Suite"; Filename: "{app}\WhisperTranscriberSuite.exe"; IconFilename: "{app}\assets\whisper.ico"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop icon"; GroupDescription: "Shortcuts:"
Name: "shellext"; Description: "Add 'Transcribe with Whisper Transcriber Suite' to the Windows Explorer right-click menu"; GroupDescription: "Integration:"

[Registry]
; Retire this app-owned integration when an overlay upgrade deselects it.
Root: HKCR; Subkey: "*\shell\WhisperTranscriberSuiteTranscribe"; ValueType: none; Flags: deletekey; Tasks: not shellext

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
Type: dirifempty; Name: "{app}"

[Code]
// Read-only detection of an existing installation. Never invoke its
// uninstaller during an upgrade: older versions delete user-added files.
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
  Result := GetUninstallStringForAppId(ExpandConstant('{#SetupSetting("AppId")}'));
end;

// --------------------------------------------------------------------
//  Detect the predecessor product ("Whisper Project", AppId OldAppId).
//  Profile import belongs to the application, which can stage settings
//  and merge SQLite history without replacing newer rows.
// --------------------------------------------------------------------

const
  OldAppId = '{734B46B9-5E70-4C4E-8833-0A7506A64376}';


// Refuse cross-product overlays: the retained predecessor uninstaller still
// owns its old folder and may recursively delete files installed beneath it.
// Resolve existing ancestors through directory handles, including reparse
// points, short names and mapped paths. Append only proven-missing components.
type
  TPredecessorFileInfo = record
    Attributes: Cardinal;
    CreationTime, AccessTime, WriteTime: TFileTime;
    VolumeSerial, SizeHigh, SizeLow, LinkCount, IndexHigh, IndexLow: Cardinal;
  end;

function PredecessorOpenPath(Name: String; Access, Share: Cardinal;
  Security: THandle; Creation, Flags: Cardinal; Template: THandle): THandle;
  external 'CreateFileW@kernel32.dll stdcall';
function PredecessorFinalPath(Handle: THandle; Buffer: String;
  Capacity, Flags: Cardinal): Cardinal;
  external 'GetFinalPathNameByHandleW@kernel32.dll stdcall';
function PredecessorFileInfo(Handle: THandle; var Info: TPredecessorFileInfo): BOOL;
  external 'GetFileInformationByHandle@kernel32.dll stdcall';
function PredecessorClosePath(Handle: THandle): BOOL;
  external 'CloseHandle@kernel32.dll stdcall';
function PredecessorPathAttributes(Name: String): Cardinal;
  external 'GetFileAttributesW@kernel32.dll stdcall';
function PredecessorLastError(): Cardinal;
  external 'GetLastError@kernel32.dll stdcall';

function CanonicalPredecessorFolder(Folder: String; var Canonical: String): Boolean;
var
  Current, Parent, Leaf, Suffix, Buffer: String;
  Handle: THandle;
  Count, Error, Attributes: Cardinal;
  Info: TPredecessorFileInfo;
begin
  Result := False;
  Canonical := '';
  if (Copy(Folder, 2, 2) <> ':\') and (Copy(Folder, 1, 2) <> '\\') then Exit;
  Current := RemoveBackslashUnlessRoot(ExpandFileName(Folder));
  if Length(Current) > 32767 then Exit;
  Suffix := '';
  while Current <> '' do begin
    // OPEN_EXISTING + BACKUP_SEMANTICS follows directory reparse targets.
    Handle := PredecessorOpenPath(Current, 0, 7, 0, 3, $02000000, 0);
    if Handle <> THandle(-1) then begin
      try
        if not PredecessorFileInfo(Handle, Info) then Exit;
        if (Info.Attributes and FILE_ATTRIBUTE_DIRECTORY) = 0 then Exit;
        SetLength(Buffer, 32768);
        // FILE_NAME_NORMALIZED + VOLUME_NAME_NT avoids drive-letter aliases.
        Count := PredecessorFinalPath(Handle, Buffer, Length(Buffer), 2);
        if (Count = 0) or (Count >= Cardinal(Length(Buffer))) then Exit;
        Canonical := AddBackslash(Copy(Buffer, 1, Count)) + Suffix;
        if Length(Canonical) > 32767 then Exit;
        Result := True;
        Exit;
      finally
        PredecessorClosePath(Handle);
      end;
    end;
    Error := PredecessorLastError();
    if (Error <> 2) and (Error <> 3) then Exit;
    // A broken/denied reparse route is not a nonexistent ordinary component.
    Attributes := PredecessorPathAttributes(Current);
    if Attributes <> $FFFFFFFF then Exit;
    Error := PredecessorLastError();
    if (Error <> 2) and (Error <> 3) then Exit;
    Leaf := ExtractFileName(Current);
    Parent := RemoveBackslashUnlessRoot(ExtractFileDir(Current));
    if (Leaf = '') or (Parent = '') or (Parent = Current) then Exit;
    Suffix := Leaf + '\' + Suffix;
    Current := Parent;
  end;
end;

// CompareStringOrdinal requires numeric TRUE=1, not an arbitrary nonzero BOOL.
function PredecessorCompareNames(First: String; FirstLength: Integer;
  Second: String; SecondLength: Integer; IgnoreCase: Integer): Integer;
  external 'CompareStringOrdinal@kernel32.dll stdcall';

function PredecessorPathsOverlap(OldDir, NewDir: String): Boolean;
var Comparison: Integer;
begin
  Result := True;
  if Length(OldDir) <= Length(NewDir) then begin
    Comparison := PredecessorCompareNames(OldDir, Length(OldDir), NewDir, Length(OldDir), 1);
    if (Comparison <> 1) and (Comparison <> 3) then Exit;
  end;
  if Length(NewDir) <= Length(OldDir) then begin
    Comparison := PredecessorCompareNames(NewDir, Length(NewDir), OldDir, Length(NewDir), 1);
    if (Comparison <> 1) and (Comparison <> 3) then Exit;
  end;
  Result := False;
end;

function PredecessorDriveType(Root: String): Cardinal;
  external 'GetDriveTypeW@kernel32.dll stdcall';

// Different SMB authority/share spellings may refer to the same storage.
// Only compare names inside one proven normalized namespace; otherwise refuse.
function PredecessorNamespace(Canonical, Original: String): String;
var Remaining, Device, Server, Share: String;
  Separator: Integer;
  DriveType: Cardinal;
begin
  Result := '';
  if Lowercase(Copy(Canonical, 1, 8)) <> '\device\' then Exit;
  Remaining := Copy(Canonical, 9, Length(Canonical));
  Separator := Pos('\', Remaining);
  if Separator = 0 then Exit;
  Device := Lowercase(Copy(Remaining, 1, Separator - 1));
  Remaining := Copy(Remaining, Separator + 1, Length(Remaining));
  if Device = 'mup' then begin
    Separator := Pos('\', Remaining);
    if Separator = 0 then Exit;
    Server := Copy(Remaining, 1, Separator - 1);
    Remaining := Copy(Remaining, Separator + 1, Length(Remaining));
    Separator := Pos('\', Remaining);
    if Separator = 0 then Exit;
    Share := Copy(Remaining, 1, Separator - 1);
    if (Server = '') or (Share = '') or (Pos(';', Server) <> 0) or
       (Pos(':', Server) <> 0) then Exit;
    Result := '\device\mup\' + Server + '\' + Share + '\';
  end else begin
    DriveType := PredecessorDriveType(AddBackslash(ExtractFileDrive(Original)));
    if (DriveType = 0) or (DriveType = 1) or (DriveType = 4) then Exit;
    if (Device = '') or (Device = 'lanmanredirector') or (Device = 'webdavredirector') then Exit;
    Result := '\device\' + Device + '\';
  end;
end;

function PredecessorFolderOverlaps(RootKey: Integer): Boolean;
var OldDir, OldPhysical, NewDir, OldNamespace, NewNamespace, UninstPath: String;
begin
  Result := False;
  OldDir := '';
  UninstPath := 'Software\Microsoft\Windows\CurrentVersion\Uninstall\' + OldAppId + '_is1';
  if not RegKeyExists(RootKey, UninstPath) then Exit;
  if not RegQueryStringValue(RootKey, UninstPath, 'Inno Setup: App Path', OldDir) then begin Result := True; Exit; end;
  if OldDir = '' then begin Result := True; Exit; end;
  // Unknown physical ownership must not permit a cross-product overlay.
  if not CanonicalPredecessorFolder(OldDir, OldPhysical) then begin Result := True; Exit; end;
  if not CanonicalPredecessorFolder(ExpandConstant('{app}'), NewDir) then begin Result := True; Exit; end;
  OldNamespace := PredecessorNamespace(OldPhysical, OldDir);
  NewNamespace := PredecessorNamespace(NewDir, ExpandConstant('{app}'));
  if (OldNamespace = '') or (NewNamespace = '') then begin Result := True; Exit; end;
  if ((Pos('\device\mup\', OldNamespace) = 1) or (Pos('\device\mup\', NewNamespace) = 1)) and
     (PredecessorCompareNames(OldNamespace, Length(OldNamespace), NewNamespace, Length(NewNamespace), 1) <> 2) then begin Result := True; Exit; end;
  OldDir := OldPhysical;
  Result := PredecessorPathsOverlap(OldDir, NewDir);
end;

function SharesPredecessorFolder(): Boolean;
begin
  // Registrations can coexist in both views at different locations. A
  // non-overlapping native-view path must not mask the 32-bit-view path.
  Result := PredecessorFolderOverlaps(HKLM) or PredecessorFolderOverlaps(HKLM32);
end;

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
  if SharesPredecessorFolder() then begin
    Result := 'Choose a different folder from the earlier Whisper Project installation. Its retained uninstaller could remove files from this folder.';
    Exit;
  end;
  if GetUninstallString() <> '' then begin
    Log('Upgrade in place; existing user additions are preserved.');
    CleanupVersionedShortcuts();
  end
  else if GetUninstallStringForAppId(OldAppId) <> '' then
    Log('Previous product retained; profile migration runs on first launch.');
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
  HubFolder, PrivateCache, AppFolder, Msg: string;
begin
  if CurUninstallStep <> usPostUninstall then
    Exit;
  // An unattended uninstall must not prompt to delete downloaded models.
  if UninstallSilent() then
    Exit;
  HubFolder := ExtractHubFolder();
  PrivateCache := ExpandConstant('{localappdata}\WhisperTranscriberSuite\Cache\models');
  if not CanDeletePrivateHub(HubFolder, PrivateCache) then begin
    Log('Skipped optional model-hub cleanup: ' + HubFolder);
    Exit;
  end;
  AppFolder := ExpandConstant('{app}');
  // Preserve custom models inside the installation directory as user data.
  if IsPathInside(HubFolder, AppFolder) then
    Exit;
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
