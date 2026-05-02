# vagg-ui

Painel administrativo web (SPEC §5.4 / Fase 7).

Stack: React 18 + Vite 5 + TypeScript + Tailwind + Radix primitives +
react-router-dom + react-i18next + axios. SPA estática servida pelo
nginx em produção; em dev, `vite` proxia `/api` para o `vagg-core`.

## Dev

```bash
cd ui
npm install
npm run dev          # http://localhost:5173 (proxia /api → :8443)
```

Defina `VITE_API_BASE` para apontar para outro `vagg-core` se preciso
(default: caminho relativo `/api/v1`).

## Build

```bash
npm run build        # gera dist/
npm run preview      # serve dist/ localmente
```

Container:

```bash
docker build -f ui/Dockerfile -t vagg/ui:dev ui/
docker run --rm -p 8080:80 \
    --link vagg-core:vagg-core \
    vagg/ui:dev
```

## Lint / type-check / tests

```bash
npm run lint
npm run build        # tsc -b roda type-check antes do bundle
npm run test
```

## Telas

| Rota | Tela |
|------|------|
| `/login` | Login (email + senha → JWT salvo em localStorage) |
| `/` | Dashboard — contadores de consultores ativos, clientes online, túneis, licença |
| `/clients` | CRUD de clientes + connect/disconnect de túnel |
| `/consultants` | CRUD de consultores |
| `/policies` | Matriz consultor × cliente |
| `/audit` | Eventos de auditoria com filtro por tipo + export CSV/JSON |
| `/system` | Versão / saúde / licença / regenerar Corefile DNS |

Tema dark/light persistido em `localStorage`. Idiomas pt-BR + en
(detecta navegador, alterna no header).

## Realtime

`usePoll` em `lib/polling.ts` faz polling de cada endpoint:

| Recurso | Intervalo |
|---------|-----------|
| Clientes | 5s (status do túnel muda rápido) |
| Consultores | 30s |
| Policies | 30s |
| Audit | 30s |
| Licença / versão | 60s |

Websockets seriam opção, mas com população esperada (≤ 100 consultores)
o overhead de polling é insignificante e simplifica o auth (mesmo bearer).

## Critérios de aceite (SPEC §11 Fase 7)

- [x] Todas as ações da §5.1 acessíveis via UI (CRUD de clients,
      consultants, policies; connect/disconnect/OTP; audit; license)
- [x] Realtime updates (polling por recurso, ver tabela acima)
- [x] Export CSV/JSON da auditoria (`pages/Audit.tsx`)
- [x] i18n pt-BR + en
- [x] Dark mode persistido
- [x] Validação visual em mobile — `Layout.tsx` tem nav vertical
      sob breakpoint `md:` e tabelas com overflow horizontal
