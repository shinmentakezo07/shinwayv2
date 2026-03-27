# cursor/ Tier A Reliability Fixes — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 6 correctness and silent-failure-mode bugs in `cursor/credentials.py`, `cursor/client.py`, and `cursor/sse.py` — blocking async lock, task leak on shutdown, missing non-streaming timeout, suppression check gap, silent buf discard, and missing log field.

**Architecture:** Three independent commit groups: (1) pure SSE logic fixes with no interface changes, (2) one atomic commit covering async lock migration + all callers + shutdown drain + call() timeout, (3) test updates. No new external dependencies.

**Tech Stack:** Python 3.12, asyncio, httpx, structlog, FastAPI, pytest-asyncio

**Spec:** `docs/superpowers/specs/2026-03-27-cursor-tier-a-fixes-design.md`

---

## Chunk 1: SSE fixes (#16, #18, #19)

Three pure-logic changes to `cursor/sse.py`. No interface changes. No caller updates needed. Safe to commit independently.

### Task 1: Write failing tests for SSE fixes

**Files:**
- Modify: `tests/test_sse.py`

- [ ] **Step 1: Open `tests/test_sse.py` and add the three new failing tests at the bottom**

```python
# ── Fix #16: suppression check on plain (non-tool) streams ──────────────────

async def test_suppression_fires_on_plain_stream():
    """iter_deltas raises CredentialError on suppression signal even when anthropic_tools=None.

    RED state note: before Fix #16 this test PASSES (no CredentialError raised, pytest.raises
    fails with 'DID NOT RAISE'). That is the expected RED failure — the guard is missing.
    """
    from unittest.mock import MagicMock
    from cursor.sse import iter_deltas
    from handlers import CredentialError

    # Build an SSE response whose first delta contains a known suppression phrase
    signal_text = "i can only answer questions about cursor"
    body = f'data: {{"delta": "{signal_text}"}}\ndata: [DONE]\n'.encode()

    resp = MagicMock()
    async def _aiter(chunk_size=65536):
        yield body
    resp.aiter_bytes = _aiter

    with pytest.raises(CredentialError):
        async for _ in iter_deltas(resp, anthropic_tools=None):
            pass


# ── Fix #19: matched signal logged ──────────────────────────────────────────

async def test_suppression_logs_matched_signal():
    """stream_suppression_abort warning includes matched_signal= field."""
    import structlog.testing
    from unittest.mock import MagicMock
    from cursor.sse import iter_deltas
    from handlers import CredentialError

    signal_text = "i am a support assistant"
    body = f'data: {{"delta": "{signal_text}"}}\ndata: [DONE]\n'.encode()

    resp = MagicMock()
    async def _aiter(chunk_size=65536):
        yield body
    resp.aiter_bytes = _aiter

    with structlog.testing.capture_logs() as captured:
        with pytest.raises(CredentialError):
            async for _ in iter_deltas(resp, anthropic_tools=None):
                pass

    abort_events = [e for e in captured if e.get("event") == "stream_suppression_abort"]
    assert abort_events, "Expected stream_suppression_abort log event"
    assert "matched_signal" in abort_events[0], (
        f"matched_signal missing from log: {abort_events[0]}"
    )
    assert abort_events[0]["matched_signal"] == signal_text


# ── Fix #18: residual buf logged at debug ────────────────────────────────────

async def test_residual_buf_logged_at_debug():
    """When bytes remain in buf after [DONE], a debug log is emitted."""
    from unittest.mock import MagicMock
    import structlog.testing
    from cursor.sse import iter_deltas

    # Normal delta line + [DONE] + trailing bytes in same chunk
    body = b'data: {"delta": "hello"}\ndata: [DONE]\nextra_trailing_bytes'

    resp = MagicMock()
    async def _aiter(chunk_size=65536):
        yield body
    resp.aiter_bytes = _aiter

    with structlog.testing.capture_logs() as captured:
        collected = []
        async for delta in iter_deltas(resp, anthropic_tools=None):
            collected.append(delta)

    assert collected == ["hello"]
    debug_events = [e for e in captured if e.get("event") == "sse_residual_bytes_after_done"]
    assert debug_events, "Expected sse_residual_bytes_after_done debug log"
    assert debug_events[0]["byte_count"] > 0
```

- [ ] **Step 2: Run the three new tests — all must FAIL**

```bash
cd /teamspace/studios/this_studio/dikders
source .venv/bin/activate
pytest tests/test_sse.py::test_suppression_fires_on_plain_stream tests/test_sse.py::test_suppression_logs_matched_signal tests/test_sse.py::test_residual_buf_logged_at_debug -v
```

Expected: 3 FAILED (suppression fires on plain stream — guard still on `anthropic_tools`; matched_signal not in log; residual bytes not logged)

---

### Task 2: Implement SSE fixes in `cursor/sse.py`

**Files:**
- Modify: `cursor/sse.py`

- [ ] **Step 1: Fix #16 + #19 — remove `anthropic_tools` gate and add `matched_signal` to log**

Note: this single edit applies both Fix #16 (de-gate suppression check) and Fix #19 (log matched signal) — both changes are in the same code block.

In `iter_deltas`, find this block (around line 129):
```python
                if anthropic_tools and len(acc_check) < 300:
                    acc_check += delta
                    lower_check = acc_check.lower()
                    if any(sig in lower_check for sig in _STREAM_ABORT_SIGNALS):
                        log.warning(
                            "stream_suppression_abort",
                            chars_received=len(acc_check),
                        )
                        raise CredentialError(
                            "Cursor support assistant identity detected in stream — retrying"
                        )
```

Replace with:
```python
                if len(acc_check) < 300:
                    acc_check += delta
                    lower_check = acc_check.lower()
                    matched = next(
                        (sig for sig in _STREAM_ABORT_SIGNALS if sig in lower_check),
                        None,
                    )
                    if matched:
                        log.warning(
                            "stream_suppression_abort",
                            matched_signal=matched,
                            chars_received=len(acc_check),
                        )
                        raise CredentialError(
                            "Cursor support assistant identity detected in stream — retrying"
                        )
```

- [ ] **Step 2: Fix #18 — log residual bytes before zeroing buf**

Find the `[DONE]` handler inside the `while b"\n" in buf:` loop (around line 122):
```python
            if isinstance(event, dict) and event.get("done"):
                buf = b""  # signal outer loop to stop
                break
```

Replace with:
```python
            if isinstance(event, dict) and event.get("done"):
                if buf:
                    log.debug("sse_residual_bytes_after_done", byte_count=len(buf))
                buf = b""
                break
```

- [ ] **Step 3: Run the three new tests — all must PASS**

```bash
pytest tests/test_sse.py::test_suppression_fires_on_plain_stream tests/test_sse.py::test_suppression_logs_matched_signal tests/test_sse.py::test_residual_buf_logged_at_debug -v
```

Expected: 3 PASSED

- [ ] **Step 4: Run the full SSE test file — no regressions**

```bash
pytest tests/test_sse.py -v
```

Expected: all existing tests PASS

- [ ] **Step 5: Commit**

```bash
git add cursor/sse.py tests/test_sse.py
git commit -m "fix(sse): suppression check on all streams, log matched signal, log residual buf"
```

---

## Chunk 2: Async lock + drain + call() timeout (atomic commit)

**CRITICAL:** All files in this chunk — `cursor/credentials.py`, `cursor/client.py`, `app.py`, `routers/internal.py` — must be modified and committed **in a single git commit**. Between completing `credentials.py` and completing `client.py`/`internal.py`, pool methods return unawaited coroutines. Do not commit partially.

### Task 3: Write failing tests for async lock and drain

**Files:**
- Modify: `tests/test_credentials.py`
- Modify: `tests/test_cursor_client.py`

- [ ] **Step 1: Add async pool method shape tests to `tests/test_credentials.py`**

Add at the bottom of the file:
```python
import asyncio
import pytest


# ── Fix #3: async pool methods ───────────────────────────────────────────────

def test_pool_next_returns_coroutine(monkeypatch):
    """After fix #3, pool.next() must return a coroutine (not a CredentialInfo directly)."""
    pool = _make_pool(monkeypatch, ["WorkosCursorSessionToken=token-a" + "x" * 80])
    result = pool.next()
    assert asyncio.iscoroutine(result), (
        f"pool.next() should return a coroutine, got {type(result)}"
    )
    # Clean up the unawaited coroutine to suppress RuntimeWarning
    result.close()


def test_pool_mark_error_returns_coroutine(monkeypatch):
    """pool.mark_error() must return a coroutine."""
    pool = _make_pool(monkeypatch, ["WorkosCursorSessionToken=token-a" + "x" * 80])
    cred = asyncio.get_event_loop().run_until_complete(pool.next())
    result = pool.mark_error(cred)
    assert asyncio.iscoroutine(result)
    result.close()


def test_pool_mark_success_returns_coroutine(monkeypatch):
    """pool.mark_success() must return a coroutine."""
    pool = _make_pool(monkeypatch, ["WorkosCursorSessionToken=token-a" + "x" * 80])
    cred = asyncio.get_event_loop().run_until_complete(pool.next())
    result = pool.mark_success(cred)
    assert asyncio.iscoroutine(result)
    result.close()


def test_pool_add_returns_coroutine(monkeypatch):
    """pool.add() must return a coroutine."""
    pool = _make_pool(monkeypatch, ["WorkosCursorSessionToken=token-a" + "x" * 80])
    result = pool.add("WorkosCursorSessionToken=token-new" + "x" * 80)
    assert asyncio.iscoroutine(result)
    result.close()


def test_pool_snapshot_returns_coroutine(monkeypatch):
    """pool.snapshot() must return a coroutine."""
    pool = _make_pool(monkeypatch, ["WorkosCursorSessionToken=token-a" + "x" * 80])
    result = pool.snapshot()
    assert asyncio.iscoroutine(result)
    result.close()


def test_pool_reset_all_returns_coroutine(monkeypatch):
    """pool.reset_all() must return a coroutine."""
    pool = _make_pool(monkeypatch, ["WorkosCursorSessionToken=token-a" + "x" * 80])
    result = pool.reset_all()
    assert asyncio.iscoroutine(result)
    result.close()
```

- [ ] **Step 1b: Update `_make_pool()` helper in `tests/test_cursor_client.py` to use `AsyncMock`**

The existing `_make_pool()` helper at the top of `tests/test_cursor_client.py` returns a `MagicMock` pool. After the credentials migration, `stream()` and `auth_me()` will `await` pool methods — awaiting a plain `MagicMock` raises `TypeError`. Update the helper **before** writing the new tests:

Find the current `_make_pool` function:
```python
def _make_pool(cred: CredentialInfo | None = None) -> MagicMock:
    """Build a minimal mock CredentialPool that satisfies CursorClient's interface."""
    pool = MagicMock()
    pool.next.return_value = cred
    pool.build_request_headers.return_value = {}
    pool.get_auth_headers.return_value = {}
    pool.mark_success = MagicMock()
    pool.mark_error = MagicMock()
    return pool
```

Replace with:
```python
def _make_pool(cred: CredentialInfo | None = None) -> MagicMock:
    """Build a minimal mock CredentialPool that satisfies CursorClient's interface.

    Uses AsyncMock for all pool methods that became async in fix #3
    (next, mark_error, mark_success). get_auth_headers and build_request_headers
    remain sync and use plain MagicMock.
    """
    pool = MagicMock()
    pool.next = AsyncMock(return_value=cred)
    pool.build_request_headers.return_value = {}
    pool.get_auth_headers.return_value = {}
    pool.mark_success = AsyncMock()
    pool.mark_error = AsyncMock()
    return pool
```

This change makes ALL existing `test_cursor_client.py` tests that use `_make_pool()` continue to pass after the credentials migration — `await pool.next()` on an `AsyncMock` works correctly.

- [ ] **Step 2: Add drain and call() timeout tests to `tests/test_cursor_client.py`**

Add at the bottom of the file:
```python
# ── Fix #11: drain_background_tasks ──────────────────────────────────────────

async def test_drain_background_tasks_empty_is_noop():
    """drain_background_tasks() returns immediately when no tasks are pending."""
    from cursor.client import drain_background_tasks, _background_tasks
    _background_tasks.clear()
    # Should not raise and should return promptly
    await drain_background_tasks(timeout=1.0)


async def test_drain_background_tasks_awaits_pending():
    """drain_background_tasks() awaits in-flight tasks before returning."""
    from cursor.client import drain_background_tasks, _background_tasks
    completed = []

    async def _slow():
        await asyncio.sleep(0.01)
        completed.append(True)

    task = asyncio.create_task(_slow())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    await drain_background_tasks(timeout=2.0)
    assert completed == [True], "Task should have completed before drain returned"


# ── Fix #15: call() timeout ───────────────────────────────────────────────────

async def test_call_timeout_raises():
    """call() raises asyncio.TimeoutError when stream stalls past timeout."""
    pool = _make_pool()
    mock_http = MagicMock()

    # Build a response that yields one byte and then hangs forever
    async def _hanging_aiter(chunk_size=65536):
        yield b'data: {"delta": "hi"}\n'
        await asyncio.sleep(9999)  # stall indefinitely

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {}
    mock_resp.aiter_bytes = _hanging_aiter
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)
    mock_http.stream = MagicMock(return_value=mock_resp)

    client = CursorClient(mock_http, pool=pool)
    with patch("cursor.client.asyncio.create_task"):
        with pytest.raises(asyncio.TimeoutError):
            await client.call(
                [{"role": "user", "content": "hi"}],
                "claude-3",
                timeout=0.05,  # 50 ms — expires before hang resolves
            )


async def test_auth_me_awaits_pool_next():
    """auth_me() correctly awaits pool.next() (AsyncMock) and returns account info."""
    from cursor.client import CursorClient

    pool = _make_pool()
    # pool.next is already AsyncMock via _make_pool — returns None
    # auth_me falls through to no-cookie path; we mock the HTTP response
    mock_http = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json = MagicMock(return_value={"email": "test@example.com"})
    mock_http.get = AsyncMock(return_value=mock_resp)

    client = CursorClient(mock_http, pool=pool)
    result = await client.auth_me()
    assert result == {"email": "test@example.com"}
    # Verify pool.next was awaited (AsyncMock records calls)
    pool.next.assert_awaited_once()
```

- [ ] **Step 3: Run the new tests — all must FAIL**

```bash
pytest tests/test_credentials.py::test_pool_next_returns_coroutine \
       tests/test_credentials.py::test_pool_mark_error_returns_coroutine \
       tests/test_credentials.py::test_pool_add_returns_coroutine \
       tests/test_credentials.py::test_pool_snapshot_returns_coroutine \
       tests/test_credentials.py::test_pool_reset_all_returns_coroutine \
       tests/test_cursor_client.py::test_drain_background_tasks_empty_is_noop \
       tests/test_cursor_client.py::test_drain_background_tasks_awaits_pending \
       tests/test_cursor_client.py::test_call_timeout_raises \
       tests/test_cursor_client.py::test_auth_me_awaits_pool_next -v
```

