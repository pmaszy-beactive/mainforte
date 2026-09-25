"""personas

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-25
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "personas",
        sa.Column("id", sa.String(26), primary_key=True),
        sa.Column("ws_id", sa.String(26), nullable=False),
        sa.Column("slug", sa.String(40), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("model", sa.String(80), nullable=False),
        sa.Column("settings", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("ws_id", "slug", name="uq_persona_ws_slug"),
    )
    op.create_index("ix_personas_ws_id", "personas", ["ws_id"])


def downgrade() -> None:
    op.drop_index("ix_personas_ws_id", table_name="personas")
    op.drop_table("personas")
