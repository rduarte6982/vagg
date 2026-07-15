// Smoke test do Admin UI em modo demo. Roda playwright contra
// http://localhost:5173/?demo=1, percorre as páginas principais,
// loga erros do console e salva screenshots em screenshots/.
//
// Pré-requisitos:
//   1. dev server rodando: npm run dev (em outro terminal)
//   2. chromium instalado: npx playwright install chromium

import { chromium } from 'playwright';
import { mkdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

const BASE = process.env.BASE || 'http://localhost:5173';
const OUT = 'screenshots';
mkdirSync(OUT, { recursive: true });

const errors = [];
const consoleErrors = [];

function logErr(label, e) {
  const msg = `[${label}] ${e.message ?? e}`;
  errors.push(msg);
  console.error('  ✗', msg);
}

const browser = await chromium.launch();
const context = await browser.newContext({
  viewport: { width: 1440, height: 900 },
  locale: 'pt-BR',
});
const page = await context.newPage();

page.on('console', (msg) => {
  if (msg.type() === 'error') {
    const text = msg.text();
    // descarta ruído conhecido (warnings de fontes/cdn)
    if (text.includes('font') || text.includes('preload')) return;
    consoleErrors.push(text);
  }
});
page.on('pageerror', (err) => consoleErrors.push(`pageerror: ${err.message}`));

async function shot(name) {
  const file = join(OUT, `${name}.png`);
  await page.screenshot({ path: file, fullPage: true });
  console.log('  📸', file);
}

async function step(label, fn) {
  console.log('▶', label);
  try {
    await fn();
    console.log('  ✓');
  } catch (e) {
    logErr(label, e);
  }
}

await step('boot — login com ?demo=1', async () => {
  await page.goto(`${BASE}/login?demo=1`, { waitUntil: 'networkidle' });
  await page.waitForSelector('input[type=email]', { timeout: 5000 });
  await shot('01-login');
});

await step('login submit', async () => {
  // o login.tsx auto-preenche em demo mode; confirmamos os valores e enviamos
  const email = await page.locator('input[type=email]').inputValue();
  const pwd = await page.locator('input[type=password]').inputValue();
  if (!email || !pwd) throw new Error(`campos vazios — email=${email} pwd=${pwd}`);
  await page.locator('button[type=submit]').click();
  await page.waitForURL(/\/$/, { timeout: 5000 });
});

await step('dashboard', async () => {
  await page.waitForSelector('text=Visão geral', { timeout: 5000 });
  await page.waitForSelector('text=Mapa da rede');
  // espera o polling do health terminar (status sai de loading "off" para on/warn)
  await page.waitForFunction(
    () => {
      const txt = document.body.innerText;
      return (
        txt.includes('Aggregator alcançável') ||
        txt.includes('túnel(eis) com erro') ||
        txt.includes('Aggregator inacessível')
      );
    },
    { timeout: 5000 },
  );
  // espera o nome de pelo menos um cliente aparecer (lista de túneis)
  await page.waitForSelector('text=Petróleo SA', { timeout: 5000 });
  await shot('02-dashboard');
});

await step('clientes', async () => {
  await page.locator('aside a[href="/clients"]').click();
  await page.waitForURL(/\/clients$/);
  await page.waitForSelector('text=Petróleo SA', { timeout: 5000 });
  await shot('03-clients');
});

await step('clientes — abrir modal de criação', async () => {
  await page.locator('button', { hasText: /Novo cliente/ }).click();
  await page.waitForSelector('text=Salvar cliente', { timeout: 3000 });
  await shot('04-clients-modal');
  // fecha
  await page.keyboard.press('Escape');
  await page.waitForSelector('text=Salvar cliente', { state: 'hidden', timeout: 3000 });
});

await step('consultores', async () => {
  await page.locator('a[href="/consultants"]').click();
  await page.waitForURL(/\/consultants$/);
  await page.waitForSelector('text=Paulo Silva', { timeout: 5000 });
  await shot('05-consultants');
});

await step('políticas', async () => {
  await page.locator('a[href="/policies"]').click();
  await page.waitForURL(/\/policies$/);
  await page.waitForSelector('text=Petróleo', { timeout: 5000 });
  await shot('06-policies');
});

await step('auditoria', async () => {
  await page.locator('a[href="/audit"]').click();
  await page.waitForURL(/\/audit$/);
  await page.waitForSelector('text=auth.login.success', { timeout: 5000 });
  await shot('07-audit');
});

await step('sistema', async () => {
  await page.locator('a[href="/system"]').click();
  await page.waitForURL(/\/system$/);
  await page.waitForSelector('text=Modo demonstração ativo', { timeout: 5000 });
  // espera o status de saúde chegar (sai de "—" para "ok")
  await page.waitForFunction(
    () => document.body.innerText.includes('0.1.0-demo'),
    { timeout: 5000 },
  );
  await shot('08-system');
});

await step('voltar ao dashboard e validar topology', async () => {
  await page.locator('a[href="/"]').first().click();
  await page.waitForURL(/\/$/);
  await page.waitForSelector('text=Mapa da rede');
  // contagem de LEDs verdes (router-led--on) precisa ser > 0
  const leds = await page.locator('.router-led--on').count();
  if (leds < 2) throw new Error(`esperava >=2 LEDs verdes no dashboard, achei ${leds}`);
});

await step('criar um cliente novo via modal', async () => {
  await page.locator('aside a[href="/clients"]').click();
  await page.waitForURL(/\/clients$/);
  await page.locator('button', { hasText: /Novo cliente/ }).click();
  await page.waitForSelector('text=Salvar cliente');
  await page.locator('input[placeholder^="ex: petroleo"]').fill('teste-smoke');
  await page.locator('input[placeholder="Petróleo SA"]').fill('Cliente Teste');
  await page.locator('input[placeholder="10.200.10.0/24"]').fill('10.200.99.0/24');
  await page.locator('input[placeholder="172.16.0.0/24"]').fill('192.168.99.0/24');
  await page.locator('button[type=submit]', { hasText: /Salvar cliente/ }).click();
  await page.waitForSelector('text=Cliente Teste', { timeout: 5000 });
  await shot('09-clients-after-create');
});

await context.close();
await browser.close();

console.log('\n=== resultado ===');
console.log(`erros de step: ${errors.length}`);
console.log(`erros de console: ${consoleErrors.length}`);
if (consoleErrors.length) {
  console.log('console errors:');
  consoleErrors.slice(0, 10).forEach((e) => console.log('  -', e));
}
writeFileSync(
  join(OUT, '_report.json'),
  JSON.stringify({ errors, consoleErrors }, null, 2),
);

if (errors.length || consoleErrors.length) process.exit(1);
console.log('OK ✅');