Expected: all FAILED (pool methods not yet async, `drain_background_tasks` doesn't exist, `call()` has no timeout, `auth_me` not awaiting pool)

---

### Task 4: Migrate `CredentialPool` to `asyncio.Lock`

**Files:**
- Modify: `cursor/credentials.py`

- [ ] **Step 1: Add `import asyncio` at the top of `cursor/credentials.py`**

Find the existing imports block (around line 18):
```python
import base64
import json
import logging
import secrets
import threading
import time
import uuid
```

Replace with:
```python
import asyncio
import base64
import json
import logging
import secrets
import time
import uuid
```

(Remove `threading` — it is only used for `threading.Lock`.)

- [ ] **Step 2: Replace `threading.Lock` with `asyncio.Lock` in `CredentialPool.__init__`**

Find:
```python
    def __init__(self) -> None:
        self._lock = threading.Lock()
```

Replace with:
```python
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
```

- [ ] **Step 3: Make `next()` async**

Find the full `def next(self)` method signature and body. Change `def next` → `async def next` and `with self._lock` → `async with self._lock`. The body is unchanged — only the `def` keyword and the context manager keyword change.

Before (signature + first lines):
```python
    def next(self) -> CredentialInfo | None:
        """Get the next healthy credential.
        ...
        """
        if not self._creds:
            return None

        now = time.time()
        with self._lock:
```

After:
```python
    async def next(self) -> CredentialInfo | None:
        """Get the next healthy credential.
        ...
        """
        if not self._creds:
            return None

        now = time.time()
        async with self._lock:
```

- [ ] **Step 4: Make `mark_error()` async**

Before:
```python
    def mark_error(self, cred: CredentialInfo) -> None:
        """Record a failed request against a credential."""
        with self._lock:
```

After:
```python
    async def mark_error(self, cred: CredentialInfo) -> None:
        """Record a failed request against a credential."""
        async with self._lock:
```

- [ ] **Step 5: Make `mark_success()` async**

Before:
```python
    def mark_success(self, cred: CredentialInfo) -> None:
        """Reset consecutive error counter after a successful request."""
        with self._lock:
```

After:
```python
    async def mark_success(self, cred: CredentialInfo) -> None:
        """Reset consecutive error counter after a successful request."""
        async with self._lock:
```

- [ ] **Step 6: Make `reset_all()` async**

Before:
```python
    def reset_all(self) -> None:
        """Manually reset all credentials to healthy."""
        with self._lock:
            self._reset_all_unsafe()
```

After:
```python
    async def reset_all(self) -> None:
        """Manually reset all credentials to healthy."""
        async with self._lock:
            self._reset_all_unsafe()
```

- [ ] **Step 7: Make `add()` async**

Before:
```python
    def add(self, cookie: str) -> bool:
        ...
        with self._lock:
```

After:
```python
    async def add(self, cookie: str) -> bool:
        ...
        async with self._lock:
```

- [ ] **Step 8: Make `snapshot()` async**

Before:
```python
    def snapshot(self) -> list[dict]:
        """Return pool status (cookie values are never exposed)."""
        now = time.time()
        with self._lock:
```

After:
```python
    async def snapshot(self) -> list[dict]:
        """Return pool status (cookie values are never exposed)."""
        now = time.time()
        async with self._lock:
```

NOTE: `_reset_all_unsafe()`, `get_auth_headers()`, and `build_request_headers()` do NOT use the lock — leave them as plain `def`. Do not touch them.

---

### Task 5: Update `cursor/client.py` — await pool calls + add drain + fix call()

**Files:**
- Modify: `cursor/client.py`

- [ ] **Step 1: Await `self._pool.next()` in `stream()`**

In `CursorClient.stream()`, find (around line 200):
```python
            _cred = cred or self._pool.next()
```

Replace with:
```python
            _cred = cred or await self._pool.next()
```

- [ ] **Step 2: Await `self._pool.mark_error()` and `self._pool.mark_success()` in `stream()`**

Find every call to `self._pool.mark_error(_cred)` and `self._pool.mark_success(_cred)` inside `stream()` — there are 5 mark_error calls and 1 mark_success call. Prepend `await` to each:

```python
# Before:
                    self._pool.mark_error(_cred)
# After:
                    await self._pool.mark_error(_cred)
```

```python
# Before:
                    self._pool.mark_success(_cred)
# After:
                    await self._pool.mark_success(_cred)
```

Do this for ALL occurrences in `stream()` — check lines ~222, ~237, ~247, ~267, ~277 for mark_error and ~230 for mark_success.

- [ ] **Step 3: Await `self._pool.next()` in `auth_me()`**

In `auth_me()` (around line 301):
```python
        _cred = cred or self._pool.next()
```

Replace with:
```python
        _cred = cred or await self._pool.next()
```

- [ ] **Step 4: Add `drain_background_tasks()` function**

After the `_background_tasks: set[asyncio.Task] = set()` line (around line 34), add:

```python
async def drain_background_tasks(timeout: float = 5.0) -> None:
    """Await all pending telemetry tasks with a timeout.

    Call during application shutdown before closing the httpx client
    to prevent RuntimeError: Event loop is closed on in-flight tasks.
    """
    if not _background_tasks:
        return
    await asyncio.wait(_background_tasks, timeout=timeout)
```

- [ ] **Step 5: Wrap `call()` in `asyncio.wait_for`**

Replace the existing `call()` method:
```python
    async def call(
        self,
        cursor_messages: list[dict],
        model: str,
        anthropic_tools: list[dict] | None = None,
        cred: CredentialInfo | None = None,
    ) -> str:
        """Non-streaming call — collects full response text."""
        chunks: list[str] = []
        async for delta in self.stream(
            cursor_messages, model, anthropic_tools, cred
        ):
            chunks.append(delta)
        return "".join(chunks)
```

With:
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

        Raises asyncio.TimeoutError if the stream stalls for longer than
        `timeout` seconds. Default matches StreamMonitor idle timeout.
        """
        async def _collect() -> str:
            chunks: list[str] = []
            async for delta in self.stream(cursor_messages, model, anthropic_tools, cred):
                chunks.append(delta)
            return "".join(chunks)

        return await asyncio.wait_for(_collect(), timeout=timeout)
```

---

### Task 6: Update `routers/internal.py` — await pool methods

**Files:**
- Modify: `routers/internal.py`

- [ ] **Step 1: Await `credential_pool.snapshot()` in `credential_status`**

Find (around line 191):
```python
        "credentials": credential_pool.snapshot(),
```

Replace with:
```python
        "credentials": await credential_pool.snapshot(),
```

- [ ] **Step 2: Await `credential_pool.reset_all()` in `credential_reset`**

Find (around line 201):
```python
    credential_pool.reset_all()
```

Replace with:
```python
    await credential_pool.reset_all()
```

- [ ] **Step 3: Await `credential_pool.add()` in the credentials add endpoint**

Find (around line 536):
```python
    added = credential_pool.add(cookie)
```

Replace with:
```python
    added = await credential_pool.add(cookie)
```

---

### Task 7: Update `app.py` — call drain before aclose()

**Files:**
- Modify: `app.py`

- [ ] **Step 1: Add drain call in lifespan `finally` block before `aclose()`**

Find the `finally:` block in `_lifespan` (around line 82). Find the line:
```python
        await _http_client.aclose()
        log.info("httpx_client_closed")
```

Insert the drain call immediately before it:
```python
        from cursor.client import drain_background_tasks
        await drain_background_tasks(timeout=5.0)
        log.info("telemetry_tasks_drained")
        await _http_client.aclose()
        log.info("httpx_client_closed")
```

---

### Task 8: Run new tests — all must pass, then commit atomically

**Files:** (verification only — no code changes)

- [ ] **Step 1: Run the new credential shape tests — all must PASS**

```bash
pytest tests/test_credentials.py::test_pool_next_returns_coroutine \
       tests/test_credentials.py::test_pool_mark_error_returns_coroutine \
       tests/test_credentials.py::test_pool_add_returns_coroutine \
       tests/test_credentials.py::test_pool_snapshot_returns_coroutine \
       tests/test_credentials.py::test_pool_reset_all_returns_coroutine -v
```

Expected: 5 PASSED

- [ ] **Step 2: Run drain and call() timeout tests — all must PASS**

```bash
pytest tests/test_cursor_client.py::test_drain_background_tasks_empty_is_noop \
       tests/test_cursor_client.py::test_drain_background_tasks_awaits_pending \
       tests/test_cursor_client.py::test_call_timeout_raises \
       tests/test_cursor_client.py::test_auth_me_awaits_pool_next -v
```

Expected: 4 PASSED

- [ ] **Step 3: Run the full test suite — 0 failures**

```bash
pytest tests/ -m 'not integration' -x -q
```

Expected: all existing tests pass. If any test fails because it calls pool methods synchronously, update that test to be `async def` and await the pool call.

- [ ] **Step 4: Fix any existing tests that call pool methods synchronously**

**In `tests/test_credentials.py`** — these tests call `pool.next()`, `pool.mark_error()`, and `pool.add()` synchronously on a real `CredentialPool` and must be converted:

- `test_credential_pool_round_robin_every_three_requests` — change `pool.next().index` → `(await pool.next()).index`; make test `async def`
- `test_credential_pool_skips_unhealthy_without_consuming_quota` — same; also `pool.mark_error(first)` → `await pool.mark_error(first)`; make test `async def`
- `test_credential_pool_auto_recovers_all_unhealthy_and_still_groups_by_three` — same pattern; also `pool.mark_error(cred)` → `await pool.mark_error(cred)`; make test `async def`
- `test_credential_pool_add_new_cookie` — `pool.add(new_cookie)` → `await pool.add(new_cookie)`; make test `async def`
- `test_credential_pool_add_duplicate_is_noop` — same
- `test_credential_pool_add_respects_max_15` — same

**In `tests/test_cursor_client.py`** — the `_make_pool()` helper update in Step 1b (above) already fixes all existing streaming tests that use `MagicMock` pool methods. No further changes needed to the existing streaming tests themselves — they will pass once `_make_pool()` returns `AsyncMock` for `next`, `mark_error`, and `mark_success`.

For each test in `test_credentials.py` converted to `async def`, `pytest-asyncio` with `asyncio_mode = auto` (already configured in this project's `pyproject.toml`/`pytest.ini`) picks them up automatically — no `@pytest.mark.asyncio` decorator needed.

- [ ] **Step 5: Atomic commit — all four files together**

```bash
git add cursor/credentials.py cursor/client.py app.py routers/internal.py \
        tests/test_credentials.py tests/test_cursor_client.py
git commit -m "fix(cursor): async pool lock, drain tasks on shutdown, call() timeout, await all pool callers"
```

---

## Chunk 3: Final validation

### Task 9: Full suite clean run

**Files:** (no changes — verification only)

- [ ] **Step 1: Run the complete unit test suite**

```bash
pytest tests/ -m 'not integration' -q
```

Expected: 0 failures. If anything fails, fix it before proceeding.

- [ ] **Step 2: Verify no `threading` import remains in `cursor/credentials.py`**

```bash
grep -n 'threading' cursor/credentials.py
```

Expected: no output.

- [ ] **Step 3: Verify all pool method callers in `routers/internal.py` are awaited**

```bash
grep -n 'credential_pool\.snapshot\|credential_pool\.reset_all\|credential_pool\.add' routers/internal.py
```

Expected: every match is preceded by `await`.

- [ ] **Step 4: Verify `drain_background_tasks` is called in `app.py`**

```bash
grep -n 'drain_background_tasks' app.py
```

Expected: at least one match inside the `finally:` block.

- [ ] **Step 5: Verify suppression check has no `anthropic_tools` gate**

```bash
grep -n 'anthropic_tools' cursor/sse.py
```

Expected: `anthropic_tools` appears only in the function signature line and `iter_deltas` docstring — NOT in the suppression check `if` condition.

---

## Execution Notes

- Run all tests from `/teamspace/studios/this_studio/dikders` with the venv active: `source .venv/bin/activate`
- `pytest-asyncio` must be installed and configured. Check with: `python -m pytest --co -q tests/test_cursor_client.py 2>&1 | head -5`
- If `asyncio_mode` is not set to `auto`, add `@pytest.mark.asyncio` to every new `async def test_*` function
- Do not skip the failing-test step (TDD). Running tests before implementing confirms the test actually exercises the code path
- Chunk 2 (Task 8 Step 5) is the most likely place for cascading failures — fix each broken test one at a time with `pytest -x`
