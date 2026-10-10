# Deploy

## Normal releases (every merge to `main`)

1. Merge a pull request. `ci` runs lint, types, unit, database and browser tests.
2. `release` builds the api, worker, web and nginx images, tags them with the commit SHA,
   pushes them to GHCR with SBOM and provenance, and scans them with Trivy.
3. `deploy` waits for your approval (GitHub → Actions → the run → Review deployments).
4. On approval it connects as the `deploy` user and sends one request, `deploy <sha>`.
   The CI key can do nothing else on the server (see [the deploy key](#the-ci-deploy-key)).
   The gate checks that the commit is on `main`, checks it out in `/opt/reluai` and runs
   `infra/scripts/deploy.sh <sha>`, which:
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
     -e 'deploy_ci_public_key="ssh-ed25519 AAAA... reluai-ci-deploy"'
   ```

   `deploy_ci_public_key` is the public half of the CI deploy key
   ([how to create it](#the-ci-deploy-key)). This hardens SSH (keys only), enables the
   firewall (22, 80, 443) and fail2ban, adds swap, installs Docker, creates the `deploy`
   user with the CI key locked to the deploy gate, checks out the repository into
   `/opt/reluai`, and installs the boot unit and the nightly backup timer.

   **Without a Linux or WSL machine** (for example from Windows), run the same playbook on
   the server itself:

   ```bash
   sudo apt-get update && sudo apt-get install -y ansible git
   git clone https://github.com/uzairazhar89/reluai.git ~/reluai-setup && cd ~/reluai-setup
   sudo ansible-playbook -i infra/ansible/inventory.local.example.ini infra/ansible/site.yml \
     -e 'deploy_ci_public_key="ssh-ed25519 AAAA... reluai-ci-deploy"'
   ```

   Either way, **log in with an SSH key before running it**: the playbook turns off password
   login, and it stops with an error if no SSH key is installed on the server.
3. **Create the secrets file** on the server:

   ```bash
   sudo -u deploy cp /opt/reluai/infra/compose/.env.example /opt/reluai/infra/compose/.env
   sudo -u deploy nano /opt/reluai/infra/compose/.env   # set every required value
   sudo chmod 600 /opt/reluai/infra/compose/.env
   ```

   Generate each secret with `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`
   (new values, not the ones from your laptop). Set `DOMAIN`, `ACME_EMAIL` and `GHCR_OWNER`;
   leave `IMAGE_TAG` empty (the deploy script sets it). Keep a copy of the file in your
   password manager.
4. **Point DNS** at the server: `A` records for `reluai.cloud` and `www.reluai.cloud` (the
   certificate covers both, so both must resolve). Remove any `AAAA` record that does not
   point at this server, because Let's Encrypt checks IPv6 first when one exists.
5. **GitHub settings** for the repository:
   - Environment `production` with you as required reviewer.
   - Secrets: `DEPLOY_SSH_KEY` (the private CI deploy key, the whole file including the
     `BEGIN`/`END` lines),
     `DEPLOY_KNOWN_HOSTS` (`ssh-keyscan -t ed25519 <host>`), `DEPLOY_USER` (`deploy`),
     `DEPLOY_HOST` (the server address).
   - Container images: GitHub → your profile → Packages → each `reluai-*` package →
     Package settings → Change visibility → Public (the code is public; the images hold no
     secrets). Alternatively keep them private and log the server in once:
     `sudo -u deploy docker login ghcr.io` with a token that can only read packages.
6. **First deploy**: approve the waiting `deploy` run, or run the `deploy` workflow manually
   with the latest released SHA. nginx starts with a temporary self-signed certificate and
   the `certbot` service obtains the real one through the webroot. nginx reloads
   certificates every 6 hours; to switch at once:
   `sudo -u deploy /opt/reluai/infra/scripts/compose.sh exec nginx nginx -s reload`.
7. **Load the pipeline history** (once):
   `sudo -u deploy /opt/reluai/infra/scripts/compose.sh exec worker reluai-pipeline backfill --drops 12`.
8. **Check**: `https://reluai.cloud/status` shows all components operational; the first
   scheduled pipeline run happens within 6 hours, or start one from the project page.

For any other Compose command on the server use `/opt/reluai/infra/scripts/compose.sh`
(`ps`, `logs -f api`, `restart worker`): it adds the production file and the deployed image
tag, which plain `docker compose` would miss.

## The CI deploy key

GitHub Actions logs in as `deploy` with its own SSH key. On the server that key is bound to
a forced command, `/usr/local/bin/reluai-deploy-gate` (source:
[`infra/scripts/deploy-gate.sh`](../../infra/scripts/deploy-gate.sh)), with the `restrict`
option. Whatever the client asks for, sshd runs the gate instead, and the gate accepts one
request: `deploy <40-character SHA>`, where the commit must already be on `main` in GitHub.
Everything else is refused and logged (`journalctl -t reluai-deploy-gate`): shells, other
commands, file copies, port and agent forwarding, unknown or unmerged commits, and a second
deploy while one is running. A leaked key can therefore only redeploy code that is already
on `main`.

Create the key pair once, on your own computer (PowerShell, WSL or Linux):

```bash
ssh-keygen -t ed25519 -C reluai-ci-deploy -f reluai-ci-deploy
```

Press Enter twice when it asks for a passphrase (CI cannot type one).

- `reluai-ci-deploy.pub` (one line) is `deploy_ci_public_key` for Ansible.
- `reluai-ci-deploy` (the private key) goes into the GitHub secret `DEPLOY_SSH_KEY`. After
  that you can delete both files; if the key is ever lost, make a new pair.

Use a different key for your own logins. To replace the CI key, create a new pair, re-run
the playbook with the new public key, and update the secret. Changes to the gate script reach
the server only when the playbook is run again.

To deploy by hand on the server (for example while GitHub is down), run the same gate, so
the same checks and the one-deploy-at-a-time lock apply:

```bash
sudo -u deploy SSH_ORIGINAL_COMMAND="deploy <full sha>" /usr/local/bin/reluai-deploy-gate
```

## Fallback: deploy without GHCR

If GHCR is unavailable, build on the server once (slow, uses both cores for several minutes):

```bash
cd /opt/reluai/infra/compose
docker compose -f compose.yaml -f compose.staging.yaml up -d --build
```

Return to image-based deploys when GHCR is back.
