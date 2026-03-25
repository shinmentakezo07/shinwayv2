# Retry Middleware — Client-Facing Retry Hints Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When Shinway returns a 429 (rate limit) response, clients currently receive only a `Retry-After` header. This plan adds `X-Retry-Count`, `X-Retry-Reason`, `X-RateLimit-Limit`, and `X-RateLimit-Remaining` headers so clients can self-throttle intelligently without polling.

**Architecture:** A new `middleware/retry.py` module provides a `RetryContext` dataclass stored on `request.state.retry` for the lifetime of a single request. A `get_retry_ctx(request)` helper retrieves it safely. No new ASGI middleware class is needed — the dataclass is populated by `middleware/rate_limit.py` at the point where a limit fires, and the headers are emitted in the existing `proxy_error_handler` in `app.py` via a new `enrich_rate_limit_response()` helper. This is the same pattern used by `middleware/logging.py` / `RequestContext`.

**Tech Stack:** Python 3.12, FastAPI, dataclasses, no new dependencies.

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `middleware/retry.py` | CREATE | `RetryContext` dataclass, `get_retry_ctx()`, `enrich_rate_limit_response()` |
| `middleware/rate_limit.py` | MODIFY | Set `retry_reason` on `RetryContext` in `enforce_rate_limit()` and `enforce_per_key_rate_limit()` |
| `app.py` | MODIFY | Call `enrich_rate_limit_response()` inside `proxy_error_handler` for `RateLimitError` |
| `tests/test_retry_middleware.py` | CREATE | Unit tests for `RetryContext`, `get_retry_ctx()`, `enrich_rate_limit_response()`, and 429 response headers |

---

## Chunk 1: `RetryContext` dataclass + `middleware/retry.py`

### Task 1: Write failing tests for `middleware/retry.py`

**Files:**
- Create: `tests/test_retry_middleware.py`

- [ ] **Step 1: Write the failing tests**

```python
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
```

- [ ] **Step 2: Run tests — expect ImportError**

```bash
cd /teamspace/studios/this_studio/dikders
pytest tests/test_retry_middleware.py -v 2>&1 | tail -15
```

Expected: `ModuleNotFoundError: No module named 'middleware.retry'`

---

### Task 2: Create `middleware/retry.py`

**Files:**
- Create: `middleware/retry.py`

- [ ] **Step 1: Write the file**

```python
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

from dataclasses import dataclass, field
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
```

- [ ] **Step 2: Run tests — expect all GREEN**

```bash
cd /teamspace/studios/this_studio/dikders
pytest tests/test_retry_middleware.py -v 2>&1 | tail -30
```

Expected: all tests PASS.

- [ ] **Step 3: Run full suite — no regressions**

```bash
pytest tests/ --ignore=tests/integration -q 2>&1 | tail -5
```

Expected: existing count + new tests pass, 0 failures.

- [ ] **Step 4: Commit**

```bash
cd /teamspace/studios/this_studio/dikders
git add middleware/retry.py tests/test_retry_middleware.py
git commit -m "feat(middleware): add RetryContext, get_retry_ctx, enrich_rate_limit_response"
```

---

## Chunk 2: Wire `RetryContext` into `middleware/rate_limit.py`

### Task 3: Set `retry_reason` when raising `RateLimitError`

Both `enforce_rate_limit()` (global limiter, sync) and `enforce_per_key_rate_limit()` (per-key limiter, async) raise `RateLimitError`. At that point the `reason` string returned by `DualBucketRateLimiter.consume()` is already available — it is either `"RPS limit exceeded"` or `"RPM limit exceeded"`. We normalise it to the short form (`"rps"` / `"rpm"`) and store it on `request.state.retry`.

Both functions must accept an optional `request` parameter (keyword-only, defaults to `None`) so callers that do not have a `Request` object (unit tests, background tasks) are unaffected. The request is available in the router before the function is called and is threaded through at the call site in **Chunk 3**.

**Files:**
- Modify: `middleware/rate_limit.py`

- [ ] **Step 1: Add `_set_retry_ctx` private helper at module level**

Insert after the `_per_key_lock` line (after line 165 in the current file, below `_per_key_limiters` and `_per_key_lock`):

