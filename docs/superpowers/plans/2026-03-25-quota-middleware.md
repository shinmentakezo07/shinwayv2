# Sliding Window Token Quota Middleware Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the in-process daily token counter in `middleware/auth.py:check_budget` with a proper sliding window quota backed by SQLite (`quota.db`). The new store survives restarts, enforces a true 24-hour rolling window per API key, and is opt-in via `SHINWAY_QUOTA_ENABLED`.

**Architecture:** `storage/quota.py` owns all DB I/O: a single `quota_usage` table stores `(api_key, window_start, tokens_used)` rows — one row per `record()` call. `get_usage_24h(api_key)` sums `tokens_used` for all rows where `window_start > now - 86400`. `prune_old()` deletes rows outside the 24-hour window — called periodically inside `record()` to prevent unbounded growth. `middleware/quota.py` is a thin logic layer: `check_quota` reads the store and raises `RateLimitError`; `record_quota_usage` writes to the store. Both are called from `check_budget` only when `settings.quota_enabled` is `True` and the key's `token_limit_daily > 0`.

**Tech Stack:** Python 3.12, aiosqlite (already installed), pydantic-settings (already installed), pytest-asyncio (already installed). Zero new dependencies.

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `storage/quota.py` | CREATE | `QuotaStore` — `init`, `close`, `record`, `get_usage_24h`, `prune_old` |
| `middleware/quota.py` | CREATE | `check_quota(api_key, token_limit_daily)` and `record_quota_usage(api_key, tokens)` |
| `config.py` | MODIFY | Add `quota_enabled: bool` field aliased to `SHINWAY_QUOTA_ENABLED` |
| `app.py` | MODIFY | Init and close `quota_store` in `_lifespan` |
| `middleware/auth.py` | MODIFY | Call `check_quota` inside `check_budget` when quota enabled |
| `tests/test_quota.py` | CREATE | Unit + async tests for `QuotaStore` and `middleware/quota.py` |

---

## Chunk 1: `storage/quota.py` — QuotaStore

### Task 1: Write failing tests for `QuotaStore`

