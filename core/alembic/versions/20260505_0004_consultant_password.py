"""Add password_hash to consultants — habilita login do VAGG Client com credenciais do usuário, sem usar admin.

Revision ID: 0004_consultant_password
Revises: 0003_portal_tables
Create Date: 2026-05-05

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_consultant_password"
down_revision: str | None = "0003_portal_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("consultants") as batch:
        batch.add_column(sa.Column("password_hash", sa.String(length=256), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("consultants") as batch:
        batch.drop_column("password_hash")
