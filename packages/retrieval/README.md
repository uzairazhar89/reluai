# reluai-retrieval

Retrieval core shared by projects that answer from documents.

- `chunking.py`: section-aware chunks that are exact spans of the source (heading path,
  character offsets), packed by sentence with optional overlap.
- `index.py`: idempotent indexing by content hash into `retrieval.document` and
  `retrieval.chunk`.
- `search.py`: PostgreSQL full-text search (headings weighted above text) with
  `websearch_to_tsquery`, an any-term fallback that reports itself, and highlight offsets
  instead of HTML; reciprocal-rank fusion for combining rankings.
- `citations.py`: numbered citations, prompt context blocks and citation checks.

Used by the Customer Support Agent's policy search.