```python
# ── Retry context helpers ─────────────────────────────────────────────────

_REASON_NORMALISE = {
    "RPS limit exceeded": "rps",
    "RPM limit exceeded": "rpm",
    "Per-key rate limit exceeded: RPS limit exceeded": "rps",
    "Per-key rate limit exceeded: RPM limit exceeded": "rpm",
}


def _set_retry_ctx(request: object | None, reason: str) -> None:
    """Populate request.state.retry with RetryContext if request is provided.

    Idempotent — creates the context on first call, updates reason on subsequent
    calls (suppression retry path may call this more than once per request).
    """
    if request is None:
        return
    from middleware.retry import RetryContext, get_retry_ctx
    ctx = get_retry_ctx(request)  # type: ignore[arg-type]
    if ctx is None:
        ctx = RetryContext()
        request.state.retry = ctx  # type: ignore[union-attr]
    # Normalise verbose bucket reason to short token for clients
    ctx.retry_reason = _REASON_NORMALISE.get(reason, reason)
```

- [ ] **Step 2: Add `request` parameter to `enforce_rate_limit()`**

Replace the current `enforce_rate_limit` signature and body:

```python
def enforce_rate_limit(api_key: str, request: object | None = None) -> None:
    """Enforce RPS + RPM rate limits for the given API key.

    All unauthenticated/anonymous requests share the 'anonymous' bucket.
    Raises RateLimitError with an accurate retry_after computed from bucket state.
    Populates request.state.retry with RetryContext when request is provided.
    """
    key = api_key or "anonymous"
    allowed, reason, retry_after = _limiter.consume(key)
    if not allowed:
        log.warning("rate_limit_exceeded", api_key=key, reason=reason, retry_after=retry_after)
        _set_retry_ctx(request, reason)
        raise RateLimitError(f"Rate limit exceeded: {reason}", retry_after=max(retry_after, 1.0))
```

- [ ] **Step 3: Add `request` parameter to `enforce_per_key_rate_limit()`**

Replace the current `enforce_per_key_rate_limit` signature and body:

```python
async def enforce_per_key_rate_limit(
    api_key: str,
    key_record: dict | None = None,
    request: object | None = None,
) -> None:
    """Enforce per-key RPS/RPM limits if configured in KeyStore.

    key_record: pass pre-fetched key record to avoid a redundant DB lookup.
    If None, fetches from store (backwards-compatible fallback).
    Only applies when the key has explicit limits set (> 0).
    Keys with 0 limits fall through to the global rate limiter.
    Populates request.state.retry with RetryContext when request is provided.
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
        _set_retry_ctx(request, reason)
        raise RateLimitError(f"Per-key rate limit exceeded: {reason}", retry_after=max(retry_after, 1.0))
```

- [ ] **Step 4: Run existing rate limit tests — expect all PASS**

```bash
cd /teamspace/studios/this_studio/dikders
pytest tests/test_rate_limit.py -v 2>&1 | tail -20
```

Expected: all existing tests PASS (the new `request=None` parameter is backwards-compatible — no callers break).

- [ ] **Step 5: Run full suite — no regressions**

```bash
pytest tests/ --ignore=tests/integration -q 2>&1 | tail -5
```

Expected: 0 failures.

- [ ] **Step 6: Commit**

```bash
cd /teamspace/studios/this_studio/dikders
git add middleware/rate_limit.py
git commit -m "feat(rate_limit): populate RetryContext with retry_reason before raising RateLimitError"
```

---

## Chunk 3: Wire `enrich_rate_limit_response()` into `app.py`

### Task 4: Enrich 429 response headers in `proxy_error_handler`

The `proxy_error_handler` in `app.py` already sets `Retry-After`. We extend the `RateLimitError` branch to also call `enrich_rate_limit_response()`. The `rate_limit` value presented to the client is the effective global limit — whichever bucket (RPS or RPM) is configured. If both are configured, use RPM (minute-scale) as the more meaningful capacity signal for clients planning their request volume.

**Files:**
- Modify: `app.py`

- [ ] **Step 1: Replace the `RateLimitError` branch in `proxy_error_handler`**

Find the existing block (lines 114-116 in current `app.py`):

```python
        headers: dict[str, str] = {}
        if isinstance(exc, _RateLimitError):
            headers["Retry-After"] = str(int(exc.retry_after))
```

Replace with:

```python
        headers: dict[str, str] = {}
        if isinstance(exc, _RateLimitError):
            headers["Retry-After"] = str(int(exc.retry_after))
            from middleware.retry import enrich_rate_limit_response, get_retry_ctx
            # Effective capacity: prefer RPM (minute-scale) as the capacity signal;
            # fall back to RPS burst if RPM is disabled (0).
            _rate_limit = int(settings.rate_limit_rpm) or int(settings.rate_limit_rps) or 0
            enrich_rate_limit_response(
                headers,
                get_retry_ctx(request),
                rate_limit=_rate_limit,
                remaining=0,
            )
```

Note: `settings` is already imported at the top of `app.py` (`from config import settings`).

- [ ] **Step 2: Run full suite — no regressions**

```bash
cd /teamspace/studios/this_studio/dikders
pytest tests/ --ignore=tests/integration -q 2>&1 | tail -5
```

