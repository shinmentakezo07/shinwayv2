"""
Shin Proxy — Response cache.

L1: in-memory TTLCache (fast, per-process, always on)
L2: Redis (optional, persistent, shared across workers — opt-in via SHINWAY_CACHE_L2_ENABLED)

Read strategy:  L1 hit → return. L1 miss → L2 check → populate L1 → return.
Write strategy: write L1 + L2 simultaneously.

Tool requests bypass cache by default (SHINWAY_CACHE_TOOL_REQUESTS=false).
"""

from __future__ import annotations

import asyncio
import hashlib
from typing import Any

import msgspec.json as msgjson

import structlog
from cachetools import TTLCache as _TTLCache

from config import settings
from runtime_config import runtime_config

log = structlog.get_logger()


# ── Redis L2 backend ──────────────────────────────────────────────────────────

class _RedisBackend:
    """Optional async Redis L2 cache backend.

    L2 is fully optional — if Redis is unavailable or disabled, every method
    returns a safe no-op value and L1 continues to work without interruption.
    """

    def __init__(self) -> None:
        self._client = None
        self._available = False
        self._init_lock = asyncio.Lock()  # prevents concurrent init and connection leaks

    async def _ensure_client(self) -> bool:
        """Lazily initialise the Redis client. Returns True if available.

        Protected by an asyncio.Lock so concurrent coroutines cannot each
        attempt to create their own client, leaking connections.
        """
        if self._client is not None:
            return self._available
        async with self._init_lock:
            # Re-check after acquiring lock — another coroutine may have finished init.
            if self._client is not None:
                return self._available
            try:
                import redis.asyncio as aioredis  # type: ignore[import]

                self._client = aioredis.from_url(
                    settings.redis_url,
                    decode_responses=False,
                    socket_connect_timeout=2,
                    socket_timeout=2,
                    max_connections=20,
                )
                await self._client.ping()
                self._available = True
                log.info("redis_l2_connected", url=settings.redis_url)
            except Exception as exc:
                log.warning("redis_l2_unavailable", error=str(exc))
                self._client = None
                self._available = False
            return self._available

    async def get(self, key: str) -> Any | None:
        if not settings.cache_l2_enabled:
            return None
        if not await self._ensure_client():
            return None
        try:
            raw = await self._client.get(f"shin:{key}")
            if raw is None:
                return None
            return msgjson.decode(raw if isinstance(raw, bytes) else raw.encode())
        except Exception as exc:
            log.debug("redis_l2_get_error", error=str(exc)[:100])
            return None

    async def set(self, key: str, value: Any) -> None:
        if not settings.cache_l2_enabled:
            return
        if not await self._ensure_client():
            return
        try:
            serialised = msgjson.encode(value)
            await self._client.setex(
                f"shin:{key}",
                runtime_config.get("cache_ttl_seconds"),
                serialised,
            )
        except Exception as exc:
            log.debug("redis_l2_set_error", error=str(exc)[:100])

    async def clear(self) -> int:
        """Delete all shin: keys. Returns count of keys deleted.

        Uses a single batched DELETE rather than one round-trip per key.
        Not atomic — keys written between scan and delete are not cleared,
        which is acceptable for a cache flush.
        """
        if not settings.cache_l2_enabled or not await self._ensure_client():
            return 0
        try:
            keys = [key async for key in self._client.scan_iter("shin:*", count=500)]
            if keys:
                await self._client.delete(*keys)
            return len(keys)
        except Exception as exc:
            log.debug("redis_l2_clear_error", error=str(exc)[:100])
            return 0


# ── Main ResponseCache ────────────────────────────────────────────────────────

