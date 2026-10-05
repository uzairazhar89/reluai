# syntax=docker/dockerfile:1.10
# The website: Next.js standalone server, non-root, read-only root filesystem at runtime.
# Build context: repository root.  docker build -f infra/docker/web.Dockerfile .

# ---- dependencies (cached until the lockfile changes) ------------------------------------
FROM node:26-alpine AS deps
WORKDIR /repo/apps/web
RUN corepack enable
COPY apps/web/package.json apps/web/pnpm-lock.yaml apps/web/pnpm-workspace.yaml ./
RUN --mount=type=cache,id=pnpm-store,target=/root/.local/share/pnpm/store \
    pnpm install --frozen-lockfile

# ---- build ---------------------------------------------------------------------------------
FROM deps AS build
# The /data page is rendered at build time from the artifact manifest.
COPY artifacts/manifest.yaml /repo/artifacts/manifest.yaml
COPY apps/web/ ./
# NEXT_PUBLIC_* values are compiled into the bundle; staging builds pass their own origin.
ARG NEXT_PUBLIC_SITE_URL=https://reluai.cloud
# No API is reachable while building, so live pages are prerendered in their "offline" state
# and filled in by the first revalidation after start (the deploy script warms them).
ENV NEXT_TELEMETRY_DISABLED=1 \
    NEXT_PUBLIC_SITE_URL=${NEXT_PUBLIC_SITE_URL} \
    API_INTERNAL_URL=http://127.0.0.1:9
RUN pnpm build

# ---- runtime -------------------------------------------------------------------------------
FROM node:26-alpine AS runtime
ARG VERSION=dev
LABEL org.opencontainers.image.title="reluai-web" \
      org.opencontainers.image.source="https://github.com/uzairazhar89/reluai" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.version="${VERSION}"
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0
RUN addgroup -S -g 10001 app && adduser -S -D -H -u 10001 -G app app
COPY --from=build --chown=10001:10001 /repo/apps/web/.next/standalone ./
COPY --from=build --chown=10001:10001 /repo/apps/web/.next/static ./.next/static
USER 10001
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD ["node", "-e", "fetch('http://127.0.0.1:3000/robots.txt').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"]
CMD ["node", "server.js"]
