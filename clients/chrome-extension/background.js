// VAGG SAML Relay — service worker
//
// Intercepta requests pra http://127.0.0.1:<PORT>/?id=<X> que o gateway
// FortiGate redireciona após login SAML. Extrai o id, chama o endpoint
// /api/v1/clients/<client>/saml-login/relay do VAGG core, e fecha a aba
// do popup. Resultado: admin clica Conectar → loga Microsoft → tunnel
// sobe sozinho, sem copy/paste.

// Pattern do callback openfortivpn --saml-login: aceita qualquer porta loopback
// (range 8020-8520 alocado dinamicamente pelo VAGG core por client_id).
const VAGG_RELAY_PATH_RE = /^http:\/\/127\.0\.0\.1:(\d+)\/\?id=([^&#]+)/;

// Logging persistente — popup mostra últimas N entradas pra debug.
async function vlog(level, msg, extra) {
  try {
    const { vagg_logs = [] } = await chrome.storage.local.get("vagg_logs");
    vagg_logs.push({
      ts: new Date().toISOString(),
      level,
      msg,
      ...(extra || {}),
    });
    // mantém últimos 50
    while (vagg_logs.length > 50) vagg_logs.shift();
    await chrome.storage.local.set({ vagg_logs });
  } catch {
    /* ignore */
  }
  console.log(`[vagg-ext ${level}]`, msg, extra || "");
}
vlog("info", "service worker booted");

// Defensive: limpa rules dinâmicas stale de boots anteriores (UA spoofs
// que não foram removidos por crash do worker). Rules são recriadas
// quando register-pending chega.
chrome.declarativeNetRequest
  .getDynamicRules()
  .then((rules) => {
    if (rules.length === 0) return;
    return chrome.declarativeNetRequest.updateDynamicRules({
      removeRuleIds: rules.map((r) => r.id),
    });
  })
  .then(() => vlog("info", "stale dynamic rules limpas"))
  .catch((err) => vlog("warn", "cleanup rules falhou", { err: String(err) }));

// ─── UA spoof dinâmico pra GP gateways ────────────────────────────────
// Gateway PaloAlto inspeciona User-Agent e redireciona pra /getsoftwarepage.esp
// (tela "instale o agent") se UA não for "PAN GlobalProtect/...". Forja UA
// via declarativeNetRequest pra fazer gateway redirecionar pro /portal/portal.esp
// (que seta cookies portal-userauthcookie). Rule é per-gatewayHost, removida
// quando relay completa OR após timeout.
const _gpUaRuleIds = new Map(); // gatewayHost -> ruleId
let _gpUaNextId = 1000;

async function installGPUaSpoof(gatewayHost, openerTabId) {
  try {
    if (_gpUaRuleIds.has(gatewayHost)) {
      vlog("info", "UA spoof já ativo pra " + gatewayHost);
      return;
    }
    const ruleId = _gpUaNextId++;
    await chrome.declarativeNetRequest.updateDynamicRules({
      addRules: [
        {
          id: ruleId,
          priority: 100,
          action: {
            type: "modifyHeaders",
            requestHeaders: [
              {
                header: "user-agent",
                operation: "set",
                value: "PAN GlobalProtect/6.0.1-19 (Windows 10)",
              },
            ],
          },
          condition: {
            urlFilter: `||${gatewayHost}`,
            resourceTypes: ["main_frame", "sub_frame", "xmlhttprequest", "other"],
          },
        },
      ],
      removeRuleIds: [],
    });
    _gpUaRuleIds.set(gatewayHost, ruleId);
    vlog("ok", "UA spoof instalado pra " + gatewayHost, { ruleId });
    // Auto-remove após 10min
    setTimeout(() => removeGPUaSpoof(gatewayHost), 10 * 60 * 1000);
  } catch (err) {
    vlog("error", "installGPUaSpoof falhou", { err: String(err) });
  }
}

async function removeGPUaSpoof(gatewayHost) {
  const ruleId = _gpUaRuleIds.get(gatewayHost);
  if (!ruleId) return;
  try {
    await chrome.declarativeNetRequest.updateDynamicRules({
      removeRuleIds: [ruleId],
    });
    _gpUaRuleIds.delete(gatewayHost);
    vlog("info", "UA spoof removido pra " + gatewayHost);
  } catch (err) {
    vlog("error", "removeGPUaSpoof falhou", { err: String(err) });
  }
}

// Cache temporária: clientId pendente pra cada janela popup.
// O VAGG painel posta `pending` aqui via chrome.runtime.sendMessage antes de
// abrir o popup. Quando capturamos uma URL 127.0.0.1, sabemos qual cliente
// é o destino do relay.
const pending = new Map(); // popupTabId -> { clientId, vaggBaseUrl, accessToken }

async function getDefaultConfig() {
  const stored = await chrome.storage.sync.get([
    "vagg_base_url",
    "vagg_access_token",
    "vagg_last_client_id",
  ]);
  return {
    vaggBaseUrl: stored.vagg_base_url || "",
    accessToken: stored.vagg_access_token || "",
    lastClientId: stored.vagg_last_client_id || "",
  };
}

async function postRelay({ clientId, samlId, vaggBaseUrl, accessToken }) {
  if (!vaggBaseUrl) {
    throw new Error("VAGG URL não configurada");
  }
  const url = `${vaggBaseUrl.replace(/\/+$/, "")}/api/v1/clients/${encodeURIComponent(
    clientId,
  )}/saml-login/relay`;
  const headers = { "Content-Type": "application/json" };
  if (accessToken) headers["Authorization"] = `Bearer ${accessToken}`;
  const res = await fetch(url, {
    method: "POST",
    headers,
    body: JSON.stringify({ saml_id: samlId }),
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`Relay falhou: HTTP ${res.status} ${body.slice(0, 200)}`);
  }
  return res.json();
}

// Mensagem do content script ou painel VAGG.
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg && msg.type === "ping") {
    sendResponse({ ok: true, version: chrome.runtime.getManifest().version });
    return true;
  }
  if (msg && msg.type === "register-pending") {
    const openerTabId = sender.tab?.id ?? -1;
    const entry = {
      clientId: msg.clientId,
      port: msg.port || 8020,
      vpnType: msg.vpnType || "openfortivpn",
      gatewayHost: msg.gatewayHost || "",
      vaggBaseUrl: msg.vaggBaseUrl,
      accessToken: msg.accessToken,
      registeredAt: Date.now(),
    };
    pending.set(openerTabId, entry);
    chrome.storage.sync.set({ vagg_last_client_id: msg.clientId }).catch(() => {});
    vlog("info", "register-pending recebido", {
      clientId: entry.clientId,
      vpnType: entry.vpnType,
      gatewayHost: entry.gatewayHost,
      port: entry.port,
      openerTabId,
    });
    // GP: UA spoof É instalado AGORA (pré-popup) — mas SÓ pro domínio
    // do gateway. Backend já redireciona popup pra Microsoft (prelogin.esp
    // resolve a SAMLRequest URL server-side), então UA spoof não afeta a
    // navegação Microsoft (regra é filtrada por ||gatewayHost). Quando o
    // SAMLResponse POSTa de volta pro gateway, UA="PAN GlobalProtect/..."
    // faz o gateway redirecionar pra /portal/portal.esp em vez de
    // /getsoftwarepage.esp → portal seta cookies → onChanged captura.
    if (entry.vpnType === "globalprotect" && entry.gatewayHost) {
      installGPUaSpoof(entry.gatewayHost, openerTabId).catch(() => {});
    }
    sendResponse({ ok: true });
    return true;
  }
  if (msg && msg.type === "get-config") {
    getDefaultConfig().then(sendResponse);
    return true; // async response
  }
  if (msg && msg.type === "set-config") {
    chrome.storage.sync
      .set({
        vagg_base_url: msg.vaggBaseUrl || "",
        vagg_access_token: msg.accessToken || "",
      })
      .then(() => sendResponse({ ok: true }));
    return true;
  }
  if (msg && msg.type === "gp-scraped-tokens") {
    // Content script encontrou tokens em HTML comments do gateway.
    const host = (msg.host || "").split(":")[0];
    if (host && msg.fields && typeof msg.fields === "object") {
      gpAccumulate(host, msg.fields, "content-script").catch(() => {});
    }
    sendResponse({ ok: true });
    return true;
  }
});

