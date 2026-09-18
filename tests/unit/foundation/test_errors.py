from core_platform.foundation.errors import ConcurrencyConflict, ErrorCategory, ValidationError


def test_validation_error_is_not_retryable() -> None:
    error = ValidationError("TEST.INVALID", "invalid")
    assert error.category is ErrorCategory.VALIDATION
    assert error.retryable is False


def test_concurrency_error_is_retryable() -> None:
    error = ConcurrencyConflict("TEST.CONFLICT", "conflict")
    assert error.category is ErrorCategory.CONCURRENCY
    assert error.retryable is True
