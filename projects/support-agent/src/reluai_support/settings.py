"""Configuration for the support agent (env prefix ``RELUAI_SUPPORT_``)."""

from __future__ import annotations

from datetime import date
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class SupportSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RELUAI_SUPPORT_", env_file=".env", extra="ignore")

    # Order snapshot built at image build time from the verified canonical download.
    data_dir: Path = Path("/var/lib/reluai/data/support")

    # The support desk works "as of" the day after the dataset ends; real dates are never
    # shifted, so delivery windows are measured from here.
    as_of: date = date(2011, 12, 10)

    # Refunds up to this amount are applied by the agent (simulated); above it, a supervisor
    # (the visitor) must approve.
    auto_approve_limit_gbp: float = Field(default=50.0, ge=0)

    max_steps_per_turn: int = Field(default=8, ge=2, le=16)
    max_customer_turns: int = Field(default=6, ge=1, le=20)
    turn_deadline_seconds: float = Field(default=25.0, gt=0)
    visitor_conversations_per_hour: int = Field(default=20, ge=1)
    visitor_messages_per_hour: int = Field(default=60, ge=1)
    conversation_ttl_hours: int = Field(default=24, ge=1)
    message_max_chars: int = Field(default=600, ge=50)

    @property
    def orders_db(self) -> Path:
        return self.data_dir / "orders.duckdb"


@lru_cache(maxsize=1)
def get_support_settings() -> SupportSettings:
    return SupportSettings()
