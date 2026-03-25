# tests/test_retry_middleware.py
"""
Tests for middleware/retry.py — RetryContext dataclass, get_retry_ctx helper,
and enrich_rate_limit_response header injection.
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# RetryContext dataclass
# ---------------------------------------------------------------------------

def test_retry_context_default_fields():
    """RetryContext initialises with zero retry_count and empty retry_reason."""
    from middleware.retry import RetryContext
    ctx = RetryContext()
    assert ctx.retry_count == 0
    assert ctx.retry_reason == ""


def test_retry_context_fields_mutable():
    """RetryContext fields can be updated in-place during request lifecycle."""
    from middleware.retry import RetryContext
    ctx = RetryContext()
    ctx.retry_count = 3
    ctx.retry_reason = "rps"
    assert ctx.retry_count == 3
    assert ctx.retry_reason == "rps"


def test_retry_context_explicit_init():
    """RetryContext accepts explicit field values at construction."""
    from middleware.retry import RetryContext
    ctx = RetryContext(retry_count=2, retry_reason="rpm")
    assert ctx.retry_count == 2
    assert ctx.retry_reason == "rpm"


# ---------------------------------------------------------------------------
# get_retry_ctx helper
# ---------------------------------------------------------------------------

def test_get_retry_ctx_returns_none_when_not_set():
    """get_retry_ctx returns None when request.state.retry has not been set."""
    from middleware.retry import get_retry_ctx
    req = MagicMock(spec=[])
    req.state = MagicMock(spec=[])  # spec=[] means no attributes — getattr returns AttributeError
    result = get_retry_ctx(req)
    assert result is None


def test_get_retry_ctx_returns_context_when_set():
    """get_retry_ctx returns the RetryContext stored on request.state.retry."""
    from middleware.retry import RetryContext, get_retry_ctx
    ctx = RetryContext(retry_count=1, retry_reason="suppression")
    req = MagicMock()
    req.state.retry = ctx
    assert get_retry_ctx(req) is ctx


def test_get_retry_ctx_returns_none_when_state_missing():
    """get_retry_ctx returns None when request has no state attribute at all."""
    from middleware.retry import get_retry_ctx
    req = MagicMock(spec=[])  # no .state
    result = get_retry_ctx(req)
    assert result is None


# ---------------------------------------------------------------------------
# enrich_rate_limit_response
# ---------------------------------------------------------------------------

def test_enrich_adds_retry_count_header():
    """enrich_rate_limit_response sets X-Retry-Count from RetryContext.retry_count."""
    from middleware.retry import RetryContext, enrich_rate_limit_response
    headers: dict[str, str] = {}
    ctx = RetryContext(retry_count=2, retry_reason="rps")
    enrich_rate_limit_response(headers, ctx, rate_limit=10, remaining=0)
    assert headers["X-Retry-Count"] == "2"


def test_enrich_adds_retry_reason_header():
    """enrich_rate_limit_response sets X-Retry-Reason from RetryContext.retry_reason."""
    from middleware.retry import RetryContext, enrich_rate_limit_response
    headers: dict[str, str] = {}
    ctx = RetryContext(retry_count=1, retry_reason="rpm")
    enrich_rate_limit_response(headers, ctx, rate_limit=60, remaining=5)
    assert headers["X-Retry-Reason"] == "rpm"


def test_enrich_adds_rate_limit_headers():
    """enrich_rate_limit_response sets X-RateLimit-Limit and X-RateLimit-Remaining."""
    from middleware.retry import RetryContext, enrich_rate_limit_response
    headers: dict[str, str] = {}
    ctx = RetryContext()
    enrich_rate_limit_response(headers, ctx, rate_limit=100, remaining=0)
    assert headers["X-RateLimit-Limit"] == "100"
    assert headers["X-RateLimit-Remaining"] == "0"


def test_enrich_with_none_ctx_does_not_raise():
    """enrich_rate_limit_response is a no-op when ctx is None (defensive path)."""
    from middleware.retry import enrich_rate_limit_response
    headers: dict[str, str] = {}
    # Must not raise — called in exception handler where ctx may be absent
    enrich_rate_limit_response(headers, None, rate_limit=10, remaining=0)
    # X-Retry-Count and X-Retry-Reason should NOT be added when ctx is None
    assert "X-Retry-Count" not in headers
    assert "X-Retry-Reason" not in headers
    # X-RateLimit-Limit and X-RateLimit-Remaining are always added (available without ctx)
    assert headers["X-RateLimit-Limit"] == "10"
    assert headers["X-RateLimit-Remaining"] == "0"


def test_enrich_zero_retry_count_emits_header():
    """X-Retry-Count: 0 is emitted even when no retries occurred (first failure)."""
    from middleware.retry import RetryContext, enrich_rate_limit_response
    headers: dict[str, str] = {}
    ctx = RetryContext(retry_count=0, retry_reason="rps")
    enrich_rate_limit_response(headers, ctx, rate_limit=5, remaining=0)
    assert headers["X-Retry-Count"] == "0"


# ---------------------------------------------------------------------------
# 429 response integration — proxy_error_handler emits enriched headers
# ---------------------------------------------------------------------------

def _make_test_app() -> FastAPI:
    """Minimal FastAPI app that replicates Shinway's proxy_error_handler wiring."""
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse
    from handlers import ProxyError, RateLimitError
    from middleware.retry import RetryContext, enrich_rate_limit_response
    from config import settings

    app = FastAPI()

    @app.exception_handler(ProxyError)
    async def proxy_error_handler(request: Request, exc: ProxyError) -> JSONResponse:
        headers: dict[str, str] = {}
        if isinstance(exc, RateLimitError):
            headers["Retry-After"] = str(int(exc.retry_after))
            from middleware.retry import get_retry_ctx
            retry_ctx = get_retry_ctx(request)
            rate_limit = int(settings.rate_limit_rps) or int(settings.rate_limit_rpm) or 0
            remaining = 0
            enrich_rate_limit_response(headers, retry_ctx, rate_limit=rate_limit, remaining=remaining)
        return JSONResponse(status_code=exc.status_code, content={"error": exc.message}, headers=headers)

    @app.get("/trigger-rps")
    async def trigger_rps(request: Request):
        """Set retry ctx and raise a RateLimitError to simulate rate limit hit."""
        from middleware.retry import RetryContext
        request.state.retry = RetryContext(retry_count=0, retry_reason="rps")
        raise RateLimitError("Rate limit exceeded: RPS limit exceeded", retry_after=1.0)

    @app.get("/trigger-rpm")
    async def trigger_rpm(request: Request):
        """Set retry ctx with rpm reason."""
        from middleware.retry import RetryContext
        request.state.retry = RetryContext(retry_count=1, retry_reason="rpm")
        raise RateLimitError("Rate limit exceeded: RPM limit exceeded", retry_after=30.0)

    @app.get("/trigger-no-ctx")
    async def trigger_no_ctx(request: Request):
        """Raise RateLimitError without setting retry ctx (ctx is None path)."""
        raise RateLimitError("Rate limit exceeded", retry_after=5.0)

    return app


