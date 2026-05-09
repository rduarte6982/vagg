# syntax=docker/dockerfile:1.7
#
# Imagem do tunnel container para clientes Fortinet SSL VPN
# (FortiClient compat) — SPEC §5.2 / Fase 5.
#
#   docker build -f tunnels/openfortivpn/Dockerfile \
#                -t vagg/tunnel-openfortivpn:dev tunnels/
#
# Por que Debian 12: Alpine removeu o pacote ``openfortivpn`` dos repos em
# 2026 (3.20+). Debian mantém o pacote via apt e tem suporte estável.
FROM debian:12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        openfortivpn \
        iproute2 \
        python3 \
        openssl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /var/run/vagg /run

COPY --chmod=0755 shared/tunnel_controller.py    /usr/local/bin/tunnel-controller
COPY --chmod=0755 openfortivpn/entrypoint.sh     /usr/local/bin/entrypoint

ENV TUNNEL_CONFIG_PATH=/config/tunnel.conf \
    TUNNEL_PASSWORD_FILE=/config/password \
    TUNNEL_OTP_PIPE=/run/otp.pipe \
    TUNNEL_PID_FILE=/run/tunnel.pid \
    TUNNEL_CONTROL_SOCKET=/var/run/vagg/control.sock \
    TUNNEL_MANAGER=openfortivpn \
    TUNNEL_LOG_LEVEL=INFO

VOLUME ["/config", "/var/run/vagg"]
# Roda como root porque openfortivpn precisa de privilégio pra pppd/route.
# A cap NET_ADMIN do compose ainda é o gate principal de segurança.
ENTRYPOINT ["/usr/local/bin/entrypoint"]