**Files:**
- Create: `tests/test_quota.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_quota.py
"""Tests for sliding window quota storage and middleware.

All storage tests use an in-memory SQLite database — no file I/O, no mocking.
asyncio_mode = auto (pytest.ini) — no @pytest.mark.asyncio needed.
"""
from __future__ import annotations

import time

import pytest
import pytest_asyncio

from storage.quota import QuotaStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def store():
    s = QuotaStore(":memory:")
    await s.init()
    yield s
    await s.close()


# ---------------------------------------------------------------------------
# Uninitialised guard
# ---------------------------------------------------------------------------


async def test_uninitialised_raises_on_record():
    s = QuotaStore(":memory:")
    with pytest.raises(RuntimeError, match="not initialised"):
        await s.record("sk-test", 100)


async def test_uninitialised_raises_on_get_usage():
    s = QuotaStore(":memory:")
    with pytest.raises(RuntimeError, match="not initialised"):
        await s.get_usage_24h("sk-test")


async def test_uninitialised_raises_on_prune():
    s = QuotaStore(":memory:")
    with pytest.raises(RuntimeError, match="not initialised"):
        await s.prune_old()


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------


async def test_init_creates_table(store):
    """init() creates the quota_usage table; get_usage_24h returns 0 on empty store."""
    result = await store.get_usage_24h("sk-test")
    assert result == 0


async def test_double_init_is_idempotent():
    """Calling init() twice does not raise — CREATE TABLE IF NOT EXISTS is safe."""
    s = QuotaStore(":memory:")
    await s.init()
    await s.init()
    await s.close()


# ---------------------------------------------------------------------------
# record + get_usage_24h
# ---------------------------------------------------------------------------


async def test_record_single_entry_appears_in_usage(store):
    """A single record() call is reflected in get_usage_24h."""
    await store.record("sk-abc", 500)
    total = await store.get_usage_24h("sk-abc")
    assert total == 500


async def test_record_accumulates_multiple_calls(store):
    """Multiple record() calls for the same key sum correctly."""
    await store.record("sk-abc", 100)
    await store.record("sk-abc", 200)
    await store.record("sk-abc", 300)
    total = await store.get_usage_24h("sk-abc")
    assert total == 600


async def test_record_isolated_per_key(store):
    """Usage for one key does not bleed into another key's total."""
    await store.record("sk-alice", 1000)
    await store.record("sk-bob", 250)
    assert await store.get_usage_24h("sk-alice") == 1000
    assert await store.get_usage_24h("sk-bob") == 250


async def test_get_usage_24h_zero_for_unknown_key(store):
    """A key with no recorded usage returns 0, not None."""
    result = await store.get_usage_24h("sk-nobody")
    assert result == 0


async def test_record_zero_tokens_is_allowed(store):
    """record() with tokens=0 is a no-op but does not raise."""
    await store.record("sk-abc", 0)
    total = await store.get_usage_24h("sk-abc")
    assert total == 0


# ---------------------------------------------------------------------------
# Sliding window — old rows excluded from get_usage_24h
# ---------------------------------------------------------------------------


async def test_old_records_excluded_from_usage(store):
    """Records with window_start older than 24 h are not counted in get_usage_24h."""
    # Insert a row directly with an old timestamp (25 hours ago)
    old_ts = int(time.time()) - (25 * 3600)
    await store._db.execute(
        "INSERT INTO quota_usage (api_key, window_start, tokens_used) VALUES (?, ?, ?)",
        ("sk-abc", old_ts, 9999),
    )
    await store._db.commit()

    # Add a current record
    await store.record("sk-abc", 100)

    total = await store.get_usage_24h("sk-abc")
    # Only the current 100 tokens should count; 9999 old tokens must be excluded
    assert total == 100


async def test_boundary_record_at_exactly_24h_is_excluded(store):
    """A record at exactly now - 86400 seconds falls outside the window and is excluded."""
    boundary_ts = int(time.time()) - 86400
    await store._db.execute(
        "INSERT INTO quota_usage (api_key, window_start, tokens_used) VALUES (?, ?, ?)",
        ("sk-abc", boundary_ts, 500),
    )
    await store._db.commit()

    total = await store.get_usage_24h("sk-abc")
    # Strict greater-than means exactly 86400 s old is outside the window
    assert total == 0


async def test_record_just_inside_window_is_included(store):
    """A record at now - 86399 seconds is inside the window and is counted."""
    recent_ts = int(time.time()) - 86399
    await store._db.execute(
        "INSERT INTO quota_usage (api_key, window_start, tokens_used) VALUES (?, ?, ?)",
        ("sk-abc", recent_ts, 300),
    )
    await store._db.commit()

    total = await store.get_usage_24h("sk-abc")
    assert total == 300


# ---------------------------------------------------------------------------
# prune_old
# ---------------------------------------------------------------------------


async def test_prune_old_removes_expired_rows(store):
    """prune_old() deletes rows with window_start <= now - 86400."""
    old_ts = int(time.time()) - (25 * 3600)
    await store._db.execute(
        "INSERT INTO quota_usage (api_key, window_start, tokens_used) VALUES (?, ?, ?)",
        ("sk-abc", old_ts, 9999),
    )
    await store._db.commit()

    await store.prune_old()

    # Row must be gone from the raw table
    async with store._db.execute(
        "SELECT COUNT(*) FROM quota_usage WHERE api_key = ?", ("sk-abc",)
    ) as cur:
        row = await cur.fetchone()
    assert row[0] == 0


async def test_prune_old_preserves_current_rows(store):
    """prune_old() does not delete rows that are still within the 24-hour window."""
    await store.record("sk-abc", 200)

    await store.prune_old()

    total = await store.get_usage_24h("sk-abc")
    assert total == 200


async def test_prune_old_on_empty_table_does_not_raise(store):
    """prune_old() on an empty table is a no-op and does not raise."""
    await store.prune_old()  # must not raise


# ---------------------------------------------------------------------------
# middleware/quota.py — check_quota and record_quota_usage
# ---------------------------------------------------------------------------


class _FakeStore:
    """Minimal QuotaStore stand-in for middleware tests."""

    def __init__(self, current_usage: int = 0) -> None:
        self._usage = current_usage
        self.recorded: list[tuple[str, int]] = []

    async def get_usage_24h(self, api_key: str) -> int:
        return self._usage

    async def record(self, api_key: str, tokens: int) -> None:
        self.recorded.append((api_key, tokens))
        self._usage += tokens


async def test_check_quota_passes_when_under_limit(monkeypatch):
    """check_quota does not raise when usage is below the daily limit."""
    from middleware import quota as quota_mod

    fake = _FakeStore(current_usage=500)
    monkeypatch.setattr(quota_mod, "quota_store", fake)

    # Should not raise — 500 used, limit 1000
    await quota_mod.check_quota("sk-abc", token_limit_daily=1000)


async def test_check_quota_passes_when_at_limit_minus_one(monkeypatch):
    """check_quota does not raise when usage is one token below the limit."""
    from middleware import quota as quota_mod

    fake = _FakeStore(current_usage=999)
    monkeypatch.setattr(quota_mod, "quota_store", fake)

    await quota_mod.check_quota("sk-abc", token_limit_daily=1000)


async def test_check_quota_raises_when_at_limit(monkeypatch):
    """check_quota raises RateLimitError when usage equals the daily limit."""
    from handlers import RateLimitError
    from middleware import quota as quota_mod

    fake = _FakeStore(current_usage=1000)
    monkeypatch.setattr(quota_mod, "quota_store", fake)

    with pytest.raises(RateLimitError):
        await quota_mod.check_quota("sk-abc", token_limit_daily=1000)


async def test_check_quota_raises_when_over_limit(monkeypatch):
    """check_quota raises RateLimitError when usage exceeds the daily limit."""
    from handlers import RateLimitError
    from middleware import quota as quota_mod

    fake = _FakeStore(current_usage=1500)
    monkeypatch.setattr(quota_mod, "quota_store", fake)

    with pytest.raises(RateLimitError):
        await quota_mod.check_quota("sk-abc", token_limit_daily=1000)


async def test_record_quota_usage_delegates_to_store(monkeypatch):
    """record_quota_usage calls store.record with the correct key and token count."""
    from middleware import quota as quota_mod

    fake = _FakeStore()
    monkeypatch.setattr(quota_mod, "quota_store", fake)

    await quota_mod.record_quota_usage("sk-abc", tokens=750)

    assert fake.recorded == [("sk-abc", 750)]


async def test_record_quota_usage_zero_tokens_is_silent(monkeypatch):
    """record_quota_usage with tokens=0 writes nothing to the store."""
    from middleware import quota as quota_mod

    fake = _FakeStore()
    monkeypatch.setattr(quota_mod, "quota_store", fake)

    await quota_mod.record_quota_usage("sk-abc", tokens=0)

    # tokens=0 is a no-op — nothing should be recorded
    assert fake.recorded == []
```

