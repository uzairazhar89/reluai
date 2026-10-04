# Architecture decision records

Short records of decisions that shape the system, why they were made and what they cost.
A decision is changed by adding a new record that supersedes the old one.

| # | Decision | Status |
| --- | --- | --- |
| [0001](0001-postgres-for-everything.md) | PostgreSQL holds data, the job queue, quotas and (later) vectors; no Redis | Accepted |
| [0002](0002-images-built-in-ci.md) | Images are built and scanned in CI and pulled from GHCR; nothing is built on the server | Accepted |
| [0003](0003-global-cpu-lease.md) | One global CPU lease for heavy work | Accepted |
| [0004](0004-licence-cleared-artifacts.md) | Only licence-cleared, checksummed third-party artifacts; no AGPL by default | Accepted |
| [0005](0005-llm-provider-chain.md) | LLM provider chain with a token budget and a deterministic last resort | Accepted |
| [0006](0006-data-provenance-labelling.md) | Every figure and dataset is labelled with its provenance | Accepted |
