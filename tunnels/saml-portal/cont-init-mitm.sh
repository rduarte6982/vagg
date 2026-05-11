#!/bin/sh
# /etc/cont-init.d/90-vagg-mitm.sh — inicia mitmproxy como daemon background
# antes do Firefox subir. Captura o tráfego do gateway VPN e grava o cookie
# em $VAGG_SAML_COOKIE_OUT quando detecta SAML success.
#
# Não retorna até o mitmproxy estar de fato escutando — assim o Firefox que
# sobe depois já encontra o proxy disponível.
set -eu

GATEWAY="${VAGG_SAML_GATEWAY_URL:-https://example.com}"
COOKIE_OUT="${VAGG_SAML_COOKIE_OUT:-/share/cookie}"
GATEWAY_HOST=$(printf '%s\n' "$GATEWAY" | sed -E 's#^https?://([^/]+).*#\1#')
# vagg_kind: 'gp' (GlobalProtect/PA) ou 'forti' (FortiGate SVPNCOOKIE).
# Default gp pra preservar comportamento legado.
KIND="${VAGG_SAML_KIND:-gp}"
# Log no /share pra sobreviver após o container ser deletado pelo orchestrator.
LOG=/share/mitm.log

mkdir -p "$(dirname "$COOKIE_OUT")"
mkdir -p /opt/vagg-mitm /var/log/vagg-mitm /share
# garante perms pro user app (uid 1000) escrever cert + log + cookie
chown -R 1000:1000 /opt/vagg-mitm /var/log/vagg-mitm "$(dirname "$COOKIE_OUT")" /share 2>/dev/null || true

echo "[vagg-mitm] starting on :8080 — gateway_host=$GATEWAY_HOST kind=$KIND out=$COOKIE_OUT" >> "$LOG"

# nohup + setsid pra desanexar do PID 1 do cont-init e virar daemon real
# que sobrevive ao supervisor de serviços.
HOME=/opt/vagg-mitm \
nohup su-exec 1000:1000 env HOME=/opt/vagg-mitm \
    mitmdump \
        --listen-port 8080 \
        --set ssl_insecure=true \
        --set "confdir=/opt/vagg-mitm/.mitmproxy" \
        -s /usr/local/share/cookie_addon.py \
        --set "vagg_cookie_out=$COOKIE_OUT" \
        --set "vagg_gateway_host=$GATEWAY_HOST" \
        --set "vagg_kind=$KIND" \
    >> "$LOG" 2>&1 &

# Espera o mitmproxy abrir a porta 8080. timeout 15s — suficiente pro
# primeiro start gerar o CA. Sem isso o Firefox sobe antes e não consegue
# proxy HTTPS.
i=0
while [ $i -lt 15 ]; do
    if (echo > /dev/tcp/127.0.0.1/8080) 2>/dev/null; then
        echo "[vagg-mitm] proxy ready on :8080" >> "$LOG"
        # Espera o CA cert ser gerado
        ca=/opt/vagg-mitm/.mitmproxy/mitmproxy-ca-cert.pem
        j=0
        while [ $j -lt 10 ] && [ ! -f "$ca" ]; do
            sleep 1
            j=$((j+1))
        done
        if [ -f "$ca" ]; then
            echo "[vagg-mitm] CA cert generated at $ca" >> "$LOG"
        else
            echo "[vagg-mitm] WARN: CA cert not generated yet" >> "$LOG"
        fi
        exit 0
    fi
    sleep 1
    i=$((i+1))
done
echo "[vagg-mitm] FAIL: proxy did not come up in 15s" >> "$LOG"
exit 0  # não bloqueia o boot do container; sem proxy a tela ainda funciona
