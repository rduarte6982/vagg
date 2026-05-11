#!/bin/bash
# Sobe Xvfb + mitmproxy + xpra com Firefox apontado pro gateway SAML.
# Quando o cookie SAML é capturado, escreve em $VAGG_SAML_COOKIE_OUT
# e o orquestrador sai do container.
set -eu

: "${VAGG_SAML_GATEWAY_URL:?VAGG_SAML_GATEWAY_URL não setado}"
: "${VAGG_SAML_COOKIE_OUT:=/share/cookie}"
: "${VAGG_SAML_PORT:=14500}"
: "${VAGG_SAML_TIMEOUT_SEC:=1200}"

log() { echo "[saml-portal $(date -u +%FT%TZ)] $*"; }

mkdir -p "$(dirname "$VAGG_SAML_COOKIE_OUT")"

# 1) Inicia mitmproxy headless na porta 8080 — captura cookies do Firefox
log "starting mitmproxy"
mitmdump -q --listen-port 8080 --set ssl_insecure=true \
    -s /usr/local/share/cookie_addon.py \
    --set "vagg_cookie_out=$VAGG_SAML_COOKIE_OUT" \
    --set "vagg_gateway_host=$(echo "$VAGG_SAML_GATEWAY_URL" | sed -E 's#^https?://([^/]+).*#\1#')" \
    > /tmp/mitmproxy.log 2>&1 &
MITM_PID=$!
sleep 2

# 2) Configura Firefox: proxy pra mitmproxy, aceita cert root do mitm
mkdir -p /home/vagg/.mozilla/firefox/profile.default
cp /usr/local/share/firefox-prefs.js /home/vagg/.mozilla/firefox/profile.default/user.js

# Confia no CA do mitmproxy. Após mitm gerar o CA em ~/.mitmproxy/, importamos.
# Esperamos o CA aparecer (mitm gera no primeiro request)
for i in 1 2 3 4 5; do
    [ -f /home/vagg/.mitmproxy/mitmproxy-ca-cert.pem ] && break
    sleep 1
done
if [ -f /home/vagg/.mitmproxy/mitmproxy-ca-cert.pem ]; then
    # Adiciona o CA ao trust do firefox
    NSS_DB="sql:/home/vagg/.mozilla/firefox/profile.default"
    mkdir -p "/home/vagg/.mozilla/firefox/profile.default"
    if command -v certutil >/dev/null; then
        certutil -A -n "mitmproxy" -t "C,," \
            -i /home/vagg/.mitmproxy/mitmproxy-ca-cert.pem -d "$NSS_DB" || true
    fi
fi

# 3) Inicia xpra servindo Firefox via HTML5
log "starting xpra on port $VAGG_SAML_PORT pointing to $VAGG_SAML_GATEWAY_URL"
xpra start \
    --bind-tcp=0.0.0.0:$VAGG_SAML_PORT \
    --html=on \
    --start="firefox --new-window '$VAGG_SAML_GATEWAY_URL'" \
    --no-daemon \
    --no-mdns \
    --no-pulseaudio \
    --no-microphone \
    --no-webcam \
    --no-printing \
    --no-notifications \
    --exit-with-children \
    :100 &
XPRA_PID=$!

# 4) Watcher: sai quando cookie é capturado OU timeout
START=$(date +%s)
while true; do
    if [ -s "$VAGG_SAML_COOKIE_OUT" ]; then
        log "cookie captured! shutting down"
        sleep 2  # garante flush
        break
    fi
    if ! kill -0 $XPRA_PID 2>/dev/null; then
        log "xpra exited unexpectedly"
        break
    fi
    NOW=$(date +%s)
    if [ $((NOW - START)) -gt "$VAGG_SAML_TIMEOUT_SEC" ]; then
        log "timeout after ${VAGG_SAML_TIMEOUT_SEC}s"
        break
    fi
    sleep 2
done

kill -TERM $XPRA_PID 2>/dev/null || true
kill -TERM $MITM_PID 2>/dev/null || true
wait
