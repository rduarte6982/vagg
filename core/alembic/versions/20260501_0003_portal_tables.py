"""Portal de Transparência (SPEC §5.6 / Fase 11) — external_viewers + tokens + log.

Revision ID: 0003_portal_tables
Revises: 0002_client_config_and_creds
Create Date: 2026-05-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_portal_tables"
down_revision: str | None = "0002_client_config_and_creds"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "external_viewers",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("client_id", sa.String(length=64), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False, server_default="auditor"),
        sa.Column("totp_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("totp_secret", sa.String(length=64), nullable=True),
        sa.Column("invited_by_id", sa.Integer(), nullable=True),
        sa.Column(
            "invited_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["invited_by_id"], ["consultants.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("client_id", "email", name="uq_external_viewer_client_email"),
        sa.CheckConstraint(
            "role IN ('auditor','manager','compliance')",
            name="ck_external_viewer_role",
        ),
    )
    op.create_table(
        "external_viewer_tokens",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("viewer_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False, unique=True),
        sa.Column("issued_ip", sa.String(length=45), nullable=True),
        sa.Column("user_agent", sa.String(length=256), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["viewer_id"], ["external_viewers.id"], ondelete="CASCADE"),
        sa.CheckConstraint("kind IN ('magic','session')", name="ck_external_viewer_token_kind"),
    )
    op.create_index("ix_external_viewer_tokens_viewer", "external_viewer_tokens", ["viewer_id"])

    op.create_table(
        "portal_access_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("viewer_id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.String(length=64), nullable=False),
        sa.Column("endpoint", sa.String(length=128), nullable=False),
        sa.Column("ip_address", sa.String(length=45), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["viewer_id"], ["external_viewers.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_portal_access_log_viewer",
        "portal_access_log",
        ["viewer_id", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_portal_access_log_viewer", table_name="portal_access_log")
    op.drop_table("portal_access_log")
    op.drop_index("ix_external_viewer_tokens_viewer", table_name="external_viewer_tokens")
    op.drop_table("external_viewer_tokens")
    op.drop_table("external_viewers")
