# Audit Remaining 8 Fixes — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development to implement this plan.

**Goal:** Fix all 8 remaining issues from the post-fix audit: replace threading primitives with async-safe equivalents, eliminate redundant DB calls, enforce model allowlists, add content validation, fix inline imports, and improve observability.

**Architecture:** Surgical fixes across 7 files. No architectural changes. Each chunk is independently committable. Tests must pass after every commit.

**Tech Stack:** Python 3.12, FastAPI, asyncio, aiosqlite, structlog, cachetools (already a dep)

---

## Chunk 1: Performance + Memory (H2, H3, H5)

### Task 1: H5 — Hoist StreamMonitor import out of hot-path streaming functions

**Files:**
- Modify: `pipeline.py` (lines 416 and 606 — two inline `from utils.stream_monitor import StreamMonitor`)

- [ ] **Step 1:** Read the top-level imports section of `pipeline.py` (lines 1–50)

- [ ] **Step 2:** Check if `StreamMonitor` is already imported at module level:
```bash
grep -n 'StreamMonitor' /teamspace/studios/this_studio/wiwi/pipeline.py | head -5
```
Expected: two hits inside functions at lines ~416 and ~606, none at module level.

- [ ] **Step 3:** Add `from utils.stream_monitor import StreamMonitor` to module-level imports in `pipeline.py`, alongside other utils imports.

- [ ] **Step 4:** Remove both inline `from utils.stream_monitor import StreamMonitor` occurrences inside `_openai_stream` and `_anthropic_stream`.

- [ ] **Step 5:** Verify import resolves:
```bash
cd /teamspace/studios/this_studio/wiwi && python -c "from pipeline import _openai_stream; print('OK')"
```
Expected: `OK`

- [ ] **Step 6:** Run tests:
```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/test_pipeline.py -q 2>&1 | tail -5
```
Expected: all pass.

- [ ] **Step 7:** Commit:
```bash
cd /teamspace/studios/this_studio/wiwi && git add pipeline.py && git commit -m 'perf: hoist StreamMonitor import to module level — removes inline import from streaming hot path'
```

---

### Task 2: H2 — LRU-bound `_per_key_limiters` dict

**Files:**
- Modify: `middleware/rate_limit.py` (lines 105–106)

The `_per_key_limiters` dict grows unbounded. When a key is deleted or its limits change, old entries are never evicted. Use `cachetools.LRUCache` (already a dependency via `cache.py`).

- [ ] **Step 1:** Confirm cachetools is installed:
```bash
cd /teamspace/studios/this_studio/wiwi && python -c "import cachetools; print(cachetools.__version__)"
```
Expected: version string.

- [ ] **Step 2:** In `middleware/rate_limit.py`, add import at top:
```python
from cachetools import LRUCache
```

- [ ] **Step 3:** Replace the plain dict with an LRUCache(maxsize=10000):
```python
# BEFORE
_per_key_limiters: dict[str, DualBucketRateLimiter] = {}
_per_key_lock = threading.Lock()

# AFTER
# LRU-bounded: evicts oldest entry when 10 000 distinct key:rpm:rps combos are reached.
# Protects against unbounded growth from key churn or limit changes.
_per_key_limiters: LRUCache[str, DualBucketRateLimiter] = LRUCache(maxsize=10_000)
_per_key_lock = threading.Lock()
```

- [ ] **Step 4:** Run tests:
```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/ -m 'not integration' -q --ignore=tests/test_client_headers.py --ignore=tests/test_context.py 2>&1 | tail -5
```
Expected: all pass.

- [ ] **Step 5:** Commit:
```bash
cd /teamspace/studios/this_studio/wiwi && git add middleware/rate_limit.py && git commit -m 'fix: LRU-bound _per_key_limiters — prevents unbounded memory growth from key churn'
```

---

### Task 3: H3 — Collapse 3x `key_store.get()` to 1 per request

**Files:**
- Modify: `middleware/auth.py`
- Modify: `middleware/rate_limit.py`
- Modify: `routers/unified.py`
- Modify: `routers/responses.py`

**Current hot path per request (DB-managed key):**
1. `verify_bearer` → `key_store.is_valid(token)` — SELECT 1 (check active)
2. `enforce_per_key_rate_limit` → `key_store.get(api_key)` — SELECT * (get limits)
3. `check_budget` → `key_store.get(api_key)` — SELECT * (get budget)

**Target:** Single `key_store.get()` call, result threaded into all consumers.

- [ ] **Step 1:** Read `middleware/auth.py` fully. Read `middleware/rate_limit.py` fully.

- [ ] **Step 2:** Add `get_and_validate` method to auth.py that fetches the full record once:

In `middleware/auth.py`, add a new function:
```python
async def get_key_record(api_key: str) -> dict | None:
    """Fetch the full key record for a DB-managed key.

    Returns None for env keys and master key (they have no DB record).
    Called once per request; result is passed into rate limit and budget checks.
    """
    if api_key in _env_keys():
        return None  # env / master key — no DB record
    from storage.keys import key_store
    return await key_store.get(api_key)
```

