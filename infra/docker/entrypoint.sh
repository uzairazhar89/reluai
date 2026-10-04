#!/bin/sh
# Container entrypoint for the API and worker images.
set -eu

# Prometheus multi-process mode keeps per-process metric files; start each container clean.
if [ -n "${PROMETHEUS_MULTIPROC_DIR:-}" ]; then
  rm -rf "${PROMETHEUS_MULTIPROC_DIR}"
  mkdir -p "${PROMETHEUS_MULTIPROC_DIR}"
fi

exec "$@"
