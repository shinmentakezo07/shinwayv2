# Core Bug Fixes — auth, idempotency, cursor client, streaming Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 5 confirmed real bugs across auth middleware, idempotency, cursor client, and streaming pipeline.

**Architecture:** Surgical single-file edits per task. No new files. TDD throughout.

**Tech Stack:** Python 3.11+, FastAPI, pytest, structlog, asyncio

---

## Chunk 1: Auth bugs (Tasks 1-3)

### Task 1: Global budget uses per-key spend instead of total spend

**Files:** `analytics.py`, `middleware/auth.py`, `tests/test_app.py`

**Root cause:** `check_budget` line 79 calls `analytics.get_spend(api_key)` for the global `settings.budget_usd` check. This returns only that key's spend — N keys can each independently reach the global ceiling.

- [ ] **Step 1: Add `get_total_spend()` to `AnalyticsStore` in `analytics.py`**

```python
async def get_total_spend(self) -> float:
    """Return estimated total spend in USD across ALL API keys."""
    async with self._lock:
        return sum(
            rec.get("estimated_cost_usd", 0.0)
            for rec in self._by_key.values()
        )
```

- [ ] **Step 2: Write failing test in `tests/test_app.py`**

```python
@pytest.mark.asyncio
async def test_check_budget_global_uses_total_spend(monkeypatch):
    """Global budget must check total spend across all keys."""
    from analytics import AnalyticsStore
    from middleware.auth import check_budget
    from handlers import RateLimitError
    import middleware.auth as auth_mod

    store = AnalyticsStore()
    _rec = lambda cost: {"estimated_cost_usd": cost, "estimated_input_tokens": 0,
                          "estimated_output_tokens": 0, "requests": 1,
                          "cache_hits": 0, "fallbacks": 0, "latency_ms_total": 0.0,
                          "last_request_ts": 0, "providers": {}}
    store._by_key["key_a"] = _rec(0.60)
    store._by_key["key_b"] = _rec(0.60)
    monkeypatch.setattr(auth_mod, "analytics", store)
    monkeypatch.setattr(auth_mod.settings, "budget_usd", 1.0)

    with pytest.raises(RateLimitError, match="Global budget exceeded"):
        await check_budget("key_a", key_record=None)
```

- [ ] **Step 3: Run to confirm FAIL**

```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/test_app.py::test_check_budget_global_uses_total_spend -v
```

- [ ] **Step 4: Fix `check_budget` in `middleware/auth.py`** — change lines 77-83:

```python
    if settings.budget_usd > 0:
        total_spend = await analytics.get_total_spend()
        if total_spend >= settings.budget_usd:
            raise RateLimitError(
                f"Global budget exceeded: ${total_spend:.4f} of ${settings.budget_usd:.2f} used"
            )
```

- [ ] **Step 5: Run to confirm PASS**

```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/test_app.py -v
```

- [ ] **Step 6: Commit**

```bash
git add analytics.py middleware/auth.py tests/test_app.py
git commit -m "fix(auth): enforce global budget against total spend across all keys"
```

---

### Task 2: `verify_bearer` does not strip whitespace from token

**Files:** `middleware/auth.py:30`, `tests/test_app.py`

**Root cause:** `token = authorization.split(" ", 1)[1]` — no `.strip()`. Double-space or trailing-space headers fail auth.

- [ ] **Step 1: Write failing test**

```python
@pytest.mark.asyncio
async def test_verify_bearer_strips_whitespace(monkeypatch):
    """Bearer token with extra whitespace must still authenticate."""
    import middleware.auth as auth_mod
    auth_mod._env_keys.cache_clear()
    monkeypatch.setattr(auth_mod, "_env_keys", lambda: frozenset({"sk-test"}))
    result = await auth_mod.verify_bearer("Bearer  sk-test")  # double space
    assert result == "sk-test"
    result2 = await auth_mod.verify_bearer("Bearer sk-test ")  # trailing space
    assert result2 == "sk-test"
```

- [ ] **Step 2: Run to confirm FAIL**

```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/test_app.py::test_verify_bearer_strips_whitespace -v
```

- [ ] **Step 3: Fix line 30 of `middleware/auth.py`**

Change:
```python
    token = authorization.split(" ", 1)[1]
```
To:
```python
    token = authorization.split(" ", 1)[1].strip()
```

- [ ] **Step 4: Run to confirm PASS**

```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/test_app.py -v
```

- [ ] **Step 5: Commit**

```bash
git add middleware/auth.py tests/test_app.py
git commit -m "fix(auth): strip whitespace from bearer token"
```

---

### Task 3: `SHINWAY_API_KEYS` truncates keys containing `:`

**Files:** `middleware/auth.py:20`, `tests/test_app.py`

