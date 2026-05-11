"""Adiciona saml_cookie + saml_cookie_expires_at em clients.

Revision ID: 0008_saml_cookie
Revises: 0007_requires_otp
Create Date: 2026-05-05

Pra VPNs que autenticam via SAML/SSO (típico em GlobalProtect com Azure AD).
O cookie é capturado num browser remoto (vagg-saml-portal) e salvo aqui.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_saml_cookie"
down_revision: str | None = "0007_requires_otp"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("clients") as batch:
        batch.add_column(sa.Column("saml_cookie", sa.Text(), nullable=True))
        batch.add_column(
            sa.Column("saml_cookie_expires_at", sa.DateTime(timezone=True), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("clients") as batch:
        batch.drop_column("saml_cookie_expires_at")
        batch.drop_column("saml_cookie")
