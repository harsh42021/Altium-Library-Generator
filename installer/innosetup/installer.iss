; Inno Setup script for Altium Library Generator.
;
; Build (on Windows, with Inno Setup installed: https://jrsoftware.org/isinfo.php):
;     1. Run PyInstaller first (see altium_libgen.spec) so dist\AltiumLibraryGenerator\ exists.
;     2. Open this file in Inno Setup Compiler (or run: iscc installer.iss)
;
; Output: installer/output/AltiumLibraryGeneratorSetup.exe

#define MyAppName "Altium Library Generator"
#define MyAppVersion "0.1.0"
#define MyAppPublisher "Your Organization"
#define MyAppExeName "AltiumLibraryGenerator.exe"

[Setup]
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
OutputBaseFilename=AltiumLibraryGeneratorSetup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; Uncomment and provide an .ico if you have one:
; SetupIconFile=app_icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: checkedonce

[Files]
; Pulls in everything PyInstaller produced (the exe plus its bundled
; Python runtime and dependencies) — this is what means end users
; never need Python or pip installed at all.
Source: "..\..\dist\AltiumLibraryGenerator\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
