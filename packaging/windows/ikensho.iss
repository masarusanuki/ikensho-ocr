; 主治医意見書 読み取り — Inno Setup スクリプト
; build.ps1 から呼ばれます。単体で実行する場合は /D で変数を渡してください。

#ifndef MyAppVersion
  #define MyAppVersion "0.1.0"
#endif
#ifndef MySourceDir
  #define MySourceDir "build\dist\ikensho"
#endif
#ifndef MyOutputDir
  #define MyOutputDir "dist"
#endif

#define MyAppName "主治医意見書 読み取り"
#define MyAppExeName "ikensho.exe"

[Setup]
AppId={{7C4B1E36-2E5B-4C1E-9E4B-6A1F3D2B8C41}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=University of Tsukuba / Department of Biomedical Informatics, University of Tsukuba Hospital
DefaultDirName={autopf}\IkenshoOCR
DefaultGroupName={#MyAppName}
OutputDir={#MyOutputDir}
OutputBaseFilename=ikensho-ocr-setup-{#MyAppVersion}
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin
DisableProgramGroupPage=yes
WizardStyle=modern
LicenseFile=..\..\LICENSE

[Languages]
Name: "japanese"; MessagesFile: "compiler:Languages\Japanese.isl"

[Tasks]
Name: "desktopicon"; Description: "デスクトップにショートカットを作る"; GroupDescription: "追加のタスク:"
Name: "addtopath";  Description: "コマンドプロンプトから ikensho を使えるようにする（PATHに追加）"; GroupDescription: "追加のタスク:"; Flags: unchecked

[Files]
Source: "{#MySourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\開発メモ・使い方"; Filename: "{app}\README.md"
Name: "{group}\{#MyAppName} をアンインストール"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
Root: HKLM; Subkey: "SYSTEM\CurrentControlSet\Control\Session Manager\Environment"; \
  ValueType: expandsz; ValueName: "Path"; ValueData: "{olddata};{app}"; \
  Check: NeedsAddPath('{app}'); Tasks: addtopath

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "今すぐ起動する"; Flags: postinstall nowait skipifsilent

[Code]
function NeedsAddPath(Param: string): boolean;
var
  OrigPath: string;
begin
  if not RegQueryStringValue(HKEY_LOCAL_MACHINE,
    'SYSTEM\CurrentControlSet\Control\Session Manager\Environment', 'Path', OrigPath)
  then begin
    Result := True;
    exit;
  end;
  Result := Pos(';' + ExpandConstant(Param) + ';', ';' + OrigPath + ';') = 0;
end;
