import { chromium } from 'playwright';

const url = process.argv[2] || 'http://localhost:5173';

const browser = await chromium.launch({ headless: true });
const ctx = await browser.newContext({ viewport: { width: 1400, height: 900 } });
const page = await ctx.newPage();

console.log('opening', url + '/?demo=1');
page.on('console', msg => console.log('[console]', msg.type(), msg.text()));
page.on('pageerror', err => console.log('[pageerror]', err.message));
page.on('response', r => {
  if (r.status() >= 400) console.log('[http]', r.status(), r.url());
});
await page.goto(url + '/?demo=1');
await page.waitForTimeout(3000);

// Print qualquer botão visível
const btns = await page.locator('button').allTextContents();
console.log('buttons found:', JSON.stringify(btns));
const inputs = await page.locator('input').count();
console.log('inputs found:', inputs);

// Tenta clicar
const submit = page.locator('button:has-text("Entrar")').first();
if (await submit.count() > 0) {
  await submit.click();
  await page.waitForLoadState('networkidle');
} else {
  console.log('NO Entrar button, current URL:', page.url());
  await page.screenshot({ path: 'screenshots/debug-startup.png' });
}

// Navega pra Usuários.
await page.click('a:has-text("Usuários")');
await page.waitForTimeout(1500);

await page.screenshot({ path: 'screenshots/users-list.png', fullPage: false });
console.log('saved screenshots/users-list.png');

// Abre o modal "Novo usuário".
await page.click('button:has-text("Novo usuário")');
await page.waitForTimeout(800);
await page.screenshot({ path: 'screenshots/users-create-modal.png' });
console.log('saved screenshots/users-create-modal.png');
await page.click('button:has-text("Cancelar")');
await page.waitForTimeout(300);

// Abre o modal "Editar" no primeiro usuário.
await page.click('button[title="Editar"]');
await page.waitForTimeout(800);
await page.screenshot({ path: 'screenshots/users-edit-modal.png' });
console.log('saved screenshots/users-edit-modal.png');

await browser.close();
