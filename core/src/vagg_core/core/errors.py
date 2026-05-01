"""Domain errors mapped to HTTP responses (SPEC §13.3 envelope)."""

from __future__ import annotations

from fastapi import HTTPException, status


class CoreError(HTTPException):
    """Base exception with a structured envelope."""

    code: str = "CORE_ERROR"
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


class NotFoundError(CoreError):
    code = "NOT_FOUND"
    default_status = status.HTTP_404_NOT_FOUND


class ConflictError(CoreError):
    code = "CONFLICT"
    default_status = status.HTTP_409_CONFLICT


class InvalidCredentialsError(CoreError):
    code = "INVALID_CREDENTIALS"
    default_status = status.HTTP_401_UNAUTHORIZED


class AuthRequiredError(CoreError):
    code = "AUTH_REQUIRED"
    default_status = status.HTTP_401_UNAUTHORIZED


class ForbiddenError(CoreError):
    code = "FORBIDDEN"
    default_status = status.HTTP_403_FORBIDDEN


class NotImplementedYetError(CoreError):
    """Returned by stubbed endpoints (Phases 3+)."""

    code = "NOT_IMPLEMENTED_YET"
    default_status = status.HTTP_501_NOT_IMPLEMENTED


class ValidationConflictError(CoreError):
    """Constraint violation we surface as 422 to mirror pydantic's input errors."""

    code = "VALIDATION_CONFLICT"
    default_status = status.HTTP_422_UNPROCESSABLE_ENTITY
