#define MyAppName "BlueLCMS"
#define MyAppVersion GetEnv("BLUELCMS_VERSION")
#define MyAppPublisher "Andre Zenz"

[Setup]
AppId={{FD4AE784-6CB4-4F29-8C80-3A79B4B6C1AE}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\BlueLCMS
DefaultGroupName=BlueLCMS
OutputDir=..\..\dist
OutputBaseFilename=BlueLCMS-setup
Compression=lzma
SolidCompression=yes

[Files]
Source: "..\..\dist\BlueLCMS\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{autoprograms}\BlueLCMS"; Filename: "{app}\BlueLCMS.exe"
Name: "{autodesktop}\BlueLCMS"; Filename: "{app}\BlueLCMS.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Run]
Filename: "{app}\BlueLCMS.exe"; Description: "Launch BlueLCMS"; Flags: nowait postinstall skipifsilent
