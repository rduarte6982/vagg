# vagg-portal

Portal de Transparência — frontend público read-only para auditores do
cliente final (SPEC §1.7 / §5.6 / Fase 11).

Stack: React 18 + Vite 5 + TypeScript + axios + react-router. Sem Tailwind /
shadcn (mantemos o bundle pequeno; o portal serve auditores que podem
usar conexões corporativas lentas).

## Telas

| Rota | Função |
|------|--------|
| `/login` | Pede email + client_id, dispara magic link |
| `/consume?token=...` | Consome o link e (se TOTP) prompt do código |
| `/dashboard` | Dashboard + timeline + download do PDF assinado |

A autenticação usa cookie httpOnly setado por `GET /portal/auth/consume`.
Não há JWT no localStorage — o portal é superfície pública e queremos
minimizar o que JS pode acessar.

## Endpoints consumidos (do vagg-core)

```
POST /portal/auth/request_magic_link   { email, client_id } → 202
GET  /portal/auth/consume?token=...    → 200 { requires_totp, ... } + cookie
POST /portal/auth/totp                 { code }
GET  /portal/dashboard                 contadores escopados ao client_id
GET  /portal/timeline                  eventos públicos do cliente
POST /portal/reports/lgpd              PDF assinado Ed25519 (download)
```

## Build

```bash
cd portal
npm install
npm run dev          # localhost:5174 (proxia /portal → :8443)
npm run build        # gera dist/
docker build -f Dockerfile -t vagg/portal:dev .
```

O container `vagg/portal` é servido em produção pelo nginx, em subdomínio
dedicado (ex: `transparency.consultoria.com.br`) configurado pelo
instalador (Fase 10).

## Verificação independente do PDF

O auditor pode rodar localmente:

```bash
python -m vagg_core.scripts.verify_audit_report relatorio.pdf
```

A chave pública Ed25519 é exposta em `GET /portal/auth/public_key` e
embutida em cada PDF — então mesmo offline o auditor consegue conferir.
