# 0001. PostgreSQL for data, jobs, quotas and vectors

Date: 2026-10-04. Status: accepted.

## Context

The site runs on one 2 vCPU / 8 GB server. The previous version ran Redis (unauthenticated
and publicly exposed) next to several databases. The projects need a relational warehouse,
a durable job queue, rate-limit counters, an LLM token ledger and, for the retrieval
projects, vector and full-text search.

## Decision

Use one PostgreSQL 16 instance (the `pgvector` image) for all of it:

- application data in per-project schemas (`retail`, `pipeline`, `platform`, ...);
- the job queue with [Procrastinate](https://procrastinate.readthedocs.io), which stores jobs
  in PostgreSQL tables and uses `LISTEN/NOTIFY`;
- quotas as atomic upserts on `platform.rate_counter`;
- the global CPU lease as an advisory lock (ADR-0003);
- embeddings with `pgvector` and keyword search with built-in full-text search.

## Consequences

- One service to back up, monitor and secure; one connection string; transactional
  consistency between a run record and its job.
- Throughput is far below what Redis or a dedicated broker can do. At portfolio traffic
  (a few jobs per minute at most) this does not matter; the queue is bounded anyway.
- Queue and data share one memory limit (768 MB); heavy analytical queries must stay
  within `statement_timeout`.
- Migrating to a dedicated broker later only touches `reluai_core.jobs`.
