"""initial schema: licenses, license_events, stripe_webhook_deliveries.

Revision ID: 0001_initial
Revises:
Create Date: 2026-05-01

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    plan_enum = postgresql.ENUM(
        "starter", "professional", "enterprise", name="plan_enum", create_type=True
    )
    status_enum = postgresql.ENUM(
        "active",
        "past_due",
        "canceled",
        "paused",
        name="license_status_enum",
        create_type=True,
    )

    op.create_table(
        "licenses",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("license_key", sa.String(length=32), nullable=False, unique=True),
        sa.Column("stripe_customer_id", sa.String(), nullable=False),
        sa.Column("stripe_subscription_id", sa.String(), nullable=False),
        sa.Column("plan", plan_enum, nullable=False),
        sa.Column("status", status_enum, nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("company_name", sa.String(), nullable=False),
        sa.Column("cnpj", sa.String(length=18), nullable=True),
        sa.Column("instance_id", sa.String(), nullable=True),
        sa.Column("fingerprint_hash", sa.String(length=64), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_refresh_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_licenses_stripe_customer_id", "licenses", ["stripe_customer_id"], unique=False
    )
    op.create_index(
        "ix_licenses_stripe_subscription_id",
        "licenses",
        ["stripe_subscription_id"],
        unique=False,
    )

    op.create_table(
        "license_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "license_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("licenses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_license_events_license_id_occurred_at",
        "license_events",
        ["license_id", "occurred_at"],
        unique=False,
    )

    op.create_table(
        "stripe_webhook_deliveries",
        sa.Column("event_id", sa.String(), primary_key=True),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("event_type", sa.String(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("stripe_webhook_deliveries")
    op.drop_index("ix_license_events_license_id_occurred_at", table_name="license_events")
    op.drop_table("license_events")
    op.drop_index("ix_licenses_stripe_subscription_id", table_name="licenses")
    op.drop_index("ix_licenses_stripe_customer_id", table_name="licenses")
    op.drop_table("licenses")
    op.execute("DROP TYPE IF EXISTS license_status_enum")
    op.execute("DROP TYPE IF EXISTS plan_enum")