- [ ] **Step 2: Run tests — expect ImportError**

```bash
cd /teamspace/studios/this_studio/dikders
pytest tests/test_quota.py -v 2>&1 | tail -10
```

Expected: `ModuleNotFoundError: No module named 'storage.quota'`

---

### Task 2: Create `storage/quota.py`

**Files:**
- Create: `storage/quota.py`

- [ ] **Step 1: Write the file**

```python
"""
Shin Proxy — SQLite store for per-key sliding window token quotas.

Table: quota_usage
  api_key      TEXT     — bearer token (never logged beyond prefix)
  window_start INTEGER  — unix timestamp of when this batch of tokens was recorded
  tokens_used  INTEGER  — token count for this row

Sliding window: get_usage_24h sums tokens_used WHERE window_start > now - 86400.
prune_old deletes rows WHERE window_start <= now - 86400 — called inside record()
once every PRUNE_EVERY_N records to bound table growth without per-record DELETE cost.
"""
from __future__ import annotations

import time

import aiosqlite
import structlog

log = structlog.get_logger()

_WINDOW_SECONDS = 86400  # 24 hours
_PRUNE_EVERY_N = 100     # prune once every N record() calls to amortise DELETE cost

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS quota_usage (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    api_key      TEXT    NOT NULL,
    window_start INTEGER NOT NULL,
    tokens_used  INTEGER NOT NULL
)
"""

_CREATE_INDEX = """
CREATE INDEX IF NOT EXISTS idx_quota_usage_key_ts
    ON quota_usage (api_key, window_start)
"""


class QuotaStore:
    """Async SQLite store for per-key sliding window token quotas."""

    def __init__(self, db_path: str = "quota.db") -> None:
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None
        self._record_count = 0

    async def init(self) -> None:
        self._db = await aiosqlite.connect(self._db_path)
        # WAL mode: concurrent reads don't block writes — consistent with ResponseStore/KeyStore
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA synchronous=NORMAL")
        await self._db.execute(_CREATE_TABLE)
        await self._db.execute(_CREATE_INDEX)
        await self._db.commit()
        log.info("quota_store_ready", path=self._db_path)

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    async def record(self, api_key: str, tokens: int) -> None:
        """Insert one usage row for *api_key* with *tokens* at the current timestamp.

        Prunes expired rows every _PRUNE_EVERY_N calls to bound table size.
        tokens=0 is accepted silently and written; callers should guard against
        it if they want to avoid DB writes on zero-token responses.
        """
        if self._db is None:
            raise RuntimeError("QuotaStore not initialised — call init() first")
        now = int(time.time())
        await self._db.execute(
            "INSERT INTO quota_usage (api_key, window_start, tokens_used) VALUES (?, ?, ?)",
            (api_key, now, tokens),
        )
        await self._db.commit()
        self._record_count += 1
        if self._record_count % _PRUNE_EVERY_N == 0:
            await self.prune_old()

    async def get_usage_24h(self, api_key: str) -> int:
        """Return the total tokens used by *api_key* within the last 24 hours.

        Returns 0 if the key has no recorded usage or does not exist.
        Uses a strict greater-than comparison: rows at exactly now-86400 are excluded.
        """
        if self._db is None:
            raise RuntimeError("QuotaStore not initialised — call init() first")
        cutoff = int(time.time()) - _WINDOW_SECONDS
        async with self._db.execute(
            "SELECT COALESCE(SUM(tokens_used), 0) FROM quota_usage "
            "WHERE api_key = ? AND window_start > ?",
            (api_key, cutoff),
        ) as cursor:
            row = await cursor.fetchone()
        return int(row[0]) if row else 0

    async def prune_old(self) -> None:
        """Delete all rows with window_start at or before now - 86400 seconds.

        Safe to call on an empty table. Called automatically inside record()
        every _PRUNE_EVERY_N insertions.
        """
        if self._db is None:
            raise RuntimeError("QuotaStore not initialised — call init() first")
        cutoff = int(time.time()) - _WINDOW_SECONDS
        await self._db.execute(
            "DELETE FROM quota_usage WHERE window_start <= ?", (cutoff,)
        )
        await self._db.commit()


# Module-level singleton — initialised in app lifespan
quota_store: QuotaStore = QuotaStore()
```

