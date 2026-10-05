# How GitHub Actions work in this repository

GitHub Actions runs scripts on GitHub's machines when something happens in the repository.
Each script is a **workflow**: a YAML file in `.github/workflows/`. Nothing needs
installing or enabling; GitHub reads these files on every push.

## The vocabulary

- **Workflow**: one YAML file, for example `ci.yml`. It says *when* to run (`on:`) and
  *what* to run (`jobs:`).
- **Trigger** (`on:`): a push to `main`, a pull request, a schedule (cron), a button in the
  Actions tab (`workflow_dispatch`), or another workflow finishing (`workflow_run`).
- **Job**: a group of steps that runs on one fresh virtual machine (a **runner**, here
  `ubuntu-24.04`). Jobs in the same workflow run in parallel unless one `needs` another.
  The machine is thrown away afterwards, so every run starts clean.
- **Step**: one command (`run: uv run ruff check .`) or one reusable **action**
  (`uses: actions/checkout@v5`, which downloads the repository onto the runner).
- **Service container**: a helper started next to a job, such as the PostgreSQL database
  the Python tests use.
- **Secret**: an encrypted value (an SSH key, a token) that steps can read but that is never
  printed in logs. Set under Settings → Secrets and variables → Actions.
- **Environment**: a named deployment target (`production`) with its own secrets and
  protection rules, such as "a person must approve".
- **Artifact**: a file a job saves for you to download (coverage report, test report).
- **`GITHUB_TOKEN`**: a temporary token GitHub gives each run. `permissions:` in the YAML
  says what it may do (read code, push images to the registry, upload scan results).

A red ✗ means a step exited with a non-zero code. Click the run, then the job, then the red
step to see the log.

## The chain in this repository

```
push to main
   │
   ▼
ci ──────────── python    lint, types, OpenAPI check, 100+ tests with network blocked
   │            datasets  download the real dataset, run the real-data regression test
   │            web       lint, format, types, unit tests, build, browser tests
   │            infra     Compose, nginx, shell scripts, Ansible, workflow files
   │ all green?
   ▼
release ─────── build 4 images (api, worker, web, nginx), tag with the commit SHA,
   │            push to ghcr.io with SBOM, scan with Trivy
   │ green?
   ▼
deploy ──────── waits for your approval (production environment), then SSH to the VPS:
   │            pull images → migrate database → restart → health gate → rollback if bad
   │ green?
   ▼
mirror ──────── refresh the read-only per-project repositories (needs MIRROR_TOKEN)
```

`release`, `deploy` and `mirror` use `workflow_run`, so each one starts only when the
previous workflow finished successfully on `main`. A red `ci` therefore stops a bad commit
from ever reaching the server.

Pull requests run only `ci`. Nothing is released from a pull request.

## Running a workflow by hand

Actions tab → pick the workflow on the left → **Run workflow**. `deploy` asks for the
commit SHA to deploy; this is also how you roll back to an older version.

## When something fails

| Symptom | Usual cause | Where to look |
| --- | --- | --- |
| `python` job red at `ruff`, `mypy` or `pytest` | code problem | the red step's log; run the same command locally |
| `OpenAPI document is up to date` red | an API change without regenerating types | run `uv run reluai openapi --out apps/web/openapi.json` and `pnpm api:types`, commit |
| `web` job red at Prettier | formatting | `cd apps/web && pnpm format` |
| `release` red at Trivy | a fixable critical vulnerability in a base image or package | update the dependency or base image |
| `deploy` red at "Configure SSH" | missing or wrong deploy secrets | Settings → Environments → production |
| "The hosted runner lost communication with the server" | something cut the runner's own network or exhausted its memory | the step that was running when it stopped |

## Cost

Public repositories get GitHub-hosted runners free. Container images stored in GHCR for a
public repository are free as well.
