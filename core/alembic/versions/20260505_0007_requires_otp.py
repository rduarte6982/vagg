"""Adiciona `requires_otp` em clients — flag pra MFA via OTP push (token gerado
no app autenticador do user, enviado durante o connect).

Revision ID: 0007_requires_otp
Revises: 0006_globalprotect
Create Date: 2026-05-05
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_requires_otp"
down_revision: str | None = "0006_globalprotect"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("clients") as batch:
        batch.add_column(
            sa.Column(
                "requires_otp",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("clients") as batch:
        batch.drop_column("requires_otp")
