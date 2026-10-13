"""The documents API end to end against PostgreSQL: upload, process, ask, inspect, delete."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update

from reluai_api.main import create_app
from reluai_core.db import Database
from reluai_core.settings import CoreSettings
from reluai_docs import service
from reluai_docs.evaluation import record_run, run_evaluation
from reluai_docs.models import DocumentRecord
from reluai_docs.questions import EvalQuestion
from reluai_docs.sample import build_sample
from reluai_docs.settings import DocsSettings, get_docs_settings
from reluai_inference.chain import ProviderChain
from reluai_retrieval.models import Chunk, Document

from .conftest import HashEmbedder
from .pdfs import SCAN_PAGE, policy_pdf, scanned_pdf
from .test_answer import _chain, _tool

pytestmark = pytest.mark.db

ChainFactory = Callable[[bool], ProviderChain | None]


@pytest.fixture
def make_client(
    core_settings: CoreSettings,
    clean_db: Database,
    docs_settings: DocsSettings,
    embedder: HashEmbedder,
) -> Iterator[Callable[..., TestClient]]:
    clients: list[TestClient] = []

    def make(chain_factory: ChainFactory = lambda _external: None) -> TestClient:
        app = create_app(core_settings, pipeline_deferrer=lambda _: None)
        app.dependency_overrides[get_docs_settings] = lambda: docs_settings
        app.state.docs_embedder = lambda: embedder
        app.state.docs_chain_factory = chain_factory
        app.state.docs_deferrer = lambda doc_id: service.process_document(
            clean_db, docs_settings, doc_id, embedder=lambda: embedder
        )
        client = TestClient(app)
        client.__enter__()
        clients.append(client)
        return client

    yield make
    for c in clients:
        c.__exit__(None, None, None)


@pytest.fixture
def client(make_client: Callable[..., TestClient]) -> TestClient:
    return make_client()


def upload(client: TestClient, data: bytes, name: str = "handbook.pdf", **headers: str):  # type: ignore[no-untyped-def]
    return client.post(
        "/api/documents/uploads",
        files={"file": (name, data, "application/pdf")},
        headers=headers,
    )


def test_upload_process_ask_and_inspect(client: TestClient, docs_settings: DocsSettings) -> None:
    r = upload(client, policy_pdf(extra_pages=1))
    assert r.status_code == 202, r.text
    doc = r.json()
    assert doc["status"] == "ready"
    assert doc["kind"] == "upload"
    assert doc["filename"] == "handbook.pdf"
    assert doc["title"] == "Returns and Refunds Handbook"
    assert (doc["page_count"], doc["pages_text"], doc["pages_ocr"]) == (3, 3, 0)
    assert doc["search_mode"] == "hybrid"
    assert doc["outline"][4] == {"level": 1, "title": "3 Lost parcels", "page": 2}
    assert doc["llm_available"] is False
    assert set(doc["timings"]) >= {"wait_ms", "read_ms", "index_ms", "embed_ms"}
    assert not list(docs_settings.spool_dir.glob("*.pdf")), "the spooled PDF is deleted"

    r = client.post(
        f"/api/documents/{doc['id']}/ask", json={"question": "When does a parcel count as lost?"}
    )
    assert r.status_code == 200, r.text
    ans = r.json()
    assert ans["method"] == "extractive"
    assert ans["fallback_reason"] == "no model is configured on this server"
    assert not ans["abstained"]
    assert "no movement for ten working days" in ans["answer"]
    cited = {p["number"]: p for p in ans["passages"]}[ans["citations"][0]]
    assert (cited["page_from"], cited["heading"]) == (2, "3 Lost parcels")
    assert ans["search_mode"] == "hybrid"
    quote = ans["quotes"][0]
    assert cited["text"][quote["start"] : quote["end"]].startswith("A parcel counts as lost")

    r = client.post(
        f"/api/documents/{doc['id']}/ask", json={"question": "Who is the company's auditor?"}
    )
    assert r.json()["abstained"] is True

    chunks = client.get(f"/api/documents/{doc['id']}/chunks", params={"limit": 50}).json()
    assert chunks["total"] == doc["chunks"] == len(chunks["items"])
    assert {c["page_from"] for c in chunks["items"]} == {1, 2, 3}


def test_owner_only_and_delete(client: TestClient, clean_db: Database) -> None:
    doc = upload(client, policy_pdf()).json()
    other = {"x-real-ip": "203.0.113.50"}
    r = client.get(f"/api/documents/{doc['id']}", headers=other)
    assert r.status_code == 403
    assert r.json()["code"] == "not_your_document"
    assert client.delete(f"/api/documents/{doc['id']}", headers=other).status_code == 403
    assert client.delete(f"/api/documents/{doc['id']}").status_code == 204
    assert client.get(f"/api/documents/{doc['id']}").status_code == 404
    with clean_db.session() as s:
        assert s.scalar(select(func.count()).select_from(Document)) == 0
        assert s.scalar(select(func.count()).select_from(Chunk)) == 0


def test_rejected_uploads(client: TestClient, docs_settings: DocsSettings) -> None:
    r = upload(client, b"just text", name="notes.txt")
    assert (r.status_code, r.json()["code"]) == (422, "not_a_pdf")
    docs_settings.upload_max_bytes = 2000
    r = upload(client, policy_pdf())
    assert (r.status_code, r.json()["code"]) == (413, "too_large")
    docs_settings.upload_max_bytes = 10 * 1024 * 1024
    r = upload(client, b"%PDF-1.7\n1 0 obj << >> garbage")
    assert r.status_code == 202
    assert (r.json()["status"], r.json()["error_code"]) == ("failed", "damaged")


def test_upload_quota_and_queue_limit(
    client: TestClient, clean_db: Database, docs_settings: DocsSettings
) -> None:
    for _ in range(3):
        assert upload(client, policy_pdf()).status_code == 202
    r = upload(client, policy_pdf())
    assert (r.status_code, r.json()["code"]) == (429, "quota_exceeded")
    with clean_db.session() as s:
        s.execute(update(DocumentRecord).values(status="queued"))
    docs_settings.max_pending = 3
    r = upload(client, policy_pdf(), **{"x-real-ip": "198.51.100.7"})
    assert (r.status_code, r.json()["code"]) == (503, "busy")


def test_scanned_upload_with_ocr_limit(client: TestClient, docs_settings: DocsSettings) -> None:
    docs_settings.max_ocr_pages = 1
    doc = upload(client, scanned_pdf([SCAN_PAGE, SCAN_PAGE])).json()
    assert doc["status"] == "ready"
    assert (doc["pages_ocr"], doc["ocr_skipped"]) == (1, [2])
    assert any("not read because OCR is limited" in w for w in doc["warnings"])
    ans = client.post(
        f"/api/documents/{doc['id']}/ask", json={"question": "How much is next day delivery?"}
    ).json()
    assert "nine pounds" in ans["answer"]


def test_expired_uploads_are_purged(
    client: TestClient, clean_db: Database, docs_settings: DocsSettings
) -> None:
    doc = upload(client, policy_pdf()).json()
    with clean_db.session() as s:
        s.execute(
            update(DocumentRecord).values(expires_at=datetime.now(UTC) - timedelta(minutes=1))
        )
    assert client.get(f"/api/documents/{doc['id']}").status_code == 404
    assert service.purge(clean_db, docs_settings) == 1
    with clean_db.session() as s:
        assert s.scalar(select(func.count()).select_from(DocumentRecord)) == 0
        assert s.scalar(select(func.count()).select_from(Chunk)) == 0
    # A spooled file the worker never picked up is cleared too.
    docs_settings.spool_dir.mkdir(parents=True, exist_ok=True)
    stale = docs_settings.spool_dir / f"{uuid.uuid4().hex}.pdf"
    stale.write_bytes(b"%PDF-")
    old = datetime.now(UTC).timestamp() - 3600
    import os

    os.utime(stale, (old, old))
    service.purge(clean_db, docs_settings)
    assert not stale.exists()


def _sample(docs_settings: DocsSettings, embedder: HashEmbedder, tmp_path: Path) -> None:
    pdf = tmp_path / "sample.pdf"
    pdf.write_bytes(policy_pdf(extra_pages=1))
    build_sample(
        pdf,
        docs_settings.sample_path,
        model_dir=docs_settings.model_dir,
        chunk_words=docs_settings.chunk_words,
        chunk_overlap=docs_settings.chunk_overlap,
        verify=False,
        embedder=embedder,
    )


def test_sample_document_uses_the_model_without_consent(
    make_client: Callable[..., TestClient],
    docs_settings: DocsSettings,
    embedder: HashEmbedder,
    tmp_path: Path,
) -> None:
    unavailable = make_client().get("/api/documents/sample")
    assert unavailable.status_code == 503
    _sample(docs_settings, embedder, tmp_path)
    reply = _tool("answer", {"text": "Refunds above fifty pounds need approval [1].",
                             "citations": [1]})  # fmt: skip
    client = make_client(lambda external: _chain(reply) if external else None)
    doc = client.get("/api/documents/sample").json()
    assert (doc["kind"], doc["status"], doc["search_mode"]) == ("sample", "ready", "hybrid")
    assert doc["source"]["licence"].startswith("Work of the US Government")
    assert doc["external_llm_available"] is True
    ans = client.post(
        f"/api/documents/{doc['id']}/ask",
        json={"question": "Which refunds need a supervisor?"},
    ).json()
    assert (ans["method"], ans["provider"], ans["tokens"]) == ("model", "fake", 120)
    assert client.delete(f"/api/documents/{doc['id']}").status_code == 403
    # Loading is idempotent.
    assert client.get("/api/documents/sample").json()["chunks"] == doc["chunks"]


def test_uploads_need_consent_for_the_hosted_model(
    make_client: Callable[..., TestClient],
) -> None:
    reply = _tool("answer", {"text": "Ten working days [1].", "citations": [1]})
    client = make_client(lambda external: _chain(reply) if external else None)
    doc = upload(client, policy_pdf()).json()
    q = {"question": "When does a parcel count as lost?"}
    ans = client.post(f"/api/documents/{doc['id']}/ask", json=q).json()
    assert ans["method"] == "extractive"
    assert ans["fallback_reason"] == "sending the passages to the hosted model needs your consent"
    ans = client.post(f"/api/documents/{doc['id']}/ask", json=q | {"allow_external": True}).json()
    assert ans["method"] == "model"


def test_evaluation_is_recorded_and_served(
    client: TestClient,
    clean_db: Database,
    docs_settings: DocsSettings,
    embedder: HashEmbedder,
    tmp_path: Path,
) -> None:
    assert client.get("/api/documents/evaluation").json() == []
    _sample(docs_settings, embedder, tmp_path)
    questions = (
        EvalQuestion("lost", "When does a parcel count as lost?", "answerable", "dev", (2,),
                     (("ten working days",),)),
        EvalQuestion("ceo", "What is the CEO's salary?", "unanswerable", "held_out"),
    )  # fmt: skip
    summary = run_evaluation(
        clean_db, docs_settings, label="extractive", mode="extractive",
        embedder=lambda: embedder, questions=questions,
    )  # fmt: skip
    assert summary is not None
    assert summary.correct == 2, [r.answer for r in summary.results]
    assert summary.metrics["retrieval_recall"] == 100.0
    record_run(clean_db, summary)
    runs = client.get("/api/documents/evaluation").json()
    assert [(r["label"], r["correct"], r["questions"]) for r in runs] == [("extractive", 2, 2)]
    assert runs[0]["results"][1]["kind"] == "unanswerable"
