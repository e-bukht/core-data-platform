from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Any


class ErrorCategory(StrEnum):
    VALIDATION = "validation"
    BUSINESS = "business"
    AUTHENTICATION = "authentication"
    AUTHORIZATION = "authorization"
    NOT_FOUND = "not_found"
    DUPLICATE = "duplicate"
    CONCURRENCY = "concurrency"
    DEPENDENCY = "dependency"
    TIMEOUT = "timeout"
    INTERNAL = "internal"


class PlatformError(Exception):
    category: ErrorCategory = ErrorCategory.INTERNAL
    retryable: bool = False

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
        correlation_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})
        self.correlation_id = correlation_id

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "category": self.category.value,
            "message": self.message,
            "retryable": self.retryable,
            "details": self.details,
            "correlation_id": self.correlation_id,
        }


class ValidationError(PlatformError):
    category = ErrorCategory.VALIDATION


class BusinessRuleViolation(PlatformError):
    category = ErrorCategory.BUSINESS


class AuthenticationError(PlatformError):
    category = ErrorCategory.AUTHENTICATION


class AuthorizationError(PlatformError):
    category = ErrorCategory.AUTHORIZATION


class ResourceNotFound(PlatformError):
    category = ErrorCategory.NOT_FOUND


class DuplicateRequest(PlatformError):
    category = ErrorCategory.DUPLICATE


class ConcurrencyConflict(PlatformError):
    category = ErrorCategory.CONCURRENCY
    retryable = True


class DependencyFailure(PlatformError):
    category = ErrorCategory.DEPENDENCY
    retryable = True


class TimeoutError(PlatformError):
    category = ErrorCategory.TIMEOUT
    retryable = True


class InternalError(PlatformError):
    category = ErrorCategory.INTERNAL
