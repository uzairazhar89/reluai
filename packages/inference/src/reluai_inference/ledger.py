"""Token ledger and daily budgets, so free-tier quotas are never exceeded.

Every call through the chain is recorded (successful or not). Before a call, the budget
policy checks the provider's spend for the current UTC day and the visitor's own spend;
when either is exhausted the chain falls through to the next provider.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy import BigInteger, DateTime, Index, Integer, String, func, select
from sqlalchemy.orm import Mapped, mapped_column

from reluai_core.db import Base, Database
from reluai_inference.errors import BudgetExceededError

Priority = Literal["visitor", "showcase"]


class LlmUsage(Base):
    __tablename__ = "llm_usage"
    __table_args__ = (
        Index("ix_llm_usage_ts_provider", "ts", "provider", "model"),
        {"schema": "platform"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(80))
    feature: Mapped[str] = mapped_column(String(40))
    visitor_key: Mapped[str | None] = mapped_column(String(16), index=True)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    outcome: Mapped[str] = mapped_column(String(24))  # ok | rate_limited | unavailable | ...


def _day_start(now: datetime | None = None) -> datetime:
    now = now or datetime.now(UTC)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


@dataclass(frozen=True, slots=True)
class BudgetPolicy:
    """Daily token budgets per ``provider:model`` (missing key = unlimited, e.g. local)."""

    daily_tokens: dict[str, int] = field(default_factory=dict)
    visitor_daily_tokens: int = 20_000
    showcase_reserve: float = 0.15  # share of each budget only scheduled showcase runs may use


class TokenLedger:
    def __init__(self, db: Database, policy: BudgetPolicy) -> None:
        self.db = db
        self.policy = policy

    def spent_today(self, provider: str, model: str) -> int:
        with self.db.session() as s:
            return int(
                s.scalar(
                    select(
                        func.coalesce(
                            func.sum(LlmUsage.prompt_tokens + LlmUsage.completion_tokens), 0
                        )
                    ).where(
                        LlmUsage.ts >= _day_start(),
                        LlmUsage.provider == provider,
                        LlmUsage.model == model,
                    )
                )
                or 0
            )

    def visitor_spent_today(self, visitor: str) -> int:
        with self.db.session() as s:
            return int(
                s.scalar(
                    select(
                        func.coalesce(
                            func.sum(LlmUsage.prompt_tokens + LlmUsage.completion_tokens), 0
                        )
                    ).where(LlmUsage.ts >= _day_start(), LlmUsage.visitor_key == visitor)
                )
                or 0
            )

    def check(
        self,
        *,
        provider: str,
        model: str,
        visitor: str | None,
        estimate: int,
        priority: Priority,
        costs_tokens: bool,
    ) -> None:
        if not costs_tokens:
            return
        budget = self.policy.daily_tokens.get(f"{provider}:{model}")
        if budget is not None:
            usable = (
                budget
                if priority == "showcase"
                else int(budget * (1 - self.policy.showcase_reserve))
            )
            if self.spent_today(provider, model) + estimate > usable:
                raise BudgetExceededError(f"{provider}:{model} daily budget reached")
        if (
            visitor
            and priority == "visitor"
            and (self.visitor_spent_today(visitor) + estimate > self.policy.visitor_daily_tokens)
        ):
            raise BudgetExceededError("visitor daily token allowance reached")

    def record(
        self,
        *,
        provider: str,
        model: str,
        feature: str,
        visitor: str | None,
        prompt_tokens: int,
        completion_tokens: int,
        latency_ms: int,
        outcome: str,
    ) -> None:
        with self.db.session() as s:
            s.add(
                LlmUsage(
                    provider=provider,
                    model=model,
                    feature=feature[:40],
                    visitor_key=visitor,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    latency_ms=latency_ms,
                    outcome=outcome,
                )
            )

    def usage_since(self, hours: int = 24) -> list[tuple[str, str, int, int]]:
        """(provider, model, calls, tokens) for the last ``hours`` — for the status page."""
        since = datetime.now(UTC) - timedelta(hours=hours)
        with self.db.session() as s:
            rows = s.execute(
                select(
                    LlmUsage.provider,
                    LlmUsage.model,
                    func.count(),
                    func.coalesce(func.sum(LlmUsage.prompt_tokens + LlmUsage.completion_tokens), 0),
                )
                .where(LlmUsage.ts >= since)
                .group_by(LlmUsage.provider, LlmUsage.model)
            ).all()
        return [(p, m, int(c), int(t)) for p, m, c, t in rows]
