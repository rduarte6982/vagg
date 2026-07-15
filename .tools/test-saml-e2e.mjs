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

const browser = await chromium.launch({ headless: true });
const ctx = await browser.newContext({ viewport: { width: 1400, height: 900 } });
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

console.log('==> 4. editar MRV (botão lápis na linha)');
const mrvRow = page.locator('tr', { hasText: 'MRV' }).first();
await mrvRow.locator('button[title="Editar"]').click();
await page.waitForTimeout(2500);
await page.screenshot({ path: 'screenshots/e2e-saml-2-edit-mrv.png' });

console.log('==> 5. clicar Autenticar via SSO');
await page.click('button:has-text("Autenticar via SSO"), button:has-text("Re-autenticar SSO")');

console.log('==> 6. aguarda 8s pra iframe iniciar');
await page.waitForTimeout(8000);
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
