"""Workspace-level operations that don't fit neatly as a single route handler."""
from __future__ import annotations

from sqlalchemy.orm import Session

from mainforte.db.models import ClientMessage, Event, Memory, Persona, Task, Upload, Widget
from mainforte.events import emit
from mainforte.personas.service import seed_defaults


def reset_workspace(db: Session, *, ws_id: str, actor: tuple[str, str | None]) -> None:
    """Wipes a workspace back to a fresh, just-created state and reseeds it — used mainly for
    testing, but exposed as a real user-facing "start over" feature (see POST /api/me/reset).

    Deliberately keeps `Subscription`, `Membership`, the `Workspace` row itself, and every `User`
    row untouched — only the workspace's *content* (chat history, personas, memory, tasks,
    widgets, uploads) is wiped. `Event`/`ClientMessage`/`Upload` have no FK on `ws_id` (append-only,
    deliberately unlinked) so they need an explicit bulk delete; `Persona`/`Memory`/`Task`/`Widget`
    do cascade off `Workspace`, but that cascade only fires when the *parent* row is deleted — since
    the `Workspace` itself survives a reset, these also need explicit bulk deletes.

    Caller is responsible for the transaction (commits happen the same way `emit()` expects — inside
    the caller's `with db_session() as db:` block) and for re-running the onboarding interview
    afterward (see `events.onboarding.run_onboarding`), since that needs an async context this
    synchronous function doesn't have.
    """
    for model in (Event, ClientMessage, Upload, Persona, Memory, Task, Widget):
        db.query(model).filter(model.ws_id == ws_id).delete(synchronize_session=False)

    seed_defaults(db, ws_id=ws_id, actor=actor)
    emit(db, "workspace.reset", ws_id=ws_id, actor=actor, payload={})
