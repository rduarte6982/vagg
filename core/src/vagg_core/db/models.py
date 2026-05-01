"""SQLAlchemy 2.0 ORM models.

SPEC §4.2 (NAT mappings), §5.1 (CRUD resources), §7 (RBAC), §8 (audit).
SQLite-friendly types only — no JSONB, no Postgres ENUMs (use TEXT + CHECK).
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# ----- Enums (stored as TEXT with CHECK constraints — SQLite-compatible) -----


class VpnType(enum.StrEnum):
    OPENVPN = "openvpn"
    OPENCONNECT = "openconnect"
    OPENFORTIVPN = "openfortivpn"
    WIREGUARD = "wireguard"
    STRONGSWAN = "strongswan"


class TunnelState(enum.StrEnum):
    STOPPED = "stopped"
    STARTING = "starting"
    UP = "up"
    DOWN = "down"
    ERRORED = "errored"


class PolicyScopeKind(enum.StrEnum):
    """Scope kind tag (full/subnet/host). Free-form value lives in ``Policy.scope_value``."""

    FULL = "full"
    SUBNET = "subnet"
    HOST = "host"


# ----- Tables -----


class Client(Base):
    """A tenant — i.e., one of the consultancy's customers (e.g., 'petroleo')."""

    __tablename__ = "clients"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # slug, e.g. "petroleo"
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    vpn_type: Mapped[VpnType] = mapped_column(
        Enum(
            VpnType,
            native_enum=False,
            length=32,
            validate_strings=True,
            values_callable=lambda enum: [e.value for e in enum],
        ),
        nullable=False,
    )
    virtual_cidr: Mapped[str] = mapped_column(String(43), nullable=False)  # IPv4/IPv6 CIDR
    real_cidr: Mapped[str] = mapped_column(String(43), nullable=False)
    dns_server: Mapped[str | None] = mapped_column(String(45), nullable=True)
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # SPEC §5.2 / §10.1: the .ovpn (or equivalent) protocol config + credentials.
    # Phase 3 stores plaintext to keep the orchestrator simple. A future phase
    # will encrypt at rest with a master key derived from VAGG_CORE_JWT_SECRET.
    config_text: Mapped[str | None] = mapped_column(Text(), nullable=True)
    vpn_username: Mapped[str | None] = mapped_column(String(128), nullable=True)
    vpn_password: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # ``lazy="selectin"`` eagerly fetches related rows in a follow-up SELECT, so async
    # endpoints can read these collections without triggering a sync lazy-load (which
    # would raise sqlalchemy.exc.MissingGreenlet under aiosqlite).
    nat_mappings: Mapped[list[NatMapping]] = relationship(
        back_populates="client",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    tunnel_status: Mapped[TunnelStatus | None] = relationship(
        back_populates="client",
        cascade="all, delete-orphan",
        uselist=False,
        lazy="selectin",
    )
    policies: Mapped[list[Policy]] = relationship(
        back_populates="client",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    __table_args__ = (
        CheckConstraint(
            "vpn_type IN ('openvpn','openconnect','openfortivpn','wireguard','strongswan')",
            name="ck_client_vpn_type",
        ),
    )


class NatMapping(Base):
    """Many-to-one with Client. SPEC §4.2 — virtual ↔ real CIDR mappings."""

    __tablename__ = "nat_mappings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    client_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )
    virtual_cidr: Mapped[str] = mapped_column(String(43), nullable=False)
    real_cidr: Mapped[str] = mapped_column(String(43), nullable=False)
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    client: Mapped[Client] = relationship(back_populates="nat_mappings")

    __table_args__ = (Index("ix_nat_mappings_client_id", "client_id"),)


class TunnelStatus(Base):
    """Denormalized cache of the live tunnel state (Phase 3 fills it; Phase 2 stubs it)."""

    __tablename__ = "tunnel_status"

    client_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("clients.id", ondelete="CASCADE"),
        primary_key=True,
    )
    container_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    state: Mapped[TunnelState] = mapped_column(
        Enum(
            TunnelState,
            native_enum=False,
            length=16,
            validate_strings=True,
            values_callable=lambda enum: [e.value for e in enum],
        ),
        nullable=False,
        default=TunnelState.STOPPED,
    )
    last_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(2048), nullable=True)

    client: Mapped[Client] = relationship(back_populates="tunnel_status")

    __table_args__ = (
        CheckConstraint(
            "state IN ('stopped','starting','up','down','errored')",
            name="ck_tunnel_state",
        ),
    )


class Consultant(Base):
    """An employee of the consultancy that connects to client networks (SPEC §7)."""

    __tablename__ = "consultants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(254), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    # Maps to OpenVPN identity (SPEC §7.2 option B: static IP mapping).
    openvpn_username: Mapped[str | None] = mapped_column(String(128), nullable=True, unique=True)
    static_pool_ip: Mapped[str | None] = mapped_column(String(45), nullable=True, unique=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="viewer")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    policies: Mapped[list[Policy]] = relationship(
        back_populates="consultant",
        cascade="all, delete-orphan",
        foreign_keys="Policy.consultant_id",
        lazy="selectin",
    )

    __table_args__ = (
        CheckConstraint("role IN ('viewer','operator','admin')", name="ck_consultant_role"),
    )


class Policy(Base):
    """Authorization rule (SPEC §7.1)."""

    __tablename__ = "policies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    consultant_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("consultants.id", ondelete="CASCADE"), nullable=False
    )
    client_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )
    scope_kind: Mapped[PolicyScopeKind] = mapped_column(
        Enum(
            PolicyScopeKind,
            native_enum=False,
            length=16,
            validate_strings=True,
            values_callable=lambda enum: [e.value for e in enum],
        ),
        nullable=False,
        default=PolicyScopeKind.FULL,
    )
    scope_value: Mapped[str | None] = mapped_column(String(64), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("consultants.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    consultant: Mapped[Consultant] = relationship(
        back_populates="policies",
        foreign_keys=[consultant_id],
    )
    client: Mapped[Client] = relationship(back_populates="policies")
    created_by: Mapped[Consultant | None] = relationship(foreign_keys=[created_by_id])

    __table_args__ = (
        CheckConstraint(
            "scope_kind IN ('full','subnet','host')",
            name="ck_policy_scope_kind",
        ),
        UniqueConstraint(
            "consultant_id",
            "client_id",
            "scope_kind",
            "scope_value",
            name="uq_policy_unique_scope",
        ),
    )


class AuditEvent(Base):
    """Append-only audit log with hash chain (SPEC §8)."""

    __tablename__ = "audit_events"

    # UUIDv7 stored as 36-char string (SQLite has no native UUID type).
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_consultant_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("consultants.id", ondelete="SET NULL"), nullable=True
    )
    payload: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    prev_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    hash: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (Index("ix_audit_events_event_type_occurred_at", "event_type", "occurred_at"),)
