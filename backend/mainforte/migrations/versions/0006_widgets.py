"""widgets

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-25
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "widgets",
        sa.Column("id", sa.String(26), primary_key=True),
        sa.Column("ws_id", sa.String(26), nullable=False),
        sa.Column("owner_id", sa.String(26), nullable=False),
        sa.Column("slug", sa.String(120), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("refresh_spec", postgresql.JSONB, nullable=True),
        sa.Column("token", sa.String(26), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["ws_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("owner_id", "slug", name="uq_widget_owner_slug"),
        sa.UniqueConstraint("token", name="uq_widgets_token"),
    )
    op.create_index("ix_widgets_ws_id", "widgets", ["ws_id"])
    op.create_index("ix_widgets_owner_id", "widgets", ["owner_id"])
    op.create_index("ix_widgets_token", "widgets", ["token"])


def downgrade() -> None:
    op.drop_index("ix_widgets_token", table_name="widgets")
    op.drop_index("ix_widgets_owner_id", table_name="widgets")
    op.drop_index("ix_widgets_ws_id", table_name="widgets")
    op.drop_table("widgets")
