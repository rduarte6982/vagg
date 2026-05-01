# syntax=docker/dockerfile:1.7
#
# Imagem do tunnel container para clientes que usam OpenConnect-compatíveis
# (Cisco AnyConnect, Palo Alto GlobalProtect — SPEC §5.2 / Fase 5).
#
# Build context: ``tunnels/`` (copia ``shared/tunnel_controller.py``)::
#
#   docker build -f tunnels/openconnect/Dockerfile -t vagg/tunnel-openconnect:dev tunnels/
#
FROM alpine:3.20

RUN apk add --no-cache \
        openconnect \
        iproute2 \
        python3 \
    && rm -rf /var/cache/apk/*

# Não-root user; cap NET_ADMIN concedida no `docker run --cap-add` pelo orchestrator.
RUN addgroup -S vagg \
    && adduser -S -G vagg -h /home/vagg vagg \
    && mkdir -p /var/run/vagg /run \
    && chown -R vagg:vagg /var/run/vagg /run

COPY --chmod=0755 shared/tunnel_controller.py    /usr/local/bin/tunnel-controller
COPY --chmod=0755 openconnect/entrypoint.sh      /usr/local/bin/entrypoint

ENV TUNNEL_CONFIG_PATH=/config/tunnel.conf \
    TUNNEL_PASSWORD_FILE=/config/password \
    TUNNEL_OTP_PIPE=/run/otp.pipe \
    TUNNEL_PID_FILE=/run/tunnel.pid \
    TUNNEL_CONTROL_SOCKET=/var/run/vagg/control.sock \
    TUNNEL_MANAGER=openconnect \
    TUNNEL_LOG_LEVEL=INFO

VOLUME ["/config", "/var/run/vagg"]
USER vagg
ENTRYPOINT ["/usr/local/bin/entrypoint"]
