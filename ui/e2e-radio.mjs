import { chromium } from 'playwright';

const BASE = process.env.VAGG_BASE || 'http://192.168.68.102';
const browser = await chromium.launch({ headless: true });
const ctx = await browser.newContext({ viewport: { width: 1400, height: 900 } });
const page = await ctx.newPage();

await page.goto(BASE);
await page.waitForLoadState('networkidle');
await page.fill('input[autocomplete=username]', 'admin');
await page.fill('input[autocomplete=current-password]', 'admin');
await page.click('button[type=submit]');
await page.waitForLoadState('networkidle');
await page.waitForTimeout(1500);

await page.click('a:has-text("Clientes")');
await page.waitForTimeout(1500);

// MRV edit
const mrvRow = page.locator('tr', { hasText: 'MRV' }).first();
await mrvRow.locator('button').nth(2).click();
await page.waitForTimeout(2500);
const radios = await page.locator('input[name=auth_method_edit]').count();
const checked = await page.locator('input[name=auth_method_edit]:checked').getAttribute('value');
console.log('MRV — radios:', radios, 'checked:', checked);
await page.locator('input[name=auth_method_edit]').first().scrollIntoViewIfNeeded();
await page.screenshot({ path: 'screenshots/e2e-radio-mrv-edit.png' });
await page.click('button:has-text("Cancelar")');
await page.waitForTimeout(800);

// Minerva edit
const minRow = page.locator('tr', { hasText: 'Minerva' }).first();
await minRow.locator('button').nth(2).click();
await page.waitForTimeout(2500);
const checkedMin = await page.locator('input[name=auth_method_edit]:checked').getAttribute('value');
console.log('Minerva — checked:', checkedMin);
await page.locator('input[name=auth_method_edit]').first().scrollIntoViewIfNeeded();
await page.screenshot({ path: 'screenshots/e2e-radio-minerva-edit.png' });

await browser.close();
console.log('done');
