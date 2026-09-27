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
    # Insert rows directly rather than calling auth.service.create_user(): that helper emits
    # events (user.created, workspace.created) via the outbox, whose after_commit hook opens its
    # own connection to mark them dispatched -- but migrations run inside alembic's single
    # outer transaction, so that second connection can't yet see tables this same run just
    # created. A migration must never trigger the event bus.
    from mainforte.auth.service import role_for
    from mainforte.db.models import Membership, User, Workspace

    db = Session(bind=op.get_bind())
    try:
        for email in _SEED_EMAILS:
            email = email.strip().lower()
            existing = db.execute(text("select 1 from users where email = :email"), {"email": email}).first()
            if existing:
                continue
            name = email.split("@")[0]
            user = User(email=email, name=name, role=role_for(email), password_hash=None)
            db.add(user)
            db.flush()
            ws = Workspace(name=f"{name}'s home", owner_id=user.id)
            db.add(ws)
            db.flush()
            db.add(Membership(workspace_id=ws.id, user_id=user.id, role="owner"))
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
