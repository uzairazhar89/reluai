"""HTTP API of the CSV analyst, against a real PostgreSQL (quotas, query log, evaluation)."""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from reluai_api.main import create_app
from reluai_core.db import Database
from reluai_core.settings import CoreSettings
from reluai_csv.evaluation import run_evaluation
from reluai_csv.models import QueryLog
from reluai_csv.settings import CsvSettings, get_csv_settings
from reluai_inference.chain import ProviderChain
from reluai_inference.providers import DeterministicProvider
from reluai_inference.types import ChatResponse

pytestmark = pytest.mark.db

CSV = b"store,visits,opened\nLeeds,120,2023-05-01\nYork,80,2023-06-12\nLeeds,95,2023-07-03\n"


def offline_chain() -> ProviderChain:
    def refuse(_: object) -> ChatResponse:
        raise AssertionError("no model in these tests")

    provider = DeterministicProvider(refuse, name="offline")
    provider.available = lambda: False  # type: ignore[method-assign]
    return ProviderChain([provider])


@pytest.fixture
def settings(upload_settings: CsvSettings) -> CsvSettings:
    return upload_settings.model_copy(update={"visitor_asks_per_hour": 5})


@pytest.fixture
def client(
    core_settings: CoreSettings, clean_db: Database, settings: CsvSettings
) -> Iterator[TestClient]:
    deferred: list[uuid.UUID] = []
    app = create_app(core_settings, pipeline_deferrer=deferred.append)
    app.dependency_overrides[get_csv_settings] = lambda: settings
    app.state.csv_chain_factory = offline_chain
    with TestClient(app) as c:
        yield c


def test_bundled_dataset(client: TestClient) -> None:
    body = client.get("/api/csv/datasets/retail").json()
    assert body["kind"] == "bundled"
    assert body["table"] == "sales"
    assert body["rows"] > 0
    assert {c["name"] for c in body["columns"]} >= {"revenue", "country", "invoiced_at"}
    assert "UCI Online Retail II" in body["provenance"]
    assert any(f["code"] == "duplicate_rows" for f in body["findings"])
    assert body["examples"]
    assert body["llm_available"] is False  # the test chain has no usable provider


def test_ask_and_log_without_question_text(client: TestClient, clean_db: Database) -> None:
    r = client.post("/api/csv/ask", json={"dataset": "retail", "question": "Revenue per year"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "answered"
    assert body["interpreter"]["kind"] == "rules"
    r = client.post(
        "/api/csv/ask", json={"dataset": "retail", "question": "Why do customers leave?"}
    )
    assert r.json()["status"] == "not_understood"
    with clean_db.session() as s:
        rows = s.scalars(select(QueryLog).order_by(QueryLog.id)).all()
        assert [(q.status, q.interpreter) for q in rows] == [
            ("answered", "rules"),
            ("not_understood", "none"),
        ]
        columns = {c.name for c in QueryLog.__table__.columns}
        assert not {"question", "text", "sql"} & columns
    usage = client.get("/api/csv/usage").json()
    assert usage["questions"] == 2
    assert usage["answered_by_rules"] == 1
    assert usage["not_understood"] == 1


def test_question_validation(client: TestClient) -> None:
    for payload in [
        {"dataset": "retail", "question": "x"},
        {"dataset": "retail", "question": "y" * 301},
        {"dataset": "../etc", "question": "How many rows?"},
        {"dataset": "retail", "question": "How many rows?", "sql": "SELECT 1"},
    ]:
        assert client.post("/api/csv/ask", json=payload).status_code == 422, payload


def test_quota(client: TestClient) -> None:
    for _ in range(5):
        r = client.post("/api/csv/ask", json={"dataset": "retail", "question": "How many rows?"})
        assert r.status_code == 200
    r = client.post("/api/csv/ask", json={"dataset": "retail", "question": "How many rows?"})
    assert r.status_code == 429
    assert r.json()["code"] == "quota_exceeded"
    assert int(r.headers["retry-after"]) > 0


def test_upload_flow(client: TestClient) -> None:
    r = client.post("/api/csv/uploads", files={"file": ("visits.csv", CSV, "text/csv")})
    assert r.status_code == 201, r.text
    upload = r.json()
    assert upload["kind"] == "upload"
    assert upload["expires_at"]
    assert client.get(f"/api/csv/uploads/{upload['id']}").json()["rows"] == 3
    r = client.post(
        "/api/csv/ask", json={"dataset": upload["id"], "question": "Total visits by store"}
    )
    body = r.json()
    assert body["status"] == "answered"
    assert body["rows"] == [["Leeds", 215], ["York", 80]]


def test_upload_rejections(client: TestClient) -> None:
    r = client.post("/api/csv/uploads", files={"file": ("book.xlsx", b"PK\x03\x04...", "x")})
    assert r.status_code == 422
    assert r.json()["code"] == "not_csv"
    r = client.post("/api/csv/uploads", files={"file": ("e.csv", b"", "text/csv")})
    assert r.json()["code"] == "empty_file"


def test_unknown_uploads_are_404(client: TestClient) -> None:
    assert client.get("/api/csv/uploads/not-an-id").status_code == 404
    r = client.post(
        "/api/csv/ask", json={"dataset": "0" * 32, "question": "How many rows are there?"}
    )
    assert r.status_code == 404
    assert r.json()["code"] == "upload_not_found"


def test_evaluation_endpoint(client: TestClient, clean_db: Database, settings: CsvSettings) -> None:
    r = client.get("/api/csv/evaluation")
    assert r.status_code == 404
    assert r.json()["code"] == "no_evaluation"
    run_evaluation(settings, record=True, db=clean_db)
    body = client.get("/api/csv/evaluation").json()
    assert body["development"]["wrong"] == 0
    assert body["development"]["declined_unexpected"] == 0
    assert body["held_out"]["questions"] > 0
    assert body["environment"]["duckdb"]
    assert len(body["items"]) == body["development"]["questions"] + body["held_out"]["questions"]
    with clean_db.session() as s:
        assert s.scalar(select(func.count()).select_from(QueryLog)) == 0


def test_scheduled_evaluation_task(
    monkeypatch: pytest.MonkeyPatch,
    core_settings: CoreSettings,
    clean_db: Database,
    settings: CsvSettings,
) -> None:
    from datetime import UTC, datetime, timedelta

    from reluai_core.runtime import Runtime, set_runtime
    from reluai_csv import tasks
    from reluai_csv.models import EvaluationRun

    monkeypatch.setattr(tasks, "get_csv_settings", lambda: settings)
    with clean_db.session() as s:
        s.add(
            QueryLog(
                dataset_kind="bundled",
                status="answered",
                interpreter="rules",
                ts=datetime.now(UTC) - timedelta(days=91),
            )
        )
    set_runtime(Runtime(settings=core_settings, db=clean_db))
    try:
        tasks.csv_evaluation.func(timestamp=0)  # type: ignore[attr-defined]
    finally:
        set_runtime(None)
    with clean_db.session() as s:
        assert s.scalar(select(func.count()).select_from(EvaluationRun)) == 1
        assert s.scalar(select(func.count()).select_from(QueryLog)) == 0  # past retention
