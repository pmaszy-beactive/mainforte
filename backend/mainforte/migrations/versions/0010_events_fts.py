"""events full-text search

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-27
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "events",
        sa.Column(
            "text_fts",
            postgresql.TSVECTOR,
            sa.Computed("to_tsvector('english', coalesce(payload->>'text', ''))", persisted=True),
            nullable=True,
        ),
    )
    op.create_index("ix_events_text_fts", "events", ["text_fts"], postgresql_using="gin")


def downgrade() -> None:
    op.drop_index("ix_events_text_fts", table_name="events")
    op.drop_column("events", "text_fts")
