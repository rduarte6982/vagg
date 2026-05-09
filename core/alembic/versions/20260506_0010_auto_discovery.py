"""Adiciona auto_discovery_enabled + auto_discovered_at em clients.

Revision ID: 0010_auto_discovery
Revises: 0009_auth_method
Create Date: 2026-05-06

Quando ``auto_discovery_enabled`` (default true), o post-connect hook do
orchestrator varre as rotas e DNS empurrados pelo gateway e popula
nat_mappings + dns_server automaticamente. Admin que quer fixar mappings
manuais desabilita o flag.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_auto_discovery"
down_revision: str | None = "0009_auth_method"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("clients") as batch:
        batch.add_column(
            sa.Column(
                "auto_discovery_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("1"),
            )
        )
        batch.add_column(
            sa.Column(
                "auto_discovered_at",
                sa.DateTime(timezone=True),
                nullable=True,
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("clients") as batch:
        batch.drop_column("auto_discovered_at")
        batch.drop_column("auto_discovery_enabled")
