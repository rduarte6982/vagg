# syntax=docker/dockerfile:1.7
#
# Imagem do tunnel container para clientes que usam OpenVPN (SPEC §5.2).
#
# Build context: a pasta ``tunnels/`` (não ``tunnels/openvpn/``), pra poder
# copiar ``shared/tunnel_controller.py``::
#
#   docker build -f tunnels/openvpn/Dockerfile -t vagg/tunnel-openvpn:dev tunnels/
#
FROM alpine:3.20

RUN apk add --no-cache \
        openvpn \
        iproute2 \
        python3 \
    && rm -rf /var/cache/apk/*

# Non-root user. ``openvpn`` precisa de NET_ADMIN no namespace, mas isso é
# concedido via ``--cap-add NET_ADMIN`` pelo orchestrator — não exigimos root.
RUN addgroup -S vagg \
    && adduser -S -G vagg -h /home/vagg vagg \
    && mkdir -p /var/run/vagg \
    && chown -R vagg:vagg /var/run/vagg

COPY --chmod=0755 shared/tunnel_controller.py /usr/local/bin/tunnel-controller
COPY --chmod=0755 openvpn/entrypoint.sh       /usr/local/bin/entrypoint

# Caminhos default — orchestrator pode sobrescrever via env.
ENV TUNNEL_CONFIG_PATH=/config/tunnel.conf \
    TUNNEL_PASSWORD_FILE=/config/password \
    TUNNEL_OTP_PIPE=/run/otp.pipe \
    TUNNEL_CONTROL_SOCKET=/var/run/vagg/control.sock \
    TUNNEL_OPENVPN_MGMT_SOCKET=/var/run/openvpn-mgmt.sock \
    TUNNEL_LOG_LEVEL=INFO

VOLUME ["/config", "/var/run/vagg"]
USER vagg
ENTRYPOINT ["/usr/local/bin/entrypoint"]
