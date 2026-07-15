/**
 * E2E Playwright — testa o fluxo SAML SSO no homelab.
 *
 * 1. abre http://192.168.68.102/
 * 2. login admin/admin
 * 3. vai em Clientes
 * 4. edita MRV
 * 5. clica "Autenticar via SSO"
 * 6. aguarda iframe carregar e captura tudo: console errors, network requests,
 *    response do iframe, screenshot final
 *
 * Roda com:
 *   cd ui && node ../.tools/test-saml-e2e.mjs
 *
 * Saída em screenshots/e2e-saml-*.png e logs no stdout.
 */

import { chromium } from 'playwright';

const BASE = process.env.VAGG_BASE || 'http://192.168.68.102';
const ADMIN_USER = 'admin';
const ADMIN_PASS = 'admin';

const browser = await chromium.launch({
  headless: true,
  args: [
    // Trata o origin self-signed como secure (libera WebCodecs / WebRTC)
    '--unsafely-treat-insecure-origin-as-secure=https://192.168.68.102,http://192.168.68.102',
    '--allow-insecure-localhost',
  ],
});
const ctx = await browser.newContext({
  viewport: { width: 1400, height: 900 },
  ignoreHTTPSErrors: true,
});
const page = await ctx.newPage();

// captura logs do browser
page.on('console', (msg) => {
  console.log(`[browser:${msg.type()}]`, msg.text());
});
page.on('pageerror', (err) => {
  console.log('[pageerror]', err.message);
});
page.on('response', (resp) => {
  const url = resp.url();
  const status = resp.status();
  if (url.includes('saml-portal') || url.includes('/api/v1/clients/') || status >= 400) {
    console.log(`[http] ${status} ${url}`);
  }
});

console.log('==> 1. abrindo', BASE);
await page.goto(BASE);
await page.waitForLoadState('networkidle');
await page.waitForTimeout(800);

console.log('==> 2. login');
await page.fill('input[autocomplete=username]', ADMIN_USER);
await page.fill('input[autocomplete=current-password]', ADMIN_PASS);
await page.click('button[type=submit]');
await page.waitForLoadState('networkidle');
await page.waitForTimeout(1500);

console.log('==> 3. ir pra clientes');
await page.click('a:has-text("Clientes")');
await page.waitForTimeout(1500);
await page.screenshot({ path: 'screenshots/e2e-saml-1-clients.png' });

console.log('==> 4. editar MRV (3º botão da linha = lápis Edit)');
const mrvRow = page.locator('tr', { hasText: 'MRV' }).first();
const buttons = mrvRow.locator('button');
const btnCount = await buttons.count();
console.log(`   buttons na linha MRV: ${btnCount}`);
// Em ordem: power, logs, edit(pencil), delete. 3º (index 2)
await buttons.nth(2).click();
await page.waitForTimeout(2500);
await page.screenshot({ path: 'screenshots/e2e-saml-2-edit-mrv.png' });

console.log('==> 5. scroll modal + procurar Autenticar via SSO');
// Lista todos os botões visiveis no modal
const allButtons = await page.locator('button').allTextContents();
console.log('   botões visíveis:', JSON.stringify(allButtons));

const ssoBtn = page.locator('button:has-text("Autenticar via SSO"), button:has-text("Re-autenticar SSO")').first();
const found = await ssoBtn.count();
console.log(`   SSO btn count: ${found}`);
if (found > 0) {
  await ssoBtn.scrollIntoViewIfNeeded();
  await page.waitForTimeout(500);
  // Aguarda EM PARALELO a chamada saml/start chegar
  const reqPromise = page
    .waitForResponse(
      (r) => r.url().includes('/saml/start') && r.request().method() === 'POST',
      { timeout: 90000 },
    )
    .catch((e) => ({ error: e.message }));

  // dispatch click via DOM API direto (evita issue de Playwright)
  await ssoBtn.evaluate((el) => el.click());
  console.log('   click() via JS DOM. waiting for /saml/start response...');
  const startResp = await reqPromise;
  if (startResp && startResp.status) {
    const json = await startResp.json().catch(() => null);
    console.log(`   /saml/start status=${startResp.status()} body=`, JSON.stringify(json));
  } else {
    console.log('   ⚠️ NO /saml/start request fired (60s):', startResp);
    // last resort: chama Saml.start via fetch pra confirmar API funciona
    const directCall = await page.evaluate(async () => {
      const t = localStorage.getItem('vagg.access_token');
      const r = await fetch('/api/v1/clients/mrv/saml/start', {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${t}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ gateway_url: 'https://gp.mrv.com.br' }),
      });
      return { status: r.status, body: await r.json() };
    });
    console.log('   direct fetch result:', JSON.stringify(directCall));
  }
} else {
  await page.screenshot({ path: 'screenshots/e2e-saml-no-button.png', fullPage: true });
  console.log('   botão não encontrado, full screenshot salvo');
}

console.log('==> 6. aguarda 90s pra iframe iniciar (backend espera o noVNC subir)');
await page.waitForTimeout(90000);
await page.screenshot({ path: 'screenshots/e2e-saml-3-modal.png' });

console.log('==> 7. inspeciona o iframe');
const frames = page.frames();
console.log(`   total frames: ${frames.length}`);
for (const f of frames) {
  console.log(`   - frame: name=${f.name()} url=${f.url()}`);
}

const samlFrame = frames.find((f) => f.url().includes('saml-portal'));
if (samlFrame) {
  console.log('   SAML frame URL:', samlFrame.url());
  // Tenta pegar o título e algum elemento
  try {
    const title = await samlFrame.title();
    console.log('   SAML frame title:', title);
  } catch (e) {
    console.log('   could not get title:', e.message);
  }
}

console.log('==> 8. tenta fetch direto da URL do iframe pra ver o status');
const iframeSrc = await page.locator('iframe[title="SAML Portal"]').getAttribute('src');
console.log('   iframe src:', iframeSrc);

if (iframeSrc) {
  const fullUrl = iframeSrc.startsWith('http') ? iframeSrc : `${BASE}${iframeSrc}`;
  const r = await page.request.get(fullUrl);
  console.log(`   GET ${fullUrl} → ${r.status()}`);
  const body = await r.text();
  console.log(`   body (first 500): ${body.slice(0, 500)}`);
}

await page.screenshot({ path: 'screenshots/e2e-saml-final.png', fullPage: false });
console.log('==> done. screenshots em ui/screenshots/e2e-saml-*.png');

await browser.close();
