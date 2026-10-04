# reluai API

The FastAPI composition root for reluai.cloud. It mounts the platform services (health,
metrics, status, contact) and every project's router, owns the Alembic migrations, and
provides the worker entrypoint and the `reluai` CLI.

```bash
uv run uvicorn reluai_api.main:create_app --factory --reload   # API on :8000
uv run reluai worker                    # job worker (pipeline runs, schedules, housekeeping)
uv run reluai db migrate                # apply migrations (uses the migration URL if set)
uv run reluai db current                # show the current revision
uv run reluai openapi --out apps/web/openapi.json   # OpenAPI document for the web client
uv run reluai contact list --days 30    # read contact-form messages
```

Interactive docs are at `/api/docs` outside production (`RELUAI_EXPOSE_API_DOCS=true` to
force them on). Errors use RFC 9457 problem details with a `code` and the request ID.

Settings are environment variables with the `RELUAI_` prefix; see
`packages/platform-core/src/reluai_core/settings.py` and `infra/compose/.env.example`.
