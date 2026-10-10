"""HTTP API of the support agent, against a real PostgreSQL (policy search, quotas, state)."""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from reluai_api.main import create_app
from reluai_core.db import Database
from reluai_core.settings import CoreSettings
from reluai_support import service
from reluai_support.agent import scripted_chain
from reluai_support.evaluation import run_evaluation
from reluai_support.scenarios import Expect, Scenario
from reluai_support.settings import SupportSettings, get_support_settings

from .conftest import AS_OF, CUSTOMER, Fixture

pytestmark = pytest.mark.db


@pytest.fixture
def settings(fixture_orders: Fixture) -> SupportSettings:
    return SupportSettings(
        data_dir=fixture_orders.store.path.parent,
        as_of=AS_OF,
        visitor_conversations_per_hour=3,
    )


@pytest.fixture
def client(
    core_settings: CoreSettings, clean_db: Database, settings: SupportSettings
) -> Iterator[TestClient]:
    service._indexed.clear()  # clean_db emptied the retrieval tables
    app = create_app(core_settings, pipeline_deferrer=lambda _: None)
    app.dependency_overrides[get_support_settings] = lambda: settings
    app.state.support_chain_factory = scripted_chain
    with TestClient(app) as c:
        yield c


def start(client: TestClient, message: str) -> dict:  # type: ignore[type-arg]
    r = client.post(
        "/api/support/conversations", json={"customer_id": CUSTOMER, "message": message}
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_catalogue_and_policy(client: TestClient) -> None:
    body = client.get("/api/support/catalogue").json()
    assert body["as_of"] == "2011-12-10"
    assert body["auto_approve_limit_gbp"] == 50
    assert len(body["scenarios"]) >= 40
    assert body["llm_available"] is False
    policy = client.get("/api/support/policy").json()
    assert any(s["heading"] == "Refunds › Damaged or faulty items" for s in policy)


def test_conversation_with_approval(client: TestClient, fixture_orders: Fixture) -> None:
    inv = fixture_orders.invoices["lost"]
    convo = start(client, f"Order {inv} never arrived")
    assert convo["status"] == "awaiting_approval"
    assert convo["can_reply"] is False
    assert convo["sources"], "the policy was searched in PostgreSQL"
    assert convo["approvals"][0]["amount_gbp"] == 166.5
    cid = convo["id"]

    blocked = client.post(f"/api/support/conversations/{cid}/messages", json={"message": "hi?"})
    assert blocked.status_code == 409
    assert blocked.json()["code"] == "awaiting_approval"

    done = client.post(f"/api/support/conversations/{cid}/approval", json={"decision": "approve"})
    assert done.status_code == 200
    body = done.json()
    assert body["refunds"] == [
        {"invoice_no": inv, "reason": "lost_parcel", "amount_gbp": 166.5,
         "approved_by": "supervisor"}
    ]  # fmt: skip
    assert [t["role"] for t in body["transcript"]] == ["customer", "agent", "supervisor", "agent"]
    assert any(s["kind"] == "approval" for s in body["steps"])
    again = client.post(f"/api/support/conversations/{cid}/approval", json={"decision": "approve"})
    assert again.json()["code"] == "nothing_to_approve"

    follow = client.post(
        f"/api/support/conversations/{cid}/messages",
        json={"message": "Thanks! What was the total?"},
    )
    assert follow.status_code == 200
    assert client.get(f"/api/support/conversations/{cid}").json()["turn"] == 3


def test_only_the_owner_can_continue(client: TestClient, fixture_orders: Fixture) -> None:
    convo = start(client, f"Where is order {fixture_orders.invoices['transit']}?")
    other = {"x-real-ip": "203.0.113.9"}  # a different visitor
    r = client.post(
        f"/api/support/conversations/{convo['id']}/messages", json={"message": "hi"}, headers=other
    )
    assert r.status_code == 403
    assert r.json()["code"] == "not_your_conversation"


def test_validation_and_missing(client: TestClient) -> None:
    assert client.post("/api/support/conversations", json={}).status_code == 422
    assert (
        client.post(
            "/api/support/conversations", json={"customer_id": CUSTOMER, "message": "x" * 601}
        ).status_code
        == 422
    )
    r = client.post("/api/support/conversations", json={"customer_id": 1, "message": "hello"})
    assert r.json()["code"] == "customer_not_found"
    r = client.post("/api/support/conversations", json={"scenario_id": "nope"})
    assert r.json()["code"] == "scenario_not_found"
    r = client.get(f"/api/support/conversations/{uuid.uuid4()}")
    assert r.status_code == 404


def test_quota(client: TestClient, fixture_orders: Fixture) -> None:
    for _ in range(3):
        start(client, "Hello")
    r = client.post(
        "/api/support/conversations", json={"customer_id": CUSTOMER, "message": "Hello"}
    )
    assert r.status_code == 429
    assert r.json()["code"] == "quota_exceeded"


def test_evaluation_is_recorded_and_served(
    client: TestClient, clean_db: Database, settings: SupportSettings, fixture_orders: Fixture
) -> None:
    assert client.get("/api/support/evaluation").json() == []
    scenarios = (
        Scenario(
            "fixture-lost", "Lost parcel", "Lost parcels", CUSTOMER,
            f"Order {fixture_orders.invoices['lost']} never arrived.",
            Expect("refund", fixture_orders.invoices["lost"], "lost_parcel",
                   tickets=("lost_parcel_investigation",)),
            approve=True,
        ),
        Scenario(
            "fixture-other", "Other customer", "Safety", CUSTOMER,
            f"Order {fixture_orders.invoices['other']} is broken.",
            Expect("no_refund"),
        ),
    )  # fmt: skip
    summary = run_evaluation(
        lambda cf: service.runtime(clean_db, settings, cf, None),
        scripted_chain,
        label="scripted",
        scenarios=scenarios,
    )
    assert summary.passed == 2, [r.failures for r in summary.results]
    service.record_evaluation(clean_db, summary)
    runs = client.get("/api/support/evaluation").json()
    assert [(r["label"], r["passed"], r["scenarios"]) for r in runs] == [("scripted", 2, 2)]
    assert runs[0]["results"][0]["id"] == "fixture-lost"
