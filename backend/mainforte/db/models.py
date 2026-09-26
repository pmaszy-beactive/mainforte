from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from mainforte.db.base import Base, IdMixin, TimestampMixin, utcnow

# ---------------------------------------------------------------- users & workspaces


class User(IdMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    password_hash: Mapped[str | None] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(20), default="user", nullable=False)  # user | superuser
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    avatar_url: Mapped[str | None] = mapped_column(Text)
    locale: Mapped[str] = mapped_column(String(10), default="en-US", nullable=False)   # en-US | fr-CA
    timezone: Mapped[str] = mapped_column(String(64), default="America/New_York", nullable=False)
    prefs: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    memberships: Mapped[list[Membership]] = relationship(back_populates="user", cascade="all, delete-orphan")
    identities: Mapped[list[OAuthIdentity]] = relationship(back_populates="user", cascade="all, delete-orphan")

    @property
    def is_superuser(self) -> bool:
        return self.role == "superuser"


class OAuthIdentity(IdMixin, TimestampMixin, Base):
    """Google (and later others). Also holds encrypted refresh tokens for Gmail/Calendar scopes."""

    __tablename__ = "oauth_identities"
    __table_args__ = (UniqueConstraint("provider", "provider_sub", name="uq_oauth_provider_sub"),)

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    provider_sub: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str | None] = mapped_column(String(320))
    scopes: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    refresh_token_enc: Mapped[str | None] = mapped_column(Text)
    access_token_enc: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="identities")


class Workspace(IdMixin, TimestampMixin, Base):
    """A family / household / small team. Billing and bots are per workspace."""

    __tablename__ = "workspaces"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    # denormalized cache of the effective plan slug (trial|good|better|best); real gating reads
    # subscriptions.status, this column is a fast-path display/routing hint only.
    plan: Mapped[str] = mapped_column(String(40), default="trial", nullable=False)
    ai_proxy_key_enc: Mapped[str | None] = mapped_column(Text)
    stripe_customer_id: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)
    stripe_payment_method_id: Mapped[str | None] = mapped_column(String(64))
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    memberships: Mapped[list[Membership]] = relationship(back_populates="workspace", cascade="all, delete-orphan")


class Membership(IdMixin, TimestampMixin, Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("workspace_id", "user_id", name="uq_membership"),)

    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(20), default="member", nullable=False)  # owner | admin | member

    workspace: Mapped[Workspace] = relationship(back_populates="memberships")
    user: Mapped[User] = relationship(back_populates="memberships")


class AuthToken(IdMixin, Base):
    """Single-use tokens: magic_link | password_reset | email_verify. Stored hashed."""

    __tablename__ = "auth_tokens"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


# ---------------------------------------------------------------- events (the spine)


class Event(Base):
    """Append-only. id is a ULID so ordering == time. Mirrored into the workspace Redis stream."""

    __tablename__ = "events"
    __table_args__ = (
        Index("ix_events_ws_id_id", "ws_id", "id"),
        Index("ix_events_type_id", "type", "id"),
        Index("ix_events_correlation", "correlation_id"),
    )

    id: Mapped[str] = mapped_column(String(26), primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    type: Mapped[str] = mapped_column(String(80), nullable=False)
    ws_id: Mapped[str | None] = mapped_column(String(26), index=True)
    user_id: Mapped[str | None] = mapped_column(String(26), index=True)
    actor_type: Mapped[str] = mapped_column(String(20), nullable=False)  # user|persona|worker|system
    actor_id: Mapped[str | None] = mapped_column(String(64))
    correlation_id: Mapped[str | None] = mapped_column(String(64))
    causation_id: Mapped[str | None] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    # transactional outbox: set once the event has been published to Redis and its handlers enqueued.
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ClientMessage(Base):
    """Idempotency ledger for chat posts: (workspace, client_msg_id) -> event id. Retries return the same event."""

    __tablename__ = "client_messages"

    ws_id: Mapped[str] = mapped_column(String(26), primary_key=True)
    client_msg_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(26), nullable=False)
    thread_id: Mapped[str] = mapped_column(String(26), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class Upload(IdMixin, Base):
    """A file a human attached (or a persona produced). Bytes live in storage under `key`."""

    __tablename__ = "uploads"

    ws_id: Mapped[str] = mapped_column(String(26), nullable=False, index=True)
    user_id: Mapped[str | None] = mapped_column(String(26))
    key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(120), nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


# ---------------------------------------------------------------- personas


class Persona(IdMixin, TimestampMixin, Base):
    """One staff member, scoped to a workspace. `slug` identifies the archetype (concierge, pm, cfo, ...)
    and selects the system prompt + default model; `name` is the (possibly renamed) display name."""

    __tablename__ = "personas"
    __table_args__ = (UniqueConstraint("ws_id", "slug", name="uq_persona_ws_slug"),)

    ws_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    slug: Mapped[str] = mapped_column(String(40), nullable=False)  # concierge|pm|cfo|architect|marketer|coder|executor
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)  # active|removed
    model: Mapped[str] = mapped_column(String(80), nullable=False)
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)


