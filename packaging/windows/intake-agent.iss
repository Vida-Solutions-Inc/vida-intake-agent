; Inno Setup script for the Intake Agent Windows installer.
;
; Produces a per-user installer (no admin prompt) that installs the bundled
; app, creates Start Menu + optional Desktop shortcuts, and offers to launch
; the app at the end. "Run at login" is managed inside the app itself.
;
; Build:
;   1) pyinstaller packaging/intake-agent.spec        -> dist\IntakeAgent.exe
;   2) iscc /DMyAppVersion=0.2.0 packaging\windows\intake-agent.iss
;   -> Output\IntakeAgentSetup.exe
;
; CI passes the version via /DMyAppVersion. A default is provided for local use.

#ifndef MyAppVersion
  #define MyAppVersion "0.2.0"
#endif
#define MyAppName "Intake Agent"
#define MyAppPublisher "Vida Solutions, Inc."
#define MyAppExeName "IntakeAgent.exe"
#define MyAppURL "https://github.com/Vida-Solutions-Inc/vida-intake-agent"

[Setup]
AppId={{8E6C2F1A-7D3B-4C9E-9A2F-1B5E3C7A9D40}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
DefaultDirName={localappdata}\Programs\Intake Agent
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\..\Output
OutputBaseFilename=IntakeAgentSetup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExeName}

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Files]
; The single-file PyInstaller build.
Source: "..\..\dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{userdesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName} now"; Flags: nowait postinstall skipifsilent
