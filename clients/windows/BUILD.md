# Build do VAGG Client (passo a passo)

> Faça tudo num **Windows com PowerShell elevado** (ou normal — a parte que
> precisa de admin é só na hora de rodar o instalador final).

## 1. Pré-requisitos (uma vez só)

```powershell
# Go
winget install GoLang.Go.1.22

# Node
winget install OpenJS.NodeJS.LTS

# Wails CLI
go install github.com/wailsapp/wails/v2/cmd/wails@latest

# Inno Setup (para gerar .exe instalador)
winget install JRSoftware.InnoSetup

# Confere
wails doctor
```

## 2. Buildar o GUI (.exe principal)

```powershell
cd <repo>\clients\windows
wails build -platform=windows/amd64 -clean -o vagg-client.exe
```

Saída: `build\bin\vagg-client.exe` (~12 MB).

> Pra testar sem instalar nada, rode `vagg-client.exe` direto. Sem o service
> rodando, ele vai mostrar **"service offline"** no dashboard e não vai
> conseguir aplicar rotas — mas o login + lista de clientes funcionam.

## 3. Buildar o service (separado)

```powershell
cd <repo>\clients\windows
$env:GOOS = "windows"; $env:GOARCH = "amd64"
go build -o build\bin\vagg-client-svc.exe .\cmd\service
```

## 4. Adicionar ícone (opcional)

Coloque um `icon.ico` 256x256 em `build\icon.ico` (qualquer ícone PNG
convertido com https://convertico.com).

## 5. Gerar instalador `.exe`

```powershell
cd <repo>\clients\windows
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" build\installer.iss
```

Saída: `build\output\vagg-client-setup-0.1.0.exe` (~15 MB).

## 6. Instalar

Clique duplo no instalador → UAC → Avançar → Avançar → Instalar.

O instalador:
- Copia binários pra `C:\Program Files\VAGG Client\`
- Cria service `vagg-client-svc` (auto-start, SYSTEM)
- Inicia o service
- Cria atalhos no Iniciar e área de trabalho
- Abre o app no fim

## 7. Primeiro uso

1. Abra **VAGG Client** (atalho do Iniciar)
2. URL do servidor: `http://192.168.68.102` (no nosso lab) ou seu HTTPS de prod
3. Usuário: `admin`
4. Senha: `admin`
5. Clica **Entrar**

A janela mostra o dashboard com:
- LED verde "Conectado ao servidor"
- 3 clientes (LongPing / Roit / Brasanitas)
- Botão "Sincronizar agora"

Fecha (X) → minimiza pro tray. Clique direito no tray → Mostrar / Sair.

## Desinstalar

Painel de Controle → Programas → **VAGG Client** → Desinstalar. O service é parado e removido automaticamente.

## Code signing (produção)

Sem assinatura, o Windows SmartScreen vai avisar que o exe é "untrusted".
Pra produção, assinar com Sectigo / DigiCert / Comodo:

```powershell
signtool sign /tr http://timestamp.sectigo.com /td sha256 /fd sha256 /a build\bin\vagg-client.exe
signtool sign /tr http://timestamp.sectigo.com /td sha256 /fd sha256 /a build\bin\vagg-client-svc.exe
signtool sign /tr http://timestamp.sectigo.com /td sha256 /fd sha256 /a build\output\vagg-client-setup-0.1.0.exe
```

## Troubleshooting

**"wails build" reclama de WebView2 missing:**
- Win10 22H2+ e Win11 já vêm com WebView2. Senão, baixe o
  [Evergreen Bootstrapper](https://developer.microsoft.com/en-us/microsoft-edge/webview2/).

**Service não inicia depois de instalar:**
- `sc query vagg-client-svc`
- `Get-EventLog -LogName Application -Source "vagg-client-svc" -Newest 10`
- Verifique se `%PROGRAMDATA%\VAGG Client\` foi criada (o service grava `gateway`
  e `managed-routes.json` lá).

**Rotas não aparecem no Windows:**
- O service precisa do **gateway** (IP do vagg-server na LAN). Hoje a GUI
  precisa escrever esse arquivo `%PROGRAMDATA%\VAGG Client\gateway` —
  o pipe pode aceitar isso como op `set-gateway` no futuro. Pra MVP,
  durante o login a GUI pode invocar:
  ```go
  os.WriteFile(filepath.Join(programDataDir(), "gateway"), []byte("192.168.68.102"), 0644)
  ```
  (precisa privilégio — adicionar regra na .iss pra dar permissão a esse path
  pro user comum).