- [ ] **Step 2: Run storage-layer tests only — expect PASS**

```bash
cd /teamspace/studios/this_studio/dikders
pytest tests/test_quota.py -v -k "not check_quota and not record_quota_usage" 2>&1 | tail -20
```

Expected: all `QuotaStore` tests PASS; middleware tests still fail with `ModuleNotFoundError: No module named 'middleware.quota'`.

- [ ] **Step 3: Commit**

```bash
git add storage/quota.py
git commit -m "feat(storage): add QuotaStore — sliding window token quota SQLite store"
```

---

## Chunk 2: `middleware/quota.py` — check_quota and record_quota_usage

### Task 3: Create `middleware/quota.py`

**Files:**
- Create: `middleware/quota.py`

- [ ] **Step 1: Write the file**

```python
"""
Shin Proxy — Per-key sliding window token quota middleware.

Two public functions:
  check_quota(api_key, token_limit_daily)
      Reads 24-hour usage from QuotaStore. Raises RateLimitError when usage
      meets or exceeds token_limit_daily. Called from check_budget before
      the request is dispatched upstream.

  record_quota_usage(api_key, tokens)
      Writes token count to QuotaStore after a response is complete.
      tokens=0 is a silent no-op — no DB write issued.

Both functions are only called when settings.quota_enabled is True and
the key's token_limit_daily > 0. That guard lives in check_budget; these
functions assume the caller has already checked the preconditions.
"""
from __future__ import annotations

import structlog

from handlers import RateLimitError
from storage.quota import quota_store

log = structlog.get_logger()


async def check_quota(api_key: str, token_limit_daily: int) -> None:
    """Raise RateLimitError if this key has reached its 24-hour token quota.

    Does not mutate any state — read-only check.
    Callers must ensure quota_store is initialised before calling this.
    """
    used = await quota_store.get_usage_24h(api_key)
    if used >= token_limit_daily:
        log.warning(
            "quota_exceeded",
            api_key=api_key[:16],
            used=used,
            limit=token_limit_daily,
        )
        raise RateLimitError("Daily token quota reached. Contact the administrator.")
    # Log approach at 80% threshold for observability
    if used >= token_limit_daily * 0.8:
        log.warning(
            "quota_approaching",
            api_key=api_key[:16],
            used=used,
            limit=token_limit_daily,
            pct=round(used / token_limit_daily * 100, 1),
        )


async def record_quota_usage(api_key: str, tokens: int) -> None:
    """Write token usage to the quota store after a response completes.

    tokens=0 is silently ignored — no DB write, no log.
    SQLite failures are caught and logged without propagating — the response
    has already been sent to the client, so a storage failure here must not
    surface as a 500.
    """
    if tokens <= 0:
        return
    try:
        await quota_store.record(api_key, tokens)
    except Exception:
        log.warning("quota_record_failed", api_key=api_key[:16], tokens=tokens, exc_info=True)
```

