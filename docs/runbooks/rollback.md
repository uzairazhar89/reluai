# Roll back

## Automatic

`infra/scripts/deploy.sh` rolls back by itself when the health gate fails after a deploy:
it starts the previous image tag (recorded in `/opt/reluai/.deployed-tag`) and the workflow
run fails, so you see it in GitHub.

## Manual

When a release passes the health gate but is wrong (a broken page, bad copy):

1. Find the last good SHA: GitHub → Actions → deploy → the last good run, or
   `cat /opt/reluai/.deployed-tag` before the bad deploy.
2. Actions → deploy → Run workflow → paste that SHA → approve.

Equivalent on the server, as `deploy`:

```bash
cd /opt/reluai && git fetch --quiet origin && git checkout <good-sha>
infra/scripts/deploy.sh <good-sha>
```

## Database migrations

Rollback restarts old code against the current schema; migrations are not reversed.
Migrations are therefore written to be backward compatible for one release (add columns and
tables first, remove them in a later release). If a migration itself is the problem,
restore from backup ([backup and restore](backup-restore.md)) after rolling back the code.

Then revert the bad commit on `main` so the next release does not reintroduce it.
