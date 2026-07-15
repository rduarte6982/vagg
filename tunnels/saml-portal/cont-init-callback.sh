#!/bin/sh
# /etc/cont-init.d/92-saml-callback.sh — sobe o saml_callback.py em background.
#
# Esse servidor escuta em 127.0.0.1:8020 e implementa o "redirect SAML" que
# o openfortivpn usa nativamente. Quando o user completa o login Microsoft
# no Firefox, o FortiGate redireciona o browser pra
#   http://127.0.0.1:8020/?id=<session>
# Este servidor extrai o session-id, troca por SVPNCOOKIE no gateway via
# /remote/saml/auth_id, e grava em /share/cookie.
#
# Necessário pra gateways FortiGate com hostcheck habilitado, que devolvem
# 403 quando o callback SAML é acessado por browser puro. O `?redirect=1`
# no /remote/saml/start é o que ativa esse fluxo no gateway — sem isso,
# ele tenta hostcheck e 403.
set -eu

GATEWAY="${VAGG_SAML_GATEWAY_URL:-}"
COOKIE_OUT="${VAGG_SAML_COOKIE_OUT:-/share/cookie}"
LOG=/share/callback.log

mkdir -p "$(dirname "$COOKIE_OUT")" /share
chmod 777 /share 2>/dev/null || true

# Só sobe pra modo forti — o GP tem fluxo próprio (cookie_addon faz tudo).
KIND="${VAGG_SAML_KIND:-gp}"
if [ "$KIND" != "forti" ]; then
    echo "[vagg-callback] skipped (kind=$KIND, not 'forti')" >> "$LOG"
    # Pra GP: limpa HSTS/HPKP cache + adiciona prefs anti-pinning.
    # Gateway PA tipo MRV tem HPKP que Firefox lembra; mitmproxy intercepta
    # com cert forjado → Firefox bloqueia com SEC_ERROR_BAD_SIGNATURE.
    # Solução: zerar pinning state + desabilitar cert pinning enforcement.
    PROFILE_DIR=/config/profile
    if [ -d "$PROFILE_DIR" ] && [ -f "$PROFILE_DIR/user.js" ]; then
        cat >> "$PROFILE_DIR/user.js" <<'EOF'
user_pref("security.cert_pinning.enforcement_level", 0);
user_pref("security.cert_pinning.process_headers_from_non_builtin_roots", false);
user_pref("network.stricttransportsecurity.preloadlist", false);
user_pref("browser.xul.error_pages.expert_bad_cert", true);
EOF
        rm -f "$PROFILE_DIR/SiteSecurityServiceState.bin" 2>/dev/null || true
        rm -f "$PROFILE_DIR/SecurityPreloadState.bin" 2>/dev/null || true
        chown -R 1000:1000 "$PROFILE_DIR" 2>/dev/null || true
        echo "[vagg-callback] GP anti-HPKP prefs added + HSTS state cleared" >> "$LOG"
    fi
    exit 0
fi

# Modo embarcado: quando o saml-portal sobe AO LADO de um tunnel container
# que já roda openfortivpn --saml-login=8020 em network=host (mesmo loopback),
# o openfortivpn é quem escuta :8020 e faz o exchange — não precisamos do
# saml_callback aqui (ele só conflitaria pela porta).
#
# Também limpa session restore do Firefox aqui pra garantir que o profile
# vai usar FF_OPEN_URL na próxima inicialização (sessão anterior persistente
# sobrescreve a URL inicial).
if [ "${VAGG_SAML_DISABLE_CALLBACK:-0}" = "1" ]; then
    echo "[vagg-callback] disabled (VAGG_SAML_DISABLE_CALLBACK=1; openfortivpn embedded handles :8020)" >> "$LOG"
    # Limpa profile INTEIRO do Firefox pra garantir abertura limpa em FF_OPEN_URL.
    # Sem isso, sessionstore* + cookies de uma execução anterior fazem o Firefox
    # restaurar tab antiga ou ficar em about:blank, ignorando FF_OPEN_URL.
    rm -rf /config/profile 2>/dev/null || true
    mkdir -p /config/profile 2>/dev/null || true
    # Cria user.js mínimo aceitando proxy + desabilitando session restore.
    # O cont-init 56-firefox-set-prefs-from-env.sh roda DEPOIS e adiciona prefs
    # vindos de FF_PREF_* envs em cima desse.
    cat > /config/profile/user.js <<'EOF'
user_pref("browser.sessionstore.resume_from_crash", false);
user_pref("browser.sessionstore.max_resumed_crashes", 0);
user_pref("toolkit.startup.max_resumed_crashes", -1);
user_pref("browser.startup.page", 0);
user_pref("browser.shell.checkDefaultBrowser", false);
user_pref("browser.tabs.warnOnClose", false);
user_pref("datareporting.policy.firstRunURL", "");
user_pref("toolkit.telemetry.reportingpolicy.firstRun", false);
user_pref("security.enterprise_roots.enabled", true);
EOF
    chown -R 1000:1000 /config/profile 2>/dev/null || true
    echo "[vagg-callback] Firefox profile cleaned + seeded with anti-resume prefs" >> "$LOG"
    exit 0
fi

if [ -z "$GATEWAY" ]; then
    echo "[vagg-callback] VAGG_SAML_GATEWAY_URL vazio — não inicia" >> "$LOG"
    exit 0
fi

echo "[vagg-callback] starting on 127.0.0.1:8020 gateway=$GATEWAY" >> "$LOG"

# Roda como root pra poder escrever em /share — não importa segurança aqui
# porque o container é descartado após captura. nohup + setsid pra
# sobreviver ao cont-init terminar.
nohup setsid python3 /usr/local/share/saml_callback.py \
    >> "$LOG" 2>&1 &

# Espera porta abrir (até 10s)
i=0
while [ $i -lt 10 ]; do
    if (echo > /dev/tcp/127.0.0.1/8020) 2>/dev/null; then
        echo "[vagg-callback] listening on :8020" >> "$LOG"
        exit 0
    fi
    sleep 1
    i=$((i+1))
done
echo "[vagg-callback] WARN: did not bind :8020 in 10s" >> "$LOG"
exit 0  # não bloqueia o boot — sem callback, cookie_addon ainda pode pegar
