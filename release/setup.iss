; Inno Setup script per GLM-OCR.
; Compila con: iscc.exe /DAppVersion=0.1.0 release\setup.iss
; (lo script build_installer.ps1 lo fa per te)

#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif
#define AppName "GLM-OCR"
#define AppPublisher "GLM-OCR"
#define AppExeName "Avvia GLM-OCR.bat"

[Setup]
AppId={{B0E5D1A7-7E26-4F68-9C4F-3F5C9E1A2BE0}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\dist
OutputBaseFilename=GLM-OCR-Setup-v{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
LicenseFile=..\LICENSE.txt
SetupIconFile=
UninstallDisplayName={#AppName} v{#AppVersion}
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "italian"; MessagesFile: "compiler:Languages\Italian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; File applicativi (sono nella root del repo, salgo di una cartella)
Source: "..\Avvia GLM-OCR.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md";          DestDir: "{app}"; DestName: "README.txt"; Flags: ignoreversion
Source: "..\LICENSE.txt";        DestDir: "{app}"; Flags: ignoreversion
Source: "..\app\*";              DestDir: "{app}\app";       Excludes: "__pycache__\*,__pycache__,*.pyc"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\installer\*";        DestDir: "{app}\installer"; Excludes: "__pycache__\*,__pycache__,*.pyc"; Flags: ignoreversion recursesubdirs createallsubdirs

[Dirs]
; Cartelle vuote che il bootstrap popolera'.
Name: "{app}\runtime"; Permissions: users-modify
Name: "{app}\data";    Permissions: users-modify
Name: "{app}\logs";    Permissions: users-modify

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent shellexec

[UninstallDelete]
; Lasciamo intatto data/ (preferenze utente). Rimuoviamo runtime/, logs/, dist temporanee.
Type: filesandordirs; Name: "{app}\runtime"
Type: filesandordirs; Name: "{app}\logs"
Type: filesandordirs; Name: "{app}\__pycache__"
Type: filesandordirs; Name: "{app}\app\__pycache__"

[Code]
procedure InitializeUninstallProgressForm();
var
  Response: Integer;
begin
  // Chiede esplicitamente se rimuovere anche i dati utente (data/).
  Response := MsgBox('Vuoi rimuovere anche i dati utente (preferenze, cache update)?' + #13#10 + #13#10 +
    'Scegli NO per conservarli per una futura reinstallazione.', mbConfirmation, MB_YESNO);
  if Response = IDYES then
  begin
    DelTree(ExpandConstant('{app}\data'), True, True, True);
  end;
end;
