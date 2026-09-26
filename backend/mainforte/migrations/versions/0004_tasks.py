"""tasks

Revision ID: 0004
Revises: dd1d98bc24b0
Create Date: 2026-09-25
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004"
down_revision = "dd1d98bc24b0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tasks",
        sa.Column("id", sa.String(26), primary_key=True),
        sa.Column("ws_id", sa.String(26), nullable=False),
        sa.Column("thread_id", sa.String(26), nullable=True),
        sa.Column("persona_id", sa.String(26), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="planned"),
        sa.Column("plan", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("current_stage", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("result", postgresql.JSONB, nullable=True),
        sa.Column("correlation_id", sa.String(26), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["ws_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["persona_id"], ["personas.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_tasks_ws_id", "tasks", ["ws_id"])
    op.create_index("ix_tasks_thread_id", "tasks", ["thread_id"])
    op.create_index("ix_tasks_persona_id", "tasks", ["persona_id"])
    op.create_index("ix_tasks_correlation_id", "tasks", ["correlation_id"])
    op.create_index("ix_tasks_ws_status", "tasks", ["ws_id", "status", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_tasks_ws_status", table_name="tasks")
    op.drop_index("ix_tasks_correlation_id", table_name="tasks")
    op.drop_index("ix_tasks_persona_id", table_name="tasks")
    op.drop_index("ix_tasks_thread_id", table_name="tasks")
    op.drop_index("ix_tasks_ws_id", table_name="tasks")
    op.drop_table("tasks")
