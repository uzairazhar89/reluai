from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from reluai_api.contact import RETENTION_DAYS, ContactMessage, purge_old_messages
from reluai_api.main import create_app
from reluai_core.db import Database
from reluai_core.settings import CoreSettings

pytestmark = pytest.mark.db

VALID = {
    "name": "Ada Lovelace",
    "email": "ada@example.com",
    "company": "Analytical Engines Ltd",
    "topic": "contract",
    "message": "We need a data pipeline for our monthly sales exports.",
}


@pytest.fixture
def client(core_settings: CoreSettings, clean_db: Database) -> Iterator[TestClient]:
    with TestClient(create_app(core_settings)) as c:
        yield c


def stored(db: Database) -> int:
    with db.session() as s:
        return int(s.scalar(select(func.count()).select_from(ContactMessage)) or 0)


def test_message_is_stored(client: TestClient, clean_db: Database) -> None:
    r = client.post("/api/contact", json=VALID, headers={"X-Real-IP": "192.0.2.50"})
    assert r.status_code == 202
    assert r.json() == {"received": True}
    assert stored(clean_db) == 1


def test_honeypot_is_silently_dropped(client: TestClient, clean_db: Database) -> None:
    r = client.post("/api/contact", json={**VALID, "website": "http://spam.example"})
    assert r.status_code == 202
    assert stored(clean_db) == 0


@pytest.mark.parametrize(
    "patch",
    [
        {"email": "not-an-email"},
        {"message": "too short"},
        {"name": "Line\nbreak"},
        {"topic": "free-stuff"},
        {"unexpected": "field"},
    ],
)
def test_invalid_input_rejected(client: TestClient, patch: dict[str, str]) -> None:
    r = client.post("/api/contact", json={**VALID, **patch})
    assert r.status_code == 422
    assert r.json()["code"] == "validation_error"


def test_rate_limited_per_visitor(client: TestClient, clean_db: Database) -> None:
    headers = {"X-Real-IP": "192.0.2.77"}
    codes = [client.post("/api/contact", json=VALID, headers=headers).status_code for _ in range(4)]
    assert codes == [202, 202, 202, 429]
    assert stored(clean_db) == 3
    other = client.post("/api/contact", json=VALID, headers={"X-Real-IP": "192.0.2.78"})
    assert other.status_code == 202


def test_old_messages_are_purged(clean_db: Database) -> None:
    now = datetime(2026, 10, 4, tzinfo=UTC)
    with clean_db.session() as s:
        for age_days in (RETENTION_DAYS + 1, RETENTION_DAYS - 1):
            s.add(
                ContactMessage(
                    received_at=now - timedelta(days=age_days),
                    name="n",
                    email="a@example.com",
                    topic="other",
                    message="x" * 20,
                    visitor_key="0" * 16,
                )
            )
    with clean_db.session() as s:
        assert purge_old_messages(s, now=now) == 1
    assert stored(clean_db) == 1
