; Inno Setup 6 Script for 对稿 · PaperDiff Studio (Windows x64)
; Packaging defaults:
;   - Per-user install by default (`PrivilegesRequired=lowest`),
;     with `PrivilegesRequiredOverridesAllowed=dialog` so admins can opt into all-users.
;   - Optional default-checked `addtopath` task installing `paperdiff.cmd`
;     and cleanly registering/unregistering `{app}` in user PATH.
;   - Intentionally does NOT hijack `.docx` / `.tex` / `.md` default associations.

#ifndef AppVersion
  #define AppVersion "0.2.0"
#endif
#ifndef SourceDir
  #define SourceDir "dist_out\PaperDiff"
#endif
#ifndef OutputDir
  #define OutputDir "..\..\release"
#endif
#ifndef OutputBaseName
  #define OutputBaseName "PaperDiff-v" + AppVersion + "-Windows-x64-Setup"
#endif
#ifndef IconFile
  #define IconFile "PaperDiff.ico"
#endif
#ifndef GuideFile
  #define GuideFile "..\..\产品使用指南.md"
#endif
#ifndef CliWrapperFile
  #define CliWrapperFile "build_work\paperdiff.cmd"
#endif

[Setup]
AppId={{8E9A3F42-5C1D-4B7E-9A21-6D0F4E2C1B88}
AppName=对稿 · PaperDiff
AppVerName=对稿 · PaperDiff {#AppVersion}
AppVersion={#AppVersion}
AppPublisher=PaperDiff Contributors
AppPublisherURL=https://github.com/maniac8/PaperDiff
AppSupportURL=https://github.com/maniac8/PaperDiff/issues
AppUpdatesURL=https://github.com/maniac8/PaperDiff/releases
DefaultDirName={autopf}\PaperDiff
DefaultGroupName=对稿 · PaperDiff
DisableProgramGroupPage=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir={#OutputDir}
OutputBaseFilename={#OutputBaseName}
SetupIconFile={#IconFile}
UninstallDisplayIcon={app}\PaperDiff.exe
UninstallDisplayName=对稿 · PaperDiff {#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ChangesEnvironment=yes
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
#ifdef HasZhCN
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
#endif

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式 / Create a desktop shortcut"; GroupDescription: "附加选项 / Additional shortcuts:"
Name: "addtopath"; Description: "将 paperdiff 命令行工具添加到 PATH / Add `paperdiff` CLI to PATH"; GroupDescription: "命令行支持 / CLI Integration:"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#CliWrapperFile}"; DestDir: "{app}"; DestName: "paperdiff.cmd"; Flags: ignoreversion
Source: "{#GuideFile}"; DestDir: "{app}"; DestName: "产品使用指南.md"; Flags: ignoreversion skipifsourcedoesntexist

[Icons]
Name: "{autoprograms}\对稿 · PaperDiff"; Filename: "{app}\PaperDiff.exe"; IconFilename: "{app}\PaperDiff.exe"
Name: "{autodesktop}\对稿 · PaperDiff"; Filename: "{app}\PaperDiff.exe"; IconFilename: "{app}\PaperDiff.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\PaperDiff.exe"; Description: "启动 对稿 · PaperDiff / Launch PaperDiff"; Flags: nowait postinstall skipifsilent

[Code]
const
  EnvironmentKey = 'Environment';

function NeedsAddPath(Param: string): boolean;
var
  OrigPath: string;
begin
  if not RegQueryStringValue(HKEY_CURRENT_USER, EnvironmentKey, 'Path', OrigPath) then
  begin
    Result := True;
    exit;
  end;
  Result := Pos(';' + Uppercase(Param) + ';', ';' + Uppercase(OrigPath) + ';') = 0;
end;

procedure EnvAddPath(PathToAdd: string);
var
  Paths: string;
begin
  if not NeedsAddPath(PathToAdd) then exit;
  if not RegQueryStringValue(HKEY_CURRENT_USER, EnvironmentKey, 'Path', Paths) then
    Paths := '';
  if (Paths <> '') and (Paths[Length(Paths)] <> ';') then
    Paths := Paths + ';';
  Paths := Paths + PathToAdd;
  RegWriteExpandStringValue(HKEY_CURRENT_USER, EnvironmentKey, 'Path', Paths);
end;

procedure EnvRemovePath(PathToRemove: string);
var
  Paths: string;
  P: Integer;
begin
  if not RegQueryStringValue(HKEY_CURRENT_USER, EnvironmentKey, 'Path', Paths) then exit;
  P := Pos(';' + Uppercase(PathToRemove) + ';', ';' + Uppercase(Paths) + ';');
  if P = 0 then exit;
  if P = 1 then
  begin
    Delete(Paths, 1, Length(PathToRemove));
    if (Length(Paths) > 0) and (Paths[1] = ';') then
      Delete(Paths, 1, 1);
  end
  else
  begin
    Delete(Paths, P - 1, Length(PathToRemove) + 1);
  end;
  RegWriteExpandStringValue(HKEY_CURRENT_USER, EnvironmentKey, 'Path', Paths);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssPostInstall) and WizardIsTaskSelected('addtopath') then
    EnvAddPath(ExpandConstant('{app}'));
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
    EnvRemovePath(ExpandConstant('{app}'));
end;
