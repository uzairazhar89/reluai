# Adding a project to the site

Every project has the same shape, so the platform does the heavy lifting: database, job
queue, CPU lease, quotas, error format, logging, metrics, deployment and the website's page
layout already exist. A new project adds its own logic, one API router, optionally some
background tasks, one migration and one page.

The Data Pipeline Observatory (`projects/pipeline-observatory`) is the reference
implementation; copy its patterns. The example below adds the AI CSV Analyst as
`projects/csv-analyst` with the site slug `ai-csv-analyst`.

## How a request flows

```
Browser ──/projects/ai-csv-analyst──► Next.js page (server-rendered, ISR)
   │                                     └─ serverGet("/api/csv/...")  ──┐
   └──── /api/csv/... (fetch from the page's interactive part) ─────────┤
                                                                         ▼
                                              nginx ──► FastAPI app (apps/api)
                                                         └─ router from projects/csv-analyst
                                                              ├─ reads/writes PostgreSQL
                                                              └─ defers heavy work ──► worker
                                                                   (Procrastinate task, CPU lease)
```

## Checklist

### 1. The Python package

```
projects/csv-analyst/
  pyproject.toml            name = "reluai-csv-analyst"; depends on reluai-core (+ reluai-inference for LLM calls)
  README.md                 problem, architecture, run instructions, results, limitations
  src/reluai_csv/
    settings.py             CsvSettings(BaseSettings), env prefix RELUAI_CSV_
    models.py               SQLAlchemy models on reluai_core.db.Base, in a schema of your own ("csv")
    schemas.py              Pydantic response/request models (these become the website's types)
    service.py              business logic: plain functions taking Database + settings
    api.py                  router = APIRouter(tags=["csv"]) with the endpoints
    tasks.py                blueprint = Blueprint() with heavy tasks (optional)
  tests/                    unit tests + db tests (mark with @pytest.mark.db)
```

The uv workspace already includes `projects/*`; run `uv sync` after creating it.

Platform services you get for free, all from `reluai_core`:

| Need | Use |
| --- | --- |
| Database session | `DatabaseDep` in endpoints; `db.session()` in services |
| Clear error to the client | `raise ProblemError(429, "...", code="quota_exceeded")` |
| Per-visitor limits | `visitor_key(client_ip(request), secret)` + `consume_quota(...)` |
| Heavy work off the request | a Procrastinate task; take `cpu_lease(...)` inside it |
| Structured logs | `log = get_logger(__name__)`; `log.info("event.name", key=value)` |
| LLM with free-tier fallbacks and budgets | `reluai_inference.build_chain(...)` and `ToolRegistry` |
| Datasets | add to `artifacts/manifest.yaml`; load with `reluai_datasets` |

### 2. Wire it into the API and worker

- `apps/api/pyproject.toml`: add `reluai-csv-analyst` to dependencies and
  `[tool.uv.sources]`; do the same in the root `pyproject.toml`.
- `apps/api/src/reluai_api/main.py`: `app.include_router(csv_api.router, prefix="/api/csv")`.
- `apps/api/src/reluai_api/jobs.py`: add `"csv": csv_blueprint` to `build_job_app`.
- Request size: if the project accepts uploads, add its prefix to `prefix_limits` in
  `main.py` and give it its own `location` with a larger `client_max_body_size` in
  `infra/nginx/snippets/app-locations.conf`.

### 3. Database migration

- `apps/api/src/reluai_api/migrations/env.py`: `import reluai_csv.models  # noqa: F401`.
- New file in `migrations/versions/`, for example `20261020_0004_csv_analyst.py` with
  `down_revision = "0003"`. Create the schema, the tables, and grant the runtime role:

  ```python
  op.execute("CREATE SCHEMA IF NOT EXISTS csv")
  op.create_table(..., schema="csv")
  op.execute("""
  DO $$ BEGIN IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'reluai_app') THEN
    GRANT USAGE ON SCHEMA csv TO reluai_app;
    GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA csv TO reluai_app;
    GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA csv TO reluai_app;
    ALTER DEFAULT PRIVILEGES IN SCHEMA csv GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO reluai_app;
  END IF; END $$;""")
  ```
- `conftest.py`: add the new tables to the `TRUNCATE` list in `clean_db`.
- Update the expected revision in `apps/api/tests/test_api.py`.

### 4. Build and type-check configuration

- `infra/docker/python.Dockerfile`: add
  `COPY projects/csv-analyst/pyproject.toml projects/csv-analyst/` next to the others
  (the dependency layer is cached from these files).
- Root `pyproject.toml`: add `"projects/csv-analyst/src"` to mypy's `files`.
- `scripts/mirror_projects.py`: add a `Mirror(...)` entry for its public mirror.

### 5. Regenerate the website's API types

```bash
uv run reluai openapi --out apps/web/openapi.json
cd apps/web && pnpm api:types
```

Then add short aliases in `apps/web/src/lib/api/types.ts`
(`export type CsvReport = S["CsvReportOut"];`). CI fails if these are stale.

### 6. The website page

```
apps/web/src/
  content/projects.ts                 set the project's status: "building" now, "live" when the demo works
  app/projects/ai-csv-analyst/page.tsx the case study (server component)
  features/csv/                       interactive parts ("use client"), queries, tests
```

- **Page**: copy `app/projects/data-pipeline-observatory/page.tsx`. Keep `revalidate`,
  `metadata`, the JSON-LD block, the header, `<ProjectToc />` and the twelve
  `<ProjectSection id="...">` blocks in order: problem, why, solution, architecture,
  implementation, demo, results, failure-handling, deployment, cost, limitations, source.
- **Server data**: `await serverGet<Type>("/api/csv/...", revalidate)` returns
  `{ ok, data }` and never throws, so render an honest fallback when `ok` is false.
- **Interactive demo**: a client component wrapped in `<QueryProvider>`, using the typed
  client: `unwrap(await api.GET("/api/csv/...", { params }))`. Pass server data as
  `initialData` so the first paint has real content. Wrap relative times in `<NowProvider>`.
- **Errors**: map API problem codes (`quota_exceeded`, `queue_full`, ...) to sentences that
  say what happened and what to do, like `triggerErrorMessage` in the pipeline demo.
- **Results section**: only measured numbers from the API, with the environment they were
  measured in (ADR-0006).
- Once `status` is `"live"`, the homepage, the projects index, the sitemap and the project
  card pick it up automatically.

### 7. Tests

- Python: unit tests for logic, db tests for SQL, an API test for each endpoint including
  quota and validation errors. They run with outbound network blocked, so mock any provider.
- Web: Vitest for components and helpers; a Playwright spec using recorded fixtures
  (`e2e/fixtures/*.json`, captured from a real local run) and `mockApi`-style routing, plus
  `expectAccessible(page)`.

### 8. Data, docs and release

- Third-party data or models: an `artifacts/manifest.yaml` entry first (licence, source,
  checksums); the `/data` page updates itself.
- The project README; an ADR if you made a decision that shapes the system.
- Push to a branch, open a pull request, merge when `ci` is green, approve the deploy.

## Local loop while building

```bash
uv run uvicorn reluai_api.main:create_app --factory --reload   # API with your router
uv run reluai worker                                            # if it has tasks
cd apps/web && pnpm dev                                         # page at /projects/<slug>
```
