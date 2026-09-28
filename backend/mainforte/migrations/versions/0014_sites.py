"""sites

Revision ID: 0014
Revises: 0013
Create Date: 2026-09-28
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sites",
        sa.Column("id", sa.String(26), primary_key=True),
        sa.Column("ws_id", sa.String(26), nullable=False),
        sa.Column("owner_id", sa.String(26), nullable=False),
        sa.Column("slug", sa.String(63), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("brief", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="provisioning"),
        sa.Column("stage", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("container_name", sa.String(120), nullable=True),
        sa.Column("dev_port", sa.Integer(), nullable=True),
        sa.Column("container_api_key_hash", sa.String(128), nullable=True),
        sa.Column("db_password_encrypted", sa.Text(), nullable=True),
        sa.Column("preview_token", sa.String(26), nullable=False),
        sa.Column("last_heartbeat", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("agent_thread_id", sa.String(26), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["ws_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("ws_id", "slug", name="uq_site_ws_slug"),
        sa.UniqueConstraint("preview_token", name="uq_sites_preview_token"),
    )
    op.create_index("ix_sites_ws_id", "sites", ["ws_id"])
    op.create_index("ix_sites_owner_id", "sites", ["owner_id"])
    op.create_index("ix_sites_preview_token", "sites", ["preview_token"])


def downgrade() -> None:
    op.drop_index("ix_sites_preview_token", table_name="sites")
    op.drop_index("ix_sites_owner_id", table_name="sites")
    op.drop_index("ix_sites_ws_id", table_name="sites")
    op.drop_table("sites")