- [ ] **Step 2: Run all quota tests — expect PASS**

```bash
cd /teamspace/studios/this_studio/dikders
pytest tests/test_quota.py -v 2>&1 | tail -30
```

Expected: all 24 tests PASS.

- [ ] **Step 3: Run full suite**

```bash
pytest tests/ --ignore=tests/integration -q 2>&1 | tail -5
```

Expected: existing count + 24 new tests, all PASS.

- [ ] **Step 4: Commit**

```bash
git add middleware/quota.py
git commit -m "feat(middleware): add check_quota and record_quota_usage"
```

---

## Chunk 3: `config.py` — add `SHINWAY_QUOTA_ENABLED`

### Task 4: Add `quota_enabled` to `config.py`

**Files:**
- Modify: `config.py`

- [ ] **Step 1: Add the field**

In `config.py`, find the `# ── Rate limiting` section. Add a new `# ── Quota` section immediately after the rate limiting block (after `rate_limit_rpm_burst`):

```python
    # ── Quota ────────────────────────────────────────────────────────────────
    # When enabled, per-key token_limit_daily is enforced via a persistent
    # SQLite sliding window (quota.db) instead of the in-process counter.
    # Default off — set SHINWAY_QUOTA_ENABLED=true to activate.
    quota_enabled: bool = Field(default=False, alias="SHINWAY_QUOTA_ENABLED")
```

- [ ] **Step 2: Verify config loads**

```bash
cd /teamspace/studios/this_studio/dikders
python -c "from config import settings; print('quota_enabled:', settings.quota_enabled)"
```

Expected: `quota_enabled: False`

- [ ] **Step 3: Run full suite**

```bash
pytest tests/ --ignore=tests/integration -q 2>&1 | tail -5
```

Expected: all tests PASS (no regressions).

- [ ] **Step 4: Commit**

```bash
git add config.py
git commit -m "feat(config): add SHINWAY_QUOTA_ENABLED setting"
```

---

## Chunk 4: `app.py` — init/close `quota_store` in lifespan

### Task 5: Wire `quota_store` into `app.py` lifespan

**Files:**
- Modify: `app.py`

- [ ] **Step 1: Init `quota_store` in the startup block**

In `app.py`, in `_lifespan`, after the `key_store.init()` block:

