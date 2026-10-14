# Document Intelligence

Two things done with the same isolated PDF reader (text layer or OCR):

- **Ask a document.** Upload a PDF, including a scanned one, and ask questions about it.
  Every answer quotes or cites the passages and pages it came from, and when the document
  does not cover a question the answer says so instead of guessing.
- **Read an invoice.** Turn an invoice into structured fields (number, date, customer,
  country, line items, total) that are checked by arithmetic before anyone relies on them.
  Accuracy is measured against real retail records the test invoices were drawn from.

Works with no language model; questions use one (Groq or a local model) only when
configured and, for uploads, only with the visitor's consent. Live demo:
<https://reluai.cloud/projects/document-intelligence>.

## How questions are answered

```
upload (API) ─► size and signature checks ─► in-memory spool ─► job (worker, CPU lease)
                                                                   │
  isolated reader process (no secrets; memory, CPU-time and write caps; wall-clock kill)
    ├─ text layer: PDFium, each line with box, font size and weight
    └─ scanned pages: PP-OCRv6 small (RapidOCR, ONNX Runtime, CPU), up to 5 per document
                                                                   │
  layout: running headers/footers removed · headings and paragraphs rebuilt · page map
  passages: ~150-word exact spans under their heading path (packages/retrieval)
  index: PostgreSQL full-text (headings weighted) + bge-small-en-v1.5 vectors in pgvector

question (API) ─► hybrid retrieval (keyword + vector, reciprocal-rank fusion)
               ─► extractive answer (quotes + citations, or abstains)
               ─► or a model through `answer` / `not_in_document` tools, citations checked
```

- **Reader** (`pdfread.py`, `child.py`, `isolation.py`): the child process caps its own
  address space, CPU time and file writes before reading; the parent kills it at the
  deadline. Password-protected, damaged and non-PDF files get specific messages.
- **Layout** (`layout.py`): lines repeated in the page margins on many pages are dropped;
  lines set larger than the body text, or short standalone bold or capitalised lines,
  become headings (up to three levels; weak signals are ignored when too many lines
  qualify, as in slides) and nest by size, then under the heading with their parent number;
  a bold label ending in a colon ("GOVERN 1:") runs into its text. Paragraphs break on
  spacing, bullets, indents and short closing lines and continue across pages. A hyphen at
  a line end is dropped unless the document itself uses the hyphenated word
  ("context-specific") or both halves as words and never the joined form.
- **Embeddings** (`embedding.py`, `wordpiece.py`): BAAI bge-small-en-v1.5 (384 dimensions,
  MIT) in ONNX Runtime, quantised to 8-bit weights at image build time, with a pure-Python
  WordPiece tokenizer (token ids match the reference implementation), so no tokenizer
  library or download machinery is needed at run time.
- **Retrieval** (`packages/retrieval`): keyword and vector rankings merged by reciprocal-rank
  fusion; for "what is X" questions a third ranking favours passages that define X.
- **Answers** (`answer.py`): extractive by default. Sentences are scored by IDF-weighted
  word overlap with the question and embedding similarity; the best must clear either
  threshold (0.52 overlap or 0.65 similarity) or the answer abstains. A model answers only
  through `answer` (citations checked against the passages it was given, one retry) or
  `not_in_document`.
- **Service** (`service.py`, `api.py`, `tasks.py`): upload, processing, questions, the
  passage explorer, deletion, expiry after an hour and the daily evaluation.

## How invoices are read

```
invoice PDF ─► isolated reader (segments=True): text cells, or deskewed OCR boxes
           ─► rows ─► item table: header row by column names, or the row above the first item
           ─► columns: boundaries at the emptiest strip of the body; roles from the heading,
                       or from content (whole numbers, the money column = qty × the other)
           ─► items (wrapped descriptions joined; resumes after page breaks), then totals
           ─► header fields: label beside or above the value; unknown labels by elimination
           ─► checks: qty × unit price = amount, lines add up to the total, number and date
                      present, sign fits the document type ─► needs review, or not
```

- **Segments** (`pdfread.py`): on the text layer a cell is the text between gaps that PDFium
  bridges with *generated* spaces (no space character in the file), so a description stays
  one piece while neighbouring cells do not; with OCR each detected box is a segment,
  rotated back by the median slope of the boxes.
- **Extraction** (`invoices/extract.py`): no model and no layout templates; the vocabulary
  of labels and headings was written from the development layouts only.
- **Test invoices** (`invoices/records.py`, `render.py`, `scan.py`): 96 real invoices from
  UCI Online Retail II (stratified by length, with credit notes and invoices without a
  customer), each drawn with ReportLab in a layout generated from a seed (labels, column
  order and wording, date and number formats, fonts, rules, wrapping, page breaks); 28 also
  as simulated scans (rasterised at 150 dpi, rotated by up to 1.2°, blurred, grey noise,
  JPEG). Every page says it is a rendering of dataset records.
- **Scoring** (`invoices/evaluate.py`): every header field, the total and each of the five
  values of every line against the record; lines are paired in order by stock code. A
  document is exact only if everything is right and no line is missing or extra.

## Run it

