"""
Shin Proxy — Retry context for client-facing retry hints.

Provides RetryContext (one per request) stored on request.state.retry.
Tracks how many internal retries were attempted before a 429 was returned,
and which bucket (rps/rpm/suppression/timeout) triggered the limit.

Usage:
    # In rate_limit.py — before raising RateLimitError:
    from middleware.retry import RetryContext, get_retry_ctx
    ctx = get_retry_ctx(request)
    if ctx is None:
        request.state.retry = RetryContext()
        ctx = request.state.retry
    ctx.retry_reason = "rps"

    # In app.py exception handler — after setting Retry-After:
    from middleware.retry import enrich_rate_limit_response, get_retry_ctx
    enrich_rate_limit_response(headers, get_retry_ctx(request), rate_limit=..., remaining=...)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import Request


@dataclass
class RetryContext:
    """Per-request retry tracking. Stored on request.state.retry.

    retry_count: number of internal upstream retries attempted before giving up.
    retry_reason: which limit fired — one of 'rps', 'rpm', 'suppression', 'timeout', ''.
    """

    retry_count: int = 0
    retry_reason: str = ""


def get_retry_ctx(request: "Request") -> RetryContext | None:
    """Return the RetryContext for this request, or None if not set."""
    return getattr(getattr(request, "state", None), "retry", None)


def enrich_rate_limit_response(
    headers: dict[str, str],
    ctx: RetryContext | None,
    *,
    rate_limit: int,
    remaining: int,
) -> None:
    """Mutate headers dict in-place with retry hint headers.

    X-Retry-Count and X-Retry-Reason require a RetryContext and are omitted
    when ctx is None (e.g. limit fired before retry ctx was initialised).
    X-RateLimit-Limit and X-RateLimit-Remaining are always written — they
    come from config, not from the per-request context.
    """
    # Always emit capacity headers — clients use these for self-throttling
    # even when they have not retried yet.
    headers["X-RateLimit-Limit"] = str(rate_limit)
    headers["X-RateLimit-Remaining"] = str(remaining)

    # Per-request retry details require ctx — absent on the first-ever limit
    # hit before rate_limit.py has had a chance to populate request.state.retry.
    if ctx is None:
        return
    headers["X-Retry-Count"] = str(ctx.retry_count)
    headers["X-Retry-Reason"] = ctx.retry_reason