```python
    from storage.quota import quota_store
    await quota_store.init()
    log.info("quota_store_started")
```

- [ ] **Step 2: Close `quota_store` in the teardown block**

In `_lifespan`, in the `finally` block, after `key_store.close()`:

```python
        from storage.quota import quota_store
        await quota_store.close()
        log.info("quota_store_closed")
```

Full `_lifespan` finally block after the change:

```python
    try:
        yield
    finally:
        from storage.keys import key_store
        await key_store.close()
        log.info("key_store_closed")
        from storage.quota import quota_store
        await quota_store.close()
        log.info("quota_store_closed")
        await response_store.close()
        log.info("response_store_closed")
        await _http_client.aclose()
        log.info("httpx_client_closed")
```

- [ ] **Step 3: Run full suite**

```bash
cd /teamspace/studios/this_studio/dikders
pytest tests/ --ignore=tests/integration -q 2>&1 | tail -5
```

Expected: all tests PASS.

- [ ] **Step 4: Commit**

```bash
git add app.py
git commit -m "feat(app): init and close quota_store in lifespan"
```

---

## Chunk 5: `middleware/auth.py` — wire `check_quota` into `check_budget`

### Task 6: Replace the in-process token counter with `check_quota`

**Files:**
- Modify: `middleware/auth.py`

The current in-process check in `check_budget` (lines 178-182):

```python
    # Per-key daily token limit (in-process counter, resets on restart)
    if rec and rec.get("token_limit_daily", 0) > 0:
        daily_tokens = await analytics.get_daily_tokens(api_key)
        if daily_tokens >= rec["token_limit_daily"]:
            raise RateLimitError("Daily token limit reached. Contact the administrator.")
```

Replace with:

```python
    # Per-key daily token limit — SQLite sliding window when quota enabled,
    # else falls back to in-process analytics counter (resets on restart).
    if rec and rec.get("token_limit_daily", 0) > 0:
        if settings.quota_enabled:
            from middleware.quota import check_quota
            await check_quota(api_key, rec["token_limit_daily"])
        else:
            daily_tokens = await analytics.get_daily_tokens(api_key)
            if daily_tokens >= rec["token_limit_daily"]:
                raise RateLimitError("Daily token limit reached. Contact the administrator.")
```

- [ ] **Step 1: Make the change**
- [ ] **Step 2: Verify import works**

```bash
cd /teamspace/studios/this_studio/dikders
python -c "from middleware.auth import check_budget; print('check_budget: OK')"
```

Expected: `check_budget: OK`

- [ ] **Step 3: Run full suite**

```bash
pytest tests/ --ignore=tests/integration -q 2>&1 | tail -5
```

Expected: all tests PASS.

- [ ] **Step 4: Commit**

```bash
git add middleware/auth.py
git commit -m "feat(auth): wire check_quota into check_budget for persistent sliding window quota"
```

---

## Chunk 6: Wire `record_quota_usage` into the pipeline

### Task 7: Call `record_quota_usage` after each completed response

**Files:**
- Modify: `pipeline/record.py`

After a response completes, the pipeline calls `_record()` in `pipeline/record.py` to log analytics. This is the right place to also write quota usage — tokens are already computed here.

- [ ] **Step 1: Read `pipeline/record.py` to find where `input_tokens` and `output_tokens` are available**

```bash
cd /teamspace/studios/this_studio/dikders
grep -n 'input_tokens\|output_tokens\|await analytics.record' pipeline/record.py
```

- [ ] **Step 2: Add `record_quota_usage` call inside `_record()`**

In `pipeline/record.py`, after the `await analytics.record(...)` call, add:

```python
    if settings.quota_enabled and api_key:
        from middleware.quota import record_quota_usage
        await record_quota_usage(api_key, tokens=input_tokens + output_tokens)
```

The full local variable context at that point already provides `input_tokens`, `output_tokens`, and `api_key` (via `params.api_key`). Confirm the exact variable names match by reading the file before editing.

- [ ] **Step 3: Run full suite**

```bash
cd /teamspace/studios/this_studio/dikders
pytest tests/ --ignore=tests/integration -q 2>&1 | tail -5
```

