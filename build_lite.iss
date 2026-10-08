[Setup]
AppId={{AiStudio-PRO-V2.6.2-LITE}
AppName=Ai Studio Pro
AppVersion=2.6.2
AppPublisher=កំពូលអ្នកបកប្រែរឿង
AppPublisherURL=https://github.com/limsorn9/Ai-Studio-Pro
AppSupportURL=https://github.com/limsorn9/Ai-Studio-Pro
AppUpdatesURL=https://github.com/limsorn9/Ai-Studio-Pro
DefaultDirName={autopf}\Ai Studio Pro
DefaultGroupName=Ai Studio Pro
AllowNoIcons=yes
; Output installer name (1 Single .exe File under 1GB)
OutputBaseFilename=AiStudioPro_v2.6.2_Lite_Setup
OutputDir=d:\Ai Studio Pro\out
; Ultra compression
Compression=lzma2/max
SolidCompression=yes
DiskSpanning=no
SetupIconFile=d:\Ai Studio Pro\phoenix_logo.ico
UninstallDisplayIcon={app}\AiStudioPro.exe
ArchitecturesInstallIn64BitMode=x64

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "d:\Ai Studio Pro\app\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "model\VoxCPM2\*,resources\khmer-fonts\*,resources\whisper\cublas*.dll,resources\whisper\ggml-cuda.dll,resources\whisper\nvrtc*.dll,environment\Lib\site-packages\torch\lib\*cuda*.dll,environment\Lib\site-packages\torch\lib\*cublas*.dll,environment\Lib\site-packages\torch\lib\*cudnn*.dll,environment\Lib\site-packages\torch\lib\*cusparse*.dll,environment\Lib\site-packages\torch\lib\*cufft*.dll,environment\Lib\site-packages\torch\lib\*cusolver*.dll,environment\Lib\site-packages\torch\lib\*nvrtc*.dll,environment\Lib\site-packages\torch\lib\*curand*.dll,environment\Lib\site-packages\torch\lib\*nvJitLink*.dll,*.lib,*.pdb"

[Icons]
Name: "{group}\Ai Studio Pro"; Filename: "{app}\AiStudioPro.exe"
Name: "{autodesktop}\Ai Studio Pro"; Filename: "{app}\AiStudioPro.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\AiStudioPro.exe"; Description: "{cm:LaunchProgram,Ai Studio Pro}"; Flags: nowait postinstall skipifsilent