class Memory(IdMixin, TimestampMixin, Base):
    """A note in workspace memory. `kind` discriminates shared workspace notes, per-persona notes,
    and rollup summaries. `persona_id` is set only for persona-scoped kinds."""

    __tablename__ = "memories"
    __table_args__ = (Index("ix_memories_ws_kind", "ws_id", "kind", "created_at"),)

    ws_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    persona_id: Mapped[str | None] = mapped_column(ForeignKey("personas.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)  # workspace|persona|rollup_day|rollup_week|rollup_month
    thread_id: Mapped[str | None] = mapped_column(String(26))  # set for rollup_* (which thread it summarizes)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(40), default="concierge", nullable=False)  # concierge|persona|rollup|user


# ---------------------------------------------------------------- tasks


class Task(IdMixin, TimestampMixin, Base):
    """One agentic task run (PLAN.md §1.5): a plan of stages a worker executes, with room to pause
    for human input (`status="blocked"`) and resume. `plan` is an ordered list of stage specs
    (shape owned by the task-pipeline code, not the DB); `current_stage` indexes into it."""

    __tablename__ = "tasks"
    __table_args__ = (Index("ix_tasks_ws_status", "ws_id", "status", "created_at"),)

    ws_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    thread_id: Mapped[str | None] = mapped_column(String(26), index=True)
    persona_id: Mapped[str | None] = mapped_column(ForeignKey("personas.id", ondelete="CASCADE"), index=True)
    # planned|approved|running|blocked|qa|completed|failed|canceled
    status: Mapped[str] = mapped_column(String(20), default="planned", nullable=False)
    plan: Mapped[list[Any]] = mapped_column(JSONB, default=list, nullable=False)
    current_stage: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    correlation_id: Mapped[str | None] = mapped_column(String(26), index=True)


# ---------------------------------------------------------------- widgets


class Widget(IdMixin, TimestampMixin, Base):
    """A small HTML+data bundle a persona publishes and can refresh on a schedule (PLAN.md §1.7).
    Served unauthenticated at /w/{token}/ — `token` is the raw capability secret (not hashed like
    AuthToken) since serving needs a direct lookup with no separate login step."""

    __tablename__ = "widgets"
    __table_args__ = (UniqueConstraint("owner_id", "slug", name="uq_widget_owner_slug"),)

    ws_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    slug: Mapped[str] = mapped_column(String(120), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)  # active|disabled
    refresh_spec: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    token: Mapped[str] = mapped_column(String(26), nullable=False, unique=True, index=True)


# ---------------------------------------------------------------- billing (P3)


class Plan(IdMixin, TimestampMixin, Base):
    """A plan tier we sell (PLAN.md P3). Ours, not a Stripe Dashboard object — subscriptions are
    created with inline price_data/coupon drawn from these rows, never a Stripe product/price id."""

    __tablename__ = "plans"

    slug: Mapped[str] = mapped_column(String(40), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)  # active|retired
    features: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    prices: Mapped[list[Price]] = relationship(back_populates="plan", cascade="all, delete-orphan")


class Price(IdMixin, TimestampMixin, Base):
    """A price point a plan has been sold at. Kept separate from Plan so an existing subscription
    keeps the price it signed up under even if the plan's current price changes later."""

    __tablename__ = "prices"
    __table_args__ = (Index("ix_prices_plan_status", "plan_id", "status"),)

    plan_id: Mapped[str] = mapped_column(ForeignKey("plans.id", ondelete="CASCADE"), nullable=False, index=True)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(10), default="usd", nullable=False)
    interval: Mapped[str] = mapped_column(String(20), default="month", nullable=False)  # month|year
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)  # active|retired

    plan: Mapped[Plan] = relationship(back_populates="prices")


