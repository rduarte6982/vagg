import { chromium } from 'playwright';

const url = process.argv[2] || 'http://localhost:5173';
const browser = await chromium.launch({ headless: true });
const ctx = await browser.newContext({ viewport: { width: 1400, height: 900 } });
const page = await ctx.newPage();

await page.goto(url + '/login');
await page.waitForTimeout(1500);
await page.screenshot({ path: 'screenshots/fix-login.png' });
console.log('saved fix-login.png');

await page.goto(url + '/?demo=1');
await page.waitForTimeout(2500);

// Vai direto pra Clients
await page.click('a:has-text("Clientes")');
await page.waitForTimeout(1500);
await page.screenshot({ path: 'screenshots/fix-clients.png' });
console.log('saved fix-clients.png');

await browser.close();
