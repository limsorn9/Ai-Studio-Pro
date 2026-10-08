[Setup]
AppId={{AiStudio-PRO-V2.7.0}
AppName=Ai Studio Pro
AppVersion=2.7.0
AppPublisher=កំពូលអ្នកបកប្រែរឿង
AppPublisherURL=https://github.com/limsorn9/Ai-Studio-Pro
AppSupportURL=https://github.com/limsorn9/Ai-Studio-Pro
AppUpdatesURL=https://github.com/limsorn9/Ai-Studio-Pro
DefaultDirName={autopf}\Ai Studio Pro
DefaultGroupName=Ai Studio Pro
AllowNoIcons=yes
; Output installer name
OutputBaseFilename=AiStudioPro_v2.7.0_Setup
OutputDir=d:\Ai Studio Pro\out
; Ultra compression
Compression=lzma2/ultra64
SolidCompression=yes
DiskSpanning=yes
DiskSliceSize=2100000000
SetupIconFile=d:\Ai Studio Pro\phoenix_logo.ico
UninstallDisplayIcon={app}\AiStudioPro.exe
ArchitecturesInstallIn64BitMode=x64

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "d:\Ai Studio Pro\app\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "model\VoxCPM2\*"

[Icons]
Name: "{group}\Ai Studio Pro"; Filename: "{app}\AiStudioPro.exe"
Name: "{autodesktop}\Ai Studio Pro"; Filename: "{app}\AiStudioPro.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\AiStudioPro.exe"; Description: "{cm:LaunchProgram,Ai Studio Pro}"; Flags: nowait postinstall skipifsilent
