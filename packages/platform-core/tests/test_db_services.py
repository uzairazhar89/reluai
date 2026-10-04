from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta

import pytest

from reluai_core.cpu_lease import LeaseUnavailableError, cpu_lease, lease_status
from reluai_core.db import Database
from reluai_core.jobs import queue_depth
from reluai_core.ratelimit import consume_quota, visitor_key

pytestmark = pytest.mark.db


def test_visitor_key_is_keyed_and_day_scoped() -> None:
    day1 = datetime(2026, 1, 1, 12, tzinfo=UTC)
    a = visitor_key("203.0.113.7", "s1", now=day1)
    assert a == visitor_key("203.0.113.7", "s1", now=day1)
    assert a != visitor_key("203.0.113.7", "s2", now=day1)
    assert a != visitor_key("203.0.113.7", "s1", now=day1 + timedelta(days=1))
    assert "203" not in a and len(a) == 16


def test_quota_counts_within_window(clean_db: Database) -> None:
    now = datetime(2026, 1, 1, 10, 15, tzinfo=UTC)
    with clean_db.session() as s:
        results = [
            consume_quota(s, key="k", limit=2, window=timedelta(hours=1), now=now) for _ in range(3)
        ]
    assert [r.allowed for r in results] == [True, True, False]
    assert results[2].remaining == 0
    assert results[2].reset_at == datetime(2026, 1, 1, 11, tzinfo=UTC)
    with clean_db.session() as s:
        later = consume_quota(
            s, key="k", limit=2, window=timedelta(hours=1), now=now + timedelta(hours=1)
        )
    assert later.allowed


def test_cpu_lease_is_exclusive_across_connections(db: Database) -> None:
    holding = threading.Event()
    release = threading.Event()

    def hold() -> None:
        with cpu_lease(db.engine, holder="test-holder", wait_seconds=1):
            holding.set()
            release.wait(5)

    t = threading.Thread(target=hold)
    t.start()
    assert holding.wait(5)
    status = lease_status(db.engine)
    assert status.held and status.holder == "test-holder"
    with (
        pytest.raises(LeaseUnavailableError),
        cpu_lease(db.engine, holder="second", wait_seconds=0.5, poll_seconds=0.1),
    ):
        pass
    release.set()
    t.join(5)
    assert lease_status(db.engine).held is False
    with cpu_lease(db.engine, holder="third", wait_seconds=1):
        assert lease_status(db.engine).holder == "third"


def test_queue_depth_reads_job_table(db: Database) -> None:
    assert queue_depth(db.engine, "heavy") == 0