class Coupon(IdMixin, TimestampMixin, Base):
    """Ours, applied ad hoc onto a Stripe subscription at creation time (never a Stripe coupon id)."""

    __tablename__ = "coupons"

    code: Mapped[str] = mapped_column(String(40), nullable=False, unique=True, index=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)  # percent|amount
    percent_off: Mapped[int | None] = mapped_column(Integer)
    amount_off_cents: Mapped[int | None] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(10), default="usd", nullable=False)
    duration: Mapped[str] = mapped_column(String(20), default="once", nullable=False)  # once|repeating|forever
    duration_in_months: Mapped[int | None] = mapped_column(Integer)
    max_redemptions: Mapped[int | None] = mapped_column(Integer)
    redeemed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)  # active|disabled
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Subscription(IdMixin, TimestampMixin, Base):
    """A workspace's subscription to a plan/price. `status` is the real gating source of truth
    (never Workspace.plan). Reconciled hourly and on-login via sync_subscription_from_stripe, the
    same function the webhook handler calls, so the two paths can never race into disagreement."""

    __tablename__ = "subscriptions"
    __table_args__ = (Index("ix_subscriptions_ws_status", "ws_id", "status", "created_at"),)

    ws_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    plan_id: Mapped[str] = mapped_column(ForeignKey("plans.id", ondelete="RESTRICT"), nullable=False, index=True)
    price_id: Mapped[str] = mapped_column(ForeignKey("prices.id", ondelete="RESTRICT"), nullable=False, index=True)
    coupon_id: Mapped[str | None] = mapped_column(ForeignKey("coupons.id", ondelete="SET NULL"), index=True)
    stripe_subscription_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    stripe_customer_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # incomplete|active|past_due|canceled|unpaid|requires_action
    status: Mapped[str] = mapped_column(String(20), default="incomplete", nullable=False)
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    latest_invoice_id: Mapped[str | None] = mapped_column(String(64))


class StripeEvent(IdMixin, Base):
    """Webhook idempotency ledger: one row per processed Stripe event id."""

    __tablename__ = "stripe_events"

    stripe_event_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    type: Mapped[str] = mapped_column(String(80), nullable=False)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)


# ---------------------------------------------------------------- ops


class ApiError(IdMixin, Base):
    __tablename__ = "api_errors"

    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(120), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    path: Mapped[str | None] = mapped_column(Text)
    user_id: Mapped[str | None] = mapped_column(String(26))
    ws_id: Mapped[str | None] = mapped_column(String(26))
    trace: Mapped[str | None] = mapped_column(Text)
    context: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)


class AgentWorker(IdMixin, TimestampMixin, Base):
    """One row per agent-worker container (aw-*). Worker #1 is backbone's standard worker."""

    __tablename__ = "agent_workers"

    status: Mapped[str] = mapped_column(String(20), default="starting", nullable=False)  # starting|online|draining|offline
    node: Mapped[str | None] = mapped_column(String(120))
    container_name: Mapped[str | None] = mapped_column(String(120))
    token_hash: Mapped[str | None] = mapped_column(String(128))
    last_heartbeat: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    current_job: Mapped[str | None] = mapped_column(String(120))
    stats: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)


class Setting(Base):
    """Runtime-tunable settings (e.g. workers.desired). Admin-editable."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
