"""Cursor credential state models."""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class CircuitBreaker:
    """Per-credential circuit breaker with half-open recovery."""

    threshold: int = 3
    cooldown: float = 300.0
    failures: int = field(default=0)
    _opened_at: float | None = field(default=None, repr=False)

    def is_open(self) -> bool:
        if self._opened_at is None:
            return False
        if time.time() - self._opened_at >= self.cooldown:
            self._opened_at = None
            self.failures = 0
            return False
        return True

    def record_failure(self) -> None:
        self.failures += 1
        if self.failures >= self.threshold:
            self._opened_at = time.time()

    def record_success(self) -> None:
        self.failures = 0
        self._opened_at = None


@dataclass
class CredentialInfo:
    """Per-credential tracking."""

    cookie: str
    index: int = 0
    request_count: int = 0
    success_count: int = 0
    error_count: int = 0
    consecutive_errors: int = 0
    last_used: float = 0.0
    last_success: float = 0.0
    last_error: float = 0.0
    last_latency_ms: float = 0.0
    latency_ms_total: float = 0.0
    avg_latency_ms: float = 0.0
    healthy: bool = True
    cooldown_until: float = 0.0
    workos_id: str = ""
    statsig_stable_id: str = ""
    cursor_anonymous_id: str = ""
    cb: CircuitBreaker = field(default_factory=CircuitBreaker)
