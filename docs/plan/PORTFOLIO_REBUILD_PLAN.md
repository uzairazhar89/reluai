# reluai.cloud — Portfolio Rebuild Plan (v4.1)

**Status:** Approved; implementation started 4 Oct 2026 (M0, M2, M3 in progress).
**Version:** v4.1, 4 Oct 2026. Supersedes v1–v4.
**Source brief:** `Initial_Instruction.txt`. Agreed deviations are listed in §0.
**Hard constraints:**
- 2 vCPU / 8 GB / no-GPU VPS, dedicated to this site
- Paid-API budget is $0; free tiers are allowed behind a fallback
- Everything Dockerized; modular monolith
- No fabricated numbers or data presented as real
- Enterprise-grade stack and repo
- The retired company microsite, the legacy demos and any UAV reference fully removed

**Changes at a glance:**
- **v3:**
  - Real, openly licensed data replaces synthetic data wherever real data can exist.
  - Groq's free tier is added behind a fallback chain.
  - A function-calling learning path runs across four projects.
  - P7 becomes a customer-support agent; P8 becomes an invoice-matching agent.
  - GIS is dropped. Eight flagships in total.
- **v4:**
  - New repo confirmed.
  - Research is reduced to one "under review" line.
  - CPU-only by design; an occasional GPU is a batch-job extra.
  - P8 replaces all organisation names with codes and uses neutral status wording.
  - Licence-plate blur added to P6.
- **v4.1:**
  - Research block now shows the paper title (D11 updated).
  - Python 3.13 in container images (3.12+ supported).
  - Development copy of the retailer dataset sourced from a verified mirror; production fetches from UCI (§4.1).

---

## 0. Decision log

