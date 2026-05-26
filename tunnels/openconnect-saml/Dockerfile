# syntax=docker/dockerfile:1.7
#
# Imagem ESPECIALIZADA pro caminho GlobalProtect + SAML (cookie pré-capturado
# pelo saml-portal/mitmproxy). Compilada from source com 2 patches locais
# que NÃO existem no openconnect upstream:
#
#   Patch 1 — host-id:
#     adiciona append_opt(request_body, "host-id", UUID) em login.esp /
#     getconfig.esp. Issue documentado há 6 anos no openconnect (MR !103,
#     issues #629/#272/#574). Sem isso, gateways MS Azure AD via PAN GP
#     (ex: MRV) rejeitam com HTTP 512 "Invalid username or password".
#
#   Patch 2 — VAGG_GP_COOKIE env injection:
#     a) renomeia o form field de cookie pra "vagg_unused" (evita o bug
#        onde --passwd-on-stdin não popula form fields nomeados diferente
#        de "passwd" → POST sai com password=empty).
#     b) injeta append_opt(request_body, "prelogin-cookie", $VAGG_GP_COOKIE)
#        diretamente no body, garantindo que o cookie chega no POST.
#
# Esta imagem é usada APENAS pelo orchestrator quando:
#   - protocol == GLOBALPROTECT
#   - saml_cookie está set
#
# Build context: ``tunnels/`` (copia ``shared/tunnel_controller.py``)::
#
#   docker build -f tunnels/openconnect-saml/Dockerfile -t vagg/tunnel-openconnect-saml:test tunnels/

# ─── Stage 1: build openconnect from source com patches ───
FROM alpine:3.20 AS openconnect-build

ARG OPENCONNECT_VERSION=v9.12

RUN apk add --no-cache \
        build-base \
        autoconf \
        automake \
        libtool \
        pkgconfig \
        git \
        gettext-dev \
        openssl-dev \
        libxml2-dev \
        zlib-dev \
        krb5-dev \
        linux-headers

WORKDIR /src
RUN git clone --depth=1 --branch ${OPENCONNECT_VERSION} \
        https://gitlab.com/openconnect/openconnect.git

# Patch 1: host-id após o append_opt de "computer".
# Mesmo bloco serve pra login.esp E getconfig.esp.
RUN cd openconnect && \
    sed -i '/append_opt(request_body, "computer", vpninfo->localname);/a\        append_opt(request_body, "host-id", "7B5A0E9F-4C2D-4A8E-9B1F-6D3C8E5A2F71");' \
        auth-globalprotect.c

# Patch 2a: rename form field de cookie pra vagg_unused (evita conflito).
RUN cd openconnect && \
    sed -i 's|opt2->type = OC_FORM_OPT_PASSWORD;|{ const char *_vc = getenv("VAGG_GP_COOKIE"); if (_vc \&\& *_vc) { free(opt2->name); opt2->name = strdup("vagg_unused"); opt2->type = OC_FORM_OPT_HIDDEN; opt2->_value = strdup(""); vpn_progress(vpninfo, PRG_INFO, "VAGG: renamed cookie field to vagg_unused (env injection takes over)\\n"); } else { opt2->type = OC_FORM_OPT_PASSWORD; } }|' \
        auth-globalprotect.c

# Patch 2b: injeta cookie direto no request body como prelogin-cookie ou
# portal-userauthcookie (controlado por VAGG_GP_COOKIE_NAME).
# CRÍTICO: só injeta na PRIMEIRA request (portal getconfig.esp OU gateway
# login.esp dependendo do flow). Após primeira, gateway emite cookie próprio
# na resposta e openconnect deve usar ESSE pra requests subsequentes. Se
# reinjetássemos nosso cookie original em /ssl-vpn/login.esp após /global-protect/
# getconfig.esp já ter rolado, gateway rejeita com HTTP 512 (portal cookie
# não é gateway cookie). Gate via static int _vagg_cookie_used.
RUN cd openconnect && \
    sed -i 's|append_opt(request_body, "host-id", "7B5A0E9F-4C2D-4A8E-9B1F-6D3C8E5A2F71");|& { static int _vagg_cookie_used = 0; const char *_vc = getenv("VAGG_GP_COOKIE"); const char *_vu = getenv("VAGG_GP_COOKIE_NAME"); if (_vc \&\& *_vc \&\& !_vagg_cookie_used) { append_opt(request_body, _vu \&\& *_vu ? _vu : "prelogin-cookie", _vc); vpn_progress(vpninfo, PRG_INFO, "VAGG: appended %s=*** (\%zu chars) [first request only]\\n", _vu \&\& *_vu ? _vu : "prelogin-cookie", strlen(_vc)); _vagg_cookie_used = 1; } else if (_vagg_cookie_used) { vpn_progress(vpninfo, PRG_INFO, "VAGG: skipping cookie injection on subsequent request (openconnect uses gateway-issued cookie)\\n"); } }|' \
        auth-globalprotect.c

RUN cd openconnect && \
    ./autogen.sh && \
    ./configure \
        --with-openssl \
        --without-gnutls \
        --disable-nls \
        --without-libpcsclite \
        --without-libpskc \
        --without-stoken \
        --with-vpnc-script=/etc/vpnc/vpnc-script \
        --prefix=/usr/local && \
    make -j$(nproc) && \
    make install-strip && \
    /usr/local/sbin/openconnect --version 2>&1 | head -1

# ─── Stage 2: runtime ───
FROM alpine:3.20

RUN apk add --no-cache \
        vpnc \
        iproute2 \
        iputils \
        python3 \
        openssl \
        libxml2 \
        zlib \
        krb5-libs \
        curl \
    && rm -rf /var/cache/apk/*

COPY --from=openconnect-build /usr/local/sbin/openconnect /usr/local/sbin/openconnect
COPY --from=openconnect-build /usr/local/lib/ /usr/local/lib/
RUN ldconfig /usr/local/lib 2>/dev/null || echo /usr/local/lib > /etc/ld-musl-x86_64.path && \
    ln -sf /usr/local/sbin/openconnect /usr/sbin/openconnect

RUN mkdir -p /var/run/vagg /run

COPY --chmod=0755 shared/tunnel_controller.py            /usr/local/bin/tunnel-controller
COPY --chmod=0755 openconnect-saml/entrypoint.sh         /usr/local/bin/entrypoint
COPY --chmod=0755 openconnect-saml/hip-report.sh         /usr/local/bin/hip-report.sh

ENV TUNNEL_CONFIG_PATH=/config/tunnel.conf \
    TUNNEL_PASSWORD_FILE=/config/password \
    TUNNEL_OTP_PIPE=/run/otp.pipe \
    TUNNEL_PID_FILE=/run/tunnel.pid \
    TUNNEL_CONTROL_SOCKET=/var/run/vagg/control.sock \
    TUNNEL_MANAGER=openconnect \
    TUNNEL_PROTOCOL=gp \
    TUNNEL_LOG_LEVEL=INFO

VOLUME ["/config", "/var/run/vagg"]
ENTRYPOINT ["/usr/local/bin/entrypoint"]
