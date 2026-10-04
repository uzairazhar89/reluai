"""Contact-form messages (platform.contact_message).

Runtime-role grants come from the default privileges set in 0001.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-04
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "contact_message",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("company", sa.String(length=120), nullable=True),
        sa.Column("topic", sa.String(length=40), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("visitor_key", sa.String(length=16), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_contact_message")),
        schema="platform",
    )
    op.create_index(
        op.f("ix_platform_contact_message_received_at"),
        "contact_message",
        ["received_at"],
        unique=False,
        schema="platform",
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_platform_contact_message_received_at"),
        table_name="contact_message",
        schema="platform",
    )
    op.drop_table("contact_message", schema="platform")
