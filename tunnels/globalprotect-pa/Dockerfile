# syntax=docker/dockerfile:1.7
#
# Imagem do tunnel container usando o cliente OFICIAL Palo Alto GlobalProtect
# Linux 6.1.2 (.deb fornecido pela MRV via licença).
#
# Componentes principais (instalados em /opt/paloaltonetworks/globalprotect/):
#   - PanGPS: daemon que estabelece o túnel e mantém estado
#   - globalprotect: CLI que conversa com PanGPS via socket local
#   - PanGpHip: gera HIP report (Host Information Profile)
#
# Build context: tunnels/  (porque copia shared/tunnel_controller.py).
#
#   docker build -f tunnels/globalprotect-pa/Dockerfile -t vagg/tunnel-globalprotect-pa:test tunnels/

FROM debian:bookworm-slim

# Deps:
# - libstdc++6, libc6: já em base, mas explícito
# - net-tools, iproute2, iputils-ping: rede
# - python3: tunnel-controller
# - curl + ca-certs: diagnóstico
# - libnss3, libgconf-2-4: bibliotecas que GP/PanGPS pode precisar (kerberos, nss)
# - dbus: gpa.service usa dbus
RUN apt-get update && apt-get install -y --no-install-recommends \
        libstdc++6 \
        libc6 \
        net-tools \
        iproute2 \
        iputils-ping \
        python3 \
        ca-certificates \
        curl \
        libnss3 \
        dbus \
        dmidecode \
        iptables \
        kmod \
        procps \
    && rm -rf /var/lib/apt/lists/*

# Instala o .deb oficial PA. Copiamos via build context — o .deb foi
# colocado pela MRV em instalador/paloalto/ e replicado em tunnels/globalprotect-pa/.
COPY globalprotect-pa/GlobalProtect.deb /tmp/gp.deb
RUN dpkg -i /tmp/gp.deb || apt-get install -y -f --no-install-recommends \
    && rm -f /tmp/gp.deb \
    && rm -rf /var/lib/apt/lists/* \
    && ls /opt/paloaltonetworks/globalprotect/ | head -10

# PATH pra incluir o binário globalprotect
ENV PATH="/opt/paloaltonetworks/globalprotect:${PATH}"

# Wrapper pro `ps` que sempre mostra cmdline completo (via -o args).
# Sem isso, default `ps -U root` mostra só "PanGPS" sem path — grep
# por "globalprotect" não match.
RUN mv /usr/bin/ps /usr/bin/ps.real && \
    printf '#!/bin/sh\nexec /usr/bin/ps.real -o pid,tty,time,args "$@"\n' > /usr/bin/ps && \
    chmod +x /usr/bin/ps

# Renomeia (cria copy via cp + chmod) o CLI pra "gpcli" — assim quando
# chamamos `gpcli connect`, o cmdline é `/opt/.../gpcli ...` sem
# "globalprotect", evitando que `ps | grep globalprotect` conte ele.
RUN cp /opt/paloaltonetworks/globalprotect/globalprotect /opt/paloaltonetworks/globalprotect/gpcli \
    && chmod +x /opt/paloaltonetworks/globalprotect/gpcli

# Container roda como root (precisa NET_ADMIN pra criar tun).
# Mas CLI globalprotect deve rodar como user normal pra evitar bug onde
# CLI faz `ps -U $USER | grep globalprotect` e acha daemon (rodando como
# root) na lista, achando que há "outra conexão".
RUN useradd -m -u 1500 -s /bin/bash gpuser \
    && mkdir -p /var/run/vagg /run

COPY --chmod=0755 shared/tunnel_controller.py     /usr/local/bin/tunnel-controller
COPY --chmod=0755 globalprotect-pa/entrypoint.sh  /usr/local/bin/entrypoint

ENV TUNNEL_CONFIG_PATH=/config/tunnel.conf \
    TUNNEL_PASSWORD_FILE=/config/password \
    TUNNEL_OTP_PIPE=/run/otp.pipe \
    TUNNEL_PID_FILE=/run/tunnel.pid \
    TUNNEL_CONTROL_SOCKET=/var/run/vagg/control.sock \
    TUNNEL_MANAGER=globalprotect \
    TUNNEL_LOG_LEVEL=INFO

VOLUME ["/config", "/var/run/vagg"]
ENTRYPOINT ["/usr/local/bin/entrypoint"]
