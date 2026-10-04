#!/bin/sh
# First boot in production: nginx cannot start without the certificate files referenced in
# the HTTPS server block, but certbot needs nginx running to answer the ACME challenge.
# Break the cycle with a short-lived self-signed placeholder; certbot replaces it and the
# reload loop below picks up the real certificate.
set -eu

[ -n "${DOMAIN:-}" ] || exit 0
live="/etc/letsencrypt/live/${DOMAIN}"
if [ ! -s "${live}/fullchain.pem" ] || [ ! -s "${live}/privkey.pem" ]; then
  echo "tls-bootstrap: no certificate for ${DOMAIN}; creating a temporary self-signed one"
  mkdir -p "${live}"
  openssl req -x509 -nodes -newkey rsa:2048 -days 2 \
    -subj "/CN=${DOMAIN}" \
    -keyout "${live}/privkey.pem" -out "${live}/fullchain.pem" >/dev/null 2>&1
fi

# Reload periodically so renewed certificates are served without a restart.
(
  while :; do
    sleep 21600
    nginx -s reload >/dev/null 2>&1 || true
  done
) &
