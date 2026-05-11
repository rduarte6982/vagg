#!/bin/bash
# /custom-cont-init.d/start-vagg — roda no startup do linuxserver/firefox
# antes do Firefox subir.
#
# Inicia mitmproxy em background (headless) e abre o gateway SAML como
# homepage do Firefox. Quando o cookie é capturado pelo addon, escrito
# em $VAGG_SAML_COOKIE_OUT, o backend (vagg-core) faz polling e pega.
set -eu

GATEWAY="${VAGG_SAML_GATEWAY_URL:-https://example.com}"
COOKIE_OUT="${VAGG_SAML_COOKIE_OUT:-/share/cookie}"
GATEWAY_HOST=$(echo "$GATEWAY" | sed -E 's#^https?://([^/]+).*#\1#')

mkdir -p "$(dirname "$COOKIE_OUT")"

# Inicia mitmproxy em background — sniff de tráfego HTTPS do firefox
echo "[vagg] starting mitmproxy on :8080 (gateway_host=$GATEWAY_HOST)"
mitmdump -q --listen-port 8080 --set ssl_insecure=true \
    -s /usr/local/share/cookie_addon.py \
    --set "vagg_cookie_out=$COOKIE_OUT" \
    --set "vagg_gateway_host=$GATEWAY_HOST" \
    > /tmp/mitmproxy.log 2>&1 &

# Espera o CA do mitm ser gerado (no primeiro tráfego)
for i in 1 2 3 4 5; do
    [ -f /config/.mitmproxy/mitmproxy-ca-cert.pem ] && break
    sleep 1
done

# Configura Firefox: home = gateway URL, proxy = mitmproxy
# linuxserver/firefox lê prefs de /defaults/user.js — só tunamos a homepage.
mkdir -p /defaults
cat > /defaults/user.js <<EOF
user_pref("network.proxy.type", 1);
user_pref("network.proxy.http", "127.0.0.1");
user_pref("network.proxy.http_port", 8080);
user_pref("network.proxy.ssl", "127.0.0.1");
user_pref("network.proxy.ssl_port", 8080);
user_pref("network.proxy.no_proxies_on", "localhost,127.0.0.1");
user_pref("security.enterprise_roots.enabled", true);
user_pref("browser.startup.homepage", "$GATEWAY");
user_pref("browser.startup.page", 1);
user_pref("browser.shell.checkDefaultBrowser", false);
user_pref("app.update.enabled", false);
user_pref("toolkit.telemetry.reportingpolicy.firstRun", false);
user_pref("datareporting.policy.firstRunURL", "");
user_pref("browser.tabs.warnOnClose", false);
EOF

# Watcher: quando cookie é capturado, mata o container (auto-cleanup).
(
    START=$(date +%s)
    while true; do
        if [ -s "$COOKIE_OUT" ]; then
            echo "[vagg] cookie captured — sending SIGTERM to PID 1"
            sleep 3   # garante que orchestrator pegue no proximo poll
            kill -TERM 1 || true
            break
        fi
        NOW=$(date +%s)
        if [ $((NOW - START)) -gt "${VAGG_SAML_TIMEOUT_SEC:-1200}" ]; then
            echo "[vagg] timeout — sending SIGTERM to PID 1"
            kill -TERM 1 || true
            break
        fi
        sleep 3
    done
) &

echo "[vagg] init complete — Firefox vai subir apontando pra $GATEWAY"
