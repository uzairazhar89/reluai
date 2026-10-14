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


# --------------------------------------------------------------------------- invoices
InvoiceRole = Literal["code", "description", "quantity", "unit_price", "amount"]


class InvoiceDocumentOut(BaseModel):
    """An invoice of the evaluation set: a real record drawn in a generated layout."""

    id: str
    number: str
    split: Literal["dev", "held_out"]
    style: int = Field(description="Layout seed; 1000 and above are held-out layouts")
    scanned: bool
    lines: int
    credit_note: bool
    last_run: Literal["exact", "flagged", "wrong"] | None = Field(
        default=None, description="Outcome in the latest evaluation run"
    )


class InvoiceBoxOut(BaseModel):
    page: int
    x0: float
    top: float
    x1: float
    bottom: float


class InvoiceFieldOut(BaseModel):
    value: str | int | None
    text: str | None
    box: InvoiceBoxOut | None
    label: str | None
    by: Literal["label", "elimination", "table", "fallback", "missing"]


class InvoiceLineOut(BaseModel):
    stock_code: str | None
    description: str | None
    quantity: int | None
    unit_price: str | None
    amount: str | None
    cells: dict[str, str]
    box: InvoiceBoxOut | None


class InvoiceCheckOut(BaseModel):
    name: str
    passed: bool
    detail: str


class InvoiceColumnOut(BaseModel):
    header: str
    role: InvoiceRole | None
    by: Literal["header", "content", "none"]


class InvoiceExtractionOut(BaseModel):
    document_type: Literal["invoice", "credit_note"] | None
    fields: dict[str, InvoiceFieldOut]
    total: InvoiceFieldOut
    subtotal: InvoiceFieldOut | None
    item_count: int | None
    lines: list[InvoiceLineOut]
    columns: list[InvoiceColumnOut]
    checks: list[InvoiceCheckOut]
    needs_review: bool
    notes: list[str]


class InvoicePageOut(BaseModel):
    number: int
    width: float
    height: float
    method: Literal["text", "ocr", "empty", "skipped"]
    preview: str | None = Field(description="data: URL of a JPEG of the page")


class InvoiceVerdictOut(BaseModel):
    read: str | int | None
    record: str | int | None
    correct: bool


class InvoiceLineVerdictOut(BaseModel):
    read: int
    record: int
    fields: dict[str, bool]
    expected: dict[str, str | int]


class InvoiceComparisonOut(BaseModel):
    exact: bool
    header: dict[str, InvoiceVerdictOut]
    lines: list[InvoiceLineVerdictOut]
    missing: list[dict[str, str | int]]
    extra: list[int]


class InvoiceRunOut(BaseModel):
    source: Literal["sample", "upload"]
    document: InvoiceDocumentOut | None
    filename: str | None
    page_count: int
    pages: list[InvoicePageOut]
    extraction: InvoiceExtractionOut
    comparison: InvoiceComparisonOut | None = Field(
        description="Each value against the record it was rendered from (sample invoices only)"
    )
    timings: dict[str, int]


class InvoiceEvaluationItemOut(BaseModel):
    id: str
    split: Literal["dev", "held_out"]
    scanned: bool
    style: int
    lines: int
    credit_note: bool
    ms: int
    exact: bool
    needs_review: bool
    header: dict[str, bool]
    truth_lines: int
    read_lines: int
    paired: int
    lines_exact: int
    mismatches: list[str]


class InvoiceEvaluationOut(BaseModel):
    ran_at: datetime
    documents: int
    exact: int
    median_ms: int
    metrics: dict[str, dict[str, object]]
    environment: dict[str, str | int | float | None]
    results: list[InvoiceEvaluationItemOut]


class InvoiceGalleryOut(BaseModel):
    documents: list[InvoiceDocumentOut]
    evaluated_at: datetime | None = Field(description="When the latest evaluation ran")
