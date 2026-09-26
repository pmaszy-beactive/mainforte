"""billing

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-26
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

PLAN_GOOD = "01M3EVDYWCA0RR3MWASE8YTZRT"
PLAN_BETTER = "01M3EVDYWCK7CPT0GRTHM9502F"
PLAN_BEST = "01M3EVDYWCHM04QR4NA0WD7C4Q"
PRICE_GOOD = "01M3EVDYWCTEAHJ1EMWT9GMJ2S"
PRICE_BETTER = "01M3EVDYWC968J9KEXN76D1X8Z"
PRICE_BEST = "01M3EVDYWCPH57KX7VCM46WXZ5"


def upgrade() -> None:
    op.add_column("workspaces", sa.Column("stripe_customer_id", sa.String(64), nullable=True))
    op.add_column("workspaces", sa.Column("stripe_payment_method_id", sa.String(64), nullable=True))
    op.create_index("ix_workspaces_stripe_customer_id", "workspaces", ["stripe_customer_id"], unique=True)

    op.create_table(
        "plans",
        sa.Column("id", sa.String(26), primary_key=True),
        sa.Column("slug", sa.String(40), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("features", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("slug", name="uq_plans_slug"),
    )
    op.create_index("ix_plans_slug", "plans", ["slug"])

    op.create_table(
        "prices",
        sa.Column("id", sa.String(26), primary_key=True),
        sa.Column("plan_id", sa.String(26), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(10), nullable=False, server_default="usd"),
        sa.Column("interval", sa.String(20), nullable=False, server_default="month"),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["plan_id"], ["plans.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_prices_plan_id", "prices", ["plan_id"])
    op.create_index("ix_prices_plan_status", "prices", ["plan_id", "status"])

    op.create_table(
        "coupons",
        sa.Column("id", sa.String(26), primary_key=True),
        sa.Column("code", sa.String(40), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("percent_off", sa.Integer(), nullable=True),
        sa.Column("amount_off_cents", sa.Integer(), nullable=True),
        sa.Column("currency", sa.String(10), nullable=False, server_default="usd"),
        sa.Column("duration", sa.String(20), nullable=False, server_default="once"),
        sa.Column("duration_in_months", sa.Integer(), nullable=True),
        sa.Column("max_redemptions", sa.Integer(), nullable=True),
        sa.Column("redeemed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("code", name="uq_coupons_code"),
    )
    op.create_index("ix_coupons_code", "coupons", ["code"])

    op.create_table(
        "subscriptions",
        sa.Column("id", sa.String(26), primary_key=True),
        sa.Column("ws_id", sa.String(26), nullable=False),
        sa.Column("plan_id", sa.String(26), nullable=False),
        sa.Column("price_id", sa.String(26), nullable=False),
        sa.Column("coupon_id", sa.String(26), nullable=True),
        sa.Column("stripe_subscription_id", sa.String(64), nullable=False),
        sa.Column("stripe_customer_id", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="incomplete"),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_at_period_end", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("latest_invoice_id", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["ws_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["plan_id"], ["plans.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["price_id"], ["prices.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["coupon_id"], ["coupons.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("stripe_subscription_id", name="uq_subscriptions_stripe_subscription_id"),
    )
    op.create_index("ix_subscriptions_ws_id", "subscriptions", ["ws_id"])
    op.create_index("ix_subscriptions_plan_id", "subscriptions", ["plan_id"])
    op.create_index("ix_subscriptions_price_id", "subscriptions", ["price_id"])
    op.create_index("ix_subscriptions_coupon_id", "subscriptions", ["coupon_id"])
    op.create_index("ix_subscriptions_stripe_subscription_id", "subscriptions", ["stripe_subscription_id"])
    op.create_index("ix_subscriptions_stripe_customer_id", "subscriptions", ["stripe_customer_id"])
    op.create_index("ix_subscriptions_ws_status", "subscriptions", ["ws_id", "status", "created_at"])

    op.create_table(
        "stripe_events",
        sa.Column("id", sa.String(26), primary_key=True),
        sa.Column("stripe_event_id", sa.String(64), nullable=False),
        sa.Column("type", sa.String(80), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("payload", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.UniqueConstraint("stripe_event_id", name="uq_stripe_events_stripe_event_id"),
    )
    op.create_index("ix_stripe_events_stripe_event_id", "stripe_events", ["stripe_event_id"])

    plans_table = sa.table(
        "plans",
        sa.column("id", sa.String),
        sa.column("slug", sa.String),
        sa.column("name", sa.String),
        sa.column("features", postgresql.JSONB),
        sa.column("sort_order", sa.Integer),
    )
    op.bulk_insert(
        plans_table,
        [
            {
                "id": PLAN_GOOD,
                "slug": "good",
                "name": "Good",
                "features": {"max_agents": 1, "max_members": 1, "widgets_limit": 3, "gmail_calendar": False},
                "sort_order": 0,
            },
            {
                "id": PLAN_BETTER,
                "slug": "better",
                "name": "Better",
                "features": {"max_agents": 3, "max_members": 5, "widgets_limit": None, "gmail_calendar": False},
                "sort_order": 1,
            },
            {
                "id": PLAN_BEST,
                "slug": "best",
                "name": "Best",
                "features": {"max_agents": None, "max_members": None, "widgets_limit": None, "gmail_calendar": True},
                "sort_order": 2,
            },
        ],
    )

    prices_table = sa.table(
        "prices",
        sa.column("id", sa.String),
        sa.column("plan_id", sa.String),
        sa.column("amount_cents", sa.Integer),
        sa.column("currency", sa.String),
        sa.column("interval", sa.String),
    )
    op.bulk_insert(
        prices_table,
        [
            {"id": PRICE_GOOD, "plan_id": PLAN_GOOD, "amount_cents": 1900, "currency": "usd", "interval": "month"},
            {"id": PRICE_BETTER, "plan_id": PLAN_BETTER, "amount_cents": 2900, "currency": "usd", "interval": "month"},
            {"id": PRICE_BEST, "plan_id": PLAN_BEST, "amount_cents": 5900, "currency": "usd", "interval": "month"},
        ],
    )


def downgrade() -> None:
    op.drop_index("ix_stripe_events_stripe_event_id", table_name="stripe_events")
    op.drop_table("stripe_events")

    op.drop_index("ix_subscriptions_ws_status", table_name="subscriptions")
    op.drop_index("ix_subscriptions_stripe_customer_id", table_name="subscriptions")
    op.drop_index("ix_subscriptions_stripe_subscription_id", table_name="subscriptions")
    op.drop_index("ix_subscriptions_coupon_id", table_name="subscriptions")
    op.drop_index("ix_subscriptions_price_id", table_name="subscriptions")
    op.drop_index("ix_subscriptions_plan_id", table_name="subscriptions")
    op.drop_index("ix_subscriptions_ws_id", table_name="subscriptions")
    op.drop_table("subscriptions")

    op.drop_index("ix_coupons_code", table_name="coupons")
    op.drop_table("coupons")

    op.drop_index("ix_prices_plan_status", table_name="prices")
    op.drop_index("ix_prices_plan_id", table_name="prices")
    op.drop_table("prices")

    op.drop_index("ix_plans_slug", table_name="plans")
    op.drop_table("plans")

    op.drop_index("ix_workspaces_stripe_customer_id", table_name="workspaces")
    op.drop_column("workspaces", "stripe_payment_method_id")
    op.drop_column("workspaces", "stripe_customer_id")
