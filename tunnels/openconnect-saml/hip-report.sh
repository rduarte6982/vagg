#!/bin/sh
# hip-report.sh — wrapper de HIP report pro openconnect contra PaloAlto GP.
#
# Acionado via --csd-wrapper=/usr/local/bin/hip-report.sh.
# openconnect passa estes args (gpst.c::run_hip_script):
#   --cookie <auth-cookie>
#   --client-ip <ipv4-do-tunnel>
#   --client-ipv6 <ipv6-do-tunnel>   (opcional)
#   --md5 <token>                     ← o gateway pediu esse exato md5 no warning
#   --client-os Linux|Mac|Windows
#
# stdout vai pro POST /ssl-vpn/hipreport.esp. PaloAlto:
#   - VALIDA <md5-sum> ESTRITAMENTE igual ao token (echo o que ele pediu)
#   - NÃO recomputa md5 do XML
#   - NÃO valida o conteúdo das categorias (a menos que policies HIP-objects
#     específicas requeiram). Categorias mínimas + spoof de Windows costuma
#     bastar pra liberar ACL completo (dlenski/openconnect #350, #470).
#
# Limpa stderr — qualquer ruído quebra o body que openconnect captura.

set -e

COOKIE=""
IP=""
IP6=""
MD5=""
COS=""
while [ $# -gt 0 ]; do
    case "$1" in
        --cookie)      COOKIE=$2; shift 2 ;;
        --client-ip)   IP=$2; shift 2 ;;
        --client-ipv6) IP6=$2; shift 2 ;;
        --md5)         MD5=$2; shift 2 ;;
        --client-os)   COS=$2; shift 2 ;;
        *)             shift ;;
    esac
done

# Extrai user/domain/computer do cookie (fields URL-encoded user= domain= computer=)
USER=$(printf '%s' "$COOKIE" | sed -n 's/.*user=\([^&]*\).*/\1/p')
DOMAIN=$(printf '%s' "$COOKIE" | sed -n 's/.*domain=\([^&]*\).*/\1/p')
COMPUTER=$(printf '%s' "$COOKIE" | sed -n 's/.*computer=\([^&]*\).*/\1/p')
[ -z "$COMPUTER" ] && COMPUTER=$(hostname 2>/dev/null || echo vagg-client)
[ -z "$USER" ]     && USER="vagg-user"

NOW=$(date -u '+%m/%d/%Y %H:%M:%S')
# Host UUID determinístico do hostname (mesmo container = mesmo UUID)
HOSTID="00000000-0000-0000-0000-$(printf '%s' "$COMPUTER" | md5sum | cut -c1-12)"

cat <<HIP
<hip-report name="hip-report">
<md5-sum>$MD5</md5-sum>
<user-name>$USER</user-name>
<domain>$DOMAIN</domain>
<host-name>$COMPUTER</host-name>
<host-id>$HOSTID</host-id>
<ip-address>$IP</ip-address>
<ipv6-address>$IP6</ipv6-address>
<generate-time>$NOW</generate-time>
<categories>
<entry name="host-info">
<client-version>5.2.10-15</client-version>
<os>Microsoft Windows 10 Enterprise , 64-bit</os>
<os-vendor>Microsoft</os-vendor>
<domain>$DOMAIN</domain>
<host-name>$COMPUTER</host-name>
<host-id>$HOSTID</host-id>
<network-interface>
<entry name="eth0">
<description>Realtek PCIe GbE Family Controller</description>
<mac-address>00-50-56-00-00-00</mac-address>
<ip-address><entry name="$IP"/></ip-address>
</entry>
</network-interface>
</entry>
<entry name="antivirus">
<list>
<entry>
<ProductInfo>
<Prod name="Windows Defender" vendor="Microsoft Corp." version="4.18.2305.7"/>
<real-time-protection>yes</real-time-protection>
<last-full-scan-time>$NOW</last-full-scan-time>
</ProductInfo>
</entry>
</list>
</entry>
<entry name="anti-malware">
<list>
<entry>
<ProductInfo>
<Prod name="Windows Defender" vendor="Microsoft Corp." version="4.18.2305.7"/>
<real-time-protection>yes</real-time-protection>
<last-full-scan-time>$NOW</last-full-scan-time>
</ProductInfo>
</entry>
</list>
</entry>
<entry name="patch-management">
<list>
<entry>
<ProductInfo>
<Prod name="Windows Update Agent" vendor="Microsoft Corp." version="10.0.19041.0"/>
<enabled>yes</enabled>
</ProductInfo>
</entry>
</list>
<missing-patches/>
</entry>
<entry name="firewall">
<list>
<entry>
<ProductInfo>
<Prod name="Windows Firewall" vendor="Microsoft Corp." version="10.0.19041.0"/>
<is-enabled>yes</is-enabled>
</ProductInfo>
</entry>
</list>
</entry>
<entry name="disk-encryption">
<list>
<entry>
<ProductInfo>
<Prod name="BitLocker Drive Encryption" vendor="Microsoft Corp." version="10.0.19041.0"/>
<drives>
<entry><drive-name>C:</drive-name><enc-state>encrypted</enc-state></entry>
</drives>
</ProductInfo>
</entry>
</list>
</entry>
</categories>
</hip-report>
HIP
