#!/usr/bin/env bash
# Restore a backup made by backup.sh.
#
#   infra/backup/restore.sh <dump-file> --into reluai_restore     # rehearsal (safe)
#   infra/backup/restore.sh <dump-file> --into reluai --yes-replace-production
#
# The rehearsal restores into a scratch database and runs row-count checks, which is how the
# restore procedure is tested (docs/runbooks/backup-restore.md). Replacing production stops
# the app containers first and requires the explicit flag.
set -euo pipefail

usage() { sed -n '2,10p' "$0"; exit 2; }
[ $# -ge 3 ] || usage
dump="$1"; shift
[ "$1" = "--into" ] || usage
target_db="$2"; shift 2
confirm="${1:-}"

ROOT="${ROOT:-/opt/reluai}"
[ -f "${dump}" ] || { echo "no such file: ${dump}" >&2; exit 1; }
[[ "${target_db}" =~ ^[a-z_][a-z0-9_]*$ ]] || { echo "invalid database name" >&2; exit 1; }
# Same Compose files and image tag as the running release.
compose() { "${ROOT}/infra/scripts/compose.sh" "$@"; }
psql_admin() { compose exec -T postgres psql -v ON_ERROR_STOP=1 -U reluai -d postgres "$@"; }

if [ "${target_db}" = "reluai" ]; then
  [ "${confirm}" = "--yes-replace-production" ] || {
    echo "refusing to replace production without --yes-replace-production" >&2; exit 1; }
  compose stop api worker
  psql_admin -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = 'reluai' AND pid <> pg_backend_pid();"
fi

psql_admin -c "DROP DATABASE IF EXISTS ${target_db};"
psql_admin -c "CREATE DATABASE ${target_db} OWNER reluai;"
compose exec -T postgres pg_restore -U reluai -d "${target_db}" --no-owner --role=reluai \
  --exit-on-error < "${dump}"

echo "restored ${dump} into ${target_db}; row counts:"
compose exec -T postgres psql -U reluai -d "${target_db}" -At -c "
  SELECT 'pipeline.run', count(*) FROM pipeline.run
  UNION ALL SELECT 'retail.invoice_line', count(*) FROM retail.invoice_line
  UNION ALL SELECT 'alembic_version', count(*) FROM alembic_version;"

if [ "${target_db}" = "reluai" ]; then
  compose start api worker
  echo "production restored and app restarted"
fi
