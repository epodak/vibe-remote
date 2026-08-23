; Inno Setup 6 构建脚本 - vibe-remote 自动化安装向导
#define MyAppName "vibe-remote"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "epodak"
#define MyAppURL "https://github.com/epodak/vibe-remote"
#define MyAppExeName "vibe-remote.exe"

[Setup]
; 唯一 GUID 标识符
AppId={{8B2F3A44-C921-4FA3-8B39-6A14D2A92E88}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=dist\installer
OutputBaseFilename=vibe-remote-Setup-x64
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; 允许普通用户无需管理员提权直接安装（也可选择全机安装）
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon} (创建桌面快捷方式)"; GroupDescription: "{cm:AdditionalIcons}"; Flags: checkedonce
Name: "autostart"; Description: "开机自动启动 (Start automatically on Windows boot)"; GroupDescription: "附加选项 (Options):"; Flags: unchecked

[Files]
Source: "dist\vibe-remote\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
Name: "{userstartup}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: autostart

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "立即运行 {#MyAppName} (Launch {#MyAppName} now)"; Flags: nowait postinstall skipifsilent
