"""Adiciona `globalprotect` ao CHECK constraint de clients.vpn_type.

Revision ID: 0006_globalprotect
Revises: 0005_seed_rduarte
Create Date: 2026-05-05

GlobalProtect (Palo Alto) é suportado via openconnect --protocol=gp. O
orchestrator usa a mesma imagem `vagg/tunnel-openconnect`; só muda a env
var TUNNEL_PROTOCOL.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0006_globalprotect"
down_revision: str | None = "0005_seed_rduarte"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # SQLite: precisa drop+create do CHECK via batch_alter_table.
    with op.batch_alter_table("clients") as batch:
        batch.drop_constraint("ck_client_vpn_type", type_="check")
        batch.create_check_constraint(
            "ck_client_vpn_type",
            "vpn_type IN ('openvpn','openconnect','openfortivpn',"
            "'wireguard','strongswan','globalprotect')",
        )


def downgrade() -> None:
    # Atenção: clients existentes com vpn_type='globalprotect' bloqueariam o
    # downgrade. Deletamos antes pra deixar o CHECK voltar coerente.
    op.execute("DELETE FROM clients WHERE vpn_type = 'globalprotect'")
    with op.batch_alter_table("clients") as batch:
        batch.drop_constraint("ck_client_vpn_type", type_="check")
        batch.create_check_constraint(
            "ck_client_vpn_type",
            "vpn_type IN ('openvpn','openconnect','openfortivpn',"
            "'wireguard','strongswan')",
        )
