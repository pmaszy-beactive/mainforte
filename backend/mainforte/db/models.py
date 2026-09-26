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
    plan: Mapped[str] = mapped_column(String(40), default="trial", nullable=False)
    ai_proxy_key_enc: Mapped[str | None] = mapped_column(Text)
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
    correlation_id: Mapped[str | None] = mapped_column(String(26))
    causation_id: Mapped[str | None] = mapped_column(String(26))
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
