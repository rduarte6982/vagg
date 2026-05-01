"""initial schema: clients, nat_mappings, tunnel_status, consultants, policies, audit_events.

Revision ID: 0001_initial
Revises:
Create Date: 2026-05-01

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "clients",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("vpn_type", sa.String(length=32), nullable=False),
        sa.Column("virtual_cidr", sa.String(length=43), nullable=False),
        sa.Column("real_cidr", sa.String(length=43), nullable=False),
        sa.Column("dns_server", sa.String(length=45), nullable=True),
        sa.Column("description", sa.String(length=512), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "vpn_type IN ('openvpn','openconnect','openfortivpn','wireguard','strongswan')",
            name="ck_client_vpn_type",
        ),
    )

    op.create_table(
        "nat_mappings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "client_id",
            sa.String(length=64),
            sa.ForeignKey("clients.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("virtual_cidr", sa.String(length=43), nullable=False),
        sa.Column("real_cidr", sa.String(length=43), nullable=False),
        sa.Column("description", sa.String(length=512), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_nat_mappings_client_id", "nat_mappings", ["client_id"])

    op.create_table(
        "tunnel_status",
        sa.Column(
            "client_id",
            sa.String(length=64),
            sa.ForeignKey("clients.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("container_id", sa.String(length=64), nullable=True),
        sa.Column("state", sa.String(length=16), nullable=False, server_default="stopped"),
        sa.Column("last_check_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=2048), nullable=True),
        sa.CheckConstraint(
            "state IN ('stopped','starting','up','down','errored')",
            name="ck_tunnel_state",
        ),
    )

    op.create_table(
        "consultants",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("email", sa.String(length=254), nullable=False, unique=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("openvpn_username", sa.String(length=128), nullable=True, unique=True),
        sa.Column("static_pool_ip", sa.String(length=45), nullable=True, unique=True),
        sa.Column("role", sa.String(length=16), nullable=False, server_default="viewer"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "role IN ('viewer','operator','admin')",
            name="ck_consultant_role",
        ),
    )

    op.create_table(
        "policies",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "consultant_id",
            sa.Integer(),
            sa.ForeignKey("consultants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "client_id",
            sa.String(length=64),
            sa.ForeignKey("clients.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("scope_kind", sa.String(length=16), nullable=False, server_default="full"),
        sa.Column("scope_value", sa.String(length=64), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_by_id",
            sa.Integer(),
            sa.ForeignKey("consultants.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "scope_kind IN ('full','subnet','host')",
            name="ck_policy_scope_kind",
        ),
        sa.UniqueConstraint(
            "consultant_id",
            "client_id",
            "scope_kind",
            "scope_value",
            name="uq_policy_unique_scope",
        ),
    )

    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column(
            "actor_consultant_id",
            sa.Integer(),
            sa.ForeignKey("consultants.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("prev_hash", sa.String(length=64), nullable=True),
        sa.Column("hash", sa.String(length=64), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_audit_events_event_type_occurred_at",
        "audit_events",
        ["event_type", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_audit_events_event_type_occurred_at", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_table("policies")
    op.drop_table("consultants")
    op.drop_table("tunnel_status")
    op.drop_index("ix_nat_mappings_client_id", table_name="nat_mappings")
    op.drop_table("nat_mappings")
    op.drop_table("clients")