- [ ] **Step 3:** Update `enforce_per_key_rate_limit` in `rate_limit.py` to accept an optional pre-fetched record:

```python
async def enforce_per_key_rate_limit(
    api_key: str,
    key_record: dict | None = None,
) -> None:
    """Enforce per-key RPS/RPM limits if configured in KeyStore.

    key_record: pre-fetched key record (pass to avoid redundant DB lookup).
    If None and api_key is a DB key, fetches from store.
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
        return

    limiter_key = f"{api_key}:{rpm}:{rps}"
    with _per_key_lock:
        if limiter_key not in _per_key_limiters:
            _per_key_limiters[limiter_key] = DualBucketRateLimiter(
                rate_rps=float(rps) if rps > 0 else 0.0,
                burst_rps=max(rps, 1),
                rate_rpm=float(rpm) if rpm > 0 else 0.0,
                burst_rpm=max(rpm, 1),
            )
        limiter = _per_key_limiters[limiter_key]

    allowed, reason = limiter.consume(api_key)
    if not allowed:
        log.warning("per_key_rate_limit_exceeded", api_key=api_key[:16], reason=reason)
        raise RateLimitError(f"Per-key rate limit exceeded: {reason}")
```

- [ ] **Step 4:** Update `check_budget` in `middleware/auth.py` to accept optional pre-fetched record:

```python
async def check_budget(api_key: str, key_record: dict | None = _SENTINEL) -> None:
    """Raise RateLimitError if per-key or global budget/token limit exceeded.

    key_record: pre-fetched key record. Pass to avoid a redundant DB lookup.
    Pass None explicitly to skip the DB lookup (env/master keys).
    Omit to have check_budget fetch it itself (backwards compat).
    """
```

Simpler approach — use a sentinel:
```python
_SENTINEL = object()

async def check_budget(api_key: str, key_record: object = _SENTINEL) -> None:
    if key_record is _SENTINEL:
        from storage.keys import key_store
        rec = await key_store.get(api_key)
    else:
        rec = key_record  # type: ignore[assignment]

    spend: float | None = None
    if rec and rec["budget_usd"] > 0:
        spend = await analytics.get_spend(api_key)
        if spend >= rec["budget_usd"]:
            raise RateLimitError(
                f"Key budget exceeded: ${spend:.4f} of ${rec['budget_usd']:.2f}"
            )
    if settings.budget_usd > 0:
        if spend is None:
            spend = await analytics.get_spend(api_key)
        if spend >= settings.budget_usd:
            raise RateLimitError(
                f"Budget exceeded: ${spend:.4f} of ${settings.budget_usd:.2f} used"
            )
    if rec and rec.get("token_limit_daily", 0) > 0:
        daily_tokens = await analytics.get_daily_tokens(api_key)
        if daily_tokens >= rec["token_limit_daily"]:
            raise RateLimitError(
                f"Daily token limit exceeded: {daily_tokens:,} of {rec['token_limit_daily']:,} tokens used"
            )
```

- [ ] **Step 5:** Update the router endpoints to call `get_key_record` once and thread the result.

In `routers/unified.py`, find both `chat_completions` and `anthropic_messages` endpoint bodies. The pattern to change:

```python
# BEFORE (3 DB calls)
api_key = await verify_bearer(authorization)
enforce_rate_limit(api_key)
await enforce_per_key_rate_limit(api_key)
await check_budget(api_key)

# AFTER (1 DB call)
api_key = await verify_bearer(authorization)
enforce_rate_limit(api_key)
key_rec = await get_key_record(api_key)
await enforce_per_key_rate_limit(api_key, key_record=key_rec)
await check_budget(api_key, key_record=key_rec)
```

Add `get_key_record` to the import line:
```python
from middleware.auth import verify_bearer, check_budget, get_key_record
```

Do the same for `text_completions` endpoint and `routers/responses.py`.

- [ ] **Step 6:** Run tests:
```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/ -m 'not integration' -q --ignore=tests/test_client_headers.py --ignore=tests/test_context.py 2>&1 | tail -10
```
Expected: all pass.

- [ ] **Step 7:** Commit:
```bash
cd /teamspace/studios/this_studio/wiwi && git add middleware/auth.py middleware/rate_limit.py routers/unified.py routers/responses.py && git commit -m 'perf: collapse 3x key_store.get() to 1 per request — thread key_record through auth chain'
```

---

## Chunk 2: Async Safety (H1)

### Task 4: H1 — Replace `threading.Lock` with async-safe alternatives

**Files:**
- Modify: `middleware/rate_limit.py` — `TokenBucket._lock` and `_per_key_lock`
- Modify: `cursor/credentials.py` — `CredentialPool._lock`

**Important:** `TokenBucket` is used both synchronously (`enforce_rate_limit` is a sync function called from async handlers) and from `enforce_per_key_rate_limit` (async). `CredentialPool.next/mark_error/mark_success` are called from async `cursor/client.py`.

**Decision:** `threading.Lock` is safe in single-threaded asyncio (which is the deployment model here — one uvicorn worker per process). However the critical sections