"""The invoice extraction API against PostgreSQL: gallery, PDF, live runs, uploads, results."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from reluai_api.main import create_app
from reluai_core.db import Database
from reluai_core.settings import CoreSettings
from reluai_docs.invoices import service
from reluai_docs.invoices.records import EvalDocument, write_set
from reluai_docs.invoices.render import render_invoice, style_for
from reluai_docs.settings import DocsSettings, get_docs_settings

from .pdfs import policy_pdf
from .test_invoices import CREDIT, INVOICE

pytestmark = pytest.mark.db

DOCS = [
    EvalDocument("536365-s1", "dev", INVOICE, 1, False),
    EvalDocument("C536379-s1004", "held_out", CREDIT, 1004, False),
]


@pytest.fixture
def client(
    core_settings: CoreSettings, clean_db: Database, docs_settings: DocsSettings
) -> Iterator[TestClient]:
    docs_settings.data_dir.mkdir(parents=True, exist_ok=True)
    write_set(DOCS, docs_settings.invoices_path)
    app = create_app(core_settings, pipeline_deferrer=lambda _: None)
    app.dependency_overrides[get_docs_settings] = lambda: docs_settings
    with TestClient(app) as c:
        yield c


def test_gallery_pdf_and_live_run(client: TestClient) -> None:
    r = client.get("/api/documents/invoices")
    assert r.status_code == 200, r.text
    body = r.json()
    assert [d["id"] for d in body["documents"]] == ["536365-s1", "C536379-s1004"]
    assert body["evaluated_at"] is None

    pdf = client.get("/api/documents/invoices/536365-s1.pdf")
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF-")

    run = client.post("/api/documents/invoices/C536379-s1004/extract")
    assert run.status_code == 200, run.text
    out = run.json()
    assert out["source"] == "sample"
    assert out["comparison"]["exact"] is True
    assert out["extraction"]["document_type"] == "credit_note"
    assert out["extraction"]["total"]["value"] == "-19.80"
    assert out["pages"][0]["preview"].startswith("data:image/jpeg;base64,")
    assert {"render_ms", "wait_ms", "read_ms", "extract_ms"} <= set(out["timings"])
    assert all(c["passed"] for c in out["extraction"]["checks"])


def test_unknown_and_malformed_ids(client: TestClient) -> None:
    assert client.post("/api/documents/invoices/999999-s1/extract").status_code == 404
    assert client.get("/api/documents/invoices/../etc.pdf").status_code in (404, 422)
    assert client.get("/api/documents/invoices/not-an-id.pdf").status_code == 422


def test_upload_is_read_but_not_kept(client: TestClient, clean_db: Database) -> None:
    pdf = render_invoice(INVOICE, style_for(7))
    r = client.post(
        "/api/documents/invoices/uploads", files={"file": ("mine.pdf", pdf, "application/pdf")}
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["source"] == "upload" and out["comparison"] is None
    assert out["filename"] == "mine.pdf"
    assert out["extraction"]["fields"]["number"]["value"] == "536365"
    assert len(out["extraction"]["lines"]) == 4
    assert out["extraction"]["needs_review"] is False

    not_invoice = client.post(
        "/api/documents/invoices/uploads",
        files={"file": ("policy.pdf", policy_pdf(), "application/pdf")},
    )
    assert not_invoice.status_code == 200
    assert not_invoice.json()["extraction"]["needs_review"] is True

    bad = client.post(
        "/api/documents/invoices/uploads", files={"file": ("x.pdf", b"hello", "application/pdf")}
    )
    assert bad.status_code == 422 and bad.json()["code"] == "not_a_pdf"


def test_quota(client: TestClient, docs_settings: DocsSettings) -> None:
    docs_settings.visitor_invoice_runs_per_hour = 1
    assert client.post("/api/documents/invoices/536365-s1/extract").status_code == 200
    r = client.post("/api/documents/invoices/536365-s1/extract")
    assert r.status_code == 429 and r.json()["code"] == "quota_exceeded"
    assert int(r.headers["retry-after"]) > 0


def test_evaluation_is_recorded_and_published(
    client: TestClient, clean_db: Database, docs_settings: DocsSettings
) -> None:
    results = service.evaluate(docs_settings, isolated=False)
    assert [r.comparison.exact for r in results] == [True, True]
    service.record_run(clean_db, results)
    r = client.get("/api/documents/invoices/evaluation")
    assert r.status_code == 200
    run = r.json()
    assert run["documents"] == 2 and run["exact"] == 2
    assert run["metrics"]["held_out.text"]["exact"] == 100.0
    gallery = client.get("/api/documents/invoices").json()
    assert {d["last_run"] for d in gallery["documents"]} == {"exact"}