class ResponseCache:
    """
    Two-level response cache.

    L1: cachetools TTLCache (in-memory, fast, per-process)
    L2: Redis (optional, persistent, shared across workers)
    """

    def __init__(self) -> None:
        self._cache: _TTLCache = _TTLCache(
            maxsize=max(1, settings.cache_max_entries),
            ttl=max(1, settings.cache_ttl_seconds),
        )
        self._l2 = _RedisBackend()

    # ── Synchronous L1 API (used by non-streaming pipeline) ──────────────────

    def get(self, key: str | None) -> Any | None:
        """Synchronous L1 get. Does NOT check L2 (use aget for async L2 support)."""
        if not runtime_config.get("cache_enabled") or not key:
            return None
        return self._cache.get(key)

    def set(self, key: str | None, value: Any) -> None:
        """Synchronous L1 set. L2 write must be done via aset."""
        if not runtime_config.get("cache_enabled") or not key or value is None:
            return
        self._cache[key] = value

    # ── Asynchronous L1 + L2 API ─────────────────────────────────────────────

    async def aget(self, key: str | None) -> Any | None:
        """Async get: check L1, then L2. Populates L1 on L2 hit."""
        if not runtime_config.get("cache_enabled") or not key:
            return None
        # L1
        val = self._cache.get(key)
        if val is not None:
            log.debug("cache_l1_hit", key=key[:16])
            return val
        # L2 — only attempted when enabled; L1 works standalone when L2 is off
        val = await self._l2.get(key)
        if val is not None:
            log.debug("cache_l2_hit", key=key[:16])
            self._cache[key] = val  # populate L1
        return val

    async def aset(self, key: str | None, value: Any) -> None:
        """Async set: write L1 and L2 simultaneously."""
        if not runtime_config.get("cache_enabled") or not key or value is None:
            return
        self._cache[key] = value
        await self._l2.set(key, value)

    async def aclear(self) -> dict:
        """Clear L1 and L2. Returns counts."""
        l1_count = len(self._cache)
        self._cache.clear()
        l2_count = await self._l2.clear()
        return {"l1_cleared": l1_count, "l2_cleared": l2_count}

    # ── Cache key builder ─────────────────────────────────────────────────────

    @staticmethod
    def build_key(
        *,
        api_style: str,
        model: str,
        messages: list,
        tools: list,
        tool_choice: Any,
        reasoning_effort: Any,
        show_reasoning: bool,
        system_text: str = "",
        max_tokens: int | None = None,
        stop: list[str] | None = None,
        json_mode: bool = False,
    ) -> str:
        """Deterministic SHA256 cache key from request parameters.

        Covers all fields that materially affect model output:
        api_style, model, messages, tools, tool_choice, reasoning_effort,
        show_reasoning, system_text, max_tokens, stop, json_mode.
        """
        payload = {
            "api_style": api_style,
            "model": model,
            "messages": messages,
            "tools": tools,
            "tool_choice": tool_choice,
            "reasoning_effort": reasoning_effort,
            "show_reasoning": show_reasoning,
            "system": system_text,
            "max_tokens": max_tokens,
            "stop": stop,
            "json_mode": json_mode,
        }
        raw = msgjson.encode({k: payload[k] for k in sorted(payload)}).decode()
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def should_cache(self, tools: list) -> bool:
        """Return True if this request should be cached.

        Tool requests are bypassed by default unless SHINWAY_CACHE_TOOL_REQUESTS=true.
        """
        if tools and not runtime_config.get("cache_tool_requests"):
            return False
        return runtime_config.get("cache_enabled")


# Module-level singleton
response_cache = ResponseCache()


# ── Idempotency cache ─────────────────────────────────────────────────────────

class IdempotencyCache:
    """Dedicated cache for idempotency entries.

    Separate from ResponseCache so that:
    - TTL is controlled independently (default 24h vs 45s for responses)
    - LRU eviction of responses cannot shrink the idempotency window
    - Shares _RedisBackend for optional cross-worker dedup when L2 is enabled

    Redis L2 is off by default (SHINWAY_CACHE_L2_ENABLED=false).
    When disabled, L1 provides per-process dedup — still covers the most
    common retry scenario (same worker, same process).
    """

    def __init__(self) -> None:
        self._cache: _TTLCache = _TTLCache(
            maxsize=max(1, settings.idem_max_entries),
            ttl=max(1, settings.idem_ttl_seconds),
        )
        self._l2 = _RedisBackend()

    async def get(self, key: str) -> Any | None:
        """Return stored value for key, or None."""
        if not runtime_config.get("cache_enabled"):
            return None
        val = self._cache.get(key)
        if val is not None:
            log.debug("idem_l1_hit", key=key[:16])
            return val
        val = await self._l2.get(key)
        if val is not None:
            log.debug("idem_l2_hit", key=key[:16])
            self._cache[key] = val
        return val

    async def set(self, key: str, value: Any) -> None:
        """Store value under key with idempotency TTL."""
        if not runtime_config.get("cache_enabled") or value is None:
            return
        self._cache[key] = value
        await self._l2.set(key, value)

    async def delete(self, key: str) -> None:
        """Remove key from L1 (and L2 if enabled)."""
        self._cache.pop(key, None)
        try:
            if settings.cache_l2_enabled and await self._l2._ensure_client():
                await self._l2._client.delete(f"shin:{key}")
        except Exception as exc:
            log.debug("idem_l2_delete_error", error=str(exc)[:100])


# Module-level singleton
idempotency_cache = IdempotencyCache()