def test_429_includes_retry_after_header():
    """RateLimitError response always includes Retry-After header."""
    client = TestClient(_make_test_app(), raise_server_exceptions=False)
    r = client.get("/trigger-rps")
    assert r.status_code == 429
    assert "retry-after" in r.headers
    assert r.headers["retry-after"] == "1"


def test_429_includes_x_retry_count_header():
    """RateLimitError response includes X-Retry-Count when RetryContext is set."""
    client = TestClient(_make_test_app(), raise_server_exceptions=False)
    r = client.get("/trigger-rps")
    assert r.status_code == 429
    assert "x-retry-count" in r.headers
    assert r.headers["x-retry-count"] == "0"


def test_429_includes_x_retry_reason_rps():
    """X-Retry-Reason is 'rps' when RPS bucket fired."""
    client = TestClient(_make_test_app(), raise_server_exceptions=False)
    r = client.get("/trigger-rps")
    assert r.status_code == 429
    assert r.headers["x-retry-reason"] == "rps"


def test_429_includes_x_retry_reason_rpm():
    """X-Retry-Reason is 'rpm' when RPM bucket fired."""
    client = TestClient(_make_test_app(), raise_server_exceptions=False)
    r = client.get("/trigger-rpm")
    assert r.status_code == 429
    assert r.headers["x-retry-reason"] == "rpm"
    assert r.headers["x-retry-count"] == "1"


def test_429_includes_x_ratelimit_headers():
    """X-RateLimit-Limit and X-RateLimit-Remaining are present on 429."""
    client = TestClient(_make_test_app(), raise_server_exceptions=False)
    r = client.get("/trigger-rps")
    assert r.status_code == 429
    assert "x-ratelimit-limit" in r.headers
    assert "x-ratelimit-remaining" in r.headers


def test_429_no_ctx_still_emits_ratelimit_headers():
    """When RetryContext is absent, X-RateLimit-* headers are still emitted."""
    client = TestClient(_make_test_app(), raise_server_exceptions=False)
    r = client.get("/trigger-no-ctx")
    assert r.status_code == 429
    assert "x-ratelimit-limit" in r.headers
    assert "x-ratelimit-remaining" in r.headers
    # X-Retry-Count and X-Retry-Reason absent when ctx is None
    assert "x-retry-count" not in r.headers
    assert "x-retry-reason" not in r.headers
