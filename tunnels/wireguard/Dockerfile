# syntax=docker/dockerfile:1.7
#
# Imagem do tunnel container WireGuard® (SPEC §5.2 / Fase 5).
#
#   docker build -f tunnels/wireguard/Dockerfile -t vagg/tunnel-wireguard:dev tunnels/
#
FROM alpine:3.20

RUN apk add --no-cache \
        wireguard-tools \
        iproute2 \
        python3 \
    && rm -rf /var/cache/apk/*

# wg-quick precisa rodar como root no container (executa ip-link, ip-addr...).
# Cap NET_ADMIN é concedida pelo orchestrator. Não criamos user vagg aqui.
RUN mkdir -p /etc/wireguard /var/run/vagg /run

COPY --chmod=0755 shared/tunnel_controller.py    /usr/local/bin/tunnel-controller
COPY --chmod=0755 wireguard/entrypoint.sh        /usr/local/bin/entrypoint

ENV TUNNEL_CONFIG_PATH=/config/tunnel.conf \
    TUNNEL_CONTROL_SOCKET=/var/run/vagg/control.sock \
    TUNNEL_MANAGER=wireguard \
    TUNNEL_LOG_LEVEL=INFO

VOLUME ["/config", "/var/run/vagg"]
ENTRYPOINT ["/usr/local/bin/entrypoint"]