```bash
uv sync --all-packages
reluai-docs fetch                 # model + sample PDF, SHA-256 checked
reluai-docs build-sample          # read, index and embed the sample into sample.json
reluai-docs ask "What are the four functions of the AI RMF core?"
reluai-docs evaluate --show       # the question set; add --provider groq with a key

reluai-docs invoices build --canonical data/canonical/online-retail-ii.parquet
reluai-docs invoices evaluate --show   # every invoice, read and compared with its record
```

Tests: `uv run pytest projects/document-intelligence` (the API tests need
`TEST_DATABASE_URL`, see the repository README; `test_real_sample.py` runs when the model and
sample are installed and checks the tokenizer against reference ids and the sample's
structure).

## Results

`reluai-docs evaluate` asks the 40 questions in `questions.py` about the sample: 30 with the
page and the facts a correct answer must contain, 10 the document does not answer (correct
response: abstain). Checks are mechanical. The set is split in two halves, alternating
within each kind; the abstention thresholds were chosen by a grid search on the dev half only
(the centre of the best-scoring plateau) and the held-out half was then scored once.

Development machine, 2 CPU cores, 13 October 2026, extractive answers (no model):

| Embedding model | Correct | Dev half | Held-out half | Right page retrieved | Median / p95 time |
| --- | --- | --- | --- | --- | --- |
| INT8 (deployed) | 32 of 40 | 19 of 20 | 13 of 20 | 93.3% | 186 / 314 ms |
| FP32 | 33 of 40 | 19 of 20 | 14 of 20 | 93.3% | 382 / 681 ms |

The INT8 model embeds a passage in 22 ms against 54 ms and needs 121 MB once loaded against
263 MB; its vectors have a median cosine of 0.998 with the full model's. The one question
the two disagree on is an unanswerable one the full model abstained on.

Where the extractive mode goes wrong, from the INT8 run:

- **Close-to-topic questions the document does not answer** (4 of the 8 misses: a maximum
  false-positive rate, incidents reported in 2022, a recommended programming language,
  NIST's headcount). A loosely related sentence clears the thresholds and is quoted. The
  dev half's unanswerable questions happened to all be off-topic, so the tuning never saw
  this case; it is what the gap between the halves measures, and what a model with a
  `not_in_document` tool is for.
- **Right passage, wrong sentences** (2): the answer to "Is the AI RMF mandatory?" is
  "voluntary", which shares no words with the question.
- **Retrieval misses** (2): "Who are AI actors?" and "When is an AI system considered
  safe?" rank broader passages first.

The server re-runs the set daily and the project page shows that run, so its figures come
from the server rather than from this table.

### Invoices

`reluai-docs invoices evaluate` reads all 124 documents through the isolated reader (as an
upload is read) and compares every value with the record. Development machine, 2 CPU
cores, 14 October 2026:

| Group | Documents | Read exactly | Lines fully right | Flagged | Wrong, not flagged | Median time |
| --- | --- | --- | --- | --- | --- | --- |
| Development layouts, PDF | 48 | 48 | 100% | 0 | 0 | 0.13 s |
| Development layouts, scanned | 14 | 14 | 100% | 0 | 0 | 5.2 s |
| Held-out layouts, PDF | 48 | 48 | 100% | 0 | 0 | 0.13 s |
| Held-out layouts, scanned | 14 | 10 | 79.3% | 2 | 2 | 4.9 s |

How to read it:

- The extractor was developed until the development groups were right, so those rows show
  that it works, not how well it generalises. Held-out layouts use seeds (1001 to 1012) that
  were not rendered or read until the extractor was frozen, and draw some labels and column
  headings from wordings reserved for them ("Pcs", "Net", "Document ref.", "Balance due").
  The held-out set was run once with the frozen extractor; the figures above are that run.
- Before freezing, the extractor was also stress-tested on development invoices with
  wordings invented for the test (not the reserved ones) and on a second set of scans of
  every development invoice; those runs found the problems fixed in development (OCR
  joining a quantity to its description, headings split by OCR, totals with unfamiliar
  labels) and are not part of the published figures.
- Of the four held-out scans not read exactly, two were flagged by the checks and two were
  not. Flagged: a quantity "-7" that OCR read as "L-", and a 22-line invoice whose headings
  "EACH (GBP)" and "AMOUNT (GBP)" OCR split as "EACH" and "(GBP) AMOUNT (GBP)", which merged
  the price and amount columns so no line multiplied out. Not flagged: two descriptions (an
  "I" read from a ruling line; "BAG , PINK" read as "BAG, PINK"). The checks cover numbers,
  not text.
- Text PDFs take about a tenth of a second including starting the reader process; scans
  take about five seconds, nearly all of it OCR.

## Data and models

- Invoices: Chen, D. (2012). Online Retail II. UCI Machine Learning Repository,
  <https://doi.org/10.24432/C5CG6D>, CC BY 4.0. Rendered as documents for evaluation; the
  retailer is not named.

- Sample: NIST AI 100-1, *Artificial Intelligence Risk Management Framework (AI RMF 1.0)*,
  a work of the US Government. <https://doi.org/10.6028/NIST.AI.100-1>
- Embeddings: BAAI bge-small-en-v1.5, MIT licence.
- OCR: PaddleOCR PP-OCRv6 small, packaged by RapidOCR, Apache 2.0.

Pins and hashes are in [`artifacts/manifest.yaml`](../../artifacts/manifest.yaml).
