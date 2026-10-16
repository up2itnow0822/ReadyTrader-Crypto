#!/usr/bin/env bash
set -euo pipefail

# Generates a local CA + 2 party certs for mTLS messaging.
# Output layout:
#   mpc_signer/certs/
#     ca.crt ca.key
#     party0.crt party0.key
#     party1.crt party1.key
#
# NOTE: For production, use a proper PKI and protect private keys.

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
OUT_DIR="${ROOT_DIR}/certs"
mkdir -p "${OUT_DIR}"

CA_KEY="${OUT_DIR}/ca.key"
CA_CRT="${OUT_DIR}/ca.crt"

if [[ ! -f "${CA_KEY}" || ! -f "${CA_CRT}" ]]; then
  openssl genrsa -out "${CA_KEY}" 4096
  openssl req -x509 -new -nodes -key "${CA_KEY}" -sha256 -days 3650 \
    -subj "/C=US/O=ReadyTrader-Crypto/CN=ReadyTrader MPC CA" \
    -out "${CA_CRT}"
fi

gen_party() {
  local name="$1"
  local cn="$2"
  local key="${OUT_DIR}/${name}.key"
  local csr="${OUT_DIR}/${name}.csr"
  local crt="${OUT_DIR}/${name}.crt"
  local ext="${OUT_DIR}/${name}.ext"

  openssl genrsa -out "${key}" 4096
  openssl req -new -key "${key}" -out "${csr}" -subj "/C=US/O=ReadyTrader-Crypto/CN=${cn}"

  cat > "${ext}" <<EOF
basicConstraints=CA:FALSE
keyUsage = digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth, clientAuth
subjectAltName = @alt_names
[alt_names]
DNS.1 = ${name}
DNS.2 = localhost
DNS.3 = mpc-party-${name#party}
IP.1 = 127.0.0.1
EOF

  openssl x509 -req -in "${csr}" -CA "${CA_CRT}" -CAkey "${CA_KEY}" -CAcreateserial \
    -out "${crt}" -days 825 -sha256 -extfile "${ext}"

  rm -f "${csr}" "${ext}"
}

gen_party "party0" "ReadyTrader MPC Party 0"
gen_party "party1" "ReadyTrader MPC Party 1"

echo "Wrote certs to ${OUT_DIR}"

