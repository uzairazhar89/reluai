from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator

import httpx
import pytest
from fastapi.testclient import TestClient

from reluai_api.main import create_app
from reluai_core.db import Database
from reluai_core.settings import CoreSettings
from reluai_pipeline.runner import execute_run
from reluai_pipeline.settings import PipelineSettings, get_pipeline_settings

pytestmark = pytest.mark.db


@pytest.fixture
def deferred() -> list[uuid.UUID]:
    return []


@pytest.fixture
def client(
    core_settings: CoreSettings,
    pipeline_settings: PipelineSettings,
    clean_db: Database,
    deferred: list[uuid.UUID],
) -> Iterator[TestClient]:
    settings = pipeline_settings.model_copy(
        update={"visitor_runs_per_hour": 3, "max_pending_runs": 10}
    )
    app = create_app(core_settings, pipeline_deferrer=deferred.append)
    app.dependency_overrides[get_pipeline_settings] = lambda: settings
    with TestClient(app) as c:
        yield c


def test_probes_and_metrics(client: TestClient) -> None:
    assert client.get("/healthz").json() == {"status": "ok"}
    ready = client.get("/readyz")
    assert ready.status_code == 200
    assert ready.json()["checks"]["migrations"]["revision"] == "0003"
    metrics = client.get("/metrics")
    assert metrics.status_code == 200
    assert "reluai_http_requests_total" in metrics.text


def test_public_status(client: TestClient) -> None:
    body = client.get("/api/status").json()
    names = {c["name"]: c["status"] for c in body["components"]}
    assert names["Database"] == "operational"
    assert names["Pipeline"] == "degraded"  # no runs yet
    assert body["status"] == "degraded"


def test_reference_endpoints(client: TestClient) -> None:
    scenarios = client.get("/api/pipeline/scenarios").json()
    assert {s["id"] for s in scenarios} == {
        "standard",
        "replay",
        "crm_flaky",
        "crm_outage",
        "corrupt_drop",
    }
    assert next(s for s in scenarios if s["id"] == "crm_outage")["simulated"] is True
    reasons = client.get("/api/pipeline/reasons").json()
    assert any(r["code"] == "stock_adjustment" for r in reasons)
    drops = client.get("/api/pipeline/drops").json()
    assert [d["key"] for d in drops] == ["2010-01", "2010-02"]
    assert not any(d["loaded"] for d in drops)


def test_visitor_run_is_queued_and_quota_enforced(
    client: TestClient, deferred: list[uuid.UUID]
) -> None:
    headers = {"X-Real-IP": "198.51.100.10"}
    ids = []
    for _ in range(3):
        r = client.post("/api/pipeline/runs", json={"scenario": "standard"}, headers=headers)
        assert r.status_code == 202, r.text
        ids.append(r.json()["run_id"])
    assert [str(x) for x in deferred] == ids
    blocked = client.post("/api/pipeline/runs", json={"scenario": "standard"}, headers=headers)
    assert blocked.status_code == 429
    assert blocked.json()["code"] == "quota_exceeded"
    assert int(blocked.headers["retry-after"]) > 0
    other = client.post(
        "/api/pipeline/runs", json={"scenario": "replay"}, headers={"X-Real-IP": "198.51.100.11"}
    )
    assert other.status_code == 202
    runs = client.get("/api/pipeline/runs").json()
    assert all(r["status"] == "queued" for r in runs)


def test_queue_capacity_limit(
    core_settings: CoreSettings, pipeline_settings: PipelineSettings, clean_db: Database
) -> None:
    app = create_app(core_settings, pipeline_deferrer=lambda run_id: None)
    tight = pipeline_settings.model_copy(update={"max_pending_runs": 1})
    app.dependency_overrides[get_pipeline_settings] = lambda: tight
    with TestClient(app) as c:
        assert (
            c.post(
                "/api/pipeline/runs",
                json={"scenario": "standard"},
                headers={"X-Real-IP": "192.0.2.1"},
            ).status_code
            == 202
        )
        full = c.post(
            "/api/pipeline/runs", json={"scenario": "standard"}, headers={"X-Real-IP": "192.0.2.2"}
        )
        assert full.status_code == 429
        assert full.json()["code"] == "queue_full"


@pytest.mark.parametrize(
    ("body", "status", "code"),
    [
        ({"scenario": "drop_tables"}, 400, "unknown_scenario"),
        ({"scenario": "standard", "extra": 1}, 422, "validation_error"),
        ({"scenario": "Robert'); --"}, 422, "validation_error"),
    ],
)
def test_bad_run_requests(
    client: TestClient, body: dict[str, object], status: int, code: str
) -> None:
    r = client.post("/api/pipeline/runs", json=body)
    assert r.status_code == status
    assert r.json()["code"] == code


def test_oversized_body_rejected(client: TestClient) -> None:
    r = client.post("/api/pipeline/runs", json={"scenario": "x" * 20_000})
    assert r.status_code == 413


def test_dashboard_reads_after_a_run(
    client: TestClient,
    clean_db: Database,
    pipeline_settings: PipelineSettings,
    crm_client_factory: Callable[[], httpx.Client],
) -> None:
    r = client.post("/api/pipeline/runs", json={"scenario": "standard"})
    run_id = uuid.UUID(r.json()["run_id"])
    execute_run(clean_db, pipeline_settings, run_id, client_factory=crm_client_factory)

    summary = client.get("/api/pipeline/summary").json()
    assert summary["last_run"]["status"] == "succeeded"
    assert summary["warehouse"]["invoice_lines"] == 8
    assert summary["drops_loaded"] == 1

    detail = client.get(f"/api/pipeline/runs/{run_id}").json()
    assert [s["name"] for s in detail["steps"]][-1] == "load"
    assert detail["run"]["dq_score"] == 100.0
    assert detail["dq_formula"].startswith("100 ×")
    assert detail["logs"][0]["event"] == "step.started"

    q = client.get(
        f"/api/pipeline/runs/{run_id}/quarantine", params={"reason": "stock_adjustment"}
    ).json()
    assert q["total"] == 1
    assert q["items"][0]["raw"]["Invoice"] == "536369"

    assert client.get(f"/api/pipeline/runs/{uuid.uuid4()}").status_code == 404
    status = client.get("/api/status").json()
    assert {c["name"]: c["status"] for c in status["components"]}["Pipeline"] == "operational"


def test_internal_crm_paginates(client: TestClient) -> None:
    page = client.get("/internal/crm/customers", params={"page_size": 1}).json()
    assert page["total"] == 2 and page["next_page"] == 2
    fault = client.get("/internal/crm/customers", headers={"X-Simulated-Fault": "outage"})
    assert fault.status_code == 503


def test_openapi_documents_public_routes(core_settings: CoreSettings) -> None:
    spec = create_app(core_settings).openapi()
    assert "/api/pipeline/summary" in spec["paths"]
    assert "/internal/crm/customers" not in spec["paths"]
    assert "/healthz" not in spec["paths"]


def test_docs_disabled_in_production(core_settings: CoreSettings) -> None:
    from pydantic import SecretStr

    from reluai_core.settings import Environment

    prod = core_settings.model_copy(
        update={"environment": Environment.PROD, "visitor_hash_secret": SecretStr("s" * 32)}
    )
    with TestClient(create_app(prod)) as c:
        assert c.get("/api/docs").status_code == 404
        assert c.get("/api/openapi.json").status_code == 404
