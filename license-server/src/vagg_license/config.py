"""Application settings.

Loaded from environment variables; see .env.example for the full list.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _normalize_db_url(url: str) -> str:
    """Coerce common Postgres URL schemes onto the asyncpg driver.

    Render and Heroku surface ``postgres://``; psycopg-aware tools surface
    ``postgresql+psycopg2://``. SQLAlchemy with asyncpg requires
    ``postgresql+asyncpg://``.
    """
    if url.startswith("postgresql+asyncpg://"):
        return url
    for prefix in ("postgresql+psycopg2://", "postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+asyncpg://" + url.removeprefix(prefix)
    return url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="VAGG_LICENSE_",
        extra="ignore",
    )

    # ----- Runtime -----
    environment: Literal["dev", "staging", "production", "test"] = "dev"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    bind_host: str = "0.0.0.0"  # noqa: S104 — container binds to all interfaces by design
    bind_port: int = 8080

    # ----- Database -----
    # Format: postgresql+asyncpg://user:pass@host:port/dbname
    # postgres:// and postgresql:// are accepted and normalized.
    database_url: SecretStr

    @field_validator("database_url", mode="before")
    @classmethod
    def _normalize_database_url(cls, raw: str | SecretStr) -> str:
        value = raw.get_secret_value() if isinstance(raw, SecretStr) else raw
        return _normalize_db_url(value)

    # ----- Ed25519 signing keys -----
    # Private key in PEM format (multi-line). Stored as secret env var in production.
    jwt_private_key_pem: SecretStr
    # Public key in PEM format. Used for self-verification on issue.
    jwt_public_key_pem: str

    # JWT lifetime: 7 dias (SPEC §6.2). License refresh is daily.
    jwt_ttl_seconds: int = 7 * 24 * 3600
    jwt_issuer: str = "vagg-license-server"

    # ----- Stripe -----
    stripe_api_key: SecretStr
    stripe_webhook_secret: SecretStr
    # Tolerance window (seconds) for Stripe webhook timestamp verification.
    stripe_webhook_tolerance_seconds: int = 300

    # ----- Plan limits (SPEC §6.1) -----
    # Stripe price IDs map to internal plan slugs. Required keys: starter, professional, enterprise.
    stripe_price_id_starter: str = Field(default="price_starter_placeholder")
    stripe_price_id_professional: str = Field(default="price_professional_placeholder")
    stripe_price_id_enterprise: str = Field(default="price_enterprise_placeholder")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return memoized Settings. Tests override via dependency injection."""
    return Settings()
