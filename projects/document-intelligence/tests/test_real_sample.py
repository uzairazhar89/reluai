"""Checks against the real model files and the built sample; skipped when they are absent.

Run ``reluai-docs fetch``, ``reluai-docs quantize`` and ``reluai-docs build-sample`` first
(the server image does this at build time). Files are looked up in the configured data
directory, then in ``data/docs`` at the repository root.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from reluai_docs.embedding import DIMENSIONS, TOKENIZER_FILE, load_embedder
from reluai_docs.sample import load_sample
from reluai_docs.settings import DocsSettings
from reluai_docs.wordpiece import WordPieceTokenizer

REPO_DATA = Path(__file__).resolve().parents[3] / "data" / "docs"


def _data_dir(required: str) -> Path:
    for d in (DocsSettings().data_dir, REPO_DATA):
        if (d / required).exists():
            return d
    pytest.skip(f"{required} is not installed")


# Token ids produced by the reference implementation (Hugging Face ``tokenizers``) for the
# published bge-small-en-v1.5 tokenizer.json: accents, curly quotes, CJK, emoji (unknown),
# numbers and long words split into pieces.
REFERENCE_IDS = [
    ("What are the four functions of the AI RMF core?",
     [101, 2054, 2024, 1996, 2176, 4972, 1997, 1996, 9932, 28549, 2546, 4563, 1029, 102]),
    ("Café NAÏVE résumé — “quoted” text, e.g. ISO/IEC TS 5723:2022.",
     [101, 7668, 15743, 13746, 1517, 1523, 9339, 1524, 3793, 1010, 1041, 1012, 1043, 1012, 11163,
      1013, 24940, 24529, 5401, 21926, 1024, 16798, 2475, 1012, 102]),
    ("Unbelievably hyperparameterised GPUs: 3.5×faster!!! (n=1,024)",
     [101, 4895, 8671, 2666, 3567, 6321, 23760, 28689, 22828, 5084, 14246, 2271, 1024, 1017,
      1012, 1019, 26306, 24333, 2121, 999, 999, 999, 1006, 1050, 1027, 1015, 1010, 6185, 2549,
      1007, 102]),
    ("日本語のテキスト and emoji 🙂 mixed in",
     [101, 1864, 1876, 1950, 1671, 30239, 30227, 30233, 30240, 1998, 7861, 29147, 2072, 100,
      3816, 1999, 102]),
    ("GOVERN 1.1: Legal and regulatory requirements involving AI are understood.",
     [101, 21208, 1015, 1012, 1015, 1024, 3423, 1998, 10738, 5918, 5994, 9932, 2024, 5319, 1012,
      102]),
]  # fmt: skip


@pytest.mark.parametrize(("text", "ids"), REFERENCE_IDS)
def test_tokenizer_matches_reference(text: str, ids: list[int]) -> None:
    path = _data_dir(f"models/{TOKENIZER_FILE}") / "models" / TOKENIZER_FILE
    assert WordPieceTokenizer.from_file(path).encode(text) == ids


def test_embeddings_rank_by_meaning() -> None:
    embedder = load_embedder(_data_dir(f"models/{TOKENIZER_FILE}") / "models")
    if embedder is None:
        pytest.skip("embedding model is not installed")
    passages = [
        "The AI RMF Core is composed of four functions: GOVERN, MAP, MEASURE, and MANAGE.",
        "Argentina won the 2022 FIFA World Cup final on penalties.",
        "Preheat the oven and fold the melted chocolate into the batter.",
    ]
    vectors = embedder.embed(passages)
    query = embedder.embed_query("Which functions make up the framework's core?")
    assert vectors.shape == (3, DIMENSIONS) and query.shape == (DIMENSIONS,)
    assert np.allclose(np.linalg.norm(vectors, axis=1), 1.0, atol=1e-3)
    scores = vectors @ query
    assert int(np.argmax(scores)) == 0
    assert scores[0] - max(scores[1:]) > 0.15


def test_built_sample_structure() -> None:
    sample = load_sample(_data_dir("sample.json") / "sample.json")
    assert sample is not None
    assert sample["page_count"] == 48 and sample["pages_empty"] == 0
    assert len(sample["embeddings"]) == sample["chunks"] > 100
    assert all(len(v) == DIMENSIONS for v in sample["embeddings"])
    outline = [(o["level"], o["title"]) for o in sample["outline"]]
    # Numbered sub-sections sit directly under their parents, with no level skipped.
    assert (2, "3. AI Risks and Trustworthiness") in outline
    assert (3, "3.2 Safe") in outline
    assert (4, "1.2.2 Risk Tolerance") in outline
    assert all(b <= a + 1 for (a, _), (b, _) in zip([(0, ""), *outline], outline, strict=False))
    # Table labels such as "GOVERN 1:" are run into their text, not listed as headings.
    assert not [t for _, t in outline if t.endswith(":")]
    text = sample["text"]
    assert "GOVERN 1: Policies, processes, procedures, and practices" in text
    # Line-end hyphens: real compounds keep theirs, word breaks are rejoined.
    assert "contextspecific" not in text and "context-specific" in text
    # Running footers ("Page 12", "NIST AI 100-1") are not in the body text.
    assert "\nPage 12\n" not in text
