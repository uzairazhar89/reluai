#!/usr/bin/env bash
# Docker Compose for the production stack on the VPS, with the same files and image tag as
# the running release (deploy.sh records the tag in /opt/reluai/.deployed-tag). Use it for
# every manual command on the server; plain `docker compose` misses the production file.
#
#   /opt/reluai/infra/scripts/compose.sh ps
#   /opt/reluai/infra/scripts/compose.sh logs -f --tail 50 api worker
#   /opt/reluai/infra/scripts/compose.sh exec worker reluai-pipeline backfill --drops 12
set -euo pipefail

ROOT="${ROOT:-/opt/reluai}"
if [ -z "${IMAGE_TAG:-}" ]; then
  IMAGE_TAG="$(cat "${ROOT}/.deployed-tag" 2> /dev/null || true)"
fi
if [ -z "${IMAGE_TAG}" ]; then
  echo "no release is deployed yet (${ROOT}/.deployed-tag is missing); run the deploy first" >&2
  exit 1
fi
export IMAGE_TAG
cd "${ROOT}/infra/compose"
exec docker compose -f compose.yaml -f compose.prod.yaml "$@"
