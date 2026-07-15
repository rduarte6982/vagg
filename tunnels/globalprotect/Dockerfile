# syntax=docker/dockerfile:1.7
#
# Imagem do tunnel container pra clientes GlobalProtect com SAML estrito
# (gateways MS Azure AD que rejeitam openconnect 9.x). Usa yuezk/gpclient,
# cliente GP nativo Rust (https://github.com/yuezk/GlobalProtect-openconnect)
# que sabe lidar com requests que openconnect não consegue replicar.
#
# Build context: ``tunnels/`` (copia ``shared/tunnel_controller.py``)::
#
#   docker build -f tunnels/globalprotect/Dockerfile -t vagg/tunnel-globalprotect:test tunnels/
#
FROM debian:bookworm-slim

ARG GPCLIENT_VERSION=2.5.1

# Deps:
# - openconnect — gpclient usa internamente pra estabelecer o tunel
# - iproute2 — ip route/addr usado pelo vpnc-script
# - vpnc-scripts — provê /etc/vpnc/vpnc-script
# - python3 — tunnel-controller
# - curl + ca-certs — pra baixar o .deb e pro preflight diagnostic
# - libwebkit2gtk-4.1-0 + xvfb — gpclient pode precisar abrir webview;
#   minimal install pra suporte mesmo no modo CLI
RUN apt-get update && apt-get install -y --no-install-recommends \
        openconnect \
        vpnc-scripts \
        iproute2 \
        iputils-ping \
        python3 \
        ca-certificates \
        curl \
        libwebkit2gtk-4.1-0 \
        xvfb \
        dbus-x11 \
    && rm -rf /var/lib/apt/lists/*

# Detecta arch e baixa o .deb correto do yuezk/GlobalProtect-openconnect.
# Usa BuildKit TARGETARCH (amd64 ou arm64). apt install ./pkg.deb
# resolve deps automaticamente (vs dpkg -i + apt -f que pode remover).
ARG TARGETARCH=amd64
RUN apt-get update \
    && curl -fsSL -o /tmp/gpclient.deb \
        "https://github.com/yuezk/GlobalProtect-openconnect/releases/download/v${GPCLIENT_VERSION}/globalprotect-openconnect_${GPCLIENT_VERSION}-1_${TARGETARCH}.deb" \
    && apt-get install -y --no-install-recommends /tmp/gpclient.deb \
    && rm -f /tmp/gpclient.deb \
    && rm -rf /var/lib/apt/lists/* \
    && which gpclient \
    && gpclient --version

# Container roda como root porque openconnect precisa de NET_ADMIN.
RUN mkdir -p /var/run/vagg /run

COPY --chmod=0755 shared/tunnel_controller.py    /usr/local/bin/tunnel-controller
COPY --chmod=0755 globalprotect/entrypoint.sh    /usr/local/bin/entrypoint

ENV TUNNEL_CONFIG_PATH=/config/tunnel.conf \
    TUNNEL_PASSWORD_FILE=/config/password \
    TUNNEL_OTP_PIPE=/run/otp.pipe \
    TUNNEL_PID_FILE=/run/tunnel.pid \
    TUNNEL_CONTROL_SOCKET=/var/run/vagg/control.sock \
    TUNNEL_MANAGER=gpclient \
    TUNNEL_LOG_LEVEL=INFO

VOLUME ["/config", "/var/run/vagg"]
ENTRYPOINT ["/usr/local/bin/entrypoint"]
