# reluai

Source for [reluai.cloud](https://reluai.cloud), the engineering portfolio of Uzair Azhar:
production-style data, AI and computer-vision projects with live demos on real data, all
running on one 2 vCPU / 8 GB server with no paid APIs.

Everything lives in this repository: the website, the API, every project, the infrastructure
and the deployment pipeline. Commit here; CI tests, builds, deploys and publishes read-only
per-project mirror repositories.

## What is live

| Project | Status | What it shows |
| --- | --- | --- |
| [Data Pipeline Observatory](projects/pipeline-observatory) | Live | ETL on 1.07 M real invoice lines: data contract, quarantine with reason codes, idempotent PostgreSQL loads, quality gates, run dashboard |
| AI CSV Analyst | In build | Natural-language questions over uploaded CSVs via validated tool calls |
| Six more | Planned | Document Q&A, support agent, edge benchmarks, invoice matching, research search, street-scene vision ([plan](docs/plan/PORTFOLIO_REBUILD_PLAN.md)) |

Nothing that is not built is presented as available, and every figure on the site comes from
a recorded run.

## Repository layout

```
apps/
  web/                 Next.js 16 website (TypeScript, Tailwind, typed API client)
  api/                 FastAPI composition root, worker entrypoint, Alembic migrations, CLI
packages/
  platform-core/       settings, logging, database, job queue, CPU lease, quotas, health, metrics
  inference/           LLM provider chain (Groq → Cerebras → local llama.cpp → deterministic)
  datasets/            artifact manifest and verified downloads
projects/
  pipeline-observatory/  P1: the data pipeline
infra/
  docker/              images (python: api + worker, web)
  compose/             base, staging and production profiles
  nginx/               edge proxy: TLS, security headers, rate limits, retired routes
  ansible/             VPS provisioning (hardening, Docker, app user, backups)
  backup/ scripts/     backup, restore, deploy with health gate and rollback
artifacts/manifest.yaml  every third-party dataset: source, licence, checksums
docs/                  architecture, decisions (ADRs), runbooks, plan
```

## Run it locally

Requirements: Python 3.12+ with [uv](https://docs.astral.sh/uv/), Node 22 with pnpm 10,
Docker (for the full stack) or a local PostgreSQL 16.

```bash
# Everything in containers, built from source (http://localhost:8080)
cp infra/compose/.env.example infra/compose/.env    # set the three required secrets
docker compose -f infra/compose/compose.yaml -f infra/compose/compose.staging.yaml up --build
```

Working on code without Docker:

```bash
uv sync                                           # Python workspace
export RELUAI_DATABASE_URL=postgresql+psycopg://reluai:reluai@127.0.0.1:5432/reluai
export RELUAI_DATA_DIR=$PWD/data \
       RELUAI_PIPELINE_CANONICAL_DIR=$PWD/data/canonical \
       RELUAI_PIPELINE_SOURCES_DIR=$PWD/data/pipeline/sources \
       RELUAI_PIPELINE_CRM_BASE_URL=http://127.0.0.1:8000/internal/crm
uv run reluai-data fetch online-retail-ii         # verified download into data/canonical
uv run reluai-pipeline build-sources              # monthly drops, catalogue, CRM register
uv run reluai db migrate
uv run uvicorn reluai_api.main:create_app --factory --reload   # API on :8000
uv run reluai worker                                            # job worker

cd apps/web && pnpm install && pnpm dev           # website on :3000, proxies /api to :8000
```

## Checks

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy
TEST_DATABASE_URL=postgresql://user:pass@127.0.0.1:5432/postgres uv run pytest --disable-socket --allow-hosts=127.0.0.1,::1,localhost
uv run python scripts/check_denylist.py

cd apps/web
pnpm lint && pnpm typecheck && pnpm test
pnpm build && pnpm e2e                            # Playwright, desktop and mobile, with axe
```

Database tests create a throwaway database per session and apply the real migrations. Browser
tests answer API calls from recorded fixtures, so they need no backend.

## Deploying

Pushes to `main` run CI; the release workflow builds and scans images and publishes them to
GHCR tagged with the commit SHA; the deploy workflow waits for approval, then runs
[`infra/scripts/deploy.sh`](infra/scripts/deploy.sh) on the server: pull, migrate, restart,
health gate, automatic rollback. See [docs/runbooks/deploy.md](docs/runbooks/deploy.md).

## Documentation

- [Architecture overview](docs/architecture/overview.md) and [resource budget](docs/architecture/resources.md)
- [Decision records](docs/adr)
- Runbooks: [deploy](docs/runbooks/deploy.md), [rollback](docs/runbooks/rollback.md),
  [backup and restore](docs/runbooks/backup-restore.md),
  [decommission the old site](docs/runbooks/decommission.md), [local LLM](docs/runbooks/local-llm.md)
- [Security policy](SECURITY.md) and [contributing](CONTRIBUTING.md)

## Licence

Code: MIT ([LICENSE](LICENSE)). Third-party data keeps its own licence and attribution, listed
in [artifacts/manifest.yaml](artifacts/manifest.yaml) and on the site's
[data page](https://reluai.cloud/data).