// Limpa pending entries > 10min sem uso.
setInterval(() => {
  const now = Date.now();
  for (const [k, v] of pending) {
    if (now - v.registeredAt > 10 * 60 * 1000) pending.delete(k);
  }
}, 60000);

// Manifest V3 não suporta mais ["blocking"] em onBeforeRequest. Usamos
// listener observador: a request pra 127.0.0.1:8020 vai falhar
// naturalmente (ERR_CONNECTION_REFUSED) porque não há nada escutando
// no PC do user. Capturamos o id e fazemos o relay independentemente.
//
// Usamos onBeforeNavigate (webNavigation) que dispara ANTES da request
// tentar — mais confiável. Fallback em onBeforeRequest pra cobrir cliques.

async function handleCallback(tabId, url) {
  await vlog("info", "handleCallback fired", { url, tabId });
  const m = VAGG_RELAY_PATH_RE.exec(url);
  if (!m) {
    await vlog("warn", "URL não bateu com pattern relay", { url });
    return;
  }
  const port = parseInt(m[1], 10);
  const samlId = decodeURIComponent(m[2]);
  await vlog("info", "id SAML extraído", {
    port,
    samlId: samlId.slice(0, 30) + "...",
  });

  // Resolve cfg: 1) pending pelo openerTabId 2) pending pela port 3) default storage
  let cfg = null;
  try {
    const tab = await chrome.tabs.get(tabId);
    const openerId = tab.openerTabId ?? -1;
    if (openerId >= 0 && pending.has(openerId)) {
      cfg = pending.get(openerId);
      await vlog("info", "cfg pendente do opener tab", {
        clientId: cfg.clientId,
        openerId,
      });
    }
  } catch (err) {
    await vlog("warn", "tab.get falhou", { err: String(err) });
  }
  // Fallback 2: procura pending por port match (caso openerTabId não bater)
  if (!cfg) {
    for (const entry of pending.values()) {
      if (entry.port === port) {
        cfg = entry;
        await vlog("info", "cfg pendente por port match", {
          clientId: cfg.clientId,
          port,
        });
        break;
      }
    }
  }
  if (!cfg) {
    // Fallback genérico: usa storage default. lastClientId é só um hint
    // (UI grava no register-pending) — funciona pra single-client setups,
    // mas com múltiplos clients SAML simultâneos o openerTabId/port match
    // acima é o caminho determinístico.
    const def = await getDefaultConfig();
    cfg = { ...def, clientId: def.lastClientId || "" };
    await vlog("info", "cfg fallback (default storage)", {
      vaggBaseUrl: cfg.vaggBaseUrl,
      hasToken: !!cfg.accessToken,
      clientId: cfg.clientId,
    });
  }
  if (!cfg.clientId || !cfg.vaggBaseUrl) {
    await vlog("error", "config incompleta — abre popup VAGG primeiro", { cfg });
    chrome.notifications.create({
      type: "basic",
      iconUrl: "icons/icon-128.png",
      title: "VAGG SAML Relay",
      message: "Capturei URL mas falta config. Abra o painel VAGG e faça login.",
    });
    return;
  }
  try {
    const result = await postRelay({
      clientId: cfg.clientId,
      samlId,
      vaggBaseUrl: cfg.vaggBaseUrl,
      accessToken: cfg.accessToken,
    });
    await vlog("ok", "relay enviado com sucesso!", { result });
    chrome.notifications.create({
      type: "basic",
      iconUrl: "icons/icon-128.png",
      title: "VAGG conectando",
      message: `Cliente "${cfg.clientId}" — túnel subindo. Janela vai fechar.`,
    });
    setTimeout(() => chrome.tabs.remove(tabId).catch(() => {}), 1500);
  } catch (err) {
    await vlog("error", "relay falhou", { err: String(err.message || err) });
    chrome.notifications.create({
      type: "basic",
      iconUrl: "icons/icon-128.png",
      title: "VAGG SAML Relay — erro",
      message: String(err.message || err).slice(0, 200),
    });
  }
}

// webNavigation.onBeforeNavigate dispara ANTES da request HTTP.
// Cobre tanto navegações via URL bar quanto links/redirects de servidor.
chrome.webNavigation.onBeforeNavigate.addListener(
  (details) => {
    vlog("info", "webNav.onBeforeNavigate", {
      url: details.url,
      frameId: details.frameId,
      tabId: details.tabId,
    });
    if (details.frameId !== 0) return; // só main frame
    handleCallback(details.tabId, details.url);
  },
  { url: [{ hostEquals: "127.0.0.1", schemes: ["http"] }] },
);

// Backup listener: webNavigation.onErrorOccurred dispara quando o browser
// tenta carregar URL e falha (ERR_CONNECTION_REFUSED). Mesmo se onBeforeNavigate
// não pegar por algum motivo, este pega — e a URL ainda está no `details.url`.
chrome.webNavigation.onErrorOccurred.addListener(
  (details) => {
    vlog("info", "webNav.onErrorOccurred", {
      url: details.url,
      error: details.error,
      frameId: details.frameId,
    });
    if (details.frameId !== 0) return;
    if (!VAGG_RELAY_PATH_RE.test(details.url)) return;
    handleCallback(details.tabId, details.url);
  },
  { url: [{ hostEquals: "127.0.0.1", schemes: ["http"] }] },
);

// ─── GlobalProtect (PaloAlto) cookie capture ──────────────────────────
//
// CRÍTICO: PaloAlto NÃO seta os cookies SAML via Set-Cookie. Ele retorna
// como CUSTOM RESPONSE HEADERS (sem prefixo Set-Cookie:) na resposta do
// POST de /SAML20/SP/ACS, e/OU como COMENTÁRIOS HTML embedados no body
// (`<!--<prelogin-cookie>...</prelogin-cookie>-->`). chrome.cookies API
// é cega pra isso. Capturamos via:
//   1. webRequest.onHeadersReceived com extraInfoSpec=["responseHeaders",
//      "extraHeaders"] — pega headers não-standard.
//   2. content_script scrape do body (fallback pra PanOS novos que embedam
//      em HTML comments).
//
// Refs autoritativas:
//   - openconnect gpst.c:1380-1406 (treats prelogin-cookie/portal-userauthcookie como sso_token)
//   - gp-saml-gui gp_saml_gui.py:152-200 (lê headers + scrapes HTML comments)

const GP_TOKEN_FIELDS = new Set([
  "prelogin-cookie",
  "portal-userauthcookie",
  "saml-username",
  "saml-auth-status",
  "saml-slo",
]);

// Acumulador por gatewayHost — chega em pedaços (headers no ACS, mais
// headers em sub-requests). Quando tem saml-username + (prelogin-cookie
// OR portal-userauthcookie) → success, posta relay e limpa.
const _gpTokens = new Map(); // gatewayHost -> { 'prelogin-cookie': '...', 'saml-username': '...' }

async function gpAccumulate(gatewayHost, fields, source) {
  let bucket = _gpTokens.get(gatewayHost);
  if (!bucket) { bucket = {}; _gpTokens.set(gatewayHost, bucket); }
  let added = false;
  for (const [k, v] of Object.entries(fields)) {
    const lk = k.toLowerCase();
    if (!GP_TOKEN_FIELDS.has(lk)) continue;
    if (!v || v === bucket[lk]) continue;
    bucket[lk] = v;
    added = true;
  }
  if (added) {
    vlog("info", `GP token acumulado (${source})`, {
      gatewayHost,
      have: Object.keys(bucket),
    });
  }
  const haveUser = !!bucket["saml-username"];
  const haveCookie = !!(bucket["prelogin-cookie"] || bucket["portal-userauthcookie"]);
  if (haveUser && haveCookie) {
    // Acha pending entry pra esse gatewayHost
    let entry = null;
    for (const e of pending.values()) {
      if (e.vpnType !== "globalprotect") continue;
      if (e.gatewayHost && gatewayHost.endsWith(e.gatewayHost)) { entry = e; break; }
    }
    if (!entry) {
      vlog("warn", "GP token completo mas nenhum pending casa", { gatewayHost });
      return;
    }
    await postGPRelay(entry, bucket, gatewayHost);
    _gpTokens.delete(gatewayHost);
    if (entry.gatewayHost) await removeGPUaSpoof(entry.gatewayHost);
  }
}

