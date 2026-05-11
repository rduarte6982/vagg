#!/bin/sh
# Service s6 dentro do jlesage/firefox: roda o mitmproxy headless capturando
# cookies SAML no tráfego do Firefox.
set -eu

GATEWAY="${VAGG_SAML_GATEWAY_URL:-https://example.com}"
COOKIE_OUT="${VAGG_SAML_COOKIE_OUT:-/share/cookie}"
GATEWAY_HOST=$(echo "$GATEWAY" | sed -E 's#^https?://([^/]+).*#\1#')

mkdir -p "$(dirname "$COOKIE_OUT")"

# inicia mitmproxy
exec mitmdump -q --listen-port 8080 --set ssl_insecure=true \
    -s /usr/local/share/cookie_addon.py \
    --set "vagg_cookie_out=$COOKIE_OUT" \
    --set "vagg_gateway_host=$GATEWAY_HOST"
