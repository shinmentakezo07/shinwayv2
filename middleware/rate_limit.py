"""
Shin Proxy — Rate limiter middleware.

Dual token-bucket rate limiter per API key:
  - RPS bucket: short-term burst control (requests per second)
  - RPM bucket: long-term throughput cap (requests per minute)

Both must pass for a request to proceed.
Set SHINWAY_RATE_LIMIT_RPS=0 or SHINWAY_RATE_LIMIT_RPM=0 to disable that layer.

The module-level _limiter singleton is constructed at import time from settings.
Changing SHINWAY_RATE_LIMIT_RPS / SHINWAY_RATE_LIMIT_RPM requires a process
restart to take effect. Per-key limits are dynamic (read from DB on each request).
"""

from __future__ import annotations

import asyncio
import threading
import time

import structlog
from cachetools import LRUCache

from config import settings
from handlers import RateLimitError

log = structlog.get_logger()

# Max distinct keys tracked inside any single TokenBucket.
# Protects against unbounded memory growth from key churn.
_BUCKET_MAX_KEYS = 10_000


class TokenBucket:
    """Single token-bucket rate limiter.

    Thread-safe via threading.Lock — called from both sync and async contexts.
    Internal key store is LRU-bounded to prevent unbounded memory growth.
    """

    def __init__(self, rate: float, burst: float) -> None:
        self.rate = rate        # tokens refilled per second
        self.burst = burst      # max tokens (bucket capacity)
        self._lock = threading.Lock()
        # LRU-bounded: evicts least-recently-used key when full.
        # Evicted keys restart with a full bucket on next access — safe for
        # rate limiting (slightly generous to evicted keys, not permissive).
        self._buckets: LRUCache = LRUCache(maxsize=_BUCKET_MAX_KEYS)

    def consume(self, key: str, tokens: float = 1.0) -> bool:
        """Consume tokens from the bucket. Returns True if allowed."""
        if self.rate <= 0:
            return True  # disabled
        now = time.monotonic()
        with self._lock:
            level, last = self._buckets.get(key, (self.burst, now))
            level = min(self.burst, level + (now - last) * self.rate)
            if level >= tokens:
                self._buckets[key] = (level - tokens, now)
                return True
            self._buckets[key] = (level, now)
            return False

    def peek(self, key: str, tokens: float = 1.0) -> bool:
        """Check if tokens are available without consuming."""
        if self.rate <= 0:
            return True
        now = time.monotonic()
        with self._lock:
            level, last = self._buckets.get(key, (self.burst, now))
            level = min(self.burst, level + (now - last) * self.rate)
            return level >= tokens

    def refund(self, key: str, tokens: float = 1.0) -> None:
        """Return tokens to the bucket (undo a consume). Capped at burst capacity."""
        if self.rate <= 0:
            return
        now = time.monotonic()
        with self._lock:
            level, last = self._buckets.get(key, (self.burst, now))
            self._buckets[key] = (min(self.burst, level + tokens), last)

    def seconds_until_token(self, key: str, tokens: float = 1.0) -> float:
        """Return seconds until at least `tokens` are available in the bucket.

        Returns 0.0 if tokens are available now.
        Used to compute accurate Retry-After values for 429 responses.
        """
        if self.rate <= 0:
            return 0.0
        now = time.monotonic()
        with self._lock:
            level, last = self._buckets.get(key, (self.burst, now))
            level = min(self.burst, level + (now - last) * self.rate)
        if level >= tokens:
            return 0.0
        return max(0.0, (tokens - level) / self.rate)


class DualBucketRateLimiter:
    """Per-key rate limiter with both RPS and RPM buckets.

    RPS bucket — refills at rate_rps tokens/sec, burst capacity = burst_rps
    RPM bucket — refills at rate_rpm/60 tokens/sec, burst capacity = burst_rpm
    """

    def __init__(
        self,
        rate_rps: float,
        burst_rps: int,
        rate_rpm: float,
        burst_rpm: int,
    ) -> None:
        self._rps = TokenBucket(rate=rate_rps, burst=float(burst_rps))
        # RPM bucket: refill rate = rpm / 60 tokens per second
        self._rpm = TokenBucket(rate=rate_rpm / 60.0 if rate_rpm > 0 else 0, burst=float(burst_rpm))

    def consume(self, key: str) -> tuple[bool, str, float]:
        """Atomically check and consume one token from both buckets.

        Returns (allowed, reason, retry_after_seconds).

        Consumes RPS first, then RPM. If RPM fails, refunds the RPS token.
        Eliminates the peek+consume split that allowed two threads to both
        pass peek before either consume landed.
        """
        if not self._rps.consume(key):
            retry = self._rps.seconds_until_token(key)
            return False, "RPS limit exceeded", retry
        if not self._rpm.consume(key):
            self._rps.refund(key)
            retry = self._rpm.seconds_until_token(key)
            return False, "RPM limit exceeded", retry
        return True, "", 0.0


