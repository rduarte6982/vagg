"""Adiciona `totp_secret` em clients — seed base32 RFC 6238 cifrado at-rest
com Fernet. Quando setado, o orchestrator gera o código TOTP automaticamente
a cada connect/reconnect, removendo a necessidade do admin digitar 6 dígitos
toda vez. Mantém `auth_method='otp'` como o gating; secret é opcional (sem
secret = modo manual antigo).

Revision ID: 0010_totp_secret
Revises: 0010_auto_discovery
Create Date: 2026-05-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_totp_secret"
down_revision: str | None = "0010_auto_discovery"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("clients") as batch:
        batch.add_column(sa.Column("totp_secret", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("clients") as batch:
        batch.drop_column("totp_secret")
