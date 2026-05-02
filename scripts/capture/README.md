# Capture script

Gera os screenshots referenciados por [docs/MANUAL-INSTALACAO.md](../../docs/MANUAL-INSTALACAO.md).

Usa **puppeteer-core** apontando para o Chromium que o Playwright já
instala, e **intercepta** chamadas `/api/*` e `/portal/*` com fixtures
determinísticas — então não precisa subir o `vagg-core` real para
gerar o manual.

## Como rodar

Em três terminais separados, na raiz do repo:

```bash
# Terminal 1
cd ui && npm run dev          # http://localhost:5173

# Terminal 2
cd portal && npm run dev      # http://localhost:5174

# Terminal 3
node scripts/capture/capture.mjs
```

Saída: `docs/manual-prints/*.png`. Re-rodar é idempotente — sobrescreve.

## Quando atualizar

- Mudou layout / navegação / labels da UI → re-rode para que os PNGs do
  manual reflitam o estado atual.
- Adicionou tela nova → atualize as `FIXTURES` e adicione um `shot()` em
  [capture.mjs](capture.mjs).

## Customização

- `CHROME_PATH=...` aponta para outro Chromium se o caminho default do
  Playwright não bater (Linux/macOS).
- Viewport é 1280×800 — bom para o GitHub renderizar sem rolagem
  horizontal e para mostrar bem em monitor 1920px.