Expected: 0 failures.

- [ ] **Step 3: Smoke test — enrich_rate_limit_response import in app context**

```bash
cd /teamspace/studios/this_studio/dikders
python -c "
from middleware.retry import RetryContext, get_retry_ctx, enrich_rate_limit_response
ctx = RetryContext(retry_count=2, retry_reason='rps')
headers = {}
enrich_rate_limit_response(headers, ctx, rate_limit=60, remaining=0)
assert headers['X-Retry-Count'] == '2'
assert headers['X-Retry-Reason'] == 'rps'
assert headers['X-RateLimit-Limit'] == '60'
assert headers['X-RateLimit-Remaining'] == '0'
print('enrich_rate_limit_response: OK')

# None ctx path
headers2 = {}
enrich_rate_limit_response(headers2, None, rate_limit=60, remaining=0)
assert 'X-Retry-Count' not in headers2
assert 'X-Retry-Reason' not in headers2
assert headers2['X-RateLimit-Limit'] == '60'
print('None ctx path: OK')
print('ALL OK')
"
```

Expected: `ALL OK`

- [ ] **Step 4: Commit**

```bash
cd /teamspace/studios/this_studio/dikders
git add app.py
git commit -m "feat(app): enrich 429 responses with X-Retry-Count, X-Retry-Reason, X-RateLimit-* headers"
```

---

## Chunk 4: Wire `request` into router call sites

### Task 5: Pass `request` to `enforce_rate_limit()` and `enforce_per_key_rate_limit()` in routers

The two enforce functions now accept an optional `request` parameter. The routers already hold a `Request` object — pass it through so `RetryContext` is populated on the actual request state, not a phantom object.

**Files:**
- Modify: `routers/openai.py`
- Modify: `routers/anthropic.py`

Read both router files first to confirm the exact call sites. The pattern in both is:

```python
enforce_rate_limit(api_key)
# ... later ...
await enforce_per_key_rate_limit(api_key, key_record=key_record)
```

- [ ] **Step 1: Read `routers/openai.py` and `routers/anthropic.py` to find the exact call sites**

```bash
grep -n 'enforce_rate_limit\|enforce_per_key_rate_limit' \
    /teamspace/studios/this_studio/dikders/routers/openai.py \
    /teamspace/studios/this_studio/dikders/routers/anthropic.py
```

Expected output: two lines per router showing the line numbers of the `enforce_rate_limit(api_key)` and `enforce_per_key_rate_limit(api_key, ...)` calls.

- [ ] **Step 2: Update `enforce_rate_limit` call in `routers/openai.py`**

Find the call `enforce_rate_limit(api_key)` in `routers/openai.py` and change it to:

```python
enforce_rate_limit(api_key, request=request)
```

- [ ] **Step 3: Update `enforce_per_key_rate_limit` call in `routers/openai.py`**

Find the call `await enforce_per_key_rate_limit(api_key, key_record=key_record)` in `routers/openai.py` and change it to:

```python
await enforce_per_key_rate_limit(api_key, key_record=key_record, request=request)
```

- [ ] **Step 4: Update `enforce_rate_limit` call in `routers/anthropic.py`**

Find the call `enforce_rate_limit(api_key)` in `routers/anthropic.py` and change it to:

```python
enforce_rate_limit(api_key, request=request)
```

- [ ] **Step 5: Update `enforce_per_key_rate_limit` call in `routers/anthropic.py`**

Find the call `await enforce_per_key_rate_limit(api_key, key_record=key_record)` in `routers/anthropic.py` and change it to:

```python
await enforce_per_key_rate_limit(api_key, key_record=key_record, request=request)
```

- [ ] **Step 6: Run full suite — no regressions**

```bash
cd /teamspace/studios/this_studio/dikders
pytest tests/ --ignore=tests/integration -q 2>&1 | tail -5
```

Expected: 0 failures.

- [ ] **Step 7: Commit**

```bash
cd /teamspace/studios/this_studio/dikders
git add routers/openai.py routers/anthropic.py
git commit -m "feat(routers): pass request to enforce_rate_limit and enforce_per_key_rate_limit"
```

---

## Chunk 5: Final validation

### Task 6: Full validation — all headers present, no regressions

**Files:** none new

- [ ] **Step 1: Full import smoke test**

