"""site source_version

Revision ID: 0015
Revises: 0014
Create Date: 2026-09-28
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Which S3-tar version (sites/{id}/source/{version}.tar.zst — see storage.py's
    # site_source_key, sites/source.py) is currently live in the container. 0 = the turn-0 master
    # seeded at provisioning time, before any chat edit has landed. Lets service.py/the persona's
    # tool dispatch know the current version without an extra S3 round-trip just to check — see
    # PLAN.md's Sites "Live editing" > "S3 object shape".
    op.add_column("sites", sa.Column("source_version", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("sites", "source_version")
