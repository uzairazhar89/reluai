# Deploy

## Normal releases (every merge to `main`)

1. Merge a pull request. `ci` runs lint, types, unit, database and browser tests.
2. `release` builds the api, worker, web and nginx images, tags them with the commit SHA,
   pushes them to GHCR with SBOM and provenance, and scans them with Trivy.
3. `deploy` waits for your approval (GitHub → Actions → the run → Review deployments).
4. On approval it connects as the `deploy` user and runs
   `git checkout <sha> && infra/scripts/deploy.sh <sha>` in `/opt/reluai`, which:
   - pulls the tagged images;
   - runs migrations in a one-off `migrate` container (as the schema owner);
   - restarts the services;
   - waits for the health gate: `/readyz` inside the API container, `/api/status` and `/`
     through nginx and TLS;
   - warms the live pages so the next visitor sees fresh figures;
   - on failure, restarts the previous tag and exits non-zero.
5. The workflow finishes with a public smoke test of `https://reluai.cloud/api/status`.

To redeploy a specific build: Actions → deploy → Run workflow → paste the full commit SHA.

## First-time setup of the server

Do this once, after the old site has been removed ([decommission](decommission.md)).

1. **Snapshot the VPS** in the provider's panel.
2. **Provision** from your laptop (WSL2 or Linux) with Ansible:

   ```bash
   cd infra/ansible
   cp inventory.example.ini inventory.ini        # your VPS address and SSH user
   ansible-galaxy collection install -r requirements.yml
   ansible-playbook -i inventory.ini site.yml \
     -e '{"deploy_authorized_keys": ["ssh-ed25519 AAAA... ci-deploy", "ssh-ed25519 AAAA... you"]}'
   ```

   This hardens SSH (keys only), enables the firewall (22, 80, 443) and fail2ban, adds
   swap, installs Docker, creates the `deploy` user, checks out the repository into
   `/opt/reluai`, and installs the boot unit and the nightly backup timer.
3. **Create the secrets file** on the server:

   ```bash
   sudo -u deploy cp /opt/reluai/infra/compose/.env.example /opt/reluai/infra/compose/.env
   sudo -u deploy nano /opt/reluai/infra/compose/.env   # set every required value
   sudo chmod 600 /opt/reluai/infra/compose/.env
   ```

   Generate each secret with `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`.
   Set `RELUAI_ENVIRONMENT=production`, `DOMAIN`, `ACME_EMAIL` and `GHCR_OWNER`.
4. **Point DNS** for `reluai.cloud` (A/AAAA) at the server.
5. **GitHub settings** for the repository:
   - Environment `production` with you as required reviewer.
   - Secrets: `DEPLOY_SSH_KEY` (private key matching the CI deploy public key),
     `DEPLOY_KNOWN_HOSTS` (`ssh-keyscan -t ed25519 <host>`), `DEPLOY_USER` (`deploy`),
     `DEPLOY_HOST` (the server address).
   - If the GHCR packages are private, log the server in once:
     `sudo -u deploy docker login ghcr.io` with a read-only token.
6. **First deploy**: run the `deploy` workflow manually with the latest released SHA.
   nginx starts with a temporary self-signed certificate and the `certbot` service obtains
   the real one through the webroot. nginx reloads certificates every 6 hours; to switch at
   once, run `docker compose -f compose.yaml -f compose.prod.yaml exec nginx nginx -s reload`
   in `/opt/reluai/infra/compose`.
7. **Check**: `https://reluai.cloud/status` shows all components operational; the first
   scheduled pipeline run happens within 6 hours, or start one from the project page.

## Fallback: deploy without GHCR

If GHCR is unavailable, build on the server once (slow, uses both cores for several minutes):

```bash
cd /opt/reluai/infra/compose
docker compose -f compose.yaml -f compose.staging.yaml up -d --build
```

Return to image-based deploys when GHCR is back.
