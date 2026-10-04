#!/usr/bin/env bash
# Deploy an image tag on the VPS with a health gate and automatic rollback.
#   infra/scripts/deploy.sh <git-sha>
# Called by the GitHub Actions deploy job over SSH (as the restricted `deploy` user), or by
# hand. Images are pulled from GHCR; nothing is built on the server.
set -euo pipefail

tag="${1:?usage: deploy.sh <image tag>}"
[[ "${tag}" =~ ^[0-9a-f]{7,40}$ ]] || { echo "tag must be a git SHA" >&2; exit 1; }

ROOT="${ROOT:-/opt/reluai}"
COMPOSE_DIR="${ROOT}/infra/compose"
STATE="${ROOT}/.deployed-tag"
cd "${COMPOSE_DIR}"
DOMAIN="$(grep -E '^DOMAIN=' .env | cut -d= -f2- | tr -d '[:space:]')"
DOMAIN="${DOMAIN:-reluai.cloud}"

compose() { IMAGE_TAG="$1" docker compose -f compose.yaml -f compose.prod.yaml "${@:2}"; }

previous="$(cat "${STATE}" 2>/dev/null || true)"
echo "deploying ${tag} (previous: ${previous:-none})"

compose "${tag}" pull --quiet
# Migrations run first (one-off container) and must succeed before app containers change.
compose "${tag}" run --rm migrate
compose "${tag}" up -d --remove-orphans

healthy=false
for _ in $(seq 1 30); do
  # Through nginx and TLS on this host (-k: the first boot uses a temporary certificate).
  if curl -fsSk --max-time 3 --resolve "${DOMAIN}:443:127.0.0.1" \
       "https://${DOMAIN}/api/status" | grep -q '"status":"\(operational\|degraded\)"'; then
    healthy=true
    break
  fi
  sleep 2
done

if [ "${healthy}" = true ]; then
  echo "${tag}" > "${STATE}"
  docker image prune -f --filter "until=168h" > /dev/null
  echo "deploy ok: ${tag}"
  exit 0
fi

echo "health gate failed for ${tag}" >&2
if [ -n "${previous}" ]; then
  echo "rolling back to ${previous}" >&2
  compose "${previous}" up -d --remove-orphans
fi
exit 1
