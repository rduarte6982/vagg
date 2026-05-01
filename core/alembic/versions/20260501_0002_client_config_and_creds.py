"""Add config_text, vpn_username, vpn_password to clients (SPEC §5.2 / §10.1).

Revision ID: 0002_client_config_and_creds
Revises: 0001_initial
Create Date: 2026-05-01

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_client_config_and_creds"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("clients") as batch:
        batch.add_column(sa.Column("config_text", sa.Text(), nullable=True))
        batch.add_column(sa.Column("vpn_username", sa.String(length=128), nullable=True))
        batch.add_column(sa.Column("vpn_password", sa.String(length=256), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("clients") as batch:
        batch.drop_column("vpn_password")
        batch.drop_column("vpn_username")
        batch.drop_column("config_text")
