"""task qa and schedule

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-26
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("last_qa_stage", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("tasks", sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("tasks", sa.Column("schedule", postgresql.JSONB, nullable=True))


def downgrade() -> None:
    op.drop_column("tasks", "schedule")
    op.drop_column("tasks", "attempt")
    op.drop_column("tasks", "last_qa_stage")
