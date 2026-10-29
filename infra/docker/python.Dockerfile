# syntax=docker/dockerfile:1.10
# One image, two roles: the API (`api` target) and the background worker (`worker` target).
# Build context: repository root.  docker build -f infra/docker/python.Dockerfile --target api .

# ---------------------------------------------------------------- dependencies + app
FROM python:3.13-slim-trixie AS build
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
COPY packages/retrieval/pyproject.toml packages/retrieval/
COPY projects/pipeline-observatory/pyproject.toml projects/pipeline-observatory/
COPY projects/csv-analyst/pyproject.toml projects/csv-analyst/
COPY projects/support-agent/pyproject.toml projects/support-agent/
COPY projects/document-intelligence/pyproject.toml projects/document-intelligence/
COPY projects/edge-benchmark/pyproject.toml projects/edge-benchmark/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-workspace --package reluai-api

# …then the workspace packages themselves, installed as regular (non-editable) wheels.
COPY apps/api apps/api
COPY packages packages
COPY projects projects
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable --package reluai-api

# ---------------------------------------------------------------- PyTorch environment
# The Edge AI Benchmark Lab measures PyTorch itself. PyTorch lives in its own environment
# (CPU-only conda-forge builds; every package and its hash come from the lock file) that
# only the lab's child processes use: the application never imports it.
FROM python:3.13-slim-trixie AS torch-env
ADD --checksum=sha256:366cd9cd8be14df1ab8ed50352a82111082a36686b2d389fdb79a92c3fafb3e3 \
    --chmod=755 \
    https://github.com/mamba-org/micromamba-releases/releases/download/2.9.0-0/micromamba-linux-64 \
    /usr/local/bin/micromamba
COPY projects/edge-benchmark/torch/conda-linux-64.lock /tmp/torch.lock
RUN MAMBA_ROOT_PREFIX=/tmp/mamba micromamba create -y -q -p /opt/torch -f /tmp/torch.lock \
 && rm -rf /tmp/mamba /tmp/torch.lock /opt/torch/include \
 && find /opt/torch -name "*.a" -delete

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
 && reluai-csv build-dataset --canonical-dir /data/canonical --out /data/csv \
 && reluai-support build-data --canonical-dir /data/canonical --out /data/support \
 && rm -f /data/canonical/*.zip /data/canonical/*.rda
# Document Intelligence: the embedding model and the sample PDF (pinned, SHA-256 checked).
# The model is quantised to 8 bits here (`onnx` is added to this stage's environment only;
# the runtime image copies the environment from `build`), then the sample is read, indexed
# and embedded so the API only loads the result. Only the INT8 model and the result are
# kept. The invoice extraction set (real invoices drawn from the canonical data, with their
# records) is written next to it; the invoices themselves are rendered on request.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable --inexact \
      --package reluai-document-intelligence --group quantize
RUN reluai-docs fetch --out /data/docs \
 && reluai-docs quantize --model-dir /data/docs/models \
 && reluai-docs build-sample --out /data/docs \
 && reluai-docs invoices build --canonical /data/canonical/online-retail-ii.parquet --out /data/docs \
 && rm -rf /data/docs/source /data/docs/models/bge-small-en-v1.5.onnx
# Edge AI Benchmark Lab: the classifiers' weights and the licence-cleared photos (both pinned
# by SHA-256), each model exported to ONNX in the PyTorch environment and quantised to 8 bits
# on the calibration photos (with the same ONNX Runtime that serves it).
COPY --from=torch-env /opt/torch /opt/torch
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable --inexact \
      --package reluai-edge-benchmark --group quantize
RUN RELUAI_BENCH_TORCH_PYTHON=/opt/torch/bin/python reluai-bench build --out /data/bench \
 && rm -rf /data/bench/source

# ---------------------------------------------------------------- runtime base
# Debian stable (trixie). Security fixes published since the base image was built are
# applied here, and pip is removed: the app runs from /opt/venv and never installs packages.
FROM python:3.13-slim-trixie AS runtime
ARG VERSION=0.0.0-dev
LABEL org.opencontainers.image.source="https://github.com/uzairazhar89/reluai" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.version="${VERSION}"
RUN apt-get update \
 && apt-get upgrade -y --no-install-recommends \
 && rm -rf /var/lib/apt/lists/* \
 && python -m pip uninstall -y pip \
 && groupadd --system --gid 10001 reluai \
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
COPY --from=torch-env /opt/torch /opt/torch
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
