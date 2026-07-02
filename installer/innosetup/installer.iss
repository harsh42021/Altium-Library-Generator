; Inno Setup script for The Construct.
;
; Build (on Windows, with Inno Setup installed: https://jrsoftware.org/isinfo.php):
;     1. Run PyInstaller first (see altium_libgen.spec) so dist\TheConstruct\ exists.
;     2. Open this file in Inno Setup Compiler (or run: iscc installer.iss)
;
; Output: installer/output/TheConstructSetup.exe

#define MyAppName "The Construct"
#define MyAppVersion "0.3.0"
; Bump MyAppVersion on every build you intend to distribute — this is
; what shows up in Add/Remove Programs and what the upgrade-detection
; logic below uses to tell the user what version is replacing what.
#define MyAppPublisher "Your Organization"
#define MyAppExeName "TheConstruct.exe"

[Setup]
; AppId is UNCHANGED from the "Altium Library Generator" builds —
; this is a rename/rebrand of the same tool, not a new product, so
; keeping the same AppId lets the upgrade-detection logic below
; correctly recognize and replace a previous install rather than
; leaving two separate apps side by side.
AppId={{B7C9D1E2-4F3A-4E5B-9C1D-1A2B3C4D5E6F}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; Requires admin to install to Program Files; installer will prompt via UAC.
PrivilegesRequired=admin
OutputDir=..\output
OutputBaseFilename=TheConstructSetup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile=..\pyinstaller\app_icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: checkedonce

[Files]
; Pulls in everything PyInstaller produced (the exe plus its bundled
; Python runtime and dependencies) — this is what means end users
; never need Python or pip installed at all.
Source: "..\..\dist\TheConstruct\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[Code]
// Upgrade detection: since AppId stays fixed across versions, a
// previous install (any version) registers itself under this same
// registry key. We look it up, and if found, offer to silently run
// its uninstaller before laying down the new version — this avoids
// leftover files from a differently-structured old build sitting
// alongside the new one in Program Files.

function GetUninstallString(): String;
var
  sUnInstPath: String;
  sUnInstallString: String;
begin
  sUnInstPath := ExpandConstant('Software\Microsoft\Windows\CurrentVersion\Uninstall\{#emit SetupSetting("AppId")}_is1');
  sUnInstallString := '';
  if not RegQueryStringValue(HKLM, sUnInstPath, 'UninstallString', sUnInstallString) then
    RegQueryStringValue(HKCU, sUnInstPath, 'UninstallString', sUnInstallString);
  Result := sUnInstallString;
end;

function GetInstalledVersion(): String;
var
  sUnInstPath: String;
  sVersion: String;
begin
  sUnInstPath := ExpandConstant('Software\Microsoft\Windows\CurrentVersion\Uninstall\{#emit SetupSetting("AppId")}_is1');
  sVersion := '';
  if not RegQueryStringValue(HKLM, sUnInstPath, 'DisplayVersion', sVersion) then
    RegQueryStringValue(HKCU, sUnInstPath, 'DisplayVersion', sVersion);
  Result := sVersion;
end;

function IsUpgrade(): Boolean;
begin
  Result := (GetUninstallString() <> '');
end;

function UnInstallOldVersion(): Integer;
var
  sUnInstallString: String;
  iResultCode: Integer;
begin
  { Return values: 1 = nothing to uninstall, 2 = uninstall failed, 3 = success }
  Result := 0;
  sUnInstallString := GetUninstallString();
  if sUnInstallString <> '' then begin
    sUnInstallString := RemoveQuotes(sUnInstallString);
    if Exec(sUnInstallString, '/SILENT /NORESTART /SUPPRESSMSGBOXES', '', SW_HIDE, ewWaitUntilTerminated, iResultCode) then
      Result := 3
    else
      Result := 2;
  end else
    Result := 1;
end;

function InitializeSetup(): Boolean;
var
  sOldVersion: String;
  iChoice: Integer;
begin
  Result := True;
  if IsUpgrade() then begin
    sOldVersion := GetInstalledVersion();
    if sOldVersion = '' then sOldVersion := '(unknown version)';
    iChoice := MsgBox(
      'A previous installation of {#MyAppName} (version ' + sOldVersion + ') was found.' + #13#10#13#10 +
      'It will be removed before installing version {#MyAppVersion}.' + #13#10#13#10 +
      'Continue?',
      mbConfirmation, MB_YESNO);
    if iChoice = IDYES then begin
      if UnInstallOldVersion() = 2 then begin
        MsgBox('The previous version could not be removed automatically. Please uninstall it manually via Add/Remove Programs, then run this installer again.', mbError, MB_OK);
        Result := False;
      end;
    end else begin
      Result := False;  // user declined — abort setup rather than install alongside the old version
    end;
  end;
end;