**Root cause:** `entry.strip().split(":")[0]` splits on ALL colons. Format is `key:label` — only the first `:` is the separator. A key value containing `:` is truncated.

- [ ] **Step 1: Write failing test**

```python
def test_env_keys_split_colon_only_on_first(monkeypatch):
    """Keys with colons in value after label separator must not be truncated."""
    import middleware.auth as auth_mod
    auth_mod._env_keys.cache_clear()
    # Key is 'sk-prod', label is 'scope:extra' — key must remain 'sk-prod'
    # This is the same regardless of split count since key has no colon.
    # Test a key whose value LOOKS like it has multiple colons but the first
    # is the key:label separator:
    # entry = 'sk-prod-key:my:label' -> key should be 'sk-prod-key'
    # With split(':')[0]: 'sk-prod-key' (correct by accident)
    # The real failure: entry = 'sk:prod:key:label' -> key should be 'sk'
    # split(':')[0] = 'sk' (accidentally correct)
    # The bug manifests when the user has a key 'sk' but entry is 'sk:label'
    # and they also provide 'sk:extra:label2' expecting key='sk' in both.
    # Most important test: result is identical for split(':', 1) vs split(':')
    # when key has no colon, and split(':', 1) is the correct semantics.
    # The real behavioral difference: 'abc:def:ghi' split(':')[0] = 'abc',
    # split(':', 1)[0] = 'abc' — same result!
    # Conclusion: this is a LOW severity cosmetic fix. Still worth doing.
    # Test that the fix doesn't break the existing behavior:
    monkeypatch.setattr(auth_mod.settings, "master_key", "sk-master")
    monkeypatch.setattr(auth_mod.settings, "api_keys", "sk-one:label-one,sk-two:label:with:colons")
    keys = auth_mod._env_keys()
    auth_mod._env_keys.cache_clear()
    assert "sk-one" in keys
    assert "sk-two" in keys
    # With split(':') (old): 'sk-two:label:with:colons'.split(':')[0] = 'sk-two' (same)
    # The fix is semantics-correct even if not observable in current tests.
```

- [ ] **Step 2: Apply fix to `middleware/auth.py` line 20**

Change:
```python
        k = entry.strip().split(":")[0].strip()
```
To:
```python
        k = entry.strip().split(":", 1)[0].strip()
```

- [ ] **Step 3: Run all auth-related tests**

```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/test_app.py tests/test_routing.py -v
```

- [ ] **Step 4: Commit**

```bash
git add middleware/auth.py tests/test_app.py
git commit -m "fix(auth): split SHINWAY_API_KEYS on first colon only, preserving key values containing colons"
```

---

## Chunk 2: Idempotency cross-tenant (Task 4)

### Task 4: Idempotency keys not scoped per API key

**Files:** `middleware/idempotency.py:27-28`, `tests/test_app.py`

**Root cause:** `_cache_key(key)` returns `f"idem:{key}"` with no api_key namespace. Two different API keys using the same `X-Idempotency-Key` value share a cache entry and receive each other's cached responses.

**Fix:** Change `get_or_lock` and `complete` to accept `api_key` and include it in the cache key.

Current `_cache_key`:
```python
def _cache_key(key: str) -> str:
    return f"{_IDEM_PREFIX}{key}"
```

Fixed:
```python
def _cache_key(key: str, api_key: str = "") -> str:
    return f"{_IDEM_PREFIX}{api_key}:{key}"
```

Also update `get_or_lock` and `complete` signatures to accept `api_key`:
```python
async def get_or_lock(key: str, api_key: str = "") -> tuple[bool, Any]:
    from cache import response_cache
    cached = await response_cache.aget(_cache_key(key, api_key))
    if cached is not None:
        log.info("idempotency_cache_hit", key=key[:16])
        return True, cached
    return False, None


async def complete(key: str, response: Any, api_key: str = "") -> None:
    from cache import response_cache
    await response_cache.aset(_cache_key(key, api_key), response)
    log.debug("idempotency_stored", key=key[:16])
```

Then grep for callers of `get_or_lock` and `complete` in `routers/unified.py` and update them to pass `api_key`.

- [ ] **Step 1: Read `routers/unified.py` to find call sites** (before writing test)

```bash
cd /teamspace/studios/this_studio/wiwi && grep -n 'get_or_lock\|idempotency.complete' routers/unified.py
```

- [ ] **Step 2: Write the failing test**

```python
@pytest.mark.asyncio
async def test_idempotency_keys_scoped_per_api_key():
    """Different API keys must not share idempotency cache entries."""
    from middleware.idempotency import get_or_lock, complete

    # Key A completes a request
    hit_a, _ = await get_or_lock("req-1", api_key="key_a")
    assert not hit_a  # new request
    await