"""marketplace v1 (listings, listing photos, orders)

Revision ID: 0013
Revises: 0012
Create Date: 2026-09-28
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "listings",
        sa.Column("id", sa.String(26), primary_key=True),
        sa.Column("seller_user_id", sa.String(26), nullable=False),
        sa.Column("ws_id", sa.String(26), nullable=True),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("category", sa.String(40), nullable=False),
        sa.Column("condition", sa.String(20), nullable=True),
        sa.Column("price_cents", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(10), nullable=False, server_default="usd"),
        sa.Column("location_label", sa.String(200), nullable=True),
        sa.Column("lat", sa.Float(), nullable=True),
        sa.Column("lng", sa.Float(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("flagged", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("report_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["seller_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["ws_id"], ["workspaces.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_listings_seller_user_id", "listings", ["seller_user_id"])
    op.create_index("ix_listings_ws_id", "listings", ["ws_id"])
    op.create_index("ix_listings_status_kind", "listings", ["status", "kind", "created_at"])
    op.create_index("ix_listings_seller", "listings", ["seller_user_id", "status"])

    op.add_column(
        "listings",
        sa.Column(
            "text_fts",
            postgresql.TSVECTOR,
            sa.Computed("to_tsvector('english', coalesce(title,'') || ' ' || coalesce(description,''))", persisted=True),
            nullable=True,
        ),
    )
    op.create_index("ix_listings_text_fts", "listings", ["text_fts"], postgresql_using="gin")

    op.create_table(
        "listing_photos",
        sa.Column("id", sa.String(26), primary_key=True),
        sa.Column("listing_id", sa.String(26), nullable=False),
        sa.Column("upload_id", sa.String(26), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["listing_id"], ["listings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["upload_id"], ["uploads.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("listing_id", "upload_id", name="uq_listing_photo"),
    )
    op.create_index("ix_listing_photos_listing_id", "listing_photos", ["listing_id"])

    op.create_table(
        "orders",
        sa.Column("id", sa.String(26), primary_key=True),
        sa.Column("listing_id", sa.String(26), nullable=False),
        sa.Column("buyer_user_id", sa.String(26), nullable=False),
        sa.Column("seller_user_id", sa.String(26), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("application_fee_cents", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(10), nullable=False, server_default="usd"),
        sa.Column("payment_method", sa.String(20), nullable=False),
        sa.Column("escrow_status", sa.String(20), nullable=False, server_default="none"),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("stripe_transfer_id", sa.String(64), nullable=True),
        sa.Column("stripe_payment_intent_id", sa.String(64), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["listing_id"], ["listings.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["buyer_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["seller_user_id"], ["users.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_orders_listing_id", "orders", ["listing_id"])
    op.create_index("ix_orders_buyer_user_id", "orders", ["buyer_user_id"])
    op.create_index("ix_orders_seller_user_id", "orders", ["seller_user_id"])
    op.create_index("ix_orders_listing", "orders", ["listing_id", "status"])
    op.create_index("ix_orders_buyer", "orders", ["buyer_user_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_orders_buyer", table_name="orders")
    op.drop_index("ix_orders_listing", table_name="orders")
    op.drop_index("ix_orders_seller_user_id", table_name="orders")
    op.drop_index("ix_orders_buyer_user_id", table_name="orders")
    op.drop_index("ix_orders_listing_id", table_name="orders")
    op.drop_table("orders")

    op.drop_index("ix_listing_photos_listing_id", table_name="listing_photos")
    op.drop_table("listing_photos")

    op.drop_index("ix_listings_text_fts", table_name="listings")
    op.drop_column("listings", "text_fts")
    op.drop_index("ix_listings_seller", table_name="listings")
    op.drop_index("ix_listings_status_kind", table_name="listings")
    op.drop_index("ix_listings_ws_id", table_name="listings")
    op.drop_index("ix_listings_seller_user_id", table_name="listings")
    op.drop_table("listings")
