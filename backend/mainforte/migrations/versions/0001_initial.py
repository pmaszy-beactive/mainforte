"""initial

Revision ID: 0001
Revises:
Create Date: 2026-09-25
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def _ts(name: str, **kw):
    return sa.Column(name, sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()"), **kw)


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(26), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False, unique=True),
        sa.Column("name", sa.String(200), nullable=False, server_default=""),
        sa.Column("password_hash", sa.Text),
        sa.Column("role", sa.String(20), nullable=False, server_default="user"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("email_verified_at", sa.DateTime(timezone=True)),
        sa.Column("last_login_at", sa.DateTime(timezone=True)),
        sa.Column("avatar_url", sa.Text),
        sa.Column("locale", sa.String(10), nullable=False, server_default="en-US"),
        sa.Column("timezone", sa.String(64), nullable=False, server_default="America/New_York"),
        sa.Column("prefs", pg.JSONB, nullable=False, server_default="{}"),
        _ts("created_at"), _ts("updated_at"),
    )
    op.create_index("ix_users_email", "users", ["email"])

    op.create_table(
        "oauth_identities",
        sa.Column("id", sa.String(26), primary_key=True),
        sa.Column("user_id", sa.String(26), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("provider_sub", sa.String(255), nullable=False),
        sa.Column("email", sa.String(320)),
        sa.Column("scopes", pg.JSONB, nullable=False, server_default="[]"),
        sa.Column("refresh_token_enc", sa.Text),
        sa.Column("access_token_enc", sa.Text),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        _ts("created_at"), _ts("updated_at"),
        sa.UniqueConstraint("provider", "provider_sub", name="uq_oauth_provider_sub"),
    )
    op.create_index("ix_oauth_identities_user_id", "oauth_identities", ["user_id"])

    op.create_table(
        "workspaces",
        sa.Column("id", sa.String(26), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("owner_id", sa.String(26), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("plan", sa.String(40), nullable=False, server_default="trial"),
        sa.Column("ai_proxy_key_enc", sa.Text),
        sa.Column("settings", pg.JSONB, nullable=False, server_default="{}"),
        _ts("created_at"), _ts("updated_at"),
    )
    op.create_index("ix_workspaces_owner_id", "workspaces", ["owner_id"])

    op.create_table(
        "memberships",
        sa.Column("id", sa.String(26), primary_key=True),
        sa.Column("workspace_id", sa.String(26), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(26), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(20), nullable=False, server_default="member"),
        _ts("created_at"), _ts("updated_at"),
        sa.UniqueConstraint("workspace_id", "user_id", name="uq_membership"),
    )
    op.create_index("ix_memberships_workspace_id", "memberships", ["workspace_id"])
    op.create_index("ix_memberships_user_id", "memberships", ["user_id"])

    op.create_table(
        "auth_tokens",
        sa.Column("id", sa.String(26), primary_key=True),
        sa.Column("user_id", sa.String(26), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("token_hash", sa.String(128), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        _ts("created_at"),
    )
    op.create_index("ix_auth_tokens_user_id", "auth_tokens", ["user_id"])

    op.create_table(
        "events",
        sa.Column("id", sa.String(26), primary_key=True),
        _ts("ts"),
        sa.Column("type", sa.String(80), nullable=False),
        sa.Column("ws_id", sa.String(26)),
        sa.Column("user_id", sa.String(26)),
        sa.Column("actor_type", sa.String(20), nullable=False),
        sa.Column("actor_id", sa.String(64)),
        sa.Column("correlation_id", sa.String(26)),
        sa.Column("causation_id", sa.String(26)),
        sa.Column("payload", pg.JSONB, nullable=False, server_default="{}"),
    )
    op.create_index("ix_events_ws_id", "events", ["ws_id"])
    op.create_index("ix_events_user_id", "events", ["user_id"])
    op.create_index("ix_events_ws_id_id", "events", ["ws_id", "id"])
    op.create_index("ix_events_type_id", "events", ["type", "id"])
    op.create_index("ix_events_correlation", "events", ["correlation_id"])

    op.create_table(
        "api_errors",
        sa.Column("id", sa.String(26), primary_key=True),
        _ts("ts"),
        sa.Column("type", sa.String(120), nullable=False),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("path", sa.Text),
        sa.Column("user_id", sa.String(26)),
        sa.Column("ws_id", sa.String(26)),
        sa.Column("trace", sa.Text),
        sa.Column("context", pg.JSONB, nullable=False, server_default="{}"),
    )
    op.create_index("ix_api_errors_ts", "api_errors", ["ts"])

    op.create_table(
        "agent_workers",
        sa.Column("id", sa.String(26), primary_key=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="starting"),
        sa.Column("node", sa.String(120)),
        sa.Column("container_name", sa.String(120)),
        sa.Column("token_hash", sa.String(128)),
        sa.Column("last_heartbeat", sa.DateTime(timezone=True)),
        sa.Column("current_job", sa.String(120)),
        sa.Column("stats", pg.JSONB, nullable=False, server_default="{}"),
        _ts("created_at"), _ts("updated_at"),
    )

    op.create_table(
        "settings",
        sa.Column("key", sa.String(120), primary_key=True),
        sa.Column("value", pg.JSONB, nullable=False),
        _ts("updated_at"),
    )


def downgrade() -> None:
    for t in ("settings", "agent_workers", "api_errors", "events", "auth_tokens", "memberships", "workspaces",
              "oauth_identities", "users"):
        op.drop_table(t)
