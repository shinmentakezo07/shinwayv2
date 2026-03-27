# cursor/ Tier A Reliability Fixes — Design Spec

**Date:** 2026-03-27
**Scope:** Six correctness and silent-failure-mode fixes across `cursor/credentials.py`, `cursor/client.py`, and `cursor/sse.py`.
**Session:** 155

---

## Problem Statement

Six issues in the `cursor/` package cause silent failures, resource leaks, or incomplete error detection in production:

1. **#3 — Blocking `threading.Lock` in async context** (`credentials.py`): `CredentialPool` uses `threading.Lock`. Every `with self._lock` call blocks the asyncio event loop thread for the lock's duration. Under concurrency, this creates a chokepoint on every credential rotation and health update.

2. **#11 — Background task leak on shutdown** (`client.py`): Telemetry tasks (`_send_telemetry`) are tracked in `_background_tasks` to prevent GC, but the set is never drained during application shutdown. If FastAPI's lifespan closes the httpx client before pending tasks complete, those tasks raise `RuntimeError: Event loop is closed`.

3. **#15 — Non-streaming `call()` has no timeout guard** (`client.py`): `call()` collects the full stream into a list. If the upstream stalls mid-stream (connection stays open, no bytes arrive), `call()` hangs indefinitely — `StreamMonitor` is only wired in the pipeline layer, not here.

4. **#16 — Suppression check skipped on non-tool streams** (`sse.py`): `if anthropic_tools and len(acc_check) < 300` — suppression detection only runs when `anthropic_tools` is truthy. The Support Assistant persona can appear in plain-text streams too, but those go unchecked.

5. **#18 — `buf` residual bytes silently discarded after `[DONE]`** (`sse.py`): When `[DONE]` is received, `buf = b""` is set and the inner loop breaks. Any bytes already buffered after the final `\n` (a partial line following `[DONE]`) are dropped without logging. Fragile if upstream behaviour changes.

6. **#19 — Suppression signal matched but not identified in logs** (`sse.py`): `stream_suppression_abort` logs `chars_received` but not which specific signal phrase matched. Debugging suppression-bypass regressions requires guessing which phrase fired.

---

## Non-Goals

- Weighted routing, per-credential rpm budgets, Prometheus metrics (Tier B)
- Health persistence, pool factory, cookie parsing improvements (Tier C)
- Any change to pipeline, converters, routers, or middleware
- Any change to the suppression phrase list itself

---

## Design

### Fix #3 — Replace `threading.Lock` with `asyncio.Lock`

**File:** `cursor/credentials.py`

`threading.Lock` is synchronous and blocks the event loop. Since the entire application is async, replace it with `asyncio.Lock`. All callers of `self._lock` are already inside async methods in the actual usage path (called from `CursorClient.stream()` which is async), so this is a safe drop-in replacement.

**Change:**
- `import asyncio` at top of file
- `self._lock = asyncio.Lock()` in `__init__`
- `_load()` is called from `__init__` (sync context at module init time) — `_load` does NOT use the lock, so no change needed there
- All lock-using methods (`next`, `mark_error`, `mark_success`, `reset_all`, `add`, `snapshot`) become `async def` and use `async with self._lock`
- `CredentialPool` callers in `client.py` (`self._pool.next()`, `self._pool.mark_error()`, `self._pool.mark_success()`) become `await self._pool.next()` etc.
- `snapshot()`, `reset_all()`, and `add()` callers in `routers/internal.py` also become awaited (three call sites: `credential_status` → `snapshot()`, `credential_reset` → `reset_all()`, `credential_add` → `add()`)
- `self._pool.next()` inside `auth_me()` in `client.py` also becomes `await self._pool.next()`
- `get_auth_headers()` and `build_request_headers()` do **not** use the lock and do **not** become async — they stay as plain `def`
- Python 3.12 note: `asyncio.Lock()` can be constructed outside a running event loop (the implicit loop deprecation was completed in 3.10) — module-level singleton construction at import time is safe

**Edge case:** `_reset_all_unsafe()` is called from within `next()` while holding the lock — it must remain sync (not acquire the lock again) since `asyncio.Lock` is not re-entrant. It already is sync, so no change needed there.

**Test impact:** Existing tests use `MagicMock` for the pool — mock signatures must add `AsyncMock` for the async methods.

---

### Fix #11 — Drain background tasks on shutdown

