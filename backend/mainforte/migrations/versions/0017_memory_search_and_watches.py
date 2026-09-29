"""memory search (memory_chunks + memories.text_fts) and standing-watch tables

Revision ID: 0017
Revises: 0016
Create Date: 2026-09-29
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "memory_chunks",
        sa.Column("id", sa.String(26), primary_key=True),
        sa.Column("ws_id", sa.String(26), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_type", sa.String(20), nullable=False),
        sa.Column("source_id", sa.String(26), nullable=False),
        sa.Column("thread_id", sa.String(26)),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_memory_chunks_ws_id", "memory_chunks", ["ws_id"])
    op.create_index("ix_memory_chunks_thread_id", "memory_chunks", ["thread_id"])
    op.create_index("ix_memory_chunks_ws_source", "memory_chunks", ["ws_id", "source_type", "created_at"])
    op.add_column(
        "memory_chunks",
        sa.Column(
            "text_fts",
            postgresql.TSVECTOR,
            sa.Computed("to_tsvector('english', coalesce(text, ''))", persisted=True),
            nullable=True,
        ),
    )
    op.create_index("ix_memory_chunks_text_fts", "memory_chunks", ["text_fts"], postgresql_using="gin")

    op.add_column(
        "memories",
        sa.Column(
            "text_fts",
            postgresql.TSVECTOR,
            sa.Computed("to_tsvector('english', coalesce(text, ''))", persisted=True),
            nullable=True,
        ),
    )
    op.create_index("ix_memories_text_fts", "memories", ["text_fts"], postgresql_using="gin")

    op.add_column("uploads", sa.Column("extracted_text", sa.Text))

    op.create_table(
        "preferences",
        sa.Column("id", sa.String(26), primary_key=True),
        sa.Column("ws_id", sa.String(26), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(26), sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("source_event_id", sa.String(26), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="noted"),
        sa.Column("task_id", sa.String(26), sa.ForeignKey("tasks.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_preferences_ws_id", "preferences", ["ws_id"])
    op.create_index("ix_preferences_user_id", "preferences", ["user_id"])
    op.create_index("ix_preferences_ws_status", "preferences", ["ws_id", "status", "created_at"])

    op.create_table(
        "fetch_cache",
        sa.Column("id", sa.String(26), primary_key=True),
        sa.Column("url", sa.Text, nullable=False, unique=True),
        sa.Column("content", postgresql.JSONB, nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("fetch_cache")
    op.drop_index("ix_preferences_ws_status", table_name="preferences")
    op.drop_index("ix_preferences_user_id", table_name="preferences")
    op.drop_index("ix_preferences_ws_id", table_name="preferences")
    op.drop_table("preferences")
    op.drop_column("uploads", "extracted_text")
    op.drop_index("ix_memories_text_fts", table_name="memories")
    op.drop_column("memories", "text_fts")
    op.drop_index("ix_memory_chunks_text_fts", table_name="memory_chunks")
    op.drop_column("memory_chunks", "text_fts")
    op.drop_index("ix_memory_chunks_ws_source", table_name="memory_chunks")
    op.drop_index("ix_memory_chunks_thread_id", table_name="memory_chunks")
    op.drop_index("ix_memory_chunks_ws_id", table_name="memory_chunks")
    op.drop_table("memory_chunks")
