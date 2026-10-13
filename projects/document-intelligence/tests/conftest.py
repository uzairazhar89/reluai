"""Fixtures for Document Intelligence: settings in a temp dir and a stand-in embedder.

``HashEmbedder`` maps text to a hashed bag of stemmed words, so vectors of texts that share
words are similar. It exercises every vector code path without the real model; tests that
need the real model (``test_real_sample.py``) skip when it is not installed.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from pathlib import Path

import numpy as np
import pytest

from reluai_docs.answer import terms
from reluai_docs.embedding import DIMENSIONS
from reluai_docs.settings import DocsSettings


class HashEmbedder:
    name = "hash-bag-of-words (test)"

    def _one(self, text: str) -> np.ndarray:
        v = np.zeros(DIMENSIONS, dtype=np.float32)
        for t in terms(text):
            if len(t) < 3:
                continue
            h = int.from_bytes(hashlib.blake2b(t.encode(), digest_size=4).digest(), "big")
            v[h % DIMENSIONS] += 1.0
        n = float(np.linalg.norm(v))
        return v / n if n else v

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, DIMENSIONS), dtype=np.float32)
        return np.stack([self._one(t) for t in texts])

    def embed_query(self, query: str) -> np.ndarray:
        return self._one(query)


@pytest.fixture
def embedder() -> HashEmbedder:
    return HashEmbedder()


@pytest.fixture
def docs_settings(tmp_path: Path) -> DocsSettings:
    return DocsSettings(
        data_dir=tmp_path / "data",
        spool_dir=tmp_path / "spool",
        read_timeout_seconds=60,
        visitor_uploads_per_hour=3,
        visitor_questions_per_hour=50,
        lease_wait_seconds=5,
    )
