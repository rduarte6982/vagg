"""Domain errors mapped to HTTP responses (SPEC §13.3 error envelope)."""

from __future__ import annotations

from fastapi import HTTPException, status


class LicenseServerError(HTTPException):
    """Base error with structured envelope."""

    code: str = "LICENSE_SERVER_ERROR"
    default_status: int = status.HTTP_500_INTERNAL_SERVER_ERROR

    def __init__(
        self,
        detail: str,
        *,
        status_code: int | None = None,
        context: dict[str, object] | None = None,
    ) -> None:
        super().__init__(
            status_code=status_code or self.default_status,
            detail={"detail": detail, "code": self.code, "context": context or {}},
        )


class LicenseNotFoundError(LicenseServerError):
    code = "LICENSE_NOT_FOUND"
    default_status = status.HTTP_404_NOT_FOUND


class FingerprintMismatchError(LicenseServerError):
    code = "FINGERPRINT_MISMATCH"
    default_status = status.HTTP_409_CONFLICT


class LicenseInactiveError(LicenseServerError):
    """Raised when a refresh request hits a canceled subscription (SPEC §6.4)."""

    code = "LICENSE_INACTIVE"
    default_status = status.HTTP_402_PAYMENT_REQUIRED


class WebhookSignatureInvalidError(LicenseServerError):
    code = "WEBHOOK_SIGNATURE_INVALID"
    default_status = status.HTTP_400_BAD_REQUEST


class StripeIntegrationError(LicenseServerError):
    code = "STRIPE_INTEGRATION_ERROR"
    default_status = status.HTTP_502_BAD_GATEWAY
