#!/usr/bin/env bash
# setup.sh — inicializa o servidor OpenVPN do lab e gera client.ovpn.
#
# Idempotente: já existindo PKI, só re-emite o client.ovpn (a menos que --reset).
#
# Uso:
#   ./setup.sh                 # primeira vez: cria PKI, configura, gera client.ovpn
#   ./setup.sh --reset         # joga fora a PKI antiga e refaz tudo
#   ./setup.sh --serve-host X  # IP/host externo que o cliente OpenVPN vai usar
#                                (default: detectar IP da máquina; em WSL2 use o
#                                 IP da WSL acessível pela LAN)

set -Eeuo pipefail
cd "$(dirname "$0")"

CLIENT_NAME="${CLIENT_NAME:-consultor}"
SERVE_HOST=""
RESET=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --reset) RESET=1; shift ;;
    --serve-host) SERVE_HOST="$2"; shift 2 ;;
    --client-name) CLIENT_NAME="$2"; shift 2 ;;
    *) echo "argumento desconhecido: $1" >&2; exit 2 ;;
  esac
done

if [[ -z "$SERVE_HOST" ]]; then
  # Tenta IP da LAN. Funciona em Linux/macOS; em WSL prefira passar --serve-host
  # com o IP da WSL: `ip route show default | awk '{print $3}'` ou hostname -I
  SERVE_HOST="$(hostname -I 2>/dev/null | awk '{print $1}')"
  [[ -z "$SERVE_HOST" ]] && SERVE_HOST="127.0.0.1"
fi

echo "→ servidor OpenVPN será publicado em udp://$SERVE_HOST:1194"

if [[ $RESET -eq 1 ]]; then
  echo "→ resetando volumes (apaga PKI)…"
  docker compose down -v 2>/dev/null || true
  rm -f client.ovpn
fi

# Inicializa PKI se ainda não existir
if ! docker volume inspect vagg-lab-vpn_ovpn_data >/dev/null 2>&1; then
  echo "→ criando volume e inicializando PKI…"
  docker volume create vagg-lab-vpn_ovpn_data >/dev/null
fi

# Detecta se a config já está populada
if ! docker run --rm -v vagg-lab-vpn_ovpn_data:/etc/openvpn kylemanna/openvpn:2.4 \
       test -f /etc/openvpn/openvpn.conf 2>/dev/null; then
  echo "→ ovpn_genconfig: subnet 192.168.99.0/24, push de rotas…"
  docker run --rm -v vagg-lab-vpn_ovpn_data:/etc/openvpn kylemanna/openvpn:2.4 \
    ovpn_genconfig \
      -u "udp://$SERVE_HOST:1194" \
      -s 10.99.0.0/24 \
      -p "route 192.168.99.0 255.255.255.0" \
      -d   # disable DNS push (vagg cuida do DNS)

  echo "→ ovpn_initpki (sem senha — laboratório, NÃO usar em prod)"
  docker run --rm -i -v vagg-lab-vpn_ovpn_data:/etc/openvpn -e EASYRSA_BATCH=1 \
    kylemanna/openvpn:2.4 ovpn_initpki nopass <<'EOF'
vagg-lab-ca
EOF
fi

# Cria o cliente (idempotente — kylemanna usa easyrsa que dá erro se já existe)
if ! docker run --rm -v vagg-lab-vpn_ovpn_data:/etc/openvpn kylemanna/openvpn:2.4 \
       test -f "/etc/openvpn/pki/issued/$CLIENT_NAME.crt" 2>/dev/null; then
  echo "→ gerando certificado do cliente '$CLIENT_NAME'…"
  docker run --rm -v vagg-lab-vpn_ovpn_data:/etc/openvpn -e EASYRSA_BATCH=1 \
    kylemanna/openvpn:2.4 easyrsa build-client-full "$CLIENT_NAME" nopass
fi

echo "→ exportando client.ovpn"
docker run --rm -v vagg-lab-vpn_ovpn_data:/etc/openvpn kylemanna/openvpn:2.4 \
  ovpn_getclient "$CLIENT_NAME" > client.ovpn

echo "→ subindo a stack…"
docker compose up -d

echo
echo "✓ Pronto."
echo
echo "Servidor OpenVPN: udp://$SERVE_HOST:1194"
echo "Cliente .ovpn:    $(pwd)/client.ovpn"
echo "Recurso interno:  http://192.168.99.10  (só visível após VPN conectada)"
echo
echo "Próximo: cadastrar este cliente no painel do vagg colando o conteúdo"
echo "de client.ovpn no campo 'Configuração do túnel'."
echo "  - vpn_type:     openvpn"
echo "  - virtual_cidr: 10.200.99.0/24"
echo "  - real_cidr:    192.168.99.0/24"
echo "  - dns_server:   (em branco)"
