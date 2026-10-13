# 0009. Uploaded documents are read in an isolated process; answers must cite them

Date: 2026-10-11. Status: accepted.

## Context

Document Q&A (P5) accepts any PDF from any visitor. PDF parsers and OCR are large native
code bases fed with untrusted input: a malformed file can hang them, exhaust memory or
crash the process. The visitor's file may be private. And answers from documents are only
useful if they can be checked, which generic "chat with your PDF" tools rarely allow.

## Decision

1. **Isolation.** Every PDF is read by a short-lived child process
   (`python -m reluai_docs.child`) started with a minimal environment (no database URL or
   API keys). Before reading input it caps its own address space, CPU time and file writes;
   the parent kills its process group at a wall-clock deadline. Its output is plain data
   (lines with positions), parsed by the parent; nothing it returns is executed.
2. **Where the work runs.** The API only validates the upload and hands the bytes to the
   worker through an in-memory volume; the worker reads, indexes and embeds under the global
   CPU lease (ADR-0003). The file is deleted as soon as it is read; extracted text expires
   after an hour and can be deleted at once.
3. **Grounded answers.** Retrieval is hybrid (PostgreSQL full-text and pgvector embeddings,
   ADR-0001). The default answerer is extractive: it quotes retrieved sentences with their
   passage numbers and abstains when nothing covers the question. A model may write the
   answer only through a tool that requires citations; citations are checked against the
   passages sent, with one retry before falling back to extractive. Passages from uploads
   go to a hosted model only with the visitor's consent.
4. **No runtime downloads.** OCR models ship inside a hash-locked wheel; the embedding model
   and the sample document are fetched at image build time from pinned URLs and checked
   against SHA-256 values in `artifacts/manifest.yaml` (ADR-0004).

## Consequences

- A hostile PDF costs at most one capped process and the visitor's own quota.
- The demo works with no model and no network, and every answer can be checked against
  its page. Extractive answers cannot combine facts from different passages; that is what
  the optional model is for, and the two are measured on the same question set.
- OCR is the expensive step, so it is capped per document (5 pages) and the cap is shown to
  the visitor rather than silently truncating.
