"""Seed user `rduarte` (password 123456) — primeiro consultor cadastrado pra
validar o fluxo de login do VAGG Client.

Revision ID: 0005_seed_rduarte
Revises: 0004_consultant_password
Create Date: 2026-05-05

Idempotente: se já existe um consultor com esse email/name, só atualiza o
password_hash. Se a tabela está vazia ou não tem o rduarte, insere.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from vagg_core.core.security import hash_password

revision: str = "0005_seed_rduarte"
down_revision: str | None = "0004_consultant_password"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_RDUARTE_EMAIL = "rduarte@vagg.example"
_RDUARTE_NAME = "rduarte"
_RDUARTE_PASSWORD = "123456"  # senha inicial pra dev/lab


def upgrade() -> None:
    pwd_hash = hash_password(_RDUARTE_PASSWORD)
    bind = op.get_bind()
    existing = bind.exec_driver_sql(
        "SELECT id FROM consultants WHERE email = ? OR name = ? LIMIT 1",
        (_RDUARTE_EMAIL, _RDUARTE_NAME),
    ).fetchone()
    if existing:
        bind.exec_driver_sql(
            "UPDATE consultants SET password_hash = ?, active = 1 WHERE id = ?",
            (pwd_hash, existing[0]),
        )
    else:
        bind.exec_driver_sql(
            "INSERT INTO consultants (email, name, password_hash, role, active) "
            "VALUES (?, ?, ?, 'admin', 1)",
            (_RDUARTE_EMAIL, _RDUARTE_NAME, pwd_hash),
        )


def downgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql(
        "DELETE FROM consultants WHERE email = ? OR name = ?",
        (_RDUARTE_EMAIL, _RDUARTE_NAME),
    )
