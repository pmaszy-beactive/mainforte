"""user last_active_at

Revision ID: 0016
Revises: 0015
Create Date: 2026-09-29
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Distinct from users.last_login_at (set once per session-mint in auth/routes.py's
    # _session_response). last_active_at is bumped on ANY authenticated request — see
    # auth/deps.py::resolve_identity — so admins can see who is actually using the product right
    # now vs. who merely has a live session.
    op.add_column("users", sa.Column("last_active_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "last_active_at")
