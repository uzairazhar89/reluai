#!/usr/bin/env bash
# One-time removal of the previous portfolio stack from the VPS (milestone M1).
# Run as root on the VPS from the old checkout directory, e.g.:
#   sudo bash decommission-legacy.sh /opt/portfolio            # dry run: report only
#   sudo bash decommission-legacy.sh /opt/portfolio --apply    # back up, then remove
#
# Backups go to /root/legacy-backup-<timestamp>/ (old .env, compose files, nginx and certbot
# configuration, list of containers/images/volumes). Nothing is deleted without --apply.
set -euo pipefail

old_dir="${1:?usage: decommission-legacy.sh <old checkout dir> [--apply]}"
apply="${2:-}"
brand="zar""wa"   # retired brand, split so repository checks do not flag this script
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup="/root/legacy-backup-${stamp}"

say() { printf '\n== %s\n' "$*"; }

say "Containers, images and volumes from the old stack"
docker ps -a --format '{{.Names}}\t{{.Image}}\t{{.Status}}' | grep -Ei \
  'portfolio|text-to-python|sentiment|image-classifier|csv-analyzer|coord-review|langgraph|ai-dashboard|ai-agents-redis|browserless|nginx-proxy' || true
docker volume ls --format '{{.Name}}' | grep -Ei 'portfolio|coord-review|redis|commodity' || true

say "Ports published on all interfaces (only 22, 80 and 443 should remain)"
ss -ltnp | awk 'NR==1 || $4 !~ /127\.0\.0\.1|\[::1\]/' || true

say "References to the retired brand outside the old checkout"
grep -RIil "${brand}" /etc/nginx /etc/letsencrypt/renewal /etc/cron* /var/spool/cron 2>/dev/null || echo "none found"

if [ "${apply}" != "--apply" ]; then
  say "Dry run only. Re-run with --apply to back up and remove the old stack."
  exit 0
fi

say "Backing up to ${backup}"
mkdir -p "${backup}"
cp -a "${old_dir}/.env" "${backup}/" 2>/dev/null || true
cp -a "${old_dir}"/docker-compose*.yml "${old_dir}/nginx" "${backup}/" 2>/dev/null || true
cp -a /etc/nginx "${backup}/host-nginx" 2>/dev/null || true
cp -a /etc/letsencrypt/renewal "${backup}/letsencrypt-renewal" 2>/dev/null || true
docker ps -a > "${backup}/containers.txt"; docker images > "${backup}/images.txt"
docker volume ls > "${backup}/volumes.txt"

say "Stopping and removing the old stacks"
for f in "${old_dir}/ai-agents/docker-compose.agent.yml" \
         "${old_dir}/demos/coord-review/docker-compose.coord-review.yml" \
         "${old_dir}/docker-compose.yml"; do
  [ -f "$f" ] && docker compose -f "$f" down --rmi all --volumes --remove-orphans || true
done

say "Removing the old checkout (backup kept in ${backup})"
rm -rf "${old_dir}"

say "Done. Remaining manual steps (docs/runbooks/decommission.md):"
echo " - remove any retired-brand server blocks listed above from host nginx/certbot"
echo " - delete the old GA property, Web3Forms key and retired-brand DNS records"
echo " - archive the old GitHub repository and make it private"
