"""
Shin Proxy — Usage / billing reporting API.

Reads from the existing in-process AnalyticsStore singleton.
No new storage introduced.

Endpoints:
    GET /v1/usage/daily              — per-day aggregates from rolling log
    GET /v1/usage/keys/{key}         — per-key lifetime stats
    GET /v1/usage/summary            — totals across all keys
"""
from __future__ import annotations

import time
from collections import defaultdict

import structlog
from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import JSONResponse

from analytics import analytics
from middleware.auth import verify_bearer
from middleware.rate_limit import enforce_rate_limit

router = APIRouter()
log = structlog.get_logger()

_SECONDS_PER_DAY = 86_400


def _day_bucket(ts: int) -> int:
    """Return the start-of-day unix timestamp (UTC) for a given ts."""
    return (ts // _SECONDS_PER_DAY) * _SECONDS_PER_DAY


@router.get("/v1/usage/daily")
async def daily_usage(
    request: Request,
    limit: int = Query(default=30, ge=1, le=90),
    authorization: str | None = Header(default=None),
):
    """Return per-day usage aggregates from the rolling request log.

    Groups the in-memory rolling log by UTC calendar day.
    Days are returned newest-first, capped at `limit` days.
    """
    api_key = await verify_bearer(authorization)
    enforce_rate_limit(api_key, request=request)

    logs = await analytics.snapshot_log(limit=200)

    by_day: dict[int, dict] = defaultdict(lambda: {
        "requests": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cost_usd": 0.0,
    })
    for entry in logs:
        bucket = _day_bucket(entry["ts"])
        by_day[bucket]["requests"] += 1
        by_day[bucket]["input_tokens"] += entry.get("input_tokens", 0)
        by_day[bucket]["output_tokens"] += entry.get("output_tokens", 0)
        by_day[bucket]["cost_usd"] += entry.get("cost_usd", 0.0)

    data = [
        {
            "date": bucket,
            "requests": v["requests"],
            "input_tokens": v["input_tokens"],
            "output_tokens": v["output_tokens"],
            "cost_usd": round(v["cost_usd"], 6),
        }
        for bucket, v in sorted(by_day.items(), reverse=True)
    ][:limit]

    return JSONResponse({
        "object": "list",
        "data": data,
        "retrieved_at": int(time.time()),
    })


@router.get("/v1/usage/keys/{key_prefix:path}")
async def key_usage(
    key_prefix: str,
    request: Request,
    authorization: str | None = Header(default=None),
):
    """Return lifetime usage stats for a specific API key."""
    api_key = await verify_bearer(authorization)
    enforce_rate_limit(api_key, request=request)

    snapshot = await analytics.snapshot()
    key_data = snapshot["keys"].get(key_prefix, {
        "requests": 0,
        "cache_hits": 0,
        "fallbacks": 0,
        "estimated_input_tokens": 0,
        "estimated_output_tokens": 0,
        "estimated_cost_usd": 0.0,
        "latency_ms_total": 0.0,
        "last_request_ts": 0,
        "providers": {},
    })
    return JSONResponse({"key": key_prefix, **key_data})


@router.get("/v1/usage/summary")
async def usage_summary(
    request: Request,
    authorization: str | None = Header(default=None),
):
    """Return aggregate totals across all API keys."""
    api_key = await verify_bearer(authorization)
    enforce_rate_limit(api_key, request=request)

    snapshot = await analytics.snapshot()
    total_requests = 0
    total_input = 0
    total_output = 0
    total_cost = 0.0
    for rec in snapshot["keys"].values():
        total_requests += rec.get("requests", 0)
        total_input += rec.get("estimated_input_tokens", 0)
        total_output += rec.get("estimated_output_tokens", 0)
        total_cost += rec.get("estimated_cost_usd", 0.0)

    return JSONResponse({
        "total_requests": total_requests,
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        "total_cost_usd": round(total_cost, 6),
        "key_count": len(snapshot["keys"]),
        "retrieved_at": int(time.time()),
    })
