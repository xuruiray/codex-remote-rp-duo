#!/usr/bin/env bash
set -euo pipefail
umask 077
base=$(cd "$(dirname "$0")" && pwd)
data=${DUO_DATA_DIR:-"$base/.duo"}
state="$data/runtime/tls"
mkdir -p "$state"
ip=${1:-${DUO_LAN_IP:-$(ipconfig getifaddr en0 2>/dev/null || true)}}
ip=${ip:-127.0.0.1}
python3 - "$ip" <<'PY'
import ipaddress, sys
ip = ipaddress.IPv4Address(sys.argv[1])
if not ip.is_private:
    raise SystemExit("需要 Mac 的局域网 IPv4 地址")
PY
if [[ ! -s $state/ca.crt || ! -s $state/ca.key ]]; then
  openssl req -x509 -newkey rsa:2048 -nodes -days 3650 -sha256 \
    -subj '/CN=Duo Codex Local CA' -addext 'basicConstraints=critical,CA:TRUE,pathlen:0' \
    -addext 'keyUsage=critical,keyCertSign,cRLSign' -keyout "$state/ca.key" -out "$state/ca.crt"
fi
if [[ -s $state/ip && $(cat "$state/ip") == "$ip" && -s $state/server.crt && -s $state/server.key ]]; then
  if openssl x509 -in "$state/server.crt" -noout -checkend 86400 && \
     openssl verify -CAfile "$state/ca.crt" -verify_ip 127.0.0.1 "$state/server.crt" && \
     openssl verify -CAfile "$state/ca.crt" -verify_ip "$ip" "$state/server.crt"; then exit; fi
fi
openssl req -newkey rsa:2048 -nodes -subj '/CN=Duo Codex Mac' \
  -keyout "$state/server.key" -out "$state/server.csr"
san=IP:127.0.0.1
if [[ $ip != 127.0.0.1 ]]; then san="$san,IP:$ip"; fi
cat > "$state/extensions" <<EOF
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectAltName=$san
EOF
openssl x509 -req -in "$state/server.csr" -CA "$state/ca.crt" -CAkey "$state/ca.key" \
  -CAcreateserial -days 397 -sha256 -extfile "$state/extensions" -out "$state/server.crt"
printf '%s\n' "$ip" > "$state/ip"
