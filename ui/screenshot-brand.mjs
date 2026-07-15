import { chromium } from 'playwright';

const url = process.argv[2] || 'http://localhost:5173';

const browser = await chromium.launch({ headless: true });
const ctx = await browser.newContext({ viewport: { width: 1400, height: 900 } });
const page = await ctx.newPage();

// Vai pro /login (não modo demo) só pra capturar o login screen com branding novo
await page.goto(url + '/login');
await page.waitForTimeout(1500);
await page.screenshot({ path: 'screenshots/brand-login.png' });
console.log('saved brand-login.png');

// Demo mode = entra direto, navega.
await page.goto(url + '/?demo=1');
await page.waitForTimeout(2500);
await page.screenshot({ path: 'screenshots/brand-dashboard.png' });
console.log('saved brand-dashboard.png');

await page.click('a:has-text("Usuários")');
await page.waitForTimeout(1500);
await page.screenshot({ path: 'screenshots/brand-users.png' });
console.log('saved brand-users.png');

await browser.close();