```bash
cd /teamspace/studios/this_studio/dikders
python -c "
from middleware.retry import RetryContext, get_retry_ctx, enrich_rate_limit_response

# RetryContext defaults
ctx = RetryContext()
assert ctx.retry_count == 0
assert ctx.retry_reason == ''

# get_retry_ctx — None when not set
from unittest.mock import MagicMock
req = MagicMock(spec=[])
req.state = MagicMock(spec=[])
assert get_retry_ctx(req) is None

# enrich with ctx
ctx2 = RetryContext(retry_count=1, retry_reason='rpm')
headers = {}
enrich_rate_limit_response(headers, ctx2, rate_limit=60, remaining=0)
assert headers['X-Retry-Count'] == '1'
assert headers['X-Retry-Reason'] == 'rpm'
assert headers['X-RateLimit-Limit'] == '60'
assert headers['X-RateLimit-Remaining'] == '0'

# enrich without ctx
headers2 = {}
enrich_rate_limit_response(headers2, None, rate_limit=60, remaining=0)
assert 'X-Retry-Count' not in headers2
assert 'X-Retry-Reason' not in headers2
assert headers2['X-RateLimit-Limit'] == '60'

print('ALL OK')
"
```

Expected: `ALL OK`

- [ ] **Step 2: Verify `_set_retry_ctx` normalisation**

```bash
cd /teamspace/studios/this_studio/dikders
python -c "
from middleware.rate_limit import _set_retry_ctx, _REASON_NORMALISE
from middleware.retry import RetryContext
from unittest.mock import MagicMock

req = MagicMock()
req.state = MagicMock(spec=['retry'])
del req.state.retry  # ensure getattr returns None

_set_retry_ctx(req, 'RPS limit exceeded')
assert req.state.retry.retry_reason == 'rps', req.state.retry.retry_reason
print('RPS normalise: OK')

req2 = MagicMock()
req2.state = MagicMock(spec=['retry'])
del req2.state.retry
_set_retry_ctx(req2, 'RPM limit exceeded')
assert req2.state.retry.retry_reason == 'rpm'
print('RPM normalise: OK')

# None request — must not raise
_set_retry_ctx(None, 'RPS limit exceeded')
print('None request: OK')

print('ALL OK')
"
```

Expected: `ALL OK`

- [ ] **Step 3: Run full test suite**

```bash
cd /teamspace/studios/this_studio/dikders
pytest tests/ --ignore=tests/integration -q 2>&1 | tail -5
```

Expected: existing count + 20 new tests pass, 0 failures.

- [ ] **Step 4: Run retry middleware tests verbosely**

```bash
cd /teamspace/studios/this_studio/dikders
pytest tests/test_retry_middleware.py -v 2>&1 | tail -30
```

Expected: all 20 tests PASS.

- [ ] **Step 5: Update UPDATES.md**

Add a new session entry at the bottom of `UPDATES.md` documenting:
- `middleware/retry.py` created — `RetryContext`, `get_retry_ctx`, `enrich_rate_limit_response`
- `middleware/rate_limit.py` modified — `_set_retry_ctx`, `_REASON_NORMALISE`, `request` param added to `enforce_rate_limit()` and `enforce_per_key_rate_limit()`
- `app.py` modified — `proxy_error_handler` enriches 429 with `X-Retry-Count`, `X-Retry-Reason`, `X-RateLimit-Limit`, `X-RateLimit-Remaining`
- `routers/openai.py`, `routers/anthropic.py` modified — `request=request` passed to both enforce functions
- `tests/test_retry_middleware.py` created — 20 unit tests

- [ ] **Step 6: Commit and push**

```bash
cd /teamspace/studios/this_studio/dikders
git add UPDATES.md
git commit -m "docs: update UPDATES.md for retry middleware"
git push
```

---

## Summary

| Chunk | Files | Tests |
|---|---|---|
| 1 | `middleware/retry.py`, `tests/test_retry_middleware.py` | 20 new tests (RetryContext, get_retry_ctx, enrich, 429 response headers) |
| 2 | `middleware/rate_limit.py` | existing 20 rate limit tests pass unchanged |
| 3 | `app.py` | existing app tests pass |
| 4 | `routers/openai.py`, `routers/anthropic.py` | existing router tests pass |
| 5 | `UPDATES.md` | full suite 0 failures |

**Headers added to every 429 response:**

| Header | Source | Always present |
|---|---|---|
| `Retry-After` | `RateLimitError.retry_after` (already existed) | Yes |
| `X-Retry-Count` | `RetryContext.retry_count` | Only when `RetryContext` set |
| `X-Retry-Reason` | `RetryContext.retry_reason` (`rps`/`rpm`/`suppression`/`timeout`) | Only when `RetryContext` set |
| `X-RateLimit-Limit` | `settings.rate_limit_rpm` or `settings.rate_limit_rps` | Yes |
| `X-RateLimit-Remaining` | `0` (limit was exceeded) | Yes |

**Zero new dependencies. Zero breaking changes. All new parameters keyword-only with `None` default.**