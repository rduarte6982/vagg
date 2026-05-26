// Content script — injetado em todo http(s) page. Jobs:
//
// 1. Sinaliza ao painel VAGG que a extensão está instalada (via postMessage)
// 2. Auto-config: lê access_token do localStorage QUANDO está num painel VAGG,
//    envia pro background pra salvar (zero config manual pelo user)
// 3. Recebe postMessage do painel pra registrar "pending" no service worker

(function () {
  // 1. Sinaliza presença via postMessage. Painel pode ouvir e marcar
  // `__vagg_extension_installed = true`.
  try {
    window.postMessage(
      { source: "vagg-ext", type: "installed", version: chrome.runtime.getManifest().version },
      "*",
    );
  } catch {
    /* ignore */
  }

  // 2. AUTO-CONFIG: se a página parece ser um painel VAGG, lê access_token
  // do localStorage e salva no background. Detecta painel VAGG por:
  //   - presença de localStorage['vagg.access_token']
  //   - meta tag <meta name="vagg-app">
  //   - title começando com 'vagg'
  function syncConfigFromPage() {
    try {
      const token = localStorage.getItem("vagg.access_token");
      const isVaggPanel =
        !!token ||
        !!document.querySelector('meta[name="vagg-app"]') ||
        (document.title || "").toLowerCase().startsWith("vagg");
      if (!isVaggPanel || !token) return;
      const vaggBaseUrl = `${location.protocol}//${location.host}`;
      chrome.runtime
        .sendMessage({
          type: "set-config",
          vaggBaseUrl,
          accessToken: token,
        })
        .catch(() => {});
    } catch {
      /* ignore */
    }
  }

  // Roda no load e depois sempre que localStorage mudar (login fresh).
  syncConfigFromPage();
  window.addEventListener("storage", syncConfigFromPage);
  // Também tenta de novo 1s depois (React/SPA pode setar token pós-render)
  setTimeout(syncConfigFromPage, 1000);
  setTimeout(syncConfigFromPage, 3000);

  // 4. GP HTML-comment scraper: PaloAlto PanOS novos embedam tokens SAML
  //    como comentários HTML no body da response do /SAML20/SP/ACS, exemplo:
  //      <!--<prelogin-cookie>VALUE</prelogin-cookie>-->
  //      <!--<saml-username>user@corp</saml-username>-->
  //    Esses tokens são INVISÍVEIS pra webRequest.onHeadersReceived
  //    (HTTP headers normais), então scraping do DOM é o fallback.
  //    Referência: gp-saml-gui gp_saml_gui.py:173-200 CommentHtmlParser.
  function scrapeGPTokens() {
    try {
      const html = document.documentElement?.outerHTML || "";
      if (!html.includes("<!--")) return;
      // Pega TODOS comments do HTML
      const fields = {};
      const re = /<!--\s*<(prelogin-cookie|portal-userauthcookie|saml-username|saml-auth-status|saml-slo)>([^<]*)<\/\1>\s*-->/gi;
      let m;
      while ((m = re.exec(html)) !== null) {
        fields[m[1].toLowerCase()] = m[2];
      }
      if (Object.keys(fields).length === 0) return;
      chrome.runtime
        .sendMessage({
          type: "gp-scraped-tokens",
          host: location.host,
          fields,
        })
        .catch(() => {});
    } catch {
      /* ignore */
    }
  }
  // Roda em qualquer page do gateway PA (/global-protect/, /SAML20/, /ssl-vpn/).
  // Filtro client-side pra evitar gastar ciclos em outros sites.
  if (/\/global-protect\/|\/SAML20\/|\/ssl-vpn\//.test(location.pathname)) {
    if (document.readyState === "loading") {
      window.addEventListener("DOMContentLoaded", scrapeGPTokens, { once: true });
    } else {
      scrapeGPTokens();
    }
    // Race: alguns redirects 302 podem rolar antes do DOM completar.
    setTimeout(scrapeGPTokens, 500);
    setTimeout(scrapeGPTokens, 1500);
  }

  // 3. Recebe mensagens do painel via window.postMessage e relaya pra background
  window.addEventListener("message", (event) => {
    if (event.source !== window) return;
    const msg = event.data;
    if (!msg || msg.source !== "vagg-page") return;

    if (msg.type === "ping") {
      window.postMessage(
        { source: "vagg-ext", type: "pong", version: chrome.runtime.getManifest().version },
        "*",
      );
      return;
    }
    if (msg.type === "register-pending") {
      chrome.runtime
        .sendMessage({
          type: "register-pending",
          clientId: msg.clientId,
          port: msg.port,
          vpnType: msg.vpnType,
          gatewayHost: msg.gatewayHost,
          vaggBaseUrl: msg.vaggBaseUrl,
          accessToken: msg.accessToken,
        })
        .catch(() => {});
    }
    if (msg.type === "set-config") {
      chrome.runtime
        .sendMessage({
          type: "set-config",
          vaggBaseUrl: msg.vaggBaseUrl,
          accessToken: msg.accessToken,
        })
        .catch(() => {});
    }
  });
})();
