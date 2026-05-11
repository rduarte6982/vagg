#!/bin/sh
# /etc/cont-init.d/91-firefox-mitm.sh — configura Firefox pra usar mitmproxy
# como proxy HTTP/HTTPS e confiar no CA dele.
#
# Roda DEPOIS do mitmproxy estar UP (script 90-) então o CA já está em
# /opt/vagg-mitm/.mitmproxy/mitmproxy-ca-cert.pem.
#
# Estratégia:
#  1) Define proxy via prefs (network.proxy.*) no profile do Firefox
#  2) Adiciona o CA do mitmproxy ao NSS trust store do profile
set -eu

PROFILE_DIR=/config/profile
LOG=/var/log/vagg-mitm/firefox-init.log
mkdir -p /var/log/vagg-mitm
mkdir -p "$PROFILE_DIR"
chown -R 1000:1000 "$PROFILE_DIR"

CA=/opt/vagg-mitm/.mitmproxy/mitmproxy-ca-cert.pem

# Se mitmproxy ainda não gerou CA, espera um pouco mais — pode estar
# inicializando em paralelo.
i=0
while [ $i -lt 20 ] && [ ! -f "$CA" ]; do
    sleep 1
    i=$((i+1))
done

if [ ! -f "$CA" ]; then
    echo "[firefox-init] WARN: CA not found, skipping trust setup" >> "$LOG"
fi

# Cria user.js no profile setando proxy + trust enterprise roots
cat > /tmp/user.js <<'EOF'
user_pref("network.proxy.type", 1);
user_pref("network.proxy.http", "127.0.0.1");
user_pref("network.proxy.http_port", 8080);
user_pref("network.proxy.ssl", "127.0.0.1");
user_pref("network.proxy.ssl_port", 8080);
user_pref("network.proxy.share_proxy_settings", true);
user_pref("network.proxy.socks_remote_dns", true);
user_pref("network.proxy.no_proxies_on", "localhost,127.0.0.1");
user_pref("security.enterprise_roots.enabled", true);
user_pref("app.update.enabled", false);
user_pref("app.update.auto", false);
user_pref("browser.startup.homepage_override.mstone", "ignore");
user_pref("browser.shell.checkDefaultBrowser", false);
user_pref("browser.tabs.warnOnClose", false);
user_pref("datareporting.policy.firstRunURL", "");
user_pref("toolkit.telemetry.reportingpolicy.firstRun", false);
user_pref("layers.acceleration.disabled", true);
user_pref("dom.ipc.processCount", 1);
user_pref("browser.sessionstore.resume_from_crash", false);
user_pref("signon.rememberSignons", false);
user_pref("dom.disable_open_during_load", false);
EOF
cp /tmp/user.js "$PROFILE_DIR/user.js"
chown 1000:1000 "$PROFILE_DIR/user.js"
echo "[firefox-init] user.js installed at $PROFILE_DIR/user.js" >> "$LOG"

# Adiciona o CA do mitmproxy ao trust do Firefox via certutil. O profile
# precisa existir; se for criação pristine vai ser criado pelo Firefox no
# primeiro boot — esse certutil pode falhar nesse caso e tudo bem
# (security.enterprise_roots.enabled cobre o caso comum de macOS, mas no
# Linux precisa do certutil).
if [ -f "$CA" ] && command -v certutil >/dev/null; then
    NSS_DB="sql:$PROFILE_DIR"
    # Tenta inicializar o NSS DB se vazio
    if ! [ -f "$PROFILE_DIR/cert9.db" ]; then
        su-exec 1000:1000 certutil -N -d "$NSS_DB" --empty-password 2>>"$LOG" || true
    fi
    su-exec 1000:1000 certutil -A -n "mitmproxy-vagg" -t "C,," \
        -i "$CA" -d "$NSS_DB" 2>>"$LOG" \
        && echo "[firefox-init] CA imported into Firefox NSS trust" >> "$LOG" \
        || echo "[firefox-init] certutil failed (non-fatal)" >> "$LOG"
fi

exit 0
