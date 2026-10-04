# 0002. Images built in CI, pulled from GHCR

Date: 2026-10-04. Status: accepted.

## Context

Building on the server competes with live traffic for two cores, makes every deploy depend
on the server's network and disk state, and means the code running in production was never
the code that was tested.

## Decision

- CI builds every image once per commit (`release.yml`), tagged with the full commit SHA.
- Each image is published to GitHub Container Registry with a software bill of materials
  and provenance attestation, then scanned with Trivy: critical findings with an available
  fix fail the release, and all findings are uploaded to GitHub code scanning.
- The server only pulls images. `infra/scripts/deploy.sh` runs migrations in a one-off
  container, restarts services and requires a health gate; on failure it restores the
  previous tag.
- Large datasets are fetched and checksum-verified during the image build, never when a
  container starts.

## Consequences

- Deploys are fast and repeatable, and rollback is "start the previous tag".
- A deploy needs GHCR to be reachable. The documented fallback is building the staging
  profile on the server (`compose.staging.yaml`), accepting the CPU cost once.
- Database migrations must stay backward compatible for one release, because rollback
  restarts old code against the migrated schema.
