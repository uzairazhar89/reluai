#!/bin/sh
# First boot in production: nginx cannot start without the certificate files referenced in
# the HTTPS server block, but certbot needs nginx running to answer the ACME challenge.
# Break the cycle with a short-lived self-signed placeholder; certbot replaces it and the
# watcher below reloads nginx when the files change.
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

# Reload when the certificate changes (first issue, renewals), checked every minute, so the
# real certificate replaces the placeholder without waiting or restarting the container.
# The starting point is the certificate nginx is about to load; a failed reload (for example
# mid-renewal) is retried on the next check.
fingerprint() { md5sum < "${live}/fullchain.pem" | cut -d' ' -f1; }
loaded="$(fingerprint)"
(
  while :; do
    sleep "${TLS_WATCH_INTERVAL:-60}"
    if [ ! -s "${live}/fullchain.pem" ] || [ ! -s "${live}/privkey.pem" ]; then continue; fi
    current="$(fingerprint)"
    [ "${current}" = "${loaded}" ] && continue
    if nginx -s reload > /dev/null 2>&1; then
      echo "tls-bootstrap: certificate for ${DOMAIN} changed; nginx reloaded"
      loaded="${current}"
    fi
  done
) &
