# Data Pipeline Observatory

A production-style ETL pipeline on 1,067,371 real invoice lines from a UK online gift
retailer ([UCI Online Retail II](https://doi.org/10.24432/C5CG6D), CC BY 4.0). It validates
every row against a data contract, quarantines what it cannot trust with a reason code,
loads PostgreSQL idempotently, scores each batch and refuses to publish one that fails a
quality gate. Live demo: <https://reluai.cloud/projects/data-pipeline-observatory>.

## The problem

Monthly invoice exports, a product catalogue and a CRM never agree. The real export contains
cancellations, thousands of exact duplicate lines (the source workbook's two yearly sheets
overlap on 1 to 9 December 2010), stock write-offs recorded as zero-price lines, bad-debt
adjustments, test records and more than a fifth of lines without a customer ID. Summed
naively it overstates sales and double-counts customers.

## How it works

```
monthly CSV drop ─┐
product catalogue ┼─► extract ─► validate ─► transform ─► quality gate ─► load
CRM REST API ─────┘     │           │                        │              │
                     retries     quarantine             stops the run    one transaction,
                     + jitter    (reason codes)         before writes    reconciliation check
```

- **Sources** (`sources/`): the dataset is split into 25 monthly CSV drops in the original
  export layout, a derived product catalogue (JSON) and a CRM customer register served by a
  paginated REST API (`/internal/crm`) that can be told to fail.
- **Contract** (`contract.py`): the header must match the 8-column contract; lines are
  parsed one at a time so a malformed line becomes one quarantined row, not a failed file.
- **Rules** (`rules.py`, `validate.py`): 18 rejection rules, 5 warning rules and exact
  duplicate removal, each with a code and explanation, evaluated in a fixed order.
- **Transform** (`transform.py`): normalised stock codes and descriptions, line types
  (product, shipping, discount, fee, ...), stable line keys (SHA-256 of the identifying
  fields).
- **Quality** (`quality.py`): 9 checks across validity, uniqueness, completeness,
  timeliness, integrity and accuracy. Score = 100 × Σ(weight × passed) / Σ(weight); weights
  are 3 for gates, 2 for warnings, 1 for information.
- **Load** (`load.py`): COPY into temporary tables, upserts with `ON CONFLICT`, then a
  reconciliation check, all in one transaction.
- **Runs** (`runner.py`, `recorder.py`): every step, log line, check and timing is stored, so
  any run can be inspected after the fact.
- **Execution** (`tasks.py`): Procrastinate jobs under the global CPU lease; a schedule every
  6 hours; stale runs are expired.
- **API** (`api.py`, `service.py`): read models for the dashboard, per-visitor quotas and a
  bounded queue for starting runs.

## Scenarios

| Scenario | What happens | Expected |
| --- | --- | --- |
| `standard` | Load the next unloaded month (or reprocess the oldest once all are loaded) | Succeeds; real issues quarantined or flagged |
| `replay` | Reprocess the last loaded month | Succeeds with 0 new rows |
| `crm_flaky` | The CRM returns HTTP 503 twice per page | Succeeds after retries |
| `crm_outage` | The CRM is down for the whole run | Fails at extract; nothing written |
| `corrupt_drop` | About 7.5% of lines damaged in transit | Rows quarantined; gate fails; nothing published |

The last three are labelled as simulated wherever they appear.

## Run it

From the repository root, with PostgreSQL running and the environment from the main
README:

```bash
uv run reluai-data fetch online-retail-ii
uv run reluai-pipeline build-sources
uv run reluai db migrate
uv run reluai-pipeline run --scenario standard --local-crm     # one run, prints the outcome
uv run reluai-pipeline backfill --drops 12 --local-crm         # the first year
```

`--local-crm` serves the mock CRM from the same process, so no API server is needed.

## Tests

```bash
TEST_DATABASE_URL=postgresql://user:pass@127.0.0.1:5432/postgres \
  uv run pytest projects/pipeline-observatory
```

Unit tests cover the contract and every rule on a small fixture; database tests cover
idempotent replays, every scenario, the read models and quarantine sampling; a slow
regression test runs the real December 2010 drop and checks its exact counts
(`-m slow`, needs the dataset).

## Results

Measured results are on the project page, read live from the running system. On the
development machine, 13 monthly drops (567,942 lines) loaded with a median run time of
1.77 s and a 95th percentile of 3.51 s; 0.69% of lines were quarantined.

## Limitations

- The data is historical (December 2009 to December 2011) and is shown with its real dates.
- The catalogue and CRM are derived from the invoices, so they cannot disagree with them in
  every way real systems do; the fault scenarios cover the important failure modes.
- pandas holds one monthly file in memory, which suits this volume; much larger drops
  would call for chunked reads or DuckDB/Polars.
- Runs execute one at a time on purpose, to protect a small shared server.
