# Resource budget

Target host: 2 vCPU, 8 GB RAM, no GPU, shared with nothing else. The previous site
over-committed (about 11.7 GB of container limits on 8 GB); these limits are sized to fit
with headroom for the OS, Docker and page cache.

## Container limits (`infra/compose/compose.yaml`)

| Service | Memory limit | CPU limit | Notes |
| --- | --- | --- | --- |
| nginx | 64 MB | 0.25 | |
| web | 256 MB | 0.5 | read-only root filesystem; ISR cache in memory |
| api | 1 GB | 1.0 | request handling; CSV analyst queries (DuckDB, 256 MB and 1 thread per query, one at a time per process); `/tmp` capped at 256 MB for uploads |
| worker | 1.5 GB | 1.0 | one heavy job at a time (CPU lease) |
| postgres | 768 MB | 0.75 | |
| migrate | 512 MB | – | one-off, exits after migrations |
| **Always on** | **≈ 3.6 GB** | | leaves ≈ 4 GB for the OS, Docker and page cache |
| llm (profile `llm`) | 2 GB | 1.5 | optional local model; ≈ 5.6 GB in total when enabled |

A 2 GB swap file (Ansible `swap_size_mb`) absorbs short spikes.

## Measured

Development machine (Intel Xeon @ 2.10 GHz, 2 vCPU), 4 October 2026. These are local process
measurements, not container metrics; they will be re-measured on the VPS after the first
deployment.

| What | Measured |
| --- | --- |
| API process, idle after serving the dashboard | ≈ 170 MB RSS |
| Worker process, idle | ≈ 165 MB RSS |
| One pipeline run, January 2011 drop (35,147 lines), peak, including the local CRM server | ≈ 275 MB RSS |
| Next.js server | ≈ 110 MB RSS |
| Pipeline run time per monthly drop, 13 drops | median 1.77 s, 95th percentile 3.51 s |
| Database size after 14 drops and their run history | ≈ 160 MB |
| API process after 8 CSV analyst questions on the 1.07M-row table (10 October 2026) | ≈ 250 MB RSS |
| CSV analyst query time, the 65 answered evaluation questions | median 9 ms, 95th percentile 74 ms |

## Rules that keep it inside the budget

- Heavy jobs take the global CPU lease; a second job waits rather than competing for the two
  cores (ADR-03).
- The queue is bounded (`RELUAI_PIPELINE_MAX_PENDING_RUNS`, default 4) and visitors have
  hourly quotas, so traffic spikes turn into polite "try later" messages, not memory pressure.
- Request bodies are capped per route (16 KB for the pipeline and contact endpoints, 2.2 MB
  for CSV uploads).
- CSV analyst queries run one at a time per API process, with a 5-second timeout and a
  256 MB DuckDB memory limit; at most 50 uploads are stored, each for an hour.
- PostgreSQL statements time out (`statement_timeout`), and the app role has its own timeout.
- Logs rotate at 10 MB × 3 files per container.
