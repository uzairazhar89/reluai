# AI CSV Analyst

Ask a table a question in plain English and see exactly what was run. The analyst profiles
the table first (types, gaps, duplicates, numbers stored as text, values that would run as
spreadsheet formulas), turns each question into a validated query plan, runs it in a
locked-down DuckDB sandbox and answers with a chart, a table, the SQL and the same query in
pandas. Live demo: <https://reluai.cloud/projects/ai-csv-analyst>.

It works on two kinds of table:

- **The retailer's invoices**: 1,067,371 real invoice lines from a UK online gift retailer
  ([UCI Online Retail II](https://doi.org/10.24432/C5CG6D), CC BY 4.0), December 2009 to
  December 2011, built into a read-only DuckDB file.
- **A visitor's CSV**: up to 2 MB, 50,000 rows and 50 columns, kept for one hour.

## How it works

```
question ─► rule-based parser ─┬─► query plan ─► validator ─► compiler ─► DuckDB sandbox
                               │      ▲                         │
                     declines  │      │ same checks             ├─ parameterised SQL
                               ▼      │                         ├─ equivalent pandas
                  optional LLM (one tool call, up to 2 retries) └─ plain-English summary
```

- **Plan** (`plan.py`): the only thing an interpreter may produce. Up to 3 measures (count,
  distinct count, sum, average, minimum, maximum), up to 2 groupings including a time bucket
  (day to year), up to 6 filters, a sort and a limit of at most 100. It is data, never code;
  its JSON Schema is the LLM's tool definition.
- **Parser** (`parser.py`): splits the question into the longest phrases it knows (columns
  and their synonyms, known values and aliases such as "UK" for United Kingdom, dates and
  periods, numbers with currency signs and separators, about 120 keyword phrases), then
  builds the plan in passes for filters, groupings and measures. Any word left over, and it
  declines rather than guesses.
- **Validator** (`validate.py`): columns exist, aggregations suit their types, values convert
  to the column's type and are spelled as in the data, dates become whole periods ("in 2011"
  is 1 January to 31 December). Problems come back as a list a model can read.
- **Compiler** (`compile.py`): quoted identifiers and bound parameters only, half-open date
  ranges on whole days, `ILIKE` with escaped wildcards; plus the pandas equivalent, a
  plain-English summary and a chart choice that must fit the result's shape.
- **Sandbox** (`sandbox.py`): read-only connections with file and network access off,
  extension loading off, the configuration locked, one thread, a 256 MB memory limit, a
  5-second timeout that interrupts the query, and one query at a time per process.
- **LLM fallback** (`llm.py`): only when the rules decline. The model sees the column list
  and two tools, `run_query_plan` and `cannot_answer`. Its arguments are validated like the
  rules' output; problems go back as the tool result for up to 2 more attempts. Uploads use
  it only if the visitor opts in, and then send the question and column names and types,
  never rows. It uses the platform's free-tier provider chain (Groq, then Cerebras) and works
  without any provider configured.
- **Profiling** (`profile.py`): per-column statistics and data-quality findings, all
  computed in DuckDB.
- **Uploads** (`datasets.py`): text files only (Excel, PDF, images, archives and executables
  are recognised by their first bytes and refused), UTF-8 or Windows-1252, converted into a
  per-upload DuckDB file in the container's memory-backed `/tmp`, deleted after an hour.
- **Evaluation** (`evaluation.py`): fixed question sets scored every 6 hours on the job
  queue; the latest run is served at `GET /api/csv/evaluation`.

## Results

Measured on the full table, Intel Xeon @ 2.10 GHz, 2 vCPU, DuckDB 1.5.6, one query thread,
256 MB memory limit, 10 October 2026. The live page shows the latest scheduled run.

| Question set | Questions | Answered correctly | Wrong | Declined, should answer | Declined correctly |
| --- | --- | --- | --- | --- | --- |
| Development (written with the rules) | 48 | 40 of 40 | 0 | 0 | 8 |
| Held out (never used to change the rules) | 31 | 24 of 29 | 1 | 4 | 2 |

A question counts as correct only if its plan matches the expected plan exactly. The
development set shows what the rules cover; the held-out set (82.8%) is the estimate of how
they do on new phrasings. The wrong answer: "Revenue from customers in EIRE per year" also
counted distinct customers, because "customers" was read as a measure.

Query time over both sets: median 9 ms, 95th percentile 74 ms.

## Run it

```bash
uv sync
uv run reluai-data fetch online-retail-ii --out data/canonical      # verified download
uv run reluai-csv build-dataset --canonical-dir data/canonical --out data/csv
RELUAI_CSV_DATA_DIR=data/csv uv run reluai-csv ask "Top 5 countries by revenue in 2011"
RELUAI_CSV_DATA_DIR=data/csv uv run reluai-csv evaluate --no-record
```

The API (`api.py`, mounted at `/api/csv` in `apps/api`):

| Endpoint | What it does |
| --- | --- |
| `GET /datasets/retail` | The bundled table's columns, profile, findings and example questions |
| `POST /uploads` | Profile an uploaded CSV (multipart, 10 per visitor per hour) |
| `GET /uploads/{id}` | An upload's profile, until it expires |
| `POST /ask` | Answer a question (60 per visitor per hour) |
| `GET /evaluation` | The latest evaluation run |
| `GET /usage` | Outcomes of visitors' questions in the last 30 days (no question text) |

## Tests

```bash
uv run pytest projects/csv-analyst                     # unit tests, no database needed
TEST_DATABASE_URL=postgresql://... uv run pytest projects/csv-analyst   # + API tests
```

- The development set must be answered exactly (the held-out set is measured, not asserted).
- 24 plans run through both the SQL and the displayed pandas code on the same data and must
  return identical rows.
- Hostile SQL (`COPY ... TO`, `ATTACH`, `INSTALL`, `read_csv('/etc/passwd')`, `SET
  lock_configuration`, writes) is sent straight to the sandbox and must fail.
- Injection strings go through the parser, validator and compiler; values must stay bound
  parameters.
- The LLM fallback is tested with scripted providers: invalid plans corrected after
  feedback, schema errors, unknown tools, refusals, outages.
- Uploads: binary and Excel files, NUL bytes, size, row and column limits, encodings,
  formula-like values, expiry and the storage cap.

## Limitations

- Answers are aggregates: no row listings, joins, shares or ratios, or filters on
  aggregates. Those questions are declined.
- The rules know a fixed vocabulary; other phrasings are declined unless a model is
  configured.
- Uploaded columns are typed by DuckDB's CSV reader; numbers with thousands separators are
  read as text (and the profile says so).
- The model fallback is not scored, because the server runs without a model by default.

Portfolio demonstration. Data: Chen, D. (2012). Online Retail II [Dataset]. UCI Machine
Learning Repository, CC BY 4.0.
