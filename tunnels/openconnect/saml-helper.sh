#!/bin/sh
# vagg-saml-helper — fake external-browser pro openconnect.
#
# Quando o gateway GP exige SAML obrigatório, openconnect chama este helper
# com a URL do IdP. Em vez de abrir browser real, devolvemos o cookie já
# capturado externamente (no DevTools do user) via stdout no formato que o
# openconnect espera.
#
# Espera env vars:
#   TUNNEL_SAML_COOKIE = "prelogin-cookie=VALUE" ou "portal-userauthcookie=VALUE"
#
# Formato esperado pelo openconnect (ver source: external-browser.c):
#   stdout linhas:
#     URL\n          ← echo da URL recebida (ack)
#     COOKIE\n       ← prefixo
#     <cookie_str>\n ← o cookie no formato "name=value"
set -eu

URL="${1:-}"

# ack da URL (alguns helpers retornam isso)
echo "$URL"

# devolve o cookie pré-capturado
if [ -n "${TUNNEL_SAML_COOKIE:-}" ]; then
    echo "COOKIE"
    echo "$TUNNEL_SAML_COOKIE"
fi
