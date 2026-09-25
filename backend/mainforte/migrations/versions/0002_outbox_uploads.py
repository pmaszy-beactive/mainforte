"""outbox + uploads + client message idempotency

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-25
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("events", sa.Column("dispatched_at", sa.DateTime(timezone=True)))
    op.create_index("ix_events_undispatched", "events", ["ts"], postgresql_where=sa.text("dispatched_at IS NULL"))
    op.create_table(
        "client_messages",
        sa.Column("ws_id", sa.String(26), primary_key=True),
        sa.Column("client_msg_id", sa.String(64), primary_key=True),
        sa.Column("event_id", sa.String(26), nullable=False),
        sa.Column("thread_id", sa.String(26), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_table(
        "uploads",
        sa.Column("id", sa.String(26), primary_key=True),
        sa.Column("ws_id", sa.String(26), nullable=False),
        sa.Column("user_id", sa.String(26)),
        sa.Column("key", sa.Text, nullable=False, unique=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(120), nullable=False),
        sa.Column("size", sa.Integer, nullable=False),
        sa.Column("sha256", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_uploads_ws_id", "uploads", ["ws_id"])


def downgrade() -> None:
    op.drop_table("uploads")
    op.drop_table("client_messages")
    op.drop_index("ix_events_undispatched", table_name="events")
    op.drop_column("events", "dispatched_at")
