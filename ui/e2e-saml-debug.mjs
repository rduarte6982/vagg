import { chromium } from 'playwright';
const BASE = process.env.VAGG_BASE || 'http://192.168.68.102';
const browser = await chromium.launch({ headless: true });
const page = await browser.newContext({ viewport: { width: 1600, height: 1000 } }).then(c => c.newPage());
page.on('console', (msg) => console.log(`[c.${msg.type()}] ${msg.text()}`));
page.on('pageerror', (err) => console.log(`[err] ${err.message}`));
await page.goto(BASE);
await page.waitForLoadState('networkidle');
await page.fill('input[autocomplete=username]', 'admin');
await page.fill('input[autocomplete=current-password]', 'admin');
await page.click('button[type=submit]');
await page.waitForLoadState('networkidle');
await page.waitForTimeout(1500);
await page.click('a:has-text("Clientes")');
await page.waitForLoadState('networkidle');
await page.waitForTimeout(1500);
const mrvRow = page.locator('tr', { hasText: 'MRV' }).first();
const buttons = await mrvRow.locator('button').all();
console.log('button count:', buttons.length);
for (let i = 0; i < buttons.length; i++) {
  const html = await buttons[i].innerHTML();
  console.log(`button ${i}: ${html.substring(0, 120).replace(/\s+/g,' ')}`);
}
await browser.close();