| # | Decision | Consequences in this plan |
|---|---|---|
| D1 | Remove the retired company microsite | New repository with clean history. Live site, VPS and accounts decommissioned (§2). A CI denylist check keeps the retired company microsite out permanently |
| D2 | Remove old demos, start afresh | No legacy code carried over. The useful *ideas* return rebuilt: text-to-code becomes P2's SQL/pandas view; the image classifier becomes P3's "Try it" tab; the CSV analyzer becomes P2; the agents dashboard becomes P7/P8. Old `/demo/*` URLs → 301 to `/projects` |
| D3 | VPS hosts only this site; a small local model may run | llama.cpp container (1–2B, 4-bit) as private/offline LLM and fallback |
| D4 | No UAV; high-return CV on open videos | P6 Street Scene Intelligence. The Research section covers medical imaging and skin-lesion work only |
| D5 | Enterprise stack; per-project repos only if the workflow stays single | Next.js + TypeScript, FastAPI / SQLAlchemy / Alembic. Monorepo source of truth with auto-published per-project mirror repos. CI builds and deploys |
| D6 | **Groq free tier allowed** (other free tiers if they add something) | Provider chain: Groq → local model → deterministic. Daily token budget guard, two-model routing, optional Cerebras failover (§5.4) |
| D7 | **Learn function calling** | Function calling is designed in as a learning path: P2 (single call) → P4 (few tools) → P7 (full agent loop) → P8 (agent investigating a deterministic engine's output) |
| D8 | **One company across P1, P2, P5, P7, using real data that can be presented with confidence** | The company is a real, anonymised UK online gift retailer (UCI *Online Retail II*, CC BY 4.0). Real SEC filings serve as P5's real-company documents. Real UK public-sector payments + contracts (OGL v3) feed P8. Synthetic data is used only where real data cannot exist, and is labelled (§4) |
| D9 | **P7 = support agent, P8 = invoice matching agent, GIS dropped** | §7 P7 and P8 |
| D10 | **Create a new repo** | `reluai` under `uzairazhar89` is created as the first step of M0 when execution starts. The old repo is archived and made private |
| D11 | **Research: title + "under review at a Springer Nature journal"; no code, no results** (title approved 4 Oct 2026) | The homepage Research block shows: *"SHEL: A Knowledge-Guided Hybrid Representation Learning Framework for Efficient Multiclass Skin Lesion Classification"* — manuscript under review at a Springer Nature journal. No abstract, figures, metrics or code until accepted; a DOI link is added once published. The standalone `/research` page is dropped as too thin. Medical-domain credibility is also carried by P4. No skin-lesion demo is built, so nothing pre-empts the paper |
| D12 | **Laptop has no GPU; office GPU only occasionally, on-site** | Every project runs and is reproducible CPU-only; no milestone depends on a GPU. The brief's "optional local-GPU mode" becomes an optional **batch GPU job**: one packaged container run for P6 bulk precompute / intent v2 training, executed on free Kaggle notebooks or on the office PC only if your employer's policy allows personal use. No office data or code ever enters the repo. GPU-produced results are labelled with their hardware |
| D13 | **Avoid any risk of offending companies or legal trouble** | P8 shows real amounts, dates and categories, but **every organisation name is replaced by a stable code** (e.g., "Supplier S-0412", "Department D-01"). The source dataset is credited only on `/data`, as the licence requires. Statuses are reworded as neutral reconciliation states. P5's real-company filings are quoted with citations only, with no evaluative claims and a "not investment advice" note. P6 blurs faces **and licence plates** |

**Brief deviation:** brief §6 asked for synthetic datasets in P1. Per D8, real open data is used instead, and fault injection is kept only for failure scenarios.

**ADRs (recorded in repo):**
- **ADR-01:** Postgres = data + job queue + vectors + full-text search; no Redis.
- **ADR-02:** Images built in CI and pulled from GHCR.
- **ADR-03:** One global CPU lease for heavy work.
- **ADR-04:** Licence-cleared artifacts only; no AGPL by default.
- **ADR-05:** LLM provider chain and token budget.
- **ADR-06:** Data provenance labelling.

---

## 1. Starting point (why fresh)

The v1 audit found:
- **Fake outputs** in three demos.
- **Unsafe execution:** LLM-written pandas run through `eval()`.
- **Exposure:** every service published its own port past the firewall, including unauthenticated Redis.
- **Over-commitment:** ~11.7 GB of container limits on an 8 GB host.
- **Fragile startup:** nginx could only start with all three compose stacks up.
- **Repo hygiene:** `.gitignore` swallowed docs and data, ~57 MB of public images, and an unrelated tracked PDF.

A clean start is cheaper than repairing it. Only the domain, VPS, GitHub account and these lessons (as CI guardrails) carry over.

---

## 2. Retired microsite & legacy decommission checklist

| Area | Action | Verified by |
|---|---|---|
| Live site | Stop/remove legacy containers, images and volumes (after backup). Interim placeholder page. The retired microsite path → 410 Gone; legacy `/demo/*` → 301 `/projects`; legacy `/api/*` → 410 | `curl` checks; no legacy containers or images |
| VPS host | Remove the retired company microsite entries from host nginx, certbot configs, cron, `/opt/portfolio/.env`; delete the old checkout after backup | Host-wide search for the retired brand name returns nothing outside backups |
| Old repo `uzairazhar89/portfolio` | You archive it and make it private. Its history still holds the retired company microsite assets and the unrelated PDF; the new repo starts clean, so no rewrite is needed | Not publicly reachable |
| External accounts | Remove the GA property, Web3Forms key, Calendly/WhatsApp links and retired-brand DNS records; request removal of the retired microsite path in Search Console | Dashboards |
| New repo guard | CI fails if the retired brand name (any case) appears in source or build output | CI job |

---

## 3. Enterprise stack

| Layer | Choice | Why |
|---|---|---|
| Frontend | **Next.js (App Router) + TypeScript strict**, Tailwind + shadcn/ui (Radix), TanStack Query, Zod, self-hosted fonts | Enterprise-standard React. Static generation gives real per-page metadata, so link previews work |
| API contract | OpenAPI → generated typed TS client; CI fails on drift | End-to-end typing |
| Backend | **Python 3.12+ (3.13 in images), FastAPI, Pydantic v2, SQLAlchemy 2.0, Alembic** | Mainstream, typed, migration-managed |
| Jobs | Postgres-backed queue (e.g., Procrastinate), periodic tasks, advisory-lock CPU lease | No Redis |
| Data | **PostgreSQL 16 + pgvector** + full-text search; DuckDB sandbox for user CSVs | One database for everything relational, queue, vector and keyword |
| LLM access | One OpenAI-compatible client layer over Groq, optional Cerebras and local llama.cpp; tool definitions written once | Provider-agnostic function calling |
| ML inference | ONNX Runtime (CPU); PyTorch CPU only in the benchmark worker | CPU-optimised, permissive licences |
| Python tooling | uv workspace, Ruff, mypy strict, pytest + coverage, pre-commit | Reproducible, enforced |
| Frontend tooling | pnpm, ESLint, Prettier, Vitest, Playwright (mobile viewports), axe, Lighthouse CI | Standard QA |
| Edge | nginx: TLS (certbot webroot + reload), rate/body limits, CSP, HSTS | Only public entry point |
| Host provisioning | **Ansible**: Docker, ufw, fail2ban, unattended upgrades, deploy user, SSH hardening, backups | Repeatable clean environment |
| CI/CD | GitHub Actions: lint → types → tests → offline test → build → Trivy → SBOM → GHCR → gated deploy → mirror publish; Renovate/Dependabot, CodeQL | Supply-chain hygiene, reversible deploys |
| Observability | structlog JSON logs, `/healthz` `/readyz`, Prometheus `/metrics`, optional monitoring profile | Real monitoring within budget |
| Docs | Per-project README, architecture docs, ADRs, runbooks, CONTRIBUTING, CODEOWNERS, CHANGELOG | What clients and hiring managers look for |

**Accepted Next.js trade-off:** ~90–110 KB gzipped baseline JavaScript plus a ~256 MB Node container. The performance targets in §8 reflect this.

---

## 4. Data strategy: real where possible, labelled where not

### 4.1 Sources

| Source | What it is | Licence / terms | Used in |
|---|---|---|---|
| **UCI Online Retail II** | 1,067,371 real invoice lines from a UK-registered online gift retailer, 1 Dec 2009 – 9 Dec 2011: invoice no. (C-prefix = cancellation), stock code, description, quantity, date, unit price (GBP), customer ID, country. Anonymised: no company or customer names. Production fetches the canonical UCI archive; development may use a mirror (the `onlineretail2` R package on GitHub), accepted only if it passes the same content checks (row count, columns, date range, content fingerprint) | **CC BY 4.0** per the current UCI page; cite Chen (2012), DOI 10.24432/C5CG6D | P1, P2, P5 (invoice extraction ground truth), P7 |
| **SEC filings** (annual/quarterly reports of a real listed company, ideally a retailer to stay on theme) | Real company documents with financial statements | SEC: information on sec.gov "may be copied or further distributed … without the SEC's permission"; cite the SEC; **no SEC seal/logos or the "EDGAR" trademark** in the UI | P5 (document Q&A with citations) |
| **UK government "spend over £25,000"** (one department, monthly files) | Real payments to real suppliers. **Organisation names replaced by codes in the demo** | **Open Government Licence v3.0** (OGL doesn't cover personal data; rows naming individuals are excluded) | P8 |
| **UK Find a Tender / Contracts Finder award notices** (same department) | Real contract awards (Open Contracting Data Standard JSON). Names replaced by the same codes | **Open Government Licence v3.0** | P8 |
| **FATURA** | 10,000 invoice images, 50 layouts. **Synthetic**, labelled as such | CC BY 4.0 | P5 (layout variety for extraction) |
| Biomedical open-access corpus + MeSH | See P4 | Per-record licence check | P4 |
| Licence-cleared street/dashcam footage | See P6 | Per-clip licence | P6 |

### 4.2 Why there are no "real company invoices from stock exchange results"

Listed companies publish financial statements, not invoices; invoices are confidential everywhere. The closest real, openly licensed equivalents are:
- **Line-level sales invoices** of a real (anonymised) retailer: Online Retail II.
- **Payment-level records** of real public bodies: UK spend data.

Real invoice *documents* under a clean licence are essentially unavailable. So document extraction uses:
- Invoices **rendered from the real Online Retail II records**. This also gives exact ground truth, so extraction accuracy is measured, not estimated.
- FATURA, for layout variety.

Both are labelled.

Pakistan Stock Exchange annual reports are public but carry no clear reuse terms like the SEC's, so SEC filings are the confident choice.

### 4.3 What stays synthetic (and is always labelled)

Things that can't exist publicly:
- Shipment tracking events
- Customer support messages and tickets
- The retailer's returns/refund policy text (written for the demo)
- Failure injections (source outages, malformed drops)

These are generated deterministically from a seed and **linked to real invoice numbers**.

### 4.4 Presentation rules

- Every demo shows a provenance badge: **Real data · source** or **Synthetic · why**.
- A `/data` page lists every dataset: source, licence, attribution text, what was changed, and what is synthetic.
- Real dates stay as published (2009–2011 for the retailer). Nothing is shifted to look recent.
- **No organisation is ever named next to an automated judgement.** P8 uses codes for every supplier and buyer. P5 only quotes a filing company's own text with citations: no ratings, predictions or "risk" verdicts about it, and a "not investment advice" note.
- **People are never identifiable:** faces and licence plates are blurred in P6, and retailer customers remain anonymous IDs.

### 4.5 The "company" across projects

**P1** ingests the retailer's real invoices → **P2** analyses them → **P5** extracts and answers questions over its invoices (plus real SEC filings) → **P7**'s support agent serves its real customers' real invoices.

One coherent business story: built on real transactions, with every synthetic addition visible.

---

## 5. Repository, delivery & runtime

### 5.1 Monorepo with per-project mirrors

```
reluai/                       ← the only repo you commit to
├─ apps/        web (Next.js) · api (FastAPI composition root + worker entrypoint)
├─ packages/    platform-core · retrieval · inference (LLM provider chain, tools runtime) · datasets (loaders + provenance)
├─ projects/    pipeline-observatory · csv-analyst · edge-bench · research-search · rag-lab
│               · street-scene · support-agent · invoice-matching
│               (each: package · tests · README · data manifest · standalone compose)
├─ infra/       compose profiles · nginx · ansible · backup
├─ artifacts/   manifest: models/datasets/footage → source URL · SHA-256 · licence · attribution
├─ docs/        architecture · ADRs · runbooks
└─ .github/     ci · release · deploy · mirror
```

- CI publishes each `projects/<x>` plus its shared packages as a standalone, read-only, runnable public repo, so each project card links to its own repo.
- Large artifacts are fetched at image build with checksum verification, never at container start.

### 5.2 Delivery flow

```
Laptop (WSL2 + Docker, staging profile, CPU-only) → one commit/push
 → PR checks (lint · types · tests · offline test · contract · Lighthouse · Trivy)
 → merge → build images (tag = SHA) → GHCR + SBOM
 → your one-click production approval → SSH deploy user → VPS: pull · migrate · restart · health gate
   · auto-rollback on failure
 → mirror job refreshes per-project repos
```

- **Fallback:** one documented VPS command.
- **Line endings:** `.gitattributes` forces LF.

### 5.3 Container topology (VPS)

```
             Internet — only 80/443 published
                          │
          ┌───────────────▼────────────────┐
          │ nginx  TLS · limits · headers   │
          └─────┬────────────────────┬──────┘
                │ pages              │ /api/*
         ┌──────▼──────┐     ┌───────▼───────┐       ┌────────────────────┐
         │ web Next.js │────►│ api FastAPI   │◄─────►│ worker             │
         └─────────────┘     │ tools runtime │ jobs  │ pipelines · bench  │
                             │ provider chain│       │ ingestion · video  │
                             └──┬─────────┬──┘       │ agent batch runs   │
                                │         │          └──┬──────────────┬──┘
                                │   ┌─────▼───────────▼┐              │
                                │   │ llm (llama.cpp)  │              │
                                │   └──────────────────┘              │
                                │   outbound HTTPS → Groq (+ optional Cerebras), budget-guarded
                         ┌──────▼─────────────────────────────────────▼───┐
                         │ postgres 16 + pgvector — data · queue · vectors │
                         │ · FTS · CPU lease · token budget ledger         │
                         └─────────────────────────────────────────────────┘
```

### 5.4 LLM provider chain

| Order | Provider | Role | Notes |
|---|---|---|---|
| 1 | **Groq free tier** | Best-quality answers and multi-step tool calling (P7, P8 agents; P5 answers; P2/P4 fallbacks) | Current free limits for `gpt-oss-120b` / `gpt-oss-20b`: ~30 req/min, 1,000 req/day, **8K tokens/min, 200K tokens/day**; tool calling supported. Catalogue changes often (Llama 3.3 70B left the free tier in Aug 2026), so model names live in config |
| 1b | Cerebras free tier (optional) | Failover serving the same `gpt-oss-120b` | Same tool definitions; verify terms at setup |
| 2 | **Local llama.cpp** (1–2B, 4-bit) | Private/offline mode and fallback | Slower, weaker at multi-step tools; measured and labelled |
| 3 | **Deterministic** | Always-available baseline | Intent parser, extractive answers, scripted agent plans |

**Guardrails:**
- **Token ledger** in Postgres with a daily budget kept below Groq's caps.
- **Per-visitor caps** and a reserved slice for scheduled "showcase" runs.
- **Automatic fall-through** to the next provider when the budget or rate limit is hit.
- **Model routing:** `gpt-oss-20b` for cheap steps (tool selection, classification), `gpt-oss-120b` for final answers. Limits are per model, so this roughly doubles capacity.
- **Answer badge:** provider, model, tokens, latency.
- **Privacy:** visitor-uploaded content goes to Groq only after an explicit opt-in notice; bundled public data needs none.
- **Key handling:** the key stays server-side.
- **Offline CI:** proves every demo still works with outbound network disabled.

**Rough capacity (estimates, measured in M2):**
- ~60 RAG answers/day, or
- ~10–13 full agent runs/day per model.

The free tier suits portfolio traffic plus recorded showcase runs.

### 5.5 CPU lease & resource budget

- One global lease covers local-LLM generation, benchmarks, video jobs, ingestion and pipeline runs.
- Groq calls don't take the lease; they're bounded by the token ledger.
- Queue depth is capped; beyond it the API returns 429 with a friendly message.

| Service | RAM limit | CPU cap |
|---|---|---|
| nginx | 64 MB | 0.25 |
| web (Next.js) | 256 MB | 0.5 |
| api | 1.0 GB | 1.0 |
| worker | 1.5 GB | 1.0 |
| llm (llama.cpp) | 2.0 GB | 1.5 |
| postgres + pgvector | 768 MB | 0.75 |
| **Total** | **~5.6 GB** (≈2.4 GB headroom) | caps, not reservations |

Optional monitoring profile: +~300 MB, enabled only if measured headroom allows.

### 5.6 Demo-safety layer (shared)

- **Rate and body limits** per route.
- **File checks:** magic-byte/MIME/extension validation; row/page/pixel/duration caps; image re-encode + EXIF strip; sandboxed video and PDF parsing with time/memory caps.
- **No code paths from user input:** no `eval`/`exec`/shell/user SQL; LLM output is data, never code; tool arguments validated against schemas before execution.
- **No real side effects from agents:** "send email", "issue refund" and "approve" are simulated and logged.
- **Databases:** DuckDB sandbox locked down; Postgres least-privilege roles + `statement_timeout`.
- **Uploads:** TTL deletion; never logged.
- **Browser:** CSP/HSTS; formula-safe CSV export.
- **Privacy:** face blur in P6 outputs.

---

## 6. Function-calling learning path

| Step | Project | What you learn |
|---|---|---|
| 1 | **P2 CSV Analyst** | One tool, one call: a strict JSON-schema query plan; argument validation; sending errors back for a retry; structured outputs |
| 2 | **P4 Research Search** | A few tools (search corpus, look up MeSH term, fetch record); the model chooses order; final answer with citations; multi-turn loop |
| 3 | **P7 Support Agent** | Full agent loop: multi-step plans, parallel calls, conversation state, retries, human approval before actions, tracing, scenario evaluation |
| 4 | **P8 Invoice Matching** | Agent over a deterministic engine's output: batch investigations, evidence gathering, structured findings, human review, measuring agent-vs-human agreement |

The loop is written by hand against the OpenAI-compatible API first. A framework (e.g., LangGraph for approval/resume) is considered only for P7/P8, after the basics are understood. The same tools run against Groq and the local model, and the reliability comparison is published.

---

## 7. Flagship projects (8)

All project pages follow the brief's 12-section template, with mode badges (**Live** · **Precomputed** · **Groq** / **Local LLM** / **Deterministic**) and provenance badges. Every number renders from a stored run (ID, date, hardware/provider).

### P1 — Data Pipeline Observatory · *Python / ETL / data engineering*

```
Real retailer invoices delivered as: monthly CSV drops · JSON product catalogue (derived) · REST-style paginated
customer/country source (internal mock serving real records, fault-injectable)
 → extract (retries, backoff, timeouts) → validate (schema + business rules; rejects → quarantine w/ reason codes)
 → transform (cancellations, returns, non-product codes, dedupe, normalise descriptions) → idempotent load
 → DQ checks (completeness · uniqueness · validity · referential integrity · freshness) → metrics + logs → dashboard
```

- **Real defects, not invented ones:** missing customer IDs, cancellations, negative quantities, zero/odd prices, non-product stock codes, duplicates, inconsistent descriptions. Their rates are measured and shown.
- **Simulated failures** (source outage, malformed drop) are injected and labelled.
- **MVP:** CSV + REST sources, core checks, dashboard. **Later:** schema-drift scenario, lineage view.

### P2 — AI CSV Analyst · *data apps / NL→SQL · function calling step 1*

```
Upload (or bundled retailer extract) → profile → validation report → question
 → deterministic intent parser ──(no match)──► LLM tool call: fill Query Plan schema (Groq → local)
 → validator → compiler → parameterised SQL → DuckDB sandbox → table + chart
 → "Interpreted as" panel + "Show as SQL / pandas" tab (code generated from the validated plan, never executed from LLM text)
```

- **MVP:** profiling, ~10 deterministic patterns, LLM fallback, charts, SQL/pandas view.

### P3 — Edge AI Benchmark Lab · *CV / model optimisation*

- **Registry:** classifiers (e.g., MobileNetV3-S, ResNet-18) plus P6 candidate models.
- **Variants:** PyTorch FP32 / ONNX FP32 / ONNX INT8.
- **Runner:** isolated subprocess.
- **Metrics:** latency p50/p95, throughput, size, RSS, CPU%, pre/infer/post split, INT8 agreement; hardware fingerprint on every report.
- **"Try it" tab** (the old classifier, done properly): upload a photo and see the top-5 from each variant side by side with timings.
- **Explainers:** why ONNX and quantisation, the trade-offs, when CPU is enough, what changes on edge hardware.

### P4 — Research Search Intelligence · *medical/research domain · function calling step 2*

```
Licence-cleared biomedical corpus (dermatology · skin lesions · medical image analysis) → ingestion → metadata
 → research question → PICO analysis → tools: search corpus · expand MeSH term · fetch record
 → hybrid search (FTS + pgvector, rank fusion) → filters → structured results with "why this matched"
```

- Works without any LLM: the deterministic path does concept expansion and search.
- **Optional:** live PubMed toggle with bundled fallback.
- **Disclaimer:** "This is a research/technical demonstration and not medical advice."
- **Results:** recall@k published.

### P5 — Document Intelligence / RAG Lab

```
Docs: real SEC filings · retailer invoices rendered from real records · FATURA (synthetic) · visitor uploads (capped)
 → parse → chunk (inspectable) → embed (ONNX) → hybrid index
 ├─ Q&A tab: retrieve → answer (deterministic extractive | local LLM | Groq), numbered citations, abstention
 └─ Extraction tab: invoice → structured JSON/CSV via schema-constrained output → validated (totals add up, dates parse)
```

- **Extraction accuracy:** measured field-by-field against the real source records.
- **SEC filings:** answers quote and cite the filing only; no evaluative or investment statements about the company; SEC credited; no SEC logos or trademarks.
- **Q&A comparison:** extractive vs local vs Groq on the same question set (faithfulness, citation precision, latency, token cost). This answers "when is a small model enough?"

### P6 — Street Scene Intelligence · *detection · tracking · pose · intent*

```
Licence-cleared street-camera + urban dashcam clips → detect → track → pose → per-track features
 (zones, velocity/heading, body/head orientation, walking vs standing, vehicle proximity)
 → crossing-intent estimate (+ feature contributions) · zone counts · dwell · near-miss (time-to-collision)
 → face + licence-plate blur → JSON tracks/events + compressed clip → web player with toggleable overlays + timeline + report
```

- **Models:** Apache-2.0/MIT candidates chosen in P3; no AGPL.
- **Intent v1:** explainable scoring. **Intent v2:** trained on self-labelled tracks; the labelling protocol is published.
- **Modes:** precomputed full clips; live zone re-scoring; ≤10 s uploads queued under the CPU lease.
- **Compute:** precompute runs CPU-only on the laptop (short clips, overnight runs are fine). The optional batch GPU job (Kaggle, or the office PC if permitted) only speeds up bulk precompute and intent v2 training. Outputs are labelled with the hardware used.

### P7 — Customer Support & Order Operations Agent · *AI automation · function calling step 3*

```
Customer message (choose a scripted scenario or type your own) about a REAL retailer invoice
 → agent loop (Groq gpt-oss: 20b routes, 120b answers → local → scripted fallback)
   tools: get_invoice · list_customer_invoices · get_shipment_status (synthetic, linked) · search_policy (P5 retrieval)
          · calculate_refund (deterministic rules) · create_ticket · draft_reply · request_approval
 → refunds/credits above threshold pause for human approval (visitor plays the supervisor)
 → reply draft + full trace (each step's tool, arguments, result, tokens, latency)
```

- **Real:** customers, invoices, products, quantities and prices.
- **Synthetic (labelled):** shipments, tickets, messages, policy text.
- **Nothing is ever sent.**
- **Evaluation:** a fixed set of 30–50 customer scenarios with expected outcomes; success rate per provider published.

### P8 — Accounts-Payable Invoice Matching Agent · *AI automation · function calling step 4*

```
Real UK department data: monthly "spend over £25k" payments (OGL v3) + its contract awards (OCDS, OGL v3)
 → P1-style ingestion (real schema drift across months handled) → supplier entity resolution
   (name normalisation, fuzzy match) on the real names, inside the pipeline only
 → pseudonymisation: every supplier and buyer name → stable code before anything is stored for display
 → deterministic two-way matcher (payment ↔ award: supplier, dates, cumulative spend vs award value)
 → reconciliation states (neutral wording):
     Reconciled · Reconciled (partial) · No linked award found · Cumulative payments above recorded award value
     · Repeated identical amount · Ambiguous match
 → agent works the open items with tools: search awards · supplier payment history · cumulative totals
   · award details → evidence-backed note → human reviewer marks "explained" / "needs more data" → audit trail
```

- **Honest scope:** public data has awards and payments but no goods receipts, so this is a **two-way match on real data**. A three-way match would need synthetic receipts and is a "later" option.
- **What an open item means:** the matcher couldn't automatically link a payment to a published award. Usual benign causes are framework agreements, contracts below publication thresholds, multi-year awards and name variations. It is a workflow state, as in any AP system, **not** a finding of error or wrongdoing, and the page says so.
- **Why codes and not names:** the licence permits names, but an automated system placing a real company next to a word like "exception" can be misread as an accusation, and fuzzy matching can be wrong. Codes keep the engineering fully real while removing that risk.
- **Measured:** reconciliation rate, open items by state, agent-vs-reviewer agreement on a reviewed sample.

---

## 8. Website

| Route | Content |
|---|---|
| `/` | Hero (title, value proposition, View Projects / Hire Me / GitHub) → 8 flagship cards with **role filter chips** (Data Engineering · AI/LLM & Agents · Computer Vision · Research) → What I Build → Engineering Capabilities → **Research block**: the SHEL paper title with "manuscript under review at a Springer Nature journal" (no results or code), plus links to P4 (medical domain) and P6 (specialised CV) → How I Work → Contact |
| `/projects/<slug>` | 12-section pages; demo = section 6; GitHub → that project's mirror repo |
| `/data` | Provenance register: every dataset, licence, attribution, real vs synthetic, what was pseudonymised |
| `/hire` · `/status` · `/privacy` | Contact (Postgres + optional SMTP, rate-limited) · live health · upload, video and LLM-provider data handling |

- **SEO:** Next.js metadata API, generated OG images, JSON-LD, sitemap, canonicals; no keyword stuffing.
- **Performance targets (mobile, Lighthouse CI):** Accessibility/SEO ≥ 95, Performance ≥ 90; LCP < 2.5 s, CLS < 0.1; content pages ≤ ~130 KB gzipped first-load JavaScript; demo bundles lazy-loaded.
- **Design:** dark technical tokens, sans + mono pair, dense cards, real run output, restrained motion, WCAG AA.

---

## 9. Milestone roadmap

Sizes are relative: S < M < L. Each project ships publicly when its milestone closes.

| # | Milestone | Size | Scope | Exit criteria |
|---|---|---|---|---|
| **M0** | Baseline & repo bootstrap | S | VPS snapshot + backups; **create `reluai` repo**; ADRs; old repo archived/private; Groq (and optional Cerebras) keys created | Rollback point; CI green on skeleton |
| **M1** | Decommission | S | §2 checklist; placeholder page | Retired microsite gone from live site; only 80/443 open |
| **M2** | Platform | L | Ansible; Compose profiles; nginx/TLS; Postgres+pgvector; api/worker; queue + CPU lease; safety layer; **provider chain + token ledger + llama.cpp**; health/metrics/logs; backup + restore drill; CI/CD with gated deploy/rollback; Next.js shell + design system; `/data` page scaffold | One-click deploy/rollback proven; restore drill passes; Groq quota and local-LLM tokens/s measured |
| **M3** | **P1** on real retailer data → **first public release** | L | P1 MVP + homepage v1 | Real DQ rates measured; failure scenarios behave as documented |
| **M4** | **P2** (function calling step 1) | M | P2 MVP incl. LLM fallback + SQL/pandas view | Injection/abuse suite passes; schema-violation retries logged |
| **M5** | Retrieval core + **P5** | L | Retrieval package; SEC filings + rendered invoices + FATURA; Q&A + extraction; provider comparison | Extraction accuracy vs real records published; QA eval in CI |
| **M6** | **P7** support agent (step 3) | L | Tools, agent loop, approval flow, trace viewer, scenario suite | Per-provider success rate published; no real side effects possible |
| **M7** | **P3** Edge Benchmark Lab | M | Registry, variants, runner, Try-it tab, P6 candidates | Hardware-fingerprinted reports; P6 model choice justified |
| **M8** | **P8** invoice matching agent (step 4) | L | Department selection after data profiling; ingestion; entity resolution; pseudonymisation; matcher; agent investigations; reviewer UI | Reconciliation rate + agent-vs-reviewer agreement published; no real organisation name in any API response, page or export (automated test) |
| **M9** | **P4** Research Search (step 2 tools) | M | Corpus licence check, ingestion, MeSH, hybrid search, tools | Recall@k published; works with PubMed unreachable |
| **M10** | **P6** Street Scene Intelligence | L | Footage licences, CPU offline pipeline (+ optional batch GPU job), labelling, intent v1, player, live re-scoring | Measured throughput; caveated intent metrics; faces and plates blurred |
| **M11** | Website completion | M | All sections incl. Research block, filters, SEO/OG, accessibility/performance pass | Lighthouse targets met; every figure traceable |
| **M12** | Hardening, mirrors, launch | M | Mirror repos live; clean Ansible rebuild; brief §22 test matrix; load test at limits; final docs incl. dependency/licence/attribution list and measured resource requirements | Every §11 deliverable ticked with evidence |

**Note on order:** the function-calling steps run P2 → P7 → P8 → P4 in delivery. P4's tools are simpler, but P4 ships later because P7/P8 have higher job-market value. Step 2 can be practised on a P4 prototype during M5 if you want the gentler ramp.

---

## 10. Key risks & mitigations

| Risk | Mitigation |
|---|---|
| Groq free tier shrinks, changes models or rate-limits | Provider chain with automatic fall-through; model names in config; contract tests per provider; token ledger; recorded showcase runs |
| Visitor data sent to a third party | Opt-in notice for uploads; bundled public data by default; `/privacy` explains providers |
| Agents take harmful or wrong actions | All actions simulated; approval gates; schema-validated tool arguments; published success rates |
| Any organisation feeling accused or misrepresented | P8 codes replace all names; neutral reconciliation states; P5 quotes filings only; no evaluative claims about named entities; automated test that no real organisation name leaks into P8 output |
| Using office hardware for personal work | GPU never on the critical path; office PC used only if employer policy permits; Kaggle as the default GPU option; no office data/code in the repo |
| Research entry compromising the paper's review | Title and status only; no abstract, results or code until accepted; DOI added after publication |
| Licence/attribution mistakes | Artifact manifest with licence + attribution per item; `/data` register; CI check; no SEC logos/trademarks |
| CPU contention on 2 vCPU | CPU lease, bounded queue, subprocess isolation, caps |
| Scope (8 flagships) | MVP cut per project; public release from M3; deferred items explicit |
| Next.js weight | Server components, static generation, lazy demo bundles, CI budgets |

---

## 11. Brief deliverables → milestones

| Brief §22 deliverable | Where |
|---|---|
| Updated website | M3 (v1) → M11 |
| Source code · Docker config | M2 onward; mirrors M12 |
| DB schema/migrations · seed/sample data | M2, M3–M10 (real data + labelled synthetic) |
| README · deployment · env-var docs | M2 → M12 |
| Architecture diagrams | M2 + each project |
| Tests · health check · logging · error handling | M2 framework, every milestone |
| Backup / recovery | M2 drill, M12 runbook |
| External dependency list · exact resource requirements | M12 (measured) |
| Clean-environment run + full test matrix | M12 |

---

## 12. Status of open items

All earlier questions are resolved (D10–D13). Go-ahead given 4 Oct 2026.

Execution notes:
- The `reluai` repository is built locally with full history. Creating it on GitHub needs either an empty `uzairazhar89/reluai` repo or a linked GitHub account; neither is available from the build workspace yet.
- VPS steps (snapshot, M1 decommission, first deploy) need SSH access, so they are delivered as runbooks and scripts for you to run.
