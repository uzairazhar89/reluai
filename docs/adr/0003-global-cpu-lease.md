# 0003. One global CPU lease for heavy work

Date: 2026-10-04. Status: accepted.

## Context

Pipeline runs, and later model inference and video processing, are CPU-bound. Two of them
at once on two cores would starve the API and the website, and visitors can trigger work.

## Decision

Heavy jobs acquire a single PostgreSQL advisory lock (`reluai_core.cpu_lease`, key
`0x52454C55`) before doing work and release it afterwards. The holder's name is recorded as
the connection's `application_name`, so the status page can say what the worker is busy
with. Jobs wait for the lease with a bounded timeout. The queue itself is bounded
(`max_pending_runs`) and visitors have hourly quotas.

## Consequences

- The site stays responsive whatever visitors do; at worst they wait or see a clear
  "queue is full, try again in a minute".
- Throughput is one heavy job at a time, by design. A larger deployment would run dedicated
  workers and remove the lease.
- The lease is released automatically if the worker dies, because advisory locks belong
  to the database session.
