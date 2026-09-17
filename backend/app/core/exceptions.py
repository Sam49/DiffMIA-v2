"""Structured exceptions.

Errors are intentionally converted into a stable machine-readable envelope:

    {"error": "MODEL_UNAVAILABLE", "message": "...", "request_id": "..."}

so that raw tracebacks are never shown to API / UI users.
"""
from __future__ import annotations

from typing import Any


class DiffMiaError(Exception):
    """Base class for expected application errors."""

    code = "INTERNAL_ERROR"
    status_code = 500

    def __init__(self, message: str = "", *, code: str | None = None, status_code: int | None = None, details: Any = None) -> None:
        super().__init__(message or self.code)
        self.message = message or self.code
        if code:
            self.code = code
        if status_code:
            self.status_code = status_code
        self.details = details


class NotFoundError(DiffMiaError):
    code = "NOT_FOUND"
    status_code = 404

    def __init__(self, message: str = "Resource not found", *, code: str | None = None, details: Any = None) -> None:
        super().__init__(message, code=code or self.code, status_code=404, details=details)


class ValidationError(DiffMiaError):
    code = "VALIDATION_ERROR"
    status_code = 422

    def __init__(self, message: str = "Invalid input", *, code: str | None = None, details: Any = None) -> None:
        super().__init__(message, code=code or self.code, status_code=422, details=details)


class AuthenticationError(DiffMiaError):
    code = "AUTHENTICATION_REQUIRED"
    status_code = 401

    def __init__(self, message: str = "Authentication required", *, code: str | None = None, details: Any = None) -> None:
        super().__init__(message, code=code or self.code, status_code=401, details=details)


class RateLimitError(DiffMiaError):
    code = "RATE_LIMITED"
    status_code = 429

    def __init__(self, message: str = "Too many requests", *, details: Any = None) -> None:
        super().__init__(message, code=self.code, status_code=429, details=details)


class PermissionDeniedError(DiffMiaError):
    code = "PERMISSION_DENIED"
    status_code = 403

    def __init__(self, message: str = "Insufficient permissions", *, code: str | None = None, details: Any = None) -> None:
        super().__init__(message, code=code or self.code, status_code=403, details=details)


class ProviderError(DiffMiaError):
    """Raised by LLM providers (load failures, missing logprobs, timeouts...)."""

    code = "MODEL_UNAVAILABLE"
    status_code = 502


class JobError(DiffMiaError):
    """Raised while executing a background experiment."""

    code = "EXPERIMENT_FAILED"
    status_code = 409


class ConflictError(DiffMiaError):
    code = "CONFLICT"
    status_code = 409

    def __init__(self, message: str = "Resource already exists", *, code: str | None = None, details: Any = None) -> None:
        super().__init__(message, code=code or self.code, status_code=409, details=details)


class UnsafeInputError(ValidationError):
    """Raised when uploaded/entered content cannot be validated safely."""

    code = "UNSAFE_INPUT"

    def __init__(self, message: str = "Input could not be validated safely", *, details: Any = None) -> None:
        super().__init__(message, code=self.code, details=details)
