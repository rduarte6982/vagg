// scripts/capture/capture.mjs — gera os PNGs referenciados por
// docs/MANUAL-INSTALACAO.md. Usa puppeteer-core apontando para o Chromium
// que o Playwright instalou. SEM dependência de servidor real do vagg-core
// — o script intercepta /api e /portal e devolve fixtures determinísticas
// para que cada tela renderize com dados realistas.
//
// Uso:
//   1. Em outro terminal: cd ui && npm run dev
//   2. Em outro terminal: cd portal && npm run dev
//   3. node scripts/capture/capture.mjs
//
// Saída: docs/manual-prints/*.png

import { mkdir } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import puppeteer from 'puppeteer-core';

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = join(here, '..', '..');
const outDir = join(repoRoot, 'docs', 'manual-prints');

const CHROME =
  process.env.CHROME_PATH ||
  `${process.env.USERPROFILE}\\AppData\\Local\\ms-playwright\\chromium-1217\\chrome-win64\\chrome.exe`;

if (!existsSync(CHROME)) {
  console.error(`Chromium não encontrado em ${CHROME}`);
  console.error('Defina CHROME_PATH ou rode `npx playwright install chromium`.');
  process.exit(1);
}

await mkdir(outDir, { recursive: true });

const NOW = new Date('2026-05-01T15:30:00Z').toISOString();

const FIXTURES = {
  // ---- vagg-core admin API ----
  '/api/v1/auth/login': () => ({
    access_token: 'fake.access.token',
    refresh_token: 'fake.refresh.token',
    token_type: 'bearer',
  }),
  '/api/v1/auth/me': () => ({ email: 'admin@suaconsultoria.com.br', role: 'admin' }),
  '/api/v1/system/version': () => ({ version: '1.0.0' }),
  '/api/v1/system/health': () => ({ status: 'ok' }),
  '/api/v1/system/license': () => ({ status: 'active', tier: 'professional' }),
  '/api/v1/clients': () => [
    {
      id: 'petroleo',
      name: 'Petroleo S.A.',
      vpn_type: 'openvpn',
      virtual_cidr: '10.200.1.0/24',
      real_cidr: '192.168.1.0/24',
      dns_server: '192.168.1.10',
      description: null,
      nat_mappings: [],
      tunnel_state: 'up',
      created_at: NOW,
      updated_at: NOW,
    },
    {
      id: 'varejo',
      name: 'Varejo Inc.',
      vpn_type: 'openconnect',
      virtual_cidr: '10.200.2.0/24',
      real_cidr: '192.168.1.0/24',
      dns_server: '192.168.1.10',
      description: null,
      nat_mappings: [],
      tunnel_state: 'up',
      created_at: NOW,
      updated_at: NOW,
    },
    {
      id: 'industria',
      name: 'Industria do Sul',
      vpn_type: 'wireguard',
      virtual_cidr: '10.200.3.0/24',
      real_cidr: '10.50.0.0/16',
      dns_server: '10.50.0.5',
      description: null,
      nat_mappings: [],
      tunnel_state: 'starting',
      created_at: NOW,
      updated_at: NOW,
    },
  ],
  '/api/v1/consultants': () => [
    {
      id: 1,
      email: 'joao.silva@suaconsultoria.com.br',
      name: 'João Silva',
      openvpn_username: 'joao.silva',
      static_pool_ip: '10.8.0.10',
      role: 'operator',
      active: true,
      created_at: NOW,
      updated_at: NOW,
    },
    {
      id: 2,
      email: 'maria.santos@suaconsultoria.com.br',
      name: 'Maria Santos',
      openvpn_username: 'maria.santos',
      static_pool_ip: '10.8.0.11',
      role: 'admin',
      active: true,
      created_at: NOW,
      updated_at: NOW,
    },
  ],
  '/api/v1/policies': () => [
    {
      id: 1,
      consultant_id: 1,
      client_id: 'petroleo',
      scope_kind: 'full',
      scope_value: null,
      expires_at: null,
      created_at: NOW,
    },
    {
      id: 2,
      consultant_id: 1,
      client_id: 'varejo',
      scope_kind: 'subnet',
      scope_value: '10.200.2.128/26',
      expires_at: null,
      created_at: NOW,
    },
    {
      id: 3,
      consultant_id: 2,
      client_id: 'industria',
      scope_kind: 'full',
      scope_value: null,
      expires_at: null,
      created_at: NOW,
    },
  ],
  '/api/v1/audit': () => [
    {
      id: 'aaaa-1',
      event_type: 'tunnel.access',
      actor_consultant_id: 1,
      payload: { client_id: 'petroleo', dst: '10.200.1.50', port: 22 },
      hash: 'a1b2c3'.repeat(10) + 'a1b2',
      occurred_at: '2026-05-01T15:25:00Z',
    },
    {
      id: 'aaaa-2',
      event_type: 'policy.created',
      actor_consultant_id: 2,
      payload: { client_id: 'varejo', consultant_id: 1, scope_kind: 'subnet' },
      hash: 'b2c3d4'.repeat(10) + 'b2c3',
      occurred_at: '2026-05-01T15:00:00Z',
    },
    {
      id: 'aaaa-3',
      event_type: 'tunnel.denied',
      actor_consultant_id: 1,
      payload: { client_id: 'industria', reason: 'no_policy' },
      hash: 'c3d4e5'.repeat(10) + 'c3d4',
      occurred_at: '2026-05-01T14:50:00Z',
    },
  ],
  // ---- portal de transparência ----
  '/portal/dashboard': () => ({
    client_id: 'petroleo',
    viewer_email: 'auditor@petroleo.com.br',
    active_consultants: 14,
    connections: 1247,
    denials: 0,
  }),
  '/portal/timeline': () => [
    {
      occurred_at: '2026-05-01T15:25:00Z',
      event_type: 'tunnel.access',
      scope_kind: 'full',
      scope_value_summary: null,
    },
    {
      occurred_at: '2026-05-01T15:00:00Z',
      event_type: 'policy.created',
      scope_kind: 'subnet',
      scope_value_summary: '<subnet>/26',
    },
  ],
};

