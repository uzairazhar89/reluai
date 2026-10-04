# syntax=docker/dockerfile:1.10
# One image, two roles: the API (`api` target) and the background worker (`worker` target).
# Build context: repository root.  docker build -f infra/docker/python.Dockerfile --target api .

ARG PYTHON_IMAGE=python:3.13-slim-bookworm

# ---------------------------------------------------------------- dependencies + app
FROM ${PYTHON_IMAGE} AS build
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /src

# Dependencies first (cached unless the lockfile changes)…
COPY pyproject.toml uv.lock ./
COPY apps/api/pyproject.toml apps/api/
COPY packages/platform-core/pyproject.toml packages/platform-core/
COPY packages/datasets/pyproject.toml packages/datasets/
COPY packages/inference/pyproject.toml packages/inference/
COPY projects/pipeline-observatory/pyproject.toml projects/pipeline-observatory/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-workspace --package reluai-api

# …then the workspace packages themselves, installed as regular (non-editable) wheels.
COPY apps/api apps/api
COPY packages packages
COPY projects projects
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable --package reluai-api

# ---------------------------------------------------------------- verified datasets
# Fetched at build time (never at container start) and accepted only if they pass the
# manifest's content checks. See artifacts/manifest.yaml.
FROM build AS data
COPY artifacts artifacts
ENV RELUAI_MANIFEST=/src/artifacts/manifest.yaml \
    RELUAI_PIPELINE_CANONICAL_DIR=/data/canonical \
    RELUAI_PIPELINE_SOURCES_DIR=/data/pipeline/sources \
    PATH=/opt/venv/bin:$PATH
RUN reluai-data fetch online-retail-ii --out /data/canonical \
 && reluai-pipeline build-sources \
 && rm -f /data/canonical/*.zip /data/canonical/*.rda

# ---------------------------------------------------------------- runtime base
FROM ${PYTHON_IMAGE} AS runtime
ARG VERSION=0.0.0-dev
LABEL org.opencontainers.image.source="https://github.com/uzairazhar89/reluai" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.version="${VERSION}"
RUN groupadd --system --gid 10001 reluai \
 && useradd --system --uid 10001 --gid reluai --home-dir /nonexistent --shell /usr/sbin/nologin reluai
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    RELUAI_VERSION=${VERSION} \
    RELUAI_DATA_DIR=/var/lib/reluai/data \
    RELUAI_MANIFEST=/opt/reluai/artifacts/manifest.yaml \
    RELUAI_PIPELINE_CANONICAL_DIR=/var/lib/reluai/data/canonical \
    RELUAI_PIPELINE_SOURCES_DIR=/var/lib/reluai/data/pipeline/sources
COPY --from=build /opt/venv /opt/venv
COPY --from=data --chown=reluai:reluai /data /var/lib/reluai/data
COPY artifacts/manifest.yaml /opt/reluai/artifacts/manifest.yaml
COPY infra/docker/entrypoint.sh /usr/local/bin/entrypoint.sh
USER reluai
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]

# ---------------------------------------------------------------- API
FROM runtime AS api
ENV PROMETHEUS_MULTIPROC_DIR=/tmp/prometheus
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=3 \
  CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2).status == 200 else 1)"]
CMD ["uvicorn", "reluai_api.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "2", "--no-server-header", "--timeout-graceful-shutdown", "20"]

# ---------------------------------------------------------------- worker
FROM runtime AS worker
CMD ["reluai", "worker", "--concurrency", "2"]
