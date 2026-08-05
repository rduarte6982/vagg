# syntax=docker/dockerfile:1.7
#
# Imagem do tunnel container IPsec (strongSwan) — SPEC §5.2 / Fase 5.
#
#   docker build -f tunnels/strongswan/Dockerfile \
#                -t vagg/tunnel-strongswan:dev tunnels/
#
FROM alpine:3.20

RUN apk add --no-cache \
        strongswan \
        iproute2 \
        python3 \
    && rm -rf /var/cache/apk/*

# strongSwan precisa de root + NET_ADMIN; charon controla XFRM no kernel.
RUN mkdir -p /etc/swanctl /var/run/vagg /run

COPY --chmod=0755 shared/tunnel_controller.py    /usr/local/bin/tunnel-controller
COPY --chmod=0755 strongswan/entrypoint.sh       /usr/local/bin/entrypoint

# TUNNEL_CONFIG_PATH tem de bater com o que o orchestrator grava
# (_stage_config escreve sempre /config/tunnel.conf, igual aos demais tunnels).
# O entrypoint faz o symlink p/ /etc/swanctl/swanctl.conf.
ENV TUNNEL_CONFIG_PATH=/config/tunnel.conf \
    TUNNEL_OTP_PIPE=/run/otp.pipe \
    TUNNEL_CONTROL_SOCKET=/var/run/vagg/control.sock \
    TUNNEL_MANAGER=strongswan \
    TUNNEL_LOG_LEVEL=INFO

VOLUME ["/config", "/var/run/vagg"]
ENTRYPOINT ["/usr/local/bin/entrypoint"]
