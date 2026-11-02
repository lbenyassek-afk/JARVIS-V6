#define MyAppName "JARVIS V6"
#define MyAppVersion "6.0.0"
#define MyAppPublisher "Reda Benyassek"
#define MyAppExeName "JARVIS V6.exe"

[Setup]
AppId={{B6403D91-890E-46B6-A210-6F0A0B6E6001}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription=JARVIS V6 Personal Intelligence
VersionInfoCopyright=Copyright (C) 2026 Reda Benyassek
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
PrivilegesRequired=lowest
OutputDir=release
OutputBaseFilename=JARVIS-V6-Setup
SetupIconFile=jarvis.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}

[Files]
Source: "dist\JARVIS V6\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\JARVIS V6"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{autodesktop}\JARVIS V6"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{userstartup}\JARVIS V6"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--background"; WorkingDir: "{app}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch JARVIS V6"; Flags: nowait postinstall skipifsilent
