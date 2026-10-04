# Contributing

This is a personal portfolio, so outside contributions are not expected, but the workflow
below is how every change is made.

## Workflow

1. Branch from `main`.
2. Make the change with tests. Keep commits small, with messages in the
   [Conventional Commits](https://www.conventionalcommits.org) style (`feat(pipeline): ...`).
3. Run the checks locally (see the README), then open a pull request using the template.
4. CI must pass. Merging to `main` releases images; deploying needs approval.

## Standards

- **Python**: 3.12+, typed (mypy strict), formatted and linted with Ruff. Settings come
  from environment variables via pydantic-settings, never hard-coded.
- **TypeScript**: strict, ESLint with no warnings, Prettier. API types are generated from
  the OpenAPI document (`uv run reluai openapi --out apps/web/openapi.json`, then
  `pnpm api:types`); never hand-write them.
- **Database**: every schema change is an Alembic migration in
  `apps/api/src/reluai_api/migrations/versions`, backward compatible for one release.
- **Tests**: unit tests for logic, database tests against a real PostgreSQL for anything
  that touches SQL, Playwright tests for user-visible flows.
- **Data and claims**: no invented numbers, users or deployments; synthetic data and
  simulated faults are labelled (ADR-0006). New datasets or models need a manifest entry
  with licence and checksums first (ADR-0004).
- **Cost**: no paid APIs. Anything that calls a model goes through the provider chain
  (ADR-0005) and must work when every hosted provider is unavailable.

## Adding a project

1. Create `projects/<name>` as a uv workspace member with its own package, `tests/` and
   `README.md` (problem, architecture, run instructions, results, limitations).
2. Expose a FastAPI router and, if it does heavy work, Procrastinate tasks that take the CPU
   lease. Mount both in `apps/api`.
3. Add its page under `apps/web/src/app/projects/<slug>` using the twelve project sections,
   and set its status in `apps/web/src/content/projects.ts` to `live` only when the demo
   works end to end.
4. Add it to `scripts/mirror_projects.sh` so it gets its own read-only mirror repository.
