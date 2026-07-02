# VAGG Client (Windows)

App desktop que substitui scripts manuais de rota. Login com credenciais
do servidor; o app sincroniza com o **VAGG Server** e mantém as rotas das
VPNs do consultor sempre atualizadas no Windows.

## O que ele faz

```
┌─────────────────────────────────────────────────────────────────┐
│ Tray icon (vagg) — sempre visível ao lado do relógio do Windows │
│                                                                 │
│  ┌────────────────────────────────────────────┐                 │
│  │ VAGG Client                              ─x│                 │
│  │ ─────────────────────────                  │                 │
│  │ ● Conectado ao servidor (192.168.68.102)   │                 │
│  │   há 3min42s                               │                 │
│  │                                            │                 │
│  │ Clientes liberados:                        │                 │
│  │  ● LongPing    Online  10.80.0.0/16        │                 │
│  │  ● Roit        Online  10.0.0.0/16 (+12)   │                 │
│  │  ● Brasanitas  Online  192.168.40.0/24 (+2)│                 │
│  │                                            │                 │
│  │ 16 rotas instaladas no Windows ✓           │                 │
│  │ Próxima sincronização em 22s               │                 │
│  │                                            │                 │
│  │  [ Sincronizar agora ]  [ Sair  ]          │                 │
│  └────────────────────────────────────────────┘                 │
└─────────────────────────────────────────────────────────────────┘
```

- Fechar (X) → minimiza pra tray (não sai)
- Botão direito no tray: Mostrar / Sincronizar / Sair
- Service `vagg-client-svc` (Windows service) faz `route add/delete` em background
- GUI fala com o service via named pipe local

## Stack técnica

| Componente | Tech |
|---|---|
| GUI desktop | [Wails v2](https://wails.io) (Go + React + Tailwind) |
| Service Windows | Go + `golang.org/x/sys/windows/svc` |
| Comunicação GUI ↔ Service | named pipe local `\\.\pipe\vagg-client` |
| Cliente HTTP | Go `net/http` + JWT |
| Tray | `github.com/getlantern/systray` (embutido pelo Wails) |
| Build do .exe | `wails build -platform=windows/amd64` |
| Instalador `.exe` | [Inno Setup](https://jrsoftware.org/isinfo.php) (`build/installer.iss`) |

## Estrutura do projeto

```
clients/windows/
├── main.go                  ← entrypoint Wails (GUI + tray)
├── app.go                   ← bindings expostos pro frontend (login, sync, status)
├── wails.json               ← config Wails
├── go.mod
├── frontend/                ← UI React + Tailwind (mesmo design do server)
│   ├── package.json
│   ├── vite.config.ts
│   ├── index.html
│   ├── src/
│   │   ├── main.tsx
│   │   ├── App.tsx
│   │   ├── pages/
│   │   │   ├── Login.tsx
│   │   │   ├── Dashboard.tsx
│   │   │   └── Settings.tsx
│   │   └── components/
│   │       └── ui/...
├── internal/
│   ├── api/                 ← cliente HTTP do vagg-server
│   │   └── client.go
│   ├── routes/              ← Windows route table manipulation
│   │   ├── manager.go       ← diff, add, remove
│   │   └── store.go         ← persistência das rotas geridas (JSON)
│   └── service/             ← Windows service (privileged)
│       ├── service.go
│       └── pipe.go          ← named pipe protocol
├── cmd/
│   ├── client/              ← GUI executable (vagg-client.exe)
│   └── service/             ← Service executable (vagg-client-svc.exe)
└── build/
    ├── installer.iss        ← Inno Setup script
    └── icon.ico             ← ícone do app
```

## Pré-requisitos pra buildar (no Windows)

1. **Go 1.22+** — https://go.dev/dl/
2. **Node 20+** — https://nodejs.org/
3. **Wails CLI**:
   ```powershell
   go install github.com/wailsapp/wails/v2/cmd/wails@latest
   ```
4. **WebView2 Runtime** (já vem no Windows 10 22H2+ e Windows 11)
5. **Inno Setup 6** (pra gerar instalador) — https://jrsoftware.org/isdl.php

## Build do `.exe` (rápido — só do GUI)

```powershell
cd clients\windows
wails build -platform=windows/amd64 -clean
# saída: build/bin/vagg-client.exe
```

Isso gera um único `.exe` portátil (~12 MB). Pode rodar direto, mas SEM
privilege ele não consegue mexer em rotas (precisa do service).

## Build completo com instalador `.exe`

```powershell
cd clients\windows

# 1. GUI
wails build -platform=windows/amd64 -clean

# 2. Service (executável separado)
$env:GOOS = "windows"; $env:GOARCH = "amd64"
go build -o build/bin/vagg-client-svc.exe ./cmd/service

# 3. Instalador (precisa Inno Setup instalado)
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" build\installer.iss
# saída: build/output/vagg-client-setup-x.y.z.exe
```

O instalador:
- Copia `vagg-client.exe` pra `C:\Program Files\VAGG Client\`
- Copia `vagg-client-svc.exe` pra `C:\Program Files\VAGG Client\service\`
- Registra o service como `vagg-client-svc` (auto-start, SYSTEM)
- Cria atalhos no menu Iniciar e área de trabalho
- Adiciona regra de firewall outbound pro vagg-server
- Solicita elevação UAC durante a instalação

## Configuração do servidor

Na primeira execução, o app pergunta:
- **URL do VAGG Server** (ex: `https://vagg.consultoria.com.br`)
- **Usuário** (cadastrado no server)
- **Senha**

Persiste em `%APPDATA%\VAGG Client\config.json` (URL apenas; credenciais
ficam em **Windows Credential Manager** via DPAPI).

## Segurança

| Item | Como tratamos |
|---|---|
| Credenciais | Windows Credential Manager (DPAPI por user) |
| TLS | obrigatório em produção (config.json valida `https://`) |
| JWT | refresh automático antes de expirar |
| Privilégio mexer rotas | Service Windows como SYSTEM (GUI nunca tem admin) |
| IPC GUI ↔ Service | named pipe com SDDL restrito ao user logado |
| Auto-update | assinatura digital obrigatória (Code Signing cert) |
| Logs locais | `%PROGRAMDATA%\VAGG Client\logs\` (rotacionado) |
| Telemetria | nenhuma — app só fala com o seu vagg-server |

## Distribuição

1. **Code Sign** o `.exe` (Sectigo / DigiCert / Comodo) — exigido em produção
2. Hospede o instalador num release do GitHub (ou web próprio)
3. Configure auto-update apontando pra esse endpoint

## Roadmap

- [ ] **v1.0** (escopo atual): tray, login, sync de rotas, lista de clientes
- [ ] **v1.1**: SSE push do servidor (substitui polling)
- [ ] **v1.2**: TOTP / 2FA no login
- [ ] **v2.0**: WireGuard embutido pra dispensar VPN da consultoria
- [ ] **v2.1**: cross-platform (macOS / Linux)
