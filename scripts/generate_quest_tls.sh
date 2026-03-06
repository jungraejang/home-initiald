#!/usr/bin/env bash
set -euo pipefail

mkdir -p certs

if ! command -v openssl >/dev/null 2>&1; then
  echo "openssl is required. Install with: sudo apt install -y openssl"
  exit 1
fi

PI_IP="${1:-}"
if [[ -z "${PI_IP}" ]]; then
  PI_IP="$(hostname -I | awk '{print $1}')"
fi

cat > certs/quest_fpv_openssl.cnf <<EOF
[req]
distinguished_name=req_distinguished_name
x509_extensions=v3_req
prompt=no

[req_distinguished_name]
CN=quest-fpv.local

[v3_req]
subjectAltName=@alt_names

[alt_names]
DNS.1=quest-fpv.local
IP.1=${PI_IP}
EOF

openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout certs/quest_fpv.key \
  -out certs/quest_fpv.crt \
  -config certs/quest_fpv_openssl.cnf

echo "Generated:"
echo "  certs/quest_fpv.crt"
echo "  certs/quest_fpv.key"
echo
echo "Set in g29_control/config.json:"
echo '  "https_enabled": true'
echo '  "https_port": 8443'
echo
echo "Open on Quest:"
echo "  https://${PI_IP}:8443"
