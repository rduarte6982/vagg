; Inno Setup script — VAGG Client installer
; Compile com:
;   "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" build\installer.iss

#define MyAppName "vagg client"
#define MyAppVersion "0.7.1"
#define MyAppPublisher "vagg."
#define MyAppURL "https://github.com/rduarte6982/vagg"
#define MyAppExeName "vagg-client.exe"
#define MyAppSvcName "vagg-client-svc.exe"
#define MyAppSvcId   "vagg-client-svc"

[Setup]
; AppId estável (NÃO MUDAR entre versões — é o que faz o Windows reconhecer
; uma instalação prévia e reinstalar por cima dela em vez de criar duplicado).
AppId={{B7E1F5D2-1C9A-4F3E-9B2A-7C4D6E8F1A2B}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=admin
OutputDir=output
OutputBaseFilename=vagg-client-setup-{#MyAppVersion}
Compression=lzma2/ultra
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Inno detecta processos com o exe instalado e oferece fechar/restartar.
CloseApplications=yes
CloseApplicationsFilter=*.exe
RestartApplications=yes
; Mostra a tela de "instalando uma versão mais recente" automaticamente.
UsePreviousAppDir=yes
UsePreviousGroup=yes
UsePreviousLanguage=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na área de trabalho"; GroupDescription: "Atalhos:"

[Files]
Source: "bin\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "bin\{#MyAppSvcName}"; DestDir: "{app}\service"; Flags: ignoreversion
Source: "icon.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\icon.ico"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\icon.ico"; Tasks: desktopicon

[Run]
; (Re-)cria o service. Se já existir, sc create vai falhar com "service already
; exists" mas o runhidden + waituntilterminated não para o setup. O
; PrepareToInstall do [Code] já deletou se necessário.
Filename: "sc.exe"; Parameters: "create {#MyAppSvcId} binPath= ""\""{app}\service\{#MyAppSvcName}\"""" start= auto DisplayName= ""vagg client route manager"""; Flags: runhidden waituntilterminated
Filename: "sc.exe"; Parameters: "description {#MyAppSvcId} ""Mantém as rotas das VPNs gerenciadas pelo vagg server."""; Flags: runhidden waituntilterminated
Filename: "sc.exe"; Parameters: "start {#MyAppSvcId}"; Flags: runhidden waituntilterminated
; Abre o app no fim
Filename: "{app}\{#MyAppExeName}"; Description: "Iniciar {#MyAppName}"; Flags: postinstall nowait

[UninstallRun]
Filename: "sc.exe"; Parameters: "stop {#MyAppSvcId}"; Flags: runhidden waituntilterminated; RunOnceId: "stopsvc"
Filename: "sc.exe"; Parameters: "delete {#MyAppSvcId}"; Flags: runhidden waituntilterminated; RunOnceId: "delsvc"
Filename: "taskkill.exe"; Parameters: "/F /IM {#MyAppExeName}"; Flags: runhidden waituntilterminated; RunOnceId: "killgui"

[Code]
{ Detecta se há uma instalação anterior pelo mesmo AppId e roda o uninstaller
  silenciosamente antes de prosseguir. Garante que o service antigo é parado e
  removido, e que os exes antigos são deletados — evita "file in use" no meio
  da cópia. }

function GetUninstallString(): String;
var
  sUnInstPath: String;
  sUnInstallString: String;
begin
  sUnInstPath := 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{#emit SetupSetting("AppId")}_is1';
  sUnInstallString := '';
  if not RegQueryStringValue(HKLM, sUnInstPath, 'UninstallString', sUnInstallString) then
    RegQueryStringValue(HKCU, sUnInstPath, 'UninstallString', sUnInstallString);
  Result := sUnInstallString;
end;

function IsUpgrade(): Boolean;
begin
  Result := (GetUninstallString() <> '');
end;

procedure StopAndKillRunning();
var
  ResultCode: Integer;
begin
  { Para o service. Ignora erro se não existir. }
  Exec(ExpandConstant('{cmd}'), '/c sc stop {#MyAppSvcId}', '',
    SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Exec(ExpandConstant('{cmd}'), '/c sc delete {#MyAppSvcId}', '',
    SW_HIDE, ewWaitUntilTerminated, ResultCode);
  { Mata o GUI se estiver rodando. }
  Exec(ExpandConstant('{cmd}'), '/c taskkill /F /IM {#MyAppExeName}', '',
    SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Exec(ExpandConstant('{cmd}'), '/c taskkill /F /IM {#MyAppSvcName}', '',
    SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Sleep(1500);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
  sUnInstallString: String;
begin
  Result := '';
  StopAndKillRunning();

  if IsUpgrade() then
  begin
    sUnInstallString := GetUninstallString();
    sUnInstallString := RemoveQuotes(sUnInstallString);
    { /SILENT roda sem progress bar; /SUPPRESSMSGBOXES não pergunta nada;
      /NORESTART evita auto-reboot. }
    Exec(sUnInstallString, '/SILENT /SUPPRESSMSGBOXES /NORESTART', '',
      SW_HIDE, ewWaitUntilTerminated, ResultCode);
    Sleep(1000);
    StopAndKillRunning();
  end;
end;

function InitializeSetup(): Boolean;
begin
  Result := True;
end;
