#!/usr/bin/env bash
# Nightly PostgreSQL backup with rotation (run on the VPS by the reluai-backup systemd timer).
#   infra/backup/backup.sh            -> /var/backups/reluai/daily/reluai-<UTC timestamp>.dump
# Keeps 7 daily and 4 weekly (Sunday) dumps. Custom format: restore with infra/backup/restore.sh.
set -euo pipefail

COMPOSE_DIR="${COMPOSE_DIR:-/opt/reluai/infra/compose}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/reluai}"
KEEP_DAILY="${KEEP_DAILY:-7}"
KEEP_WEEKLY="${KEEP_WEEKLY:-4}"

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "${BACKUP_DIR}/daily" "${BACKUP_DIR}/weekly"
target="${BACKUP_DIR}/daily/reluai-${stamp}.dump"

cd "${COMPOSE_DIR}"
# pg_dump runs inside the database container as the schema owner; output streams to the host.
docker compose exec -T postgres pg_dump -U reluai -d reluai --format=custom --compress=6 \
  > "${target}.partial"
mv "${target}.partial" "${target}"

# Sanity check: the archive must list its contents.
docker compose exec -T postgres pg_restore --list < "${target}" > /dev/null

if [ "$(date -u +%u)" = "7" ]; then
  cp "${target}" "${BACKUP_DIR}/weekly/"
fi

prune() {  # keep the newest $2 files in $1
  find "$1" -maxdepth 1 -name 'reluai-*.dump' -printf '%T@ %p\n' | sort -rn \
    | tail -n "+$(( $2 + 1 ))" | cut -d' ' -f2- | xargs -r rm -f --
}
prune "${BACKUP_DIR}/daily" "${KEEP_DAILY}"
prune "${BACKUP_DIR}/weekly" "${KEEP_WEEKLY}"

size="$(du -h "${target}" | cut -f1)"
echo "backup ok: ${target} (${size})"
