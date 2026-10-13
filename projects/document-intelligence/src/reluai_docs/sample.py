"""The bundled sample document, prepared at image build time.

Visitors without a PDF to hand can try the Q&A on it, and the evaluation question set is
written against it. ``build_sample`` reads the PDF with the same isolated reader as uploads,
builds the text and passages, embeds them, and writes ``sample.json``; at run time the API
loads that file into the database without any heavy work.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from reluai_docs.embedding import TextEmbedder, load_embedder, sha256_file
from reluai_docs.isolation import ReaderLimits, read_isolated
from reluai_docs.layout import build_document
from reluai_docs.pdfread import ReadLimits
from reluai_retrieval.chunking import chunk_text


@dataclass(frozen=True, slots=True)
class SampleSpec:
    id: str
    title: str
    publisher: str
    url: str
    file_url: str
    filename: str
    sha256: str
    licence: str


SAMPLE = SampleSpec(
    id="nist-ai-100-1",
    title="Artificial Intelligence Risk Management Framework (AI RMF 1.0)",
    publisher="National Institute of Standards and Technology (NIST), NIST AI 100-1, January 2023",
    url="https://doi.org/10.6028/NIST.AI.100-1",
    file_url="https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.100-1.pdf",
    filename="NIST.AI.100-1.pdf",
    sha256="7576edb531d9848825814ee88e28b1795d3a84b435b4b797d3670eafdc4a89f1",
    licence="Work of the US Government, not subject to copyright in the United States",
)


def build_sample(
    pdf_path: Path,
    out_path: Path,
    *,
    model_dir: Path,
    chunk_words: int,
    chunk_overlap: int,
    spec: SampleSpec = SAMPLE,
    verify: bool = True,
    embedder: TextEmbedder | None = None,
) -> dict[str, Any]:
    digest = sha256_file(pdf_path)
    if verify and digest != spec.sha256:
        raise ValueError(f"{pdf_path.name}: SHA-256 {digest} does not match {spec.sha256}")
    data = pdf_path.read_bytes()
    result = read_isolated(
        data,
        ReaderLimits(ReadLimits(max_pages=500, max_ocr_pages=0), timeout_seconds=300,
                     cpu_seconds=300, max_bytes=len(data)),
    )  # fmt: skip
    built = build_document(result.pages, max_chars=2_000_000)
    chunks = chunk_text(built.text, max_words=chunk_words, overlap=chunk_overlap)
    embedder = embedder or load_embedder(model_dir)
    vectors: list[list[float]] | None = None
    model: str | None = None
    if embedder is not None:
        emb = embedder.embed([f"{c.heading}\n{c.text}" if c.heading else c.text for c in chunks])
        vectors = [[round(float(x), 6) for x in row] for row in emb]
        model = embedder.name
    payload: dict[str, Any] = {
        "spec": asdict(spec),
        "file_bytes": len(data),
        "page_count": result.page_count,
        "pages_text": sum(1 for p in result.pages if p.method == "text"),
        "pages_empty": sum(1 for p in result.pages if p.method == "empty"),
        "title": spec.title,
        "text": built.text,
        "text_sha256": hashlib.sha256(built.text.encode()).hexdigest(),
        "page_starts": built.page_starts,
        "outline": [asdict(o) for o in built.outline],
        "chunk_words": chunk_words,
        "chunk_overlap": chunk_overlap,
        "chunks": len(chunks),
        "embedding_model": model,
        "embeddings": vectors,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(".partial")
    tmp.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    tmp.replace(out_path)
    return payload


def load_sample(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data
