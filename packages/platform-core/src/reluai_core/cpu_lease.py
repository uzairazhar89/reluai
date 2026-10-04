"""A single, global "CPU lease" so only one heavy job runs at a time on a 2-vCPU host.

Implemented with a PostgreSQL session-level advisory lock, so it works across containers
(API, worker, CLI) without Redis. The lock is released when the context exits or, if the
process dies, when its database connection closes.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from sqlalchemy import Engine, text

from reluai_core.logging import get_logger

# Stays below 2**31 so pg_locks reports it as classid=0, objid=<key>.
CPU_LEASE_KEY = 0x52454C55  # "RELU"
_APP_PREFIX = "cpu-lease:"

log = get_logger(__name__)


class LeaseUnavailableError(RuntimeError):
    """The CPU lease could not be acquired within the allowed wait."""


@dataclass(frozen=True, slots=True)
class LeaseStatus:
    held: bool
    holder: str | None


@contextmanager
def cpu_lease(
    engine: Engine,
    *,
    holder: str,
    wait_seconds: float,
    poll_seconds: float = 1.0,
) -> Iterator[None]:
    """Hold the global CPU lease for the duration of the block.

    ``holder`` is a short human-readable label (e.g. ``pipeline-run:<id>``) shown on the
    status page while the lease is held.
    """
    conn = engine.connect().execution_options(isolation_level="AUTOCOMMIT")
    started = time.monotonic()
    acquired = False
    try:
        conn.execute(
            text("SELECT set_config('application_name', :n, false)"),
            {"n": (_APP_PREFIX + holder)[:63]},
        )
        while True:
            acquired = bool(
                conn.execute(
                    text("SELECT pg_try_advisory_lock(:k)"), {"k": CPU_LEASE_KEY}
                ).scalar_one()
            )
            if acquired:
                break
            if time.monotonic() - started >= wait_seconds:
                raise LeaseUnavailableError(
                    f"CPU lease busy for more than {wait_seconds:.0f}s (wanted by {holder})"
                )
            time.sleep(poll_seconds)
        log.info(
            "cpu_lease.acquired",
            holder=holder,
            waited_ms=round((time.monotonic() - started) * 1000),
        )
        yield
    finally:
        try:
            if acquired:
                conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": CPU_LEASE_KEY})
                log.info("cpu_lease.released", holder=holder)
        finally:
            conn.close()


def lease_status(engine: Engine) -> LeaseStatus:
    """Who (if anyone) currently holds the CPU lease."""
    sql = text(
        """
        SELECT a.application_name
        FROM pg_locks l JOIN pg_stat_activity a ON a.pid = l.pid
        WHERE l.locktype = 'advisory' AND l.classid = 0 AND l.objid = :k
          AND l.objsubid = 1 AND l.granted
        LIMIT 1
        """
    )
    with engine.connect() as conn:
        name = conn.execute(sql, {"k": CPU_LEASE_KEY}).scalar_one_or_none()
    if name is None:
        return LeaseStatus(held=False, holder=None)
    return LeaseStatus(held=True, holder=str(name).removeprefix(_APP_PREFIX))