**File:** `cursor/client.py`, `app.py`

Add a module-level coroutine `drain_background_tasks(timeout: float = 5.0)` in `client.py`:

```python
async def drain_background_tasks(timeout: float = 5.0) -> None:
    """Await all pending telemetry tasks with a timeout.
    Call during application shutdown before closing the httpx client.
    """
    if not _background_tasks:
        return
    await asyncio.wait(_background_tasks, timeout=timeout)
```

In `app.py`'s `_lifespan` `finally` block, call `drain_background_tasks()` **before** `await _http_client.aclose()`:

```python
from cursor.client import drain_background_tasks
await drain_background_tasks(timeout=5.0)
await _http_client.aclose()
```

This ensures all in-flight telemetry fire-and-forget tasks complete (or are abandoned after 5 s) before the httpx client closes.

---

### Fix #15 — Add idle timeout to `call()` non-streaming path

**File:** `cursor/client.py`

`call()` currently has no timeout. Wrap the stream collection in `asyncio.wait_for`:

```python
async def call(
    self,
    cursor_messages: list[dict],
    model: str,
    anthropic_tools: list[dict] | None = None,
    cred: CredentialInfo | None = None,
    timeout: float = 120.0,
) -> str:
    """Non-streaming call — collects full response text.
    Raises asyncio.TimeoutError if the stream stalls for longer than `timeout` seconds.
    """
    async def _collect() -> str:
        chunks: list[str] = []
        async for delta in self.stream(cursor_messages, model, anthropic_tools, cred):
            chunks.append(delta)
        return "".join(chunks)

    return await asyncio.wait_for(_collect(), timeout=timeout)
```

The default `timeout=120.0` s matches the existing `StreamMonitor` idle timeout used in pipeline. Callers can override per-call.

---

### Fix #16 — Run suppression check on all streams, not just tool streams

**File:** `cursor/sse.py`

The current guard:
```python
if anthropic_tools and len(acc_check) < 300:
```

Change to always accumulate and always check:
```python
if len(acc_check) < 300:
    acc_check += delta
    lower_check = acc_check.lower()
    if any(sig in lower_check for sig in _STREAM_ABORT_SIGNALS):
        ...
        raise CredentialError(...)
```

The `acc_check` accumulation was already unconditional on `got_any`, but the check block was gated on `anthropic_tools`. Removing that gate means plain-text streams also get suppression detection in the first 300 chars. The cost is negligible — it is a substring scan on at most 300 chars per delta until the buffer fills.

The `anthropic_tools` parameter is still needed by `iter_deltas` callers (signature unchanged). It is simply no longer used to gate suppression.

---

### Fix #18 — Log residual bytes on `[DONE]`, don't silently drop

**File:** `cursor/sse.py`

Check whether `buf` has remaining content **before** zeroing it, then zero and break:

```python
if event.get("done"):
    if buf:  # bytes after the final \n before [DONE]
        log.debug("sse_residual_bytes_after_done", byte_count=len(buf))
    buf = b""
    break
```

This is a `debug`-level log — it fires only when the upstream sends unexpected trailing bytes, which should never happen in normal operation. It makes the silent discard visible without noise in production logs.

---

### Fix #19 — Log which suppression signal matched

**File:** `cursor/sse.py`

Replace the current suppression check:
```python
if any(sig in lower_check for sig in _STREAM_ABORT_SIGNALS):
    log.warning("stream_suppression_abort", chars_received=len(acc_check))
    raise CredentialError(...)
```

With a named-match version:
```python
matched = next((sig for sig in _STREAM_ABORT_SIGNALS if sig in lower_check), None)
if matched:
    log.warning(
        "stream_suppression_abort",
        matched_signal=matched,
        chars_received=len(acc_check),
    )
    raise CredentialError(...)
```

This adds `matched_signal=` to the structured log event, identifying exactly which phrase triggered the abort.

---

## Affected Files

| File | Changes |
|---|---|
| `cursor/credentials.py` | `threading.Lock` → `asyncio.Lock`; all lock-using methods become async |
| `cursor/client.py` | `drain_background_tasks()` added; `call()` wrapped in `wait_for`; pool method calls awaited |
| `app.py` | `drain_background_tasks()` called in lifespan `finally` before `aclose()` |
| `cursor/sse.py` | Suppression check de-gated; residual buf logging; matched signal logging |
| `tests/test_cursor_client.py` | `AsyncMock` for pool methods; `call()` timeout test; task drain test |
| `tests/test_sse.py` | New/updated tests for suppression on non-tool streams; signal name in log |
| `tests/test_credentials.py` | `AsyncMock`-aware pool tests |

