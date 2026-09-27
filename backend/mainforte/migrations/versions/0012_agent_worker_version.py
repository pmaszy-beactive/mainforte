"""agent worker version column

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-27T00:00:00Z
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = '0012'
down_revision = '0011'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('agent_workers', sa.Column('version', sa.String(length=20), nullable=True))


def downgrade() -> None:
    op.drop_column('agent_workers', 'version')
