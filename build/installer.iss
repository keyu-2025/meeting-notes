; installer.iss — Inno Setup 6 script for Meeting Notes
;
; Prerequisites:
;   1. Build the exe first:  python build/build.py
;   2. Install Inno Setup 6: https://jrsoftware.org/isdl.php
;   3. Open this file in Inno Setup IDE, or compile from command line:
;        iscc build\installer.iss
;
; Output: dist\MeetingNotes_Setup_1.0.0.exe
;
; What the installer does:
;   - Copies dist\MeetingNotes\ to %ProgramFiles%\MeetingNotes\
;   - Creates a Start Menu shortcut
;   - Creates an optional Desktop shortcut
;   - Registers an uninstaller in "Add/Remove Programs"
;   - Does NOT bundle Python, Ollama, or model files
;     (models download on first launch via the setup wizard)

#define MyAppName      "会议纪要"
#define MyAppNameEn    "MeetingNotes"
#define MyAppVersion   "1.0.0"
#define MyAppPublisher "MeetingNotes"
#define MyAppURL       "https://github.com/your-repo/meeting-notes"
#define MyAppExeName   "MeetingNotes.exe"
#define MyAppId        "{{A3F1C2D4-9E8B-4F27-B6A0-3D5E7C8F1234}"

; Path to the PyInstaller output directory (relative to this .iss file)
#define SourceDir "..\dist\MeetingNotes"

[Setup]
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppNameEn}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
LicenseFile=
; No license file — remove or point to a LICENSE.txt if you have one
InfoBeforeFile=
InfoAfterFile=
; Output location
OutputDir=..\dist
OutputBaseFilename={#MyAppNameEn}_Setup_{#MyAppVersion}
; Use a custom icon if available, otherwise comment out
; SetupIconFile=icon.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest         ; No admin needed (installs to AppData if no admin)
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763             ; Windows 10 1809+
UninstallDisplayIcon={app}\{#MyAppExeName}

; Multi-language support
ShowLanguageDialog=auto

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
Name: "english";     MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon";    Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "quicklaunchicon"; Description: "{cm:CreateQuickLaunchIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked; OnlyBelowVersion: 6.1; Check: not IsAdminInstallMode

[Files]
; Copy everything from dist\MeetingNotes\
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

; NOTE: Models are NOT included here — they are downloaded at first launch.
; If you want to ship them pre-bundled to avoid network access on first run,
; uncomment the following and adjust the path:
; Source: "models\*"; DestDir: "{userappdata}\MeetingNotes\models"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; Start Menu
Name: "{group}\{#MyAppName}";            Filename: "{app}\{#MyAppExeName}"
Name: "{group}\卸载 {#MyAppName}";      Filename: "{uninstallexe}"

; Desktop (optional)
Name: "{autodesktop}\{#MyAppName}";      Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

; Quick Launch (Win XP / Vista only)
Name: "{userappdata}\Microsoft\Internet Explorer\Quick Launch\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: quicklaunchicon

[Run]
; Offer to launch the app immediately after install
Filename: "{app}\{#MyAppExeName}"; \
    Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; \
    Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Remove user-created output folder next to exe on uninstall
Type: filesandordirs; Name: "{app}\output"

[Code]
// ── Optional: Check for previous installation and offer upgrade ──────────
function InitializeSetup(): Boolean;
begin
  Result := True;
end;

// ── Custom page: remind user that Ollama is a separate install ─────────
var
  OllamaPage: TOutputMsgWizardPage;

procedure InitializeWizard;
begin
  OllamaPage := CreateOutputMsgPage(
    wpSelectDir,
    '关于 Ollama',
    '会议总结功能需要 Ollama（独立程序）',
    '本安装程序仅安装【会议纪要】应用本身。' + #13#10 +
    #13#10 +
    '首次启动时，应用会自动：' + #13#10 +
    '  • 下载语音识别模型（SenseVoice，约 300 MB）' + #13#10 +
    '  • 检测 Ollama 安装状态，并引导您安装' + #13#10 +
    '  • 下载会议总结模型（Qwen 2.5，约 2 GB）' + #13#10 +
    #13#10 +
    '如果您已经安装了 Ollama，无需任何额外操作。' + #13#10 +
    #13#10 +
    'Ollama 下载地址: https://ollama.com/download/windows'
  );
end;
