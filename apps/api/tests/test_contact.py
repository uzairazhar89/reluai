from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from reluai_api.contact import ContactMessage
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
