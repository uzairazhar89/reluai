# Architecture overview

One VPS (2 vCPU, 8 GB RAM, no GPU) runs the whole site with Docker Compose. Only nginx is
reachable from the internet; everything else sits on internal networks.

```
                 Internet (80, 443)
                        │
                 ┌──────▼──────┐   TLS, security headers, per-IP rate and connection limits,
                 │    nginx    │   410 for retired routes, /internal and /metrics blocked
                 └──┬───────┬──┘
          /         │       │  /api/*
   ┌────────────────▼┐     ┌▼────────────────┐
   │  web (Next.js)  │────►│  api (FastAPI)  │  typed REST, problem+json errors,
   │  ISR pages,     │ SSR │  quotas, limits │  per-visitor quotas, body limits
   │  client islands │     └───┬─────────┬───┘
   └─────────────────┘         │ defer   │ read
                               ▼         ▼
                       ┌────────────────────────┐
                       │ PostgreSQL 16          │  warehouse · run metadata · quarantine
                       │ (+ pgvector)           │  job queue (Procrastinate) · quotas
                       └───────────▲────────────┘
                                   │ fetch jobs, CPU lease
                          ┌────────┴────────┐
                          │ worker          │  pipeline runs, schedules, housekeeping
                          └────────┬────────┘
                                   │ optional (profile "llm")
                          ┌────────▼────────┐
                          │ llama.cpp       │  local fallback model, CPU only
                          └─────────────────┘
```

Networks: `edge` (nginx, web, api) and `backend` (api, worker, postgres, llm; marked
internal, so it has no route to the internet). Postgres publishes no port.

## Request paths

- **Pages.** nginx → web. Pages that show live figures are statically generated and
  revalidated at most once a minute (ISR); the server fetches from the API over the internal
  network, so a page view does not hit the API unless the page is due for refresh. When the
  API is unreachable, pages render an explicit offline state instead of failing.
- **Interactive demos.** The browser calls `/api/...` on the same origin; nginx routes it to
  the API. Writes (starting a run, sending a message) have tighter nginx limits plus
  per-visitor quotas in the API.
- **Heavy work.** The API never does heavy work in a request. It validates, checks quotas and
  queue depth, records the run and defers a job. The worker executes it under a global CPU
  lease (a PostgreSQL advisory lock), so only one heavy job runs at a time.

## Data flow of the pipeline (P1)

```
UCI Online Retail II ──verified fetch──► canonical parquet ──build-sources──► 25 monthly CSV drops
                                                                              product catalogue (JSON)
                                                                              CRM register (served by
                                                                              /internal/crm, paginated)
drop + catalogue + CRM ──► extract ─► validate ─► transform ─► quality gate ─► load (one transaction)
                                          │                                       │
                                          ▼                                       ▼
                                     quarantine                           retail.* warehouse
                     (every stage records steps, log lines, checks and timings in pipeline.*)
```

Details, failure handling and measured results: the project page and
[projects/pipeline-observatory](../../projects/pipeline-observatory/README.md).

## Code organisation

- `packages/platform-core`: cross-cutting services every project uses (settings, logging,
  database, job queue, CPU lease, quotas, errors, health, metrics).
- `packages/inference`: the LLM provider chain and tool registry used by AI projects.
- `packages/datasets`: the artifact manifest and verified downloads.
- `projects/<name>`: one Python package per project with its own models, API router, tasks
  and tests. The API mounts each router; the worker registers each task blueprint.
- `apps/api`: the composition root, migrations and CLI. `apps/web`: the website.

## Security boundaries

- Only 22 (SSH, key-only), 80 and 443 are open on the host.
- The GitHub Actions deploy key is bound to a forced command (`infra/scripts/deploy-gate.sh`)
  that accepts only `deploy <sha>` for a commit on `main`; it cannot open a shell or forward
  ports.
- Every container runs with `no-new-privileges`. The web, API and worker containers also run
  as non-root users, drop all Linux capabilities and have read-only root filesystems.
- The application connects as `reluai_app`, which can read and write data but not change the
  schema; migrations run separately as the owner role.
- Every user input is validated with Pydantic; no user input is ever executed as code, SQL
  or a shell command.
- Secrets live in `infra/compose/.env` on the server (never in git) and in GitHub
  environment secrets.

## Observability

- Structured JSON logs from every service with request IDs.
- Prometheus metrics at `/metrics` (blocked at nginx; scraped on the internal network).
- `/healthz` (liveness) and `/readyz` (database, migration version, disk) on the API;
  the public `/status` page summarises component health and recent runs.
