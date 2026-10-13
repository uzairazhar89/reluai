# Document Q&A

Upload a PDF, including a scanned one, and ask questions about it. Every answer quotes or
cites the passages and pages it came from, and when the document does not cover a question
the answer says so instead of guessing. Works with no language model; uses one (Groq or a
local model) only when configured and, for uploads, only with the visitor's consent. Live
demo: <https://reluai.cloud/projects/document-intelligence>.

## How it works

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

## Run it

```bash
uv sync --all-packages
reluai-docs fetch                 # model + sample PDF, SHA-256 checked
reluai-docs build-sample          # read, index and embed the sample into sample.json
reluai-docs ask "What are the four functions of the AI RMF core?"
reluai-docs evaluate --show       # the question set; add --provider groq with a key
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

## Data and models

- Sample: NIST AI 100-1, *Artificial Intelligence Risk Management Framework (AI RMF 1.0)*,
  a work of the US Government. <https://doi.org/10.6028/NIST.AI.100-1>
- Embeddings: BAAI bge-small-en-v1.5, MIT licence.
- OCR: PaddleOCR PP-OCRv6 small, packaged by RapidOCR, Apache 2.0.

Pins and hashes are in [`artifacts/manifest.yaml`](../../artifacts/manifest.yaml).
