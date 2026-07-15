# syntax=docker/dockerfile:1.7
#
# vagg-saml-portal — browser remoto pra autenticação SAML.
#
# Base: jlesage/firefox — Firefox + TigerVNC + noVNC (canvas + websocket).
# Diferente do linuxserver/firefox (que usa Selkies/WebCodecs e exige HTTPS
# com cert TRUSTED), o noVNC do jlesage funciona em HTTP plano e/ou cert
# self-signed sem problemas — secure context não é requerido.
#
# Adicionamos mitmproxy em cima pra capturar cookies SAML quando o user
# terminar o login.

FROM jlesage/firefox:v25.04.1

USER root

# mitmproxy do repo community do Alpine (sem precisar compilar).
# nss-tools traz `certutil` pra adicionar o CA do mitmproxy ao trust store
# do Firefox (NSS sql:). su-exec drop privileges em scripts cont-init que
# rodam como root mas precisam executar como user app (uid 1000).
RUN apk add --no-cache mitmproxy ca-certificates nss-tools su-exec \
    && rm -rf /var/cache/apk/*

RUN mkdir -p /share && chmod 777 /share

# Diretório de trabalho do mitmproxy (CA + sessões). HOME do user app é
# /dev/null, então mitmproxy precisa de um confdir explícito.
RUN mkdir -p /opt/vagg-mitm /var/log/vagg-mitm && \
    chown -R 1000:1000 /opt/vagg-mitm /var/log/vagg-mitm

# Python3 — usado pelo saml_callback.py (server local 127.0.0.1:8020 que
# implementa o redirect openfortivpn-style pra bypass de hostcheck FortiGate)
RUN apk add --no-cache python3 \
    && rm -rf /var/cache/apk/*

# Cookie addon do mitmproxy
COPY --chmod=0644 saml-portal/cookie_addon.py /usr/local/share/cookie_addon.py

# Callback HTTP server local — bypass de hostcheck FortiGate (openfortivpn-style)
COPY --chmod=0755 saml-portal/saml_callback.py /usr/local/share/saml_callback.py

# /etc/cont-init.d/ é extension point oficial do jlesage — scripts aqui
# rodam UMA VEZ antes dos serviços (Firefox/X11/nginx) subirem. Ideal pra
# iniciar mitmproxy + callback server como daemons background.
COPY --chmod=0755 saml-portal/cont-init-mitm.sh /etc/cont-init.d/90-vagg-mitm.sh

# Confia no CA do mitmproxy via certutil dentro do profile do Firefox
COPY --chmod=0755 saml-portal/firefox-init.sh /etc/cont-init.d/91-firefox-mitm.sh

# Callback server pra bypass do hostcheck FortiGate (modo forti only)
COPY --chmod=0755 saml-portal/cont-init-callback.sh /etc/cont-init.d/92-vagg-callback.sh

ENV VAGG_SAML_GATEWAY_URL="" \
    VAGG_SAML_COOKIE_OUT="/share/cookie" \
    VAGG_SAML_TIMEOUT_SEC="1200" \
    APP_NAME="VAGG SAML Portal" \
    DARK_MODE=1 \
    WEB_LISTENING_PORT=14500 \
    KEEP_APP_RUNNING=1 \
    DISPLAY_WIDTH=1280 \
    DISPLAY_HEIGHT=800 \
    SECURE_CONNECTION=0

EXPOSE 14500
