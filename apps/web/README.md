# reluai web

The website for reluai.cloud: Next.js 16 (App Router, Turbopack), React 19, TypeScript
(strict), Tailwind CSS v4, TanStack Query and a typed API client generated from the API's
OpenAPI document.

## Structure

```
src/app/            routes: home, /projects, /projects/<slug>, /data, /hire, /status, /privacy,
                    sitemap, robots, Open Graph image, icon
src/components/     shared UI (header, footer, buttons, badges, project page sections)
src/features/       interactive islands per feature (pipeline dashboard, contact form)
src/content/        project catalogue (status: live, building or planned)
src/lib/api/        generated schema, typed client, server-side fetch helper
e2e/                Playwright tests with recorded API fixtures and axe checks
```

Pages that show live figures are statically generated and revalidated at most once a minute
(ISR). Server-side reads go to `API_INTERNAL_URL` and never throw: if the API is down, pages
render an explicit offline state. Browser-side calls use same-origin `/api/...`, which nginx
routes to the API in production and `next dev` proxies locally.

## Commands

```bash
pnpm install
pnpm dev                 # http://localhost:3000, proxies /api to API_INTERNAL_URL (default :8000)
pnpm lint && pnpm typecheck && pnpm test
pnpm build && pnpm e2e   # browser tests against the production build, desktop and mobile
pnpm api:types           # regenerate src/lib/api/schema.d.ts from openapi.json
```

To try a production build against a local API: `LOCAL_API_PROXY=1 pnpm build && pnpm start`.
To run Playwright with a system Chromium: `PW_CHROMIUM_PATH=/path/to/chromium pnpm e2e`.

## Environment

| Variable               | Where   | Purpose                                                                                   |
| ---------------------- | ------- | ----------------------------------------------------------------------------------------- |
| `API_INTERNAL_URL`     | runtime | API origin for server-side reads (`http://api:8000` in Compose)                           |
| `NEXT_PUBLIC_SITE_URL` | build   | canonical origin for metadata, sitemap and robots; non-production origins are not indexed |
| `LOCAL_API_PROXY`      | build   | `1` keeps the `/api` proxy in a production build (local testing only)                     |
