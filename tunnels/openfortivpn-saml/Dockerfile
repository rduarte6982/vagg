# syntax=docker/dockerfile:1.7
#
# Imagem ESPECIALIZADA pro caminho FortiGate SSL VPN + SAML SSO via Azure AD
# (FortiClient + Microsoft Authenticator MFA).
#
# Como funciona:
#   1. saml-portal (xpra-html5 firefox + mitmproxy) sobe primeiro
#   2. User abre o iframe da UI, navega pelo SAML do gateway dentro do
#      browser remoto, autentica com email/senha + Microsoft Authenticator
#   3. mitmproxy captura o SVPNCOOKIE setado pelo gateway no callback
#   4. Cookie escrito em /share/cookie
#   5. Este container lê o cookie e roda openfortivpn --cookie=...
#   6. Tunnel sobe sem precisar de senha em runtime
#
# Por que Debian trixie: openfortivpn 1.23.1 (vs 1.19 do bookworm) tem
# suporte estável a --cookie e --saml-login. trixie é Debian 13 estável.
#
#   docker build -f tunnels/openfortivpn-saml/Dockerfile \
#                -t vagg/tunnel-openfortivpn-saml:test tunnels/

FROM debian:trixie-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        openfortivpn \
        iproute2 \
        python3 \
        openssl \
        ca-certificates \
        curl \
        jq \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /var/run/vagg /run /share

COPY --chmod=0755 shared/tunnel_controller.py            /usr/local/bin/tunnel-controller
COPY --chmod=0755 openfortivpn-saml/entrypoint.sh        /usr/local/bin/entrypoint

ENV TUNNEL_CONFIG_PATH=/config/tunnel.conf \
    TUNNEL_PASSWORD_FILE=/config/password \
    TUNNEL_OTP_PIPE=/run/otp.pipe \
    TUNNEL_PID_FILE=/run/tunnel.pid \
    TUNNEL_CONTROL_SOCKET=/var/run/vagg/control.sock \
    TUNNEL_MANAGER=openfortivpn \
    TUNNEL_LOG_LEVEL=INFO \
    TUNNEL_SAML_COOKIE_PATH=/share/cookie

VOLUME ["/config", "/var/run/vagg", "/share"]
# Roda como root: openfortivpn precisa de privilégio pra pppd/route;
# NET_ADMIN do compose é o gate principal de segurança.
ENTRYPOINT ["/usr/local/bin/entrypoint"]
