"""Retrieval core shared by projects that answer from documents.

Documents are split into section-aware chunks whose text is an exact span of the source,
indexed with PostgreSQL full-text search (headings weighted above body text) and returned
as ranked hits that carry everything a citation needs: document, section, character
offsets and a highlighted snippet.
"""

from reluai_retrieval.chunking import Chunk, chunk_text
from reluai_retrieval.citations import Citation, cited_numbers, context_block
from reluai_retrieval.index import IndexResult, SourceDocument, index_document
from reluai_retrieval.search import Hit, SearchResult, search

__all__ = [
    "Chunk",
    "Citation",
    "Hit",
    "IndexResult",
    "SearchResult",
    "SourceDocument",
    "chunk_text",
    "cited_numbers",
    "context_block",
    "index_document",
    "search",
]
