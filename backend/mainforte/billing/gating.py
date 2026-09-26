"""Plan gating (P3 Money). Plain callables invoked explicitly at call sites, not a blanket FastAPI
dependency. `subscriptions.status` (via the active subscription's plan) is the real gating source
of truth; Workspace.plan is only a denormalized cache — never gate off it directly here either,
since a canceled-but-not-yet-reconciled subscription must stop granting access."""
from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from mainforte.db.models import Membership, Plan, Subscription, Workspace

TRIAL_FEATURES = {"max_agents": 1, "max_members": 1, "widgets_limit": 3, "gmail_calendar": False}

_GATING_STATUSES = ("active", "past_due")


def effective_features(db: Session, ws: Workspace) -> dict:
    sub = (
        db.query(Subscription)
        .filter(Subscription.ws_id == ws.id, Subscription.status.in_(_GATING_STATUSES))
        .order_by(Subscription.created_at.desc())
        .first()
    )
    if not sub:
        return TRIAL_FEATURES
    plan = db.get(Plan, sub.plan_id)
    return plan.features if plan else TRIAL_FEATURES


def require_member_capacity(db: Session, ws: Workspace) -> None:
    features = effective_features(db, ws)
    max_members = features.get("max_members")
    if max_members is None:
        return
    count = db.query(Membership).filter_by(workspace_id=ws.id).count()
    if count >= max_members:
        raise HTTPException(
            status.HTTP_402_PAYMENT_REQUIRED,
            f"plan allows at most {max_members} member(s); upgrade to add more",
        )
