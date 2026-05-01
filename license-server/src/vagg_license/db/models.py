"""SQLAlchemy 2.0 ORM models for licenses and license_events (SPEC §6.8)."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class LicenseStatus(enum.StrEnum):
    """Mirrors SPEC §6.7. Values are lowercase to match Stripe convention."""

    ACTIVE = "active"
    PAST_DUE = "past_due"
    CANCELED = "canceled"
    PAUSED = "paused"


class Plan(enum.StrEnum):
    """Plan slugs (SPEC §6.1)."""

    STARTER = "starter"
    PROFESSIONAL = "professional"
    ENTERPRISE = "enterprise"


class License(Base):
    __tablename__ = "licenses"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    license_key: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)

    stripe_customer_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    stripe_subscription_id: Mapped[str] = mapped_column(String, nullable=False, index=True)

    plan: Mapped[Plan] = mapped_column(Enum(Plan, name="plan_enum"), nullable=False)
    status: Mapped[LicenseStatus] = mapped_column(
        Enum(LicenseStatus, name="license_status_enum"),
        nullable=False,
    )

    email: Mapped[str] = mapped_column(String, nullable=False)
    company_name: Mapped[str] = mapped_column(String, nullable=False)
    cnpj: Mapped[str | None] = mapped_column(String(18), nullable=True)

    # Set on first /activate; cannot change afterwards (anti-tampering, SPEC §6.6).
    instance_id: Mapped[str | None] = mapped_column(String, nullable=True)
    fingerprint_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_refresh_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    events: Mapped[list[LicenseEvent]] = relationship(
        back_populates="license",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class LicenseEvent(Base):
    __tablename__ = "license_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    license_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("licenses.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    license: Mapped[License] = relationship(back_populates="events")

    __table_args__ = (
        Index("ix_license_events_license_id_occurred_at", "license_id", "occurred_at"),
    )


# Idempotency for Stripe webhook delivery.
class StripeWebhookDelivery(Base):
    __tablename__ = "stripe_webhook_deliveries"

    event_id: Mapped[str] = mapped_column(String, primary_key=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    event_type: Mapped[str] = mapped_column(String, nullable=False)


# Convenience: explicit UTC timestamp helper used by services.
UTC_NOW_SQL = text("(now() at time zone 'utc')")
