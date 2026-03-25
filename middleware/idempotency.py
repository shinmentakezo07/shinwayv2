"""
Shin Proxy — Idempotency key middleware.

Deduplicates non-streaming requests bearing an X-Idempotency-Key header.
Uses IdempotencyCache (L1 in-memory + optional Redis L2) so that dedup
works correctly across multiple uvicorn workers when Redis is enabled.

Redis L2 is off by default (SHINWAY_CACHE_L2_ENABLED=false).
With WORKERS=1 or Redis disabled: per-process L1 only — still deduplicates
within the same worker, which covers the most common retry scenario.
With Redis L2 enabled: full cross-worker dedup.

Only applies to non-streaming POST requests (streaming SSE cannot be replayed).

Idempotency window: SHINWAY_IDEM_TTL_SECONDS (default 86400 = 24h).
This is independent of the response cache TTL — tuning one does not affect
the other.

Note on response identity: idempotency hits return the same id and created
timestamp as the original response. This is intentional — the contract of
idempotency is "return the exact same response". This differs from the
response cache (content-keyed), which regenerates id/created to avoid
returning one caller's id to a different caller.

In-flight deduplication: the first call for a new key writes an in-progress
sentinel (_SENTINEL). Concurrent calls seeing the sentinel get (True, None)
and should treat this as a 202 / retry-later signal. On completion the
sentinel is replaced with the real response. On failure it is deleted so
retries are processed fresh.
"""

from __future__ import annotations

import re
from typing import Any

import structlog

log = structlog.get_logger()

_IDEM_PREFIX = "idem:"
_IDEM_KEY_RE = re.compile(r'^[A-Za-z0-9_\-]{1,256}$')

# Sentinel stored while request is in-flight. Callers that read this know
# another worker/coroutine is processing the same key.
_SENTINEL: dict = {"__idem_status__": "in_progress"}


def validate_idem_key(key: str) -> None:
    """Raise ValueError if the idempotency key is invalid.

    Valid keys: 1–256 characters, alphanumeric, hyphen, or underscore.
    Colons are rejected to prevent cache key namespace injection.
    """
    if not key:
        raise ValueError("X-Idempotency-Key must not be empty")
    if len(key) > 256:
        raise ValueError("X-Idempotency-Key must be at most 256 characters")
    if not _IDEM_KEY_RE.match(key):
        raise ValueError(
            "X-Idempotency-Key contains invalid characters — "
            "only alphanumeric, hyphen, and underscore are allowed"
        )


def _cache_key(key: str, api_key: str = "") -> str:
    return f"{_IDEM_PREFIX}{api_key}:{key}"


def _is_sentinel(value: Any) -> bool:
    return isinstance(value, dict) and value.get("__idem_status__") == "in_progress"


async def get_or_lock(key: str, api_key: str = "") -> tuple[bool, Any]:
    """Check if key has a completed or in-progress response.

    Returns:
        (False, None)  — key is new; sentinel written; caller should proceed
        (True, resp)   — completed response found; caller should return it
        (True, None)   — in-progress sentinel found; caller should return 202

    Cache entries are scoped per api_key to prevent cross-tenant response replay.
    """
    from cache import idempotency_cache
    ck = _cache_key(key, api_key)
    cached = await idempotency_cache.get(ck)
    if cached is not None:
        if _is_sentinel(cached):
            log.info("idempotency_in_progress", key=key[:16])
            return True, None  # another coroutine is processing this key
        log.info("idempotency_cache_hit", key=key[:16])
        return True, cached
    # New key — write sentinel so concurrent duplicates know we are in-flight
    await idempotency_cache.set(ck, _SENTINEL)
    return False, None


async def complete(key: str, response: Any, api_key: str = "") -> None:
    """Replace the in-progress sentinel with the completed response.

    Note: the original id and created timestamp are preserved intentionally —
    idempotency guarantees an identical response, unlike the response cache
    which regenerates these fields for different callers.
    """
    from cache import idempotency_cache
    await idempotency_cache.set(_cache_key(key, api_key), response)
    log.debug("idempotency_stored", key=key[:16])


async def release(key: str, api_key: str = "") -> None:
    """Delete the in-progress sentinel when a request fails.

    This allows subsequent retries to be processed fresh rather than
    permanently seeing a stale sentinel.
    """
    from cache import idempotency_cache
    await idempotency_cache.delete(_cache_key(key, api_key))
    log.debug("idempotency_released", key=key[:16])