Expected: all tests PASS.

- [ ] **Step 4: Commit**

```bash
git add pipeline/record.py
git commit -m "feat(pipeline): call record_quota_usage after each completed response"
```

---

## Chunk 7: Final validation

### Task 8: Smoke test and full suite

**Files:** none new

- [ ] **Step 1: Import smoke test**

```bash
cd /teamspace/studios/this_studio/dikders
python -c "
import asyncio
from storage.quota import QuotaStore
from config import settings

async def _smoke():
    s = QuotaStore(':memory:')
    await s.init()
    await s.record('sk-test', 500)
    await s.record('sk-test', 300)
    total = await s.get_usage_24h('sk-test')
    assert total == 800, f'expected 800, got {total}'
    await s.prune_old()
    total_after = await s.get_usage_24h('sk-test')
    assert total_after == 800, 'prune_old removed current rows — wrong'
    await s.close()
    print('QuotaStore: OK')
    print('quota_enabled default:', settings.quota_enabled)
    assert settings.quota_enabled is False
    print('ALL OK')

asyncio.run(_smoke())
"
```

Expected: `ALL OK`

- [ ] **Step 2: Full test suite**

```bash
pytest tests/ --ignore=tests/integration -q 2>&1 | tail -5
```

Expected: existing count + 24 new quota tests, all PASS.

- [ ] **Step 3: Verify `SHINWAY_QUOTA_ENABLED=true` activates the path**

```bash
cd /teamspace/studios/this_studio/dikders
SHINWAY_QUOTA_ENABLED=true python -c "
from config import settings
print('quota_enabled:', settings.quota_enabled)
assert settings.quota_enabled is True
print('OK')
"
```

Expected: `quota_enabled: True`

- [ ] **Step 4: Update `UPDATES.md`**

Add a new session entry at the bottom of `UPDATES.md` documenting:
- `storage/quota.py` created — `QuotaStore` with `init`, `close`, `record`, `get_usage_24h`, `prune_old`
- `middleware/quota.py` created — `check_quota`, `record_quota_usage`
- `config.py` — added `quota_enabled` / `SHINWAY_QUOTA_ENABLED`
- `app.py` — init and close `quota_store` in `_lifespan`
- `middleware/auth.py` — replaced in-process analytics counter with `check_quota` call when `quota_enabled`
- `pipeline/record.py` — added `record_quota_usage` call after each completed response
- `tests/test_quota.py` — 24 new tests covering `QuotaStore` and middleware layer

- [ ] **Step 5: Commit and push**

```bash
git add UPDATES.md
git commit -m "docs: update UPDATES.md for quota middleware"
git push
```

---

## Summary

| Chunk | Task | File(s) | Tests |
|---|---|---|---|
| 1 | QuotaStore storage | `storage/quota.py` | `tests/test_quota.py` (17 store tests) |
| 2 | Quota middleware | `middleware/quota.py` | `tests/test_quota.py` (7 middleware tests) |
| 3 | Config flag | `config.py` | existing config tests |
| 4 | Lifespan wiring | `app.py` | existing app tests |
| 5 | check_budget wiring | `middleware/auth.py` | existing auth tests |
| 6 | Record usage | `pipeline/record.py` | existing pipeline tests |
| 7 | Final validation | — | 24 new + all existing |

**Sliding window semantics:**
- Window is always 24 hours (86400 s), rolling from the current moment
- Boundary condition: `window_start > now - 86400` (strict greater-than) — a row at exactly 24 h old is outside the window
- `prune_old()` uses `<= now - 86400` (less-than-or-equal) — consistent with the exclusive window boundary
- `prune_old()` is called inside `record()` every 100 insertions to amortise the DELETE cost without a background task

**Backwards compatibility:**
- `SHINWAY_QUOTA_ENABLED=false` (default) — existing in-process counter path in `check_budget` is unchanged
- `SHINWAY_QUOTA_ENABLED=true` — sliding window quota replaces the in-process counter for keys with `token_limit_daily > 0`
- Keys with `token_limit_daily = 0` are never checked regardless of the flag

**Zero new dependencies. Zero breaking changes.**
