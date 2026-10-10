#!/bin/sh
# Runs in the certbot container (compose.prod.yaml). Obtains the Let's Encrypt certificate
# for DOMAIN and www.DOMAIN through nginx's webroot, then renews it twice a day. nginx
# notices changed certificate files within a minute and reloads (30-tls-bootstrap.sh).
set -u
: "${DOMAIN:?set DOMAIN}"
: "${ACME_EMAIL:?set ACME_EMAIL}"
webroot=/var/www/certbot
trap 'exit 0' TERM INT

# Let nginx start answering on port 80 before Let's Encrypt calls back.
sleep "${CERTBOT_START_DELAY:-15}"

while :; do
  if [ -f "/etc/letsencrypt/renewal/${DOMAIN}.conf" ]; then
    certbot renew --webroot -w "${webroot}" --quiet
    sleep "${CERTBOT_RENEW_INTERVAL:-43200}" &
    wait $!
  else
    # nginx's temporary self-signed files occupy the live directory; certbot needs it free.
    rm -rf "/etc/letsencrypt/live/${DOMAIN}"
    if certbot certonly --webroot -w "${webroot}" --non-interactive --agree-tos \
      -m "${ACME_EMAIL}" -d "${DOMAIN}" -d "www.${DOMAIN}"; then
      echo "certbot-loop: certificate obtained for ${DOMAIN} and www.${DOMAIN}"
    else
      # Let's Encrypt allows 5 failed validations per name per hour; 20 minutes stays below.
      echo "certbot-loop: request failed (do ${DOMAIN} and www.${DOMAIN} point at this server?); retrying in 20 minutes"
      sleep "${CERTBOT_RETRY_INTERVAL:-1200}" &
      wait $!
    fi
  fi
done