---

## Dependency and Interface Impact

- `CredentialPool.next()`, `mark_error()`, `mark_success()`, `add()`, `snapshot()`, `reset_all()` become `async` — any caller must `await` them.
- `routers/internal.py` has three call sites that must be awaited: `credential_pool.snapshot()` in `credential_status`, `credential_pool.reset_all()` in `credential_reset`, and `credential_pool.add()` in `credential_add`.
- `cursor/client.py` — `auth_me()` calls `self._pool.next()` (line ~301) and must also be updated to `await self._pool.next()`.
- No external API or client-facing contract changes.
- No new dependencies.

---

## Testing Strategy

| Test | What it verifies |
|---|---|
| `test_pool_next_is_async` | `next()` is a coroutine |
| `test_pool_mark_error_is_async` | `mark_error()` is a coroutine |
| `test_pool_mark_success_is_async` | `mark_success()` is a coroutine |
| `test_pool_add_is_async` | `add()` is a coroutine |
| `test_pool_snapshot_is_async` | `snapshot()` is a coroutine |
| `test_pool_reset_all_is_async` | `reset_all()` is a coroutine |
| `test_drain_background_tasks_completes` | `drain_background_tasks()` awaits pending tasks before returning |
| `test_drain_empty_set_noop` | `drain_background_tasks()` is a no-op when no tasks pending |
| `test_call_timeout_raises` | `call()` raises `asyncio.TimeoutError` when stalled — use `asyncio.wait_for` mock or a stream that never yields with `timeout=0.01` |
| `test_auth_me_awaits_pool_next` | `auth_me()` correctly awaits `pool.next()` (AsyncMock) and returns account info |
| `test_credential_add_endpoint_awaits_pool` | `POST /internal/credentials` returns correct `added` bool, not a truthy coroutine object |
| `test_suppression_fires_on_plain_stream` | `iter_deltas` raises `CredentialError` on suppression signal even when `anthropic_tools=None` |
| `test_suppression_logs_matched_signal` | `stream_suppression_abort` log event contains `matched_signal=` field |
| `test_residual_buf_logged_at_debug` | debug log emitted when bytes remain in buf after `[DONE]` |

**Existing test migration:** Any existing test that calls `pool.next()`, `pool.mark_error()`, `pool.mark_success()`, `pool.add()`, `pool.snapshot()`, or `pool.reset_all()` synchronously must be updated to use `AsyncMock` and `await`. Specifically, tests in `test_credentials.py` that call `pool.next()` directly (e.g. round-robin tests) must become `async def` tests and `await pool.next()`. The helper `_make_pool()` in `test_cursor_client.py` must switch `MagicMock` to `AsyncMock` for all pool methods that become async.

---

## Rollout Order

1. **Commit 1:** `cursor/sse.py` — fixes #16, #18, #19. Pure logic, no interface changes, no caller updates. Codebase stays fully working after this commit.
2. **Commit 2 (atomic — all files in one commit):** `cursor/credentials.py` + `cursor/client.py` + `app.py` + `routers/internal.py` — fix #3, #11, #15. These four files **must land in the same commit**. Between completing `credentials.py` and completing `client.py`/`internal.py`, the pool methods return coroutines that are not awaited — the codebase would be broken. Committing them atomically prevents any broken intermediate state reaching the repo.
3. **Commit 3:** All test file updates — `test_cursor_client.py`, `test_credentials.py`, `tests/test_sse.py` (new suppression tests). Full suite must pass (0 failures) before this commit is made.

**Rule:** Never commit steps in Commit 2 partially. All four files or none.

---

## Success Criteria

- `CredentialPool` lock is `asyncio.Lock`; all lock-using methods are `async def`
- `drain_background_tasks()` is called in `app.py` lifespan teardown before `aclose()`
- `call()` raises `asyncio.TimeoutError` on stalled stream
- Suppression check fires on all streams (not just tool streams)
- `stream_suppression_abort` log contains `matched_signal=` field
- Residual bytes after `[DONE]` produce a `debug`-level log instead of silent discard
- Full test suite passes — 0 failures
- No new external dependencies introduced
