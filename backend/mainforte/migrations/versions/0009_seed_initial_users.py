"""seed initial users

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-26
"""
from __future__ import annotations

from alembic import op
from sqlalchemy import text
from sqlalchemy.orm import Session

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

# No plaintext passwords here: every seeded user is created with password_hash=None
# (magic-link / password-reset only) so nothing sensitive lands in git history.
_SEED_EMAILS = ["paul@beactive.ai", "alice@beactive.ai", "daniel@beactive.ai", "kainat@beactive.ai"]


def upgrade() -> None:
    from mainforte.auth.service import create_user

    db = Session(bind=op.get_bind())
    try:
        for email in _SEED_EMAILS:
            email = email.strip().lower()
            existing = db.execute(text("select 1 from users where email = :email"), {"email": email}).first()
            if existing:
                continue
            create_user(db, email=email, password=None)
        db.commit()
    finally:
        db.close()


def downgrade() -> None:
    db = Session(bind=op.get_bind())
    try:
        emails = _SEED_EMAILS
        # workspaces cascade-delete their memberships/personas; drop those before the owning users
        db.execute(
            text("delete from workspaces where owner_id in (select id from users where email = any(:emails))"),
            {"emails": emails},
        )
        db.execute(text("delete from users where email = any(:emails)"), {"emails": emails})
        db.commit()
    finally:
        db.close()