# ── Module-level singleton ────────────────────────────────────────────────────
# Constructed at import time — changing SHINWAY_RATE_LIMIT_* env vars requires
# a process restart. Per-key limits are dynamic (read from DB each request).

def _rpm_burst() -> int:
    """Return effective RPM burst capacity.

    If SHINWAY_RATE_LIMIT_RPM_BURST is explicitly set (> 0) use it.
    Otherwise default to rate_limit_rpm (full minute quota available at startup).
    """
    if settings.rate_limit_rpm_burst > 0:
        return settings.rate_limit_rpm_burst
    return max(1, int(settings.rate_limit_rpm))


_limiter = DualBucketRateLimiter(
    rate_rps=settings.rate_limit_rps,
    burst_rps=settings.rate_limit_burst,
    rate_rpm=settings.rate_limit_rpm,
    burst_rpm=_rpm_burst(),
)

# Per-key limiter cache: "<key>:<rpm>:<rps>" → DualBucketRateLimiter
# Created on first use with limits read from KeyStore.
# LRU-bounded: evicts oldest entry when 10_000 distinct key:rpm:rps combinations are reached.
_per_key_limiters: LRUCache = LRUCache(maxsize=10_000)
# asyncio.Lock: _per_key_limiters is only accessed from async context.
_per_key_lock = asyncio.Lock()


def enforce_rate_limit(api_key: str) -> None:
    """Enforce RPS + RPM rate limits for the given API key.

    All unauthenticated/anonymous requests share the 'anonymous' bucket.
    Raises RateLimitError with an accurate retry_after computed from bucket state.
    """
    key = api_key or "anonymous"
    allowed, reason, retry_after = _limiter.consume(key)
    if not allowed:
        log.warning("rate_limit_exceeded", api_key=key, reason=reason, retry_after=retry_after)
        raise RateLimitError(f"Rate limit exceeded: {reason}", retry_after=max(retry_after, 1.0))


async def enforce_per_key_rate_limit(
    api_key: str,
    key_record: dict | None = None,
) -> None:
    """Enforce per-key RPS/RPM limits if configured in KeyStore.

    key_record: pass pre-fetched key record to avoid a redundant DB lookup.
    If None, fetches from store (backwards-compatible fallback).
    Only applies when the key has explicit limits set (> 0).
    Keys with 0 limits fall through to the global rate limiter.
    """
    rec = key_record
    if rec is None:
        from storage.keys import key_store
        rec = await key_store.get(api_key)
    if rec is None:
        return  # env key or master key — no per-key limits

    rpm = rec.get("rpm_limit", 0)
    rps = rec.get("rps_limit", 0)
    if rpm == 0 and rps == 0:
        return  # no per-key limits — global limiter handles it

    # Cache key encodes the limits so a limit change gets a fresh bucket.
    limiter_key = f"{api_key}:{rpm}:{rps}"
    async with _per_key_lock:
        if limiter_key not in _per_key_limiters:
            _per_key_limiters[limiter_key] = DualBucketRateLimiter(
                rate_rps=float(rps) if rps > 0 else 0.0,
                burst_rps=max(rps, 1),
                rate_rpm=float(rpm) if rpm > 0 else 0.0,
                burst_rpm=max(rpm, 1),
            )
        limiter = _per_key_limiters[limiter_key]

    allowed, reason, retry_after = limiter.consume(api_key)
    if not allowed:
        log.warning("per_key_rate_limit_exceeded", api_key=api_key[:16], reason=reason, retry_after=retry_after)
        raise RateLimitError(f"Per-key rate limit exceeded: {reason}", retry_after=max(retry_after, 1.0))
