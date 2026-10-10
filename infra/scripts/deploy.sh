#!/usr/bin/env bash
# Deploy an image tag on the VPS with a health gate and automatic rollback.
#   infra/scripts/deploy.sh <git-sha>
# Called by the GitHub Actions deploy job through the SSH deploy gate (deploy-gate.sh), or by
# hand as the deploy user. Images are pulled from GHCR; nothing is built on the server.
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

ready() {
  # 1. Inside the API container: database reachable, schema at the expected migration, disk free.
  compose "${tag}" exec -T api python -c \
    "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/readyz', timeout=3).status == 200 else 1)" \
    > /dev/null 2>&1 || return 1
  # 2. Through nginx and TLS on this host (-k: the first boot uses a temporary certificate).
  curl -fsSk --max-time 3 --resolve "${DOMAIN}:443:127.0.0.1" "https://${DOMAIN}/api/status" \
    | grep -q '"status":"\(operational\|degraded\)"' || return 1
  # 3. The website itself renders.
  curl -fsSk --max-time 5 --resolve "${DOMAIN}:443:127.0.0.1" -o /dev/null "https://${DOMAIN}/" || return 1
}

healthy=false
for _ in $(seq 1 30); do
  if ready; then
    healthy=true
    break
  fi
  sleep 2
done

if [ "${healthy}" = true ]; then
  # Pages are prerendered without an API at build time; one request each triggers their
  # regeneration with live data so the next visitor sees real figures.
  for page in / /projects/data-pipeline-observatory /status; do
    curl -fsSk --max-time 5 --resolve "${DOMAIN}:443:127.0.0.1" -o /dev/null "https://${DOMAIN}${page}" || true
  done
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
