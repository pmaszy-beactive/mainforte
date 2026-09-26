"""widen event correlation/causation id columns

Stage-scoped correlation ids (P2 phase 5) are "{task_correlation_id}:{stage_index}", which
overflows the original String(26) sized for a bare ULID.

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-25
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("events", "correlation_id", type_=sa.String(64))
    op.alter_column("events", "causation_id", type_=sa.String(64))


def downgrade() -> None:
    op.alter_column("events", "causation_id", type_=sa.String(26))
    op.alter_column("events", "correlation_id", type_=sa.String(26))
