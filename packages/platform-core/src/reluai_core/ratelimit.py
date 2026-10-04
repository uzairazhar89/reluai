"""Anonymous per-visitor quotas stored in PostgreSQL.

nginx already limits request *rates*; this module enforces *quotas* on expensive actions
(e.g. "3 pipeline runs per visitor per hour") across all API processes. Visitors are
identified by a keyed hash of their IP address and the current day, so raw IPs are never
stored and keys cannot be linked across days.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import DateTime, Integer, String, text
from sqlalchemy.orm import Mapped, Session, mapped_column

from reluai_core.db import Base


class RateCounter(Base):
    __tablename__ = "rate_counter"
    __table_args__ = {"schema": "platform"}  # noqa: RUF012 - SQLAlchemy convention

    key: Mapped[str] = mapped_column(String(160), primary_key=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


@dataclass(frozen=True, slots=True)
class QuotaResult:
    allowed: bool
    limit: int
    remaining: int
    reset_at: datetime

    @property
    def retry_after_seconds(self) -> int:
        return max(1, int((self.reset_at - datetime.now(UTC)).total_seconds()))


def visitor_key(ip: str, secret: str, *, now: datetime | None = None) -> str:
    """Keyed, day-scoped pseudonym for a client IP (16 hex chars)."""
    day = (now or datetime.now(UTC)).strftime("%Y-%m-%d")
    digest = hmac.new(secret.encode(), f"{day}|{ip}".encode(), hashlib.sha256).hexdigest()
    return digest[:16]


def consume_quota(
    session: Session,
    *,
    key: str,
    limit: int,
    window: timedelta,
    now: datetime | None = None,
) -> QuotaResult:
    """Atomically count one use of ``key`` in the current fixed window."""
    now = now or datetime.now(UTC)
    seconds = int(window.total_seconds())
    window_start = datetime.fromtimestamp((int(now.timestamp()) // seconds) * seconds, UTC)
    count = session.execute(
        text(
            """
            INSERT INTO platform.rate_counter (key, window_start, count)
            VALUES (:key, :ws, 1)
            ON CONFLICT (key, window_start)
            DO UPDATE SET count = platform.rate_counter.count + 1
            RETURNING count
            """
        ),
        {"key": key, "ws": window_start},
    ).scalar_one()
    reset_at = window_start + window
    return QuotaResult(
        allowed=count <= limit, limit=limit, remaining=max(0, limit - count), reset_at=reset_at
    )


def purge_expired(session: Session, *, older_than: timedelta = timedelta(days=2)) -> int:
    result = session.execute(
        text("DELETE FROM platform.rate_counter WHERE window_start < :cutoff"),
        {"cutoff": datetime.now(UTC) - older_than},
    )
    return int(getattr(result, "rowcount", 0) or 0)
