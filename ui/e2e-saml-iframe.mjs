import { chromium } from 'playwright';
const BASE = process.env.VAGG_BASE || 'http://192.168.68.102';
const browser = await chromium.launch({ headless: true });
const ctx = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
const page = await ctx.newPage();
page.on('console', (m) => console.log(`[c.${m.type()}] ${m.text()}`));

await page.goto(BASE);
await page.waitForLoadState('networkidle');
await page.fill('input[autocomplete=username]', 'admin');
await page.fill('input[autocomplete=current-password]', 'admin');
await page.click('button[type=submit]');
await page.waitForTimeout(1500);
await page.click('a:has-text("Clientes")');
await page.waitForTimeout(1500);

// Garante que MRV está stopped (pra exibir botão Connect)
const tok = await page.evaluate(async () => {
  const r = await fetch('/api/v1/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' }, body: 'username=admin&password=admin' });
  return (await r.json()).access_token;
});
await page.evaluate(async (t) => {
  await fetch('/api/v1/clients/mrv/disconnect', { method: 'POST', headers: { Authorization: `Bearer ${t}` } });
  await fetch('/api/v1/clients/mrv/saml/cookie', { method: 'DELETE', headers: { Authorization: `Bearer ${t}` } });
  await fetch('/api/v1/clients/mrv/saml/stop', { method: 'POST', headers: { Authorization: `Bearer ${t}` } });
}, tok);
await page.reload();
await page.waitForTimeout(2000);

const mrvRow = page.locator('tr', { hasText: 'MRV' }).first();
await mrvRow.locator('button').nth(0).click();

await page.waitForSelector('[role=dialog]', { timeout: 90_000 });
console.log('modal opened');
await page.waitForTimeout(15_000); // dá tempo do Firefox abrir e navegar
await page.screenshot({ path: 'screenshots/e2e-saml-idp-direct.png', fullPage: true });
console.log('screenshot saved');
await browser.close();
