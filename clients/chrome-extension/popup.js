const urlInput = document.getElementById("vaggBaseUrl");
const tokenInput = document.getElementById("accessToken");
const statusLine = document.getElementById("status-line");
const cfgUrlSpan = document.getElementById("cfg-url");
const cfgTokenSpan = document.getElementById("cfg-token");

function refreshStatus() {
  chrome.runtime.sendMessage({ type: "get-config" }, (cfg) => {
    const url = cfg?.vaggBaseUrl || "";
    const tok = cfg?.accessToken || "";
    urlInput.value = url;
    tokenInput.value = tok;
    cfgUrlSpan.textContent = url || "—";
    cfgTokenSpan.textContent = tok ? `${tok.slice(0, 14)}…${tok.slice(-6)}` : "—";
    if (url && tok) {
      statusLine.innerHTML = '<span class="ok">✓ Configurada</span> — pronta pra capturar SAML.';
    } else {
      statusLine.innerHTML =
        '<span class="warn">⚠ Aguardando login</span> — abra o painel VAGG e faça login.';
    }
  });
}

function refreshLogs() {
  chrome.storage.local.get("vagg_logs", ({ vagg_logs }) => {
    const logsEl = document.getElementById("logs");
    if (!logsEl) return;
    const list = vagg_logs || [];
    if (list.length === 0) {
      logsEl.textContent = "Sem atividade ainda.";
      return;
    }
    const colors = { error: "#ff8a80", warn: "#d4af37", ok: "#4ade80", info: "#99a3ba" };
    logsEl.innerHTML = list
      .slice(-20)
      .reverse()
      .map((e) => {
        const time = e.ts ? e.ts.slice(11, 19) : "";
        const color = colors[e.level] || "#99a3ba";
        const extra = Object.keys(e)
          .filter((k) => !["ts", "level", "msg"].includes(k))
          .map((k) => `${k}=${JSON.stringify(e[k]).slice(0, 60)}`)
          .join(" ");
        return `<div><span style="color: var(--muted)">${time}</span> <span style="color: ${color}">[${e.level}]</span> ${e.msg} <span style="color: var(--muted); font-size: 9px">${extra}</span></div>`;
      })
      .join("");
  });
}

document.getElementById("clear-logs")?.addEventListener("click", () => {
  chrome.storage.local.set({ vagg_logs: [] }, () => refreshLogs());
});

refreshStatus();
refreshLogs();
// Refresh a cada 2s pra pegar auto-config recém-feito + logs
setInterval(() => {
  refreshStatus();
  refreshLogs();
}, 2000);

document.getElementById("save").addEventListener("click", () => {
  const vaggBaseUrl = urlInput.value.trim();
  const accessToken = tokenInput.value.trim();
  chrome.runtime.sendMessage(
    { type: "set-config", vaggBaseUrl, accessToken },
    () => refreshStatus(),
  );
});
