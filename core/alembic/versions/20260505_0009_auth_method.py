"""Adiciona coluna auth_method (none|otp|saml) em clients.

Revision ID: 0009_auth_method
Revises: 0008_saml_cookie
Create Date: 2026-05-05

Source of truth pro tipo de autenticação MFA do cliente. Substitui o
boolean requires_otp como campo principal do UI, mas mantemos requires_otp
derivado pra compat com o orchestrator e endpoints antigos.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_auth_method"
down_revision: str | None = "0008_saml_cookie"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("clients") as batch:
        batch.add_column(
            sa.Column(
                "auth_method",
                sa.String(length=16),
                nullable=False,
                server_default=sa.text("'none'"),
            )
        )
    # Migra clientes que já tinham requires_otp=true → auth_method='otp'
    op.execute("UPDATE clients SET auth_method = 'otp' WHERE requires_otp = 1")
    # GP com cookie capturado → auth_method='saml'
    op.execute(
        "UPDATE clients SET auth_method = 'saml' "
        "WHERE vpn_type = 'globalprotect' AND saml_cookie IS NOT NULL"
    )


def downgrade() -> None:
    with op.batch_alter_table("clients") as batch:
        batch.drop_column("auth_method")
