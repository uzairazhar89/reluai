# Backup and restore

## What is backed up

`infra/backup/backup.sh` runs nightly at 02:30 UTC (systemd timer `reluai-backup.timer`,
installed by Ansible). It writes a compressed custom-format `pg_dump` of the `reluai`
database to `/var/backups/reluai` and keeps 7 daily and 4 weekly (Sunday) dumps.

The database holds everything that cannot be rebuilt: the warehouse, run history,
quarantine, quotas and contact messages. Datasets and images are rebuilt from the manifest
and GHCR, and secrets live in `infra/compose/.env` (keep your own copy in a password
manager).

Check the last run:

```bash
systemctl list-timers reluai-backup.timer
journalctl -u reluai-backup.service -n 20
ls -lh /var/backups/reluai/daily
```

Copy backups off the server regularly (for example `rsync` to your laptop, or the
provider's snapshot feature): a backup on the same disk does not survive losing the server.

## Rehearse a restore (safe, do this monthly)

```bash
cd /opt/reluai
sudo infra/backup/restore.sh /var/backups/reluai/daily/<file>.dump --into reluai_restore
```

This restores into a scratch database next to production and prints row counts for the
main tables. Compare them with the live site, then drop the scratch database:

```bash
cd infra/compose && docker compose exec -T postgres psql -U reluai -d postgres \
  -c "DROP DATABASE reluai_restore"
```

## Restore production

Only when production data is lost or corrupted. It stops the API and worker, replaces the
database and starts them again.

```bash
cd /opt/reluai
sudo infra/backup/restore.sh /var/backups/reluai/daily/<file>.dump --into reluai --yes-replace-production
```

Then check `https://reluai.cloud/status` and the dashboard. Runs and messages created after
the backup was taken are lost.
