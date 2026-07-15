import { chromium } from 'playwright';

const BASE = process.env.VAGG_BASE || 'http://192.168.68.102';

const browser = await chromium.launch({ headless: true });
const ctx = await browser.newContext({ viewport: { width: 1400, height: 900 } });
const page = await ctx.newPage();

page.on('console', (m) => console.log(`[browser:${m.type()}]`, m.text()));

await page.goto(BASE);
await page.waitForLoadState('networkidle');
await page.fill('input[autocomplete=username]', 'admin');
await page.fill('input[autocomplete=current-password]', 'admin');
await page.click('button[type=submit]');
await page.waitForLoadState('networkidle');
await page.waitForTimeout(1500);

await page.click('a:has-text("Clientes")');
await page.waitForTimeout(1500);

const mrvRow = page.locator('tr', { hasText: 'MRV' }).first();
const buttons = mrvRow.locator('button');
await buttons.nth(2).click();
await page.waitForTimeout(2500);

console.log('==> procurando botão Abrir Microsoft Login');
const btn = page.locator('button:has-text("Abrir Microsoft Login")').first();
const found = await btn.count();
console.log(`   count: ${found}`);
if (found === 0) {
  await page.screenshot({ path: 'screenshots/saml-prelogin-no-btn.png', fullPage: true });
  console.log('   botão não achado — full screenshot saved');
  await browser.close();
  process.exit(1);
}

await btn.scrollIntoViewIfNeeded();
await page.waitForTimeout(500);
await page.screenshot({ path: 'screenshots/saml-prelogin-modal.png' });

// Captura nova aba quando o botão é clicado
const [newPage] = await Promise.all([
  ctx.waitForEvent('page', { timeout: 30000 }),
  btn.click(),
]);
console.log('==> nova aba aberta');
await newPage.waitForLoadState('domcontentloaded', { timeout: 30000 });
const newUrl = newPage.url();
console.log('   URL:', newUrl.slice(0, 200));
console.log('   tenant?', newUrl.includes('login.microsoftonline.com') ? 'YES Microsoft' : 'NO');
await newPage.screenshot({ path: 'screenshots/saml-prelogin-microsoft.png' });

await browser.close();
console.log('done');
