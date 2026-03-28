"""Retry helpers for Cursor upstream requests."""

from __future__ import annotations

import random

from handlers import CredentialError, RateLimitError
from runtime_config import runtime_config


class RetrySettings(tuple):
    __slots__ = ()

    @property
    def attempts(self) -> int:
        return self[0]

    @property
    def backoff_seconds(self) -> float:
        return self[1]


def get_retry_settings() -> RetrySettings:
    """Snapshot retry-related runtime settings for a single request."""
    return RetrySettings(
        (
            int(runtime_config.get("retry_attempts")),
            float(runtime_config.get("retry_backoff_seconds")),
        )
    )


def exponential_backoff_delay(attempt: int, backoff_seconds: float) -> float:
    """Return jittered exponential backoff delay with existing limits."""
    base = backoff_seconds * (2**attempt)
    jitter = random.uniform(0, base * 0.3)
    return min(base + jitter, 30.0)


def retry_exception_delay(
    exc: Exception,
    attempt: int,
    backoff_seconds: float,
) -> float:
    """Return the wait for a retry after a classified exception."""
    if isinstance(exc, (CredentialError, RateLimitError)):
        wait = getattr(exc, "retry_after", backoff_seconds * (2**attempt))
        jitter = random.uniform(0, min(wait * 0.1, 5.0))
        return min(wait + jitter, 120.0)
    return exponential_backoff_delay(attempt, backoff_seconds)