async function setupFixtures(page) {
  await page.setRequestInterception(true);
  page.on('request', (req) => {
    const url = new URL(req.url());
    const path = url.pathname;
    if (path in FIXTURES) {
      const body = JSON.stringify(FIXTURES[path]());
      req.respond({
        status: 200,
        contentType: 'application/json',
        body,
      });
      return;
    }
    // Pass-through everything else (HTML, JS, CSS).
    req.continue();
  });
}

async function shot(page, name) {
  const filePath = join(outDir, `${name}.png`);
  await page.screenshot({ path: filePath, fullPage: false });
  console.log(`  ✓ ${name}.png`);
}

async function captureUi(browser) {
  const page = await browser.newPage();
  await page.setViewport({ width: 1280, height: 800, deviceScaleFactor: 1 });
  await setupFixtures(page);

  console.log('UI (admin):');

  // Login
  await page.goto('http://localhost:5173/login', { waitUntil: 'networkidle2' });
  await page.waitForSelector('input[type="email"]');
  await shot(page, 'ui-01-login');

  // Login preenchido
  await page.type('input[type="email"]', 'admin@suaconsultoria.com.br');
  await page.type('input[type="password"]', '••••••••••••••');
  await shot(page, 'ui-02-login-filled');

  // Pré-popular tokens para pular o login real (já temos fixtures de /auth/me).
  await page.evaluate(() => {
    localStorage.setItem('vagg.access_token', 'fake.access.token');
    localStorage.setItem('vagg.refresh_token', 'fake.refresh.token');
  });

  await page.goto('http://localhost:5173/', { waitUntil: 'networkidle2' });
  await page.waitForSelector('h1');
  await shot(page, 'ui-03-dashboard');

  await page.goto('http://localhost:5173/clients', { waitUntil: 'networkidle2' });
  await page.waitForSelector('table');
  await shot(page, 'ui-04-clients-list');

  await page.goto('http://localhost:5173/consultants', { waitUntil: 'networkidle2' });
  await page.waitForSelector('table');
  await shot(page, 'ui-05-consultants-list');

  await page.goto('http://localhost:5173/policies', { waitUntil: 'networkidle2' });
  await page.waitForSelector('table');
  await shot(page, 'ui-06-policies-list');

  await page.goto('http://localhost:5173/audit', { waitUntil: 'networkidle2' });
  await page.waitForSelector('table');
  await shot(page, 'ui-07-audit-list');

  await page.goto('http://localhost:5173/system', { waitUntil: 'networkidle2' });
  await page.waitForSelector('h1');
  await shot(page, 'ui-08-system');

  await page.close();
}

async function capturePortal(browser) {
  const page = await browser.newPage();
  await page.setViewport({ width: 1280, height: 800, deviceScaleFactor: 1 });
  await setupFixtures(page);

  console.log('Portal:');

  await page.goto('http://localhost:5174/login', { waitUntil: 'networkidle2' });
  await page.waitForSelector('h1');
  await shot(page, 'portal-01-login');

  await page.type('input[type="email"]', 'auditor@petroleo.com.br');
  await page.type('#client_id', 'petroleo');
  await shot(page, 'portal-02-login-filled');

  await page.goto('http://localhost:5174/dashboard', { waitUntil: 'networkidle2' });
  await page.waitForSelector('h1');
  await shot(page, 'portal-03-dashboard');

  await page.close();
}

const browser = await puppeteer.launch({
  executablePath: CHROME,
  headless: 'new',
  args: ['--no-sandbox', '--disable-dev-shm-usage'],
});

try {
  await captureUi(browser);
  await capturePortal(browser);
  console.log(`\nDone. PNGs em ${outDir}`);
} finally {
  await browser.close();
}
