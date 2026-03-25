# CursorClient.stream() Refactor Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Refactor `CursorClient.stream()` into smaller, focused helpers while preserving behavior (minor cleanup allowed if tests pass).

**Architecture:** Keep `CursorClient` as the owner of HTTP + credential logic; extract payload serialization, single-attempt streaming, SSE consumption, and suppression checks into private helpers. `stream()` remains the retry orchestrator.

**Tech Stack:** Python 3.11, FastAPI, httpx, orjson, pytest.

---

### Task 1: Add suppression-check tests

**Files:**
- Create: `tests/test_cursor_client.py`

**Step 1: Write the failing tests**

```python
import pytest
import httpx

from cursor.client import CursorClient
from handlers import CredentialError


@pytest.mark.asyncio
async def test_check_suppression_raises_when_tools_enabled():
    async with httpx.AsyncClient() as http_client:
        client = CursorClient(http_client)
        with pytest.raises(CredentialError):
            client._check_suppression(
                "I can only answer questions about Cursor.",
                has_tools=True,
            )


@pytest.mark.asyncio
async def test_check_suppression_noop_when_tools_disabled():
    async with httpx.AsyncClient() as http_client:
        client = CursorClient(http_client)
        client._check_suppression(
            "I can only answer questions about Cursor.",
            has_tools=False,
        )
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_cursor_client.py::test_check_suppression_raises_when_tools_enabled -v`
Expected: FAIL with `AttributeError: 'CursorClient' object has no attribute '_check_suppression'`

**Step 3: Write minimal implementation**

(Implemented in Task 2.)

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_cursor_client.py::test_check_suppression_raises_when_tools_enabled -v`
Expected: PASS

**Step 5: Commit**

```bash
git add tests/test_cursor_client.py cursor/client.py
git commit -m "test: cover suppression checks"
```

---

### Task 2: Add suppression helper + constants

**Files:**
- Modify: `cursor/client.py:30-320`
- Test: `tests/test_cursor_client.py`

**Step 1: Write minimal implementation**

Add module-level constant:
```python
_STREAM_ABORT_SIGNALS = [
    "i can only answer questions about cursor",
    "cannot act as a general-purpose assistant",
    "execute arbitrary instructions",
    "i am a support assistant",
    "as a cursor support",
    "my role is to assist with cursor",
    "i can only access /docs",
    "i can only help with cursor",
]
```

Add helper on `CursorClient`:
```python
def _check_suppression(self, acc_check: str, *, has_tools: bool) -> None:
    if not has_tools:
        return
    lower_check = acc_check.lower()
    if any(sig in lower_check for sig in _STREAM_ABORT_SIGNALS):
        log.warning("stream_suppression_abort", chars_received=len(acc_check))
        raise CredentialError(
            "Cursor support assistant identity detected in stream — retrying"
        )
```

**Step 2: Run tests**

Run: `pytest tests/test_cursor_client.py::test_check_suppression_raises_when_tools_enabled -v`
Expected: PASS

**Step 3: Commit**

```bash
git add cursor/client.py
git commit -m "refactor: extract suppression helper"
```

---

### Task 3: Extract payload serialization helper

**Files:**
- Modify: `cursor/client.py:163-210`

**Step 1: Update code**

Add a helper:
```python
async def _serialize_payload(self, payload: dict) -> bytes:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: orjson.dumps(payload))
```

Use it in `stream()`:
```python
payload_bytes = await self._serialize_payload(payload)
```

**Step 2: Run focused tests**

Run: `pytest tests/test_cursor_client.py -v`
Expected: PASS

**Step 3: Commit**

```bash
git add cursor/client.py
git commit -m "refactor: extract payload serialization"
```

---

### Task 4: Extract SSE consumption loop

**Files:**
- Modify: `cursor/client.py:211-290`

**Step 1: Update code**

Create `_consume_sse(response, anthropic_tools)` to contain:
- 64KB `aiter_bytes`
- buffer/line parsing
- first-token + idle timeouts
- suppression detection via `_check_suppression`
- yield deltas

**Step 2: Run focused tests**

Run: `pytest tests/test_cursor_client.py -v`
Expected: PASS

**Step 3: Commit**

```bash
git add cursor/client.py
git commit -m "refactor: extract SSE consumption"
```

---

### Task 5: Extract single-attempt stream logic

**Files:**
- Modify: `cursor/client.py:185-318`

**Step 1: Update code**

Create `_attempt_stream(payload_bytes, cred, anthropic_tools)`:
- build headers
- open `async with self._http.stream(...)`
- validate status
- delegate to `_consume_sse`
- mark success

`stream()` keeps retry loop and uses `_attempt_stream`.

**Step 2: Run focused tests**

Run: `pytest tests/test_cursor_client.py -v`
Expected: PASS

**Step 3: Commit**

```bash
git add cursor/client.py
git commit -m "refactor: extract single stream attempt"
```

---

### Task 6: Final verification

**Files:**
- Test: `tests/test_cursor_client.py`
- Optional: `tests/test_pipeline.py`

**Step 1: Run tests**

Run: `pytest tests/test_cursor_client.py -v`
Expected: PASS

Optional: `pytest tests/test_pipeline.py -v`
Expected: PASS

**Step 2: Commit (if needed)**

```bash
git status
```

---

## Notes
- User approved minor cleanup if tests pass.
- No worktree (user requested work in main).