async function postGPRelay(entry, bucket, gatewayHost) {
  const cookieName = bucket["prelogin-cookie"]
    ? "prelogin-cookie"
    : "portal-userauthcookie";
  const cookieValue = bucket[cookieName];
  const samlUser = bucket["saml-username"];
  vlog("ok", "GP capture COMPLETO — posting relay", {
    clientId: entry.clientId,
    cookieName,
    samlUser,
  });
  try {
    const url = `${entry.vaggBaseUrl.replace(/\/+$/, "")}/api/v1/clients/${encodeURIComponent(entry.clientId)}/saml-login/relay-cookie`;
    const payload = {
      gateway_host: gatewayHost,
      cookies: [{ name: cookieName, value: cookieValue, domain: gatewayHost }],
      saml_username: samlUser,
    };
    const res = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${entry.accessToken}`,
      },
      body: JSON.stringify(payload),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status} ${await res.text()}`);
    vlog("ok", "GP relay-cookie enviado!", { status: res.status });
    chrome.notifications.create({
      type: "basic",
      iconUrl: "icons/icon-128.png",
      title: "VAGG conectando (GP)",
      message: `Cliente "${entry.clientId}" — cookies SAML capturados. Túnel subindo.`,
    });
  } catch (err) {
    vlog("error", "GP relay-cookie falhou", { err: String(err) });
  }
}

// PRIMARY: webRequest.onHeadersReceived com extraHeaders — pega CUSTOM
// response headers (prelogin-cookie:, portal-userauthcookie:, saml-username:).
// extraHeaders é obrigatório em MV3 pra ler headers não-standard.
chrome.webRequest.onHeadersReceived.addListener(
  (details) => {
    try {
      const host = new URL(details.url).host.split(":")[0];
      const interesting = {};
      // Diagnóstico: loga TODOS headers prelogin*/portal*/saml* de responses
      // pra paths PaloAlto. Crítico pra descobrir se o gateway emite
      // portal-userauthcookie ou só prelogin-cookie.
      const isPanoSPath = /\/SAML20\/|\/global-protect\/|\/ssl-vpn\//.test(details.url);
      const diag = {};
      for (const h of details.responseHeaders || []) {
        const lk = h.name.toLowerCase();
        if (GP_TOKEN_FIELDS.has(lk)) interesting[lk] = h.value;
        if (isPanoSPath && /^(prelogin|portal|saml|authcookie)/i.test(lk)) {
          diag[lk] = h.value.length > 30 ? h.value.slice(0, 30) + "...(len=" + h.value.length + ")" : h.value;
        }
      }
      if (Object.keys(diag).length > 0) {
        vlog("info", "PA response headers (diag)", { url: details.url.slice(0, 80), headers: Object.keys(diag) });
      }
      if (Object.keys(interesting).length > 0) {
        gpAccumulate(host, interesting, "webRequest").catch(() => {});
      }
    } catch (err) {
      vlog("warn", "onHeadersReceived erro", { err: String(err) });
    }
  },
  { urls: ["<all_urls>"], types: ["main_frame", "sub_frame", "xmlhttprequest"] },
  ["responseHeaders", "extraHeaders"],
);

// Bridge pro content script: page scraping (HTML comments) reporta tokens aqui.
// SECONDARY: PaloAlto PanOS novos embedam tokens como HTML comments
// `<!--<prelogin-cookie>...</prelogin-cookie>-->` em vez de response headers.

// Note: receiver pro msg.type === "gp-scraped-tokens" é adicionado abaixo
// junto ao listener principal (chrome.runtime.onMessage).

// Diagnóstico: loga navegações pelo gateway pra debug. Captura real
// dos tokens SAML acontece via webRequest.onHeadersReceived acima.
chrome.webNavigation.onCompleted.addListener(
  (details) => {
    if (details.frameId !== 0) return;
    if (/\/global-protect\/|\/SAML20\/|\/ssl-vpn\//.test(details.url)) {
      // Apenas log diagnóstico — captura de fato acontece via webRequest.
      vlog("info", "GP nav match (diagnóstico)", { url: details.url });
    }
  },
  {
    url: [
      { urlContains: "/global-protect/" },
      { urlContains: "/SAML20/" },
      { urlContains: "/ssl-vpn/" },
    ],
  },
);
