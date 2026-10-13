"""Request and response models of the Document Intelligence API."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Status = Literal["queued", "reading", "ocr", "indexing", "embedding", "ready", "failed"]


class OutlineOut(BaseModel):
    level: int
    title: str
    page: int


class DocumentSourceOut(BaseModel):
    title: str
    publisher: str
    url: str
    licence: str
    sha256: str


class DocumentOut(BaseModel):
    id: uuid.UUID
    kind: Literal["upload", "sample"]
    filename: str
    title: str | None
    status: Status
    progress_done: int
    progress_total: int
    file_bytes: int
    page_count: int = Field(description="Pages in the file")
    pages_read: int
    pages_text: int = Field(description="Pages read from the PDF's text layer")
    pages_ocr: int = Field(description="Scanned pages read with OCR")
    pages_empty: int
    ocr_skipped: list[int] = Field(description="Scanned pages beyond the OCR limit (not read)")
    chars: int
    chunks: int
    truncated: bool
    search_mode: Literal["hybrid", "keyword"] | None
    embedding_model: str | None
    outline: list[OutlineOut]
    warnings: list[str]
    error_code: str | None
    error_message: str | None
    created_at: datetime
    expires_at: datetime | None
    timings: dict[str, int]
    source: DocumentSourceOut | None = None
    llm_available: bool = Field(description="A model can write answers (otherwise extractive)")
    external_llm_available: bool = Field(
        description="A hosted model (Groq) is configured; uploads need the visitor's consent"
    )


class ChunkOut(BaseModel):
    ordinal: int
    heading: str
    page_from: int
    page_to: int
    words: int
    text: str


class ChunksOut(BaseModel):
    total: int
    offset: int
    items: list[ChunkOut]


class QuestionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=2, max_length=300)
    mode: Literal["auto", "extractive"] = Field(
        default="auto", description="auto: a model if one may be used, else extractive"
    )
    allow_external: bool = Field(
        default=False,
        description="For uploads: allow sending the retrieved passages to the hosted model",
    )


class PassageOut(BaseModel):
    number: int
    heading: str
    page_from: int
    page_to: int
    text: str
    snippet: str
    highlights: list[tuple[int, int]]
    keyword_rank: int | None
    vector_rank: int | None
    similarity: float | None


class QuoteOut(BaseModel):
    number: int
    start: int
    end: int


class AttemptOut(BaseModel):
    provider: str
    model: str
    outcome: str
    latency_ms: int


class AnswerOut(BaseModel):
    question: str
    answer: str
    citations: list[int]
    abstained: bool
    method: Literal["extractive", "model"]
    note: str | None
    fallback_reason: str | None = Field(description="Why a model did not write this answer")
    quotes: list[QuoteOut]
    passages: list[PassageOut]
    search_mode: Literal["hybrid", "keyword"]
    keyword_match: Literal["all", "any", "none"]
    provider: str | None
    model: str | None
    tokens: int
    retries: int
    attempts: list[AttemptOut]
    retrieval_ms: int
    answer_ms: int
    word_overlap: float | None = Field(
        default=None,
        description="Extractive: weighted share of the question's words in the best sentence",
    )
    similarity: float | None = Field(
        default=None,
        description="Extractive: cosine similarity of the best sentence to the question",
    )


class QaEvaluationItemOut(BaseModel):
    id: str
    question: str
    kind: Literal["answerable", "unanswerable"]
    split: Literal["dev", "held_out"]
    method: Literal["extractive", "model"]
    correct: bool
    abstained: bool
    retrieved: bool = Field(description="An expected page was among the retrieved passages")
    cited_expected: bool = Field(description="The answer cited a passage on an expected page")
    latency_ms: int
    tokens: int
    answer: str


class QaEvaluationRunOut(BaseModel):
    label: str
    ran_at: datetime
    document: str
    questions: int
    correct: int
    tokens: int
    median_latency_ms: int
    p95_latency_ms: int
    metrics: dict[str, float | int]
    environment: dict[str, str | int | float | None]
    results: list[QaEvaluationItemOut]
