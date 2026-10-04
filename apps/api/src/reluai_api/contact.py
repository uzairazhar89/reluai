"""Contact form: messages are validated, rate-limited per visitor and stored in PostgreSQL.

Read them with ``reluai contact list``. A hidden ``website`` field catches naive bots: when
it is filled in the request is accepted (so bots learn nothing) but nothing is stored.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from reluai_core.db import Base, DatabaseDep
from reluai_core.errors import ProblemError
from reluai_core.http import client_ip
from reluai_core.logging import get_logger
from reluai_core.ratelimit import consume_quota, visitor_key

router = APIRouter(tags=["contact"])
log = get_logger(__name__)

EMAIL_PATTERN = r"^[^@\s]{1,64}@[^@\s]{1,255}\.[A-Za-z]{2,}$"
MESSAGES_PER_HOUR = 3
MESSAGES_PER_DAY = 6


class ContactMessage(Base):
    __tablename__ = "contact_message"
    __table_args__ = {"schema": "platform"}  # noqa: RUF012 - SQLAlchemy convention

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(320))
    company: Mapped[str | None] = mapped_column(String(120))
    topic: Mapped[str] = mapped_column(String(40))
    message: Mapped[str] = mapped_column(Text)
    visitor_key: Mapped[str] = mapped_column(String(16))


Topic = Annotated[
    str,
    Field(pattern=r"^(project|contract|full_time|consulting|other)$"),
]


class ContactIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=120)
    email: str = Field(max_length=320, pattern=EMAIL_PATTERN)
    company: str | None = Field(default=None, max_length=120)
    topic: Topic = "project"
    message: str = Field(min_length=20, max_length=4000)
    website: str | None = Field(default=None, max_length=200, description="Leave empty")

    @field_validator("name", "company")
    @classmethod
    def _single_line(cls, v: str | None) -> str | None:
        if v is not None and ("\n" in v or "\r" in v):
            raise ValueError("must be a single line")
        return v


class ContactAccepted(BaseModel):
    received: bool = True


@router.post("/contact", response_model=ContactAccepted, status_code=status.HTTP_202_ACCEPTED)
def post_contact(body: ContactIn, request: Request, db: DatabaseDep) -> ContactAccepted:
    """Send a message. Limited to 3 per hour and 6 per day per visitor."""
    secret = request.app.state.core_settings.visitor_hash_secret.get_secret_value()
    visitor = visitor_key(client_ip(request), secret)
    if body.website:  # honeypot
        log.info("contact.honeypot", visitor=visitor)
        return ContactAccepted()
    with db.session() as s:
        hourly = consume_quota(
            s, key=f"contact-h:{visitor}", limit=MESSAGES_PER_HOUR, window=timedelta(hours=1)
        )
        daily = consume_quota(
            s, key=f"contact-d:{visitor}", limit=MESSAGES_PER_DAY, window=timedelta(days=1)
        )
    if not (hourly.allowed and daily.allowed):
        retry = max(
            hourly.retry_after_seconds if not hourly.allowed else 0,
            daily.retry_after_seconds if not daily.allowed else 0,
        )
        raise ProblemError(
            429,
            "Message limit reached. Please email directly instead.",
            code="quota_exceeded",
            headers={"Retry-After": str(retry)},
        )
    with db.session() as s:
        s.add(
            ContactMessage(
                name=body.name,
                email=body.email,
                company=body.company,
                topic=body.topic,
                message=body.message,
                visitor_key=visitor,
            )
        )
    log.info("contact.received", topic=body.topic, at=datetime.now(UTC).isoformat())
    return ContactAccepted()
