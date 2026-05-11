#!/usr/bin/with-contenv sh
# Service s6 que roda o mitmproxy headless dentro do container saml-portal.
# É iniciado em paralelo com o firefox (que tem proxy=127.0.0.1:8080
# configurado via /defaults/user.js).
set -eu

GATEWAY_HOST=$(echo "${VAGG_SAML_GATEWAY_URL:-}" | sed -E 's#^https?://([^/]+).*#\1#')

exec mitmdump -q --listen-port 8080 --set ssl_insecure=true \
    -s /usr/local/share/cookie_addon.py \
    --set "vagg_cookie_out=${VAGG_SAML_COOKIE_OUT:-/share/cookie}" \
    --set "vagg_gateway_host=${GATEWAY_HOST}"
