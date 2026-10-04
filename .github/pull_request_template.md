## What and why

## How it was tested
- [ ] `uv run pytest` (and `-m slow` if pipeline/data code changed)
- [ ] `pnpm test && pnpm e2e` (if the website changed)
- [ ] Numbers shown on the site come from recorded runs, not typed values

## Checklist
- [ ] New datasets/models are in `artifacts/manifest.yaml` with licence and attribution
- [ ] Migrations added for schema changes (`alembic revision --autogenerate`) and reviewed
- [ ] Docs/ADRs updated where behaviour or architecture changed
