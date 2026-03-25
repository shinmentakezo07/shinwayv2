"""
Shin Proxy — Analytics ring buffer + usage tracking.

Lightweight in-process analytics.  Replace with Prometheus/ClickHouse for prod.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field

import msgspec.json as msgjson

from config import settings
from runtime_config import runtime_config


@dataclass
class RequestLog:
    """A single request record."""

    api_key: str
    provider: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: float
    fallback: bool = False
    cache_hit: bool = False
    ttft_ms: int | None = None
    output_tps: float | None = None
    ts: float = field(default_factory=time.time)


class AnalyticsStore:
    """Per-key usage tracker with snapshot support."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._by_key: dict[str, dict] = {}
        self._log: deque = deque(maxlen=200)  # rolling log of last 200 requests

    def _ensure(self, api_key: str) -> dict:
        if api_key not in self._by_key:
            self._by_key[api_key] = {
                "requests": 0,
                "cache_hits": 0,
                "fallbacks": 0,
                "estimated_input_tokens": 0,
                "estimated_output_tokens": 0,
                "estimated_cost_usd": 0.0,
                "latency_ms_total": 0.0,
                "last_request_ts": 0,
                "providers": {},
            }
        return self._by_key[api_key]

    async def record(self, log: RequestLog) -> None:
        async with self._lock:
            rec = self._ensure(log.api_key or "anonymous")
            rec["requests"] += 1
            if log.cache_hit:
                rec["cache_hits"] += 1
            if log.fallback:
                rec["fallbacks"] += 1
            rec["estimated_input_tokens"] += log.input_tokens
            rec["estimated_output_tokens"] += log.output_tokens
            rec["estimated_cost_usd"] += log.cost_usd
            rec["latency_ms_total"] += log.latency_ms
            rec["last_request_ts"] = int(time.time())
            rec["providers"][log.provider] = (
                rec["providers"].get(log.provider, 0) + 1
            )
            # Rolling log entry
            entry: dict = {
                "ts": int(log.ts),
                "api_key": log.api_key or "anonymous",
                "provider": log.provider,
                "input_tokens": log.input_tokens,
                "output_tokens": log.output_tokens,
                "latency_ms": round(log.latency_ms, 1),
                "cache_hit": log.cache_hit,
                "cost_usd": round(log.cost_usd, 6),
            }
            if log.ttft_ms is not None:
                entry["ttft_ms"] = log.ttft_ms
            if log.output_tps is not None:
                entry["output_tps"] = round(log.output_tps, 1)
            self._log.appendleft(entry)

    async def snapshot(self) -> dict:
        async with self._lock:
            return {
                "ts": int(time.time()),
                "keys": msgjson.decode(msgjson.encode(self._by_key)),
            }

    async def snapshot_log(self, limit: int = 50) -> list:
        """Return the most recent `limit` request log entries."""
        async with self._lock:
            return list(self._log)[:limit]

    async def get_spend(self, api_key: str) -> float:
        """Return estimated total spend in USD for a given API key."""
        async with self._lock:
            return self._by_key.get(api_key, {}).get("estimated_cost_usd", 0.0)

    async def get_total_spend(self) -> float:
        """Return estimated total spend in USD across ALL API keys."""
        async with self._lock:
            return sum(
                rec.get("estimated_cost_usd", 0.0)
                for rec in self._by_key.values()
            )

    async def get_daily_tokens(self, api_key: str) -> int:
        """Return estimated total tokens used since server start for a given API key.

        Note: This is an in-process counter reset on restart, not a rolling 24h window.
        Sufficient for soft daily-limit enforcement between restarts.
        """
        async with self._lock:
            rec = self._by_key.get(api_key, {})
            return rec.get("estimated_input_tokens", 0) + rec.get("estimated_output_tokens", 0)


def estimate_cost(
    provider: str, input_tokens: int, output_tokens: int
) -> float:
    """Estimate cost in USD for a request."""
    prices = {
        "anthropic": runtime_config.get("price_anthropic_per_1k"),
        "openai": runtime_config.get("price_openai_per_1k"),
    }
    unit = prices.get(provider, prices["anthropic"])
    return ((input_tokens + output_tokens) / 1000.0) * unit


# Module-level singleton
analytics = AnalyticsStore()
