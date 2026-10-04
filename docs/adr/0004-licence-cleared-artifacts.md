# 0004. Licence-cleared, checksummed artifacts only

Date: 2026-10-04. Status: accepted.

## Context

The demos use third-party datasets, and later models and video footage. The previous
repository committed large binaries and an unrelated document. A public portfolio must be
able to show that it has the right to use everything it shows.

## Decision

- Every third-party artifact is listed in `artifacts/manifest.yaml` with its source, licence,
  attribution, modifications and content checks (row count, columns, date range, content
  fingerprint or SHA-256).
- Artifacts are never committed. They are fetched at image build time and rejected if a
  check fails. A pinned mirror may be used when the canonical host is unreachable, but only
  if it passes the same checks.
- The website's `/data` page is rendered from the manifest, so the public record and the
  verification cannot drift apart.
- Licences that would impose obligations on the whole site (AGPL and similar) are not used
  without a new decision record.

## Consequences

- Adding a dataset or model means writing its manifest entry first, including how to verify
  it.
- Builds fail loudly when an upstream file changes, rather than silently serving different
  data.
