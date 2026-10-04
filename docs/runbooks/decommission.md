# Decommission the old site (milestone M1)

The previous portfolio stack (several Compose projects, host nginx entries, a retired
company microsite and an exposed Redis) is removed before the new stack is deployed.

## 1. Before you start

- Take a provider snapshot of the VPS.
- Keep a copy of anything you still want from the old checkout (for example images you
  might reuse). Nothing from the old repository is needed by the new site.

## 2. Dry run

Copy `infra/decommission/decommission-legacy.sh` to the server and run it against the old
checkout. It only reports:

```bash
sudo bash decommission-legacy.sh /opt/portfolio
```

It lists the old containers and volumes, every port published on a public interface, and
any reference to the retired brand in host nginx, certbot renewal files and cron.

## 3. Apply

```bash
sudo bash decommission-legacy.sh /opt/portfolio --apply
```

It backs up the old `.env`, Compose files, nginx and certbot configuration and inventories
to `/root/legacy-backup-<timestamp>/`, stops and removes the old stacks with their images
and volumes, and deletes the old checkout.

## 4. Manual steps

- Remove any retired-brand server blocks the dry run listed from host nginx and certbot;
  then stop and disable host nginx (`systemctl disable --now nginx`), because the new nginx
  runs in a container.
- Check that only 22, 80 and 443 listen publicly: `ss -ltnp`.
- Delete the old analytics property, the old form-service key and DNS records for the
  retired brand.
- Archive the old GitHub repository and make it private.
- After a week without problems, delete `/root/legacy-backup-*` (keep a copy off the server
  if you want).

The new site serves `410 Gone` for the retired paths and old demo APIs, and redirects
`/demo/...` to `/projects` (`infra/nginx/snippets/legacy-routes.conf`), so search engines
drop the old URLs quickly.
