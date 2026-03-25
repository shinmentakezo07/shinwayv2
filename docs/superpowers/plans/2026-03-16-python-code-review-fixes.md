# Python Code Review Fixes — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development to implement this plan.

**Goal:** Fix all CRITICAL, HIGH, and MEDIUM issues found in the full-codebase Python code review — improving security, reliability, and async correctness without changing external behaviour.

**Architecture:** Surgical targeted fixes across 8 files. No refactoring of business logic. Each fix is independent and commits separately. Tests must pass after every commit.

**Tech Stack:** Python 3.12, FastAPI, asyncio, pydantic-settings, aiosqlite, structlog, httpx

---

## Chunk 1: CRITICAL Fixes

### Task 1: C1 — Hard-fail on default/missing master key

**Files:**
- Modify: `config.py` — remove default, add validator
- Modify: `app.py` — startup check

- [ ] **Step 1:** Read current `config.py:31` and `app.py` lifespan section

- [ ] **Step 2:** In `config.py`, change:
```python
# BEFORE
master_key: str = Field(default="sk-local-dev", alias="LITELLM_MASTER_KEY")

# AFTER
master_key: str = Field(default="sk-local-dev", alias="LITELLM_MASTER_KEY")
```
Keep the field default for local dev, but add a startup validator in `app.py` lifespan that raises `RuntimeError` if the key equals the placeholder in non-debug mode.

- [ ] **Step 3:** In `app.py` `_lifespan`, after `global _http_client`, add:
```python
if not settings.debug and settings.master_key == "sk-local-dev":
    raise RuntimeError(
        "LITELLM_MASTER_KEY is set to the default placeholder 'sk-local-dev'. "
        "Set a real key in .env or set DEBUG=true to suppress this check."
    )
```

- [ ] **Step 4:** Verify tests still pass:
```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/test_app.py -v -x 2>&1 | tail -20
```

- [ ] **Step 5:** Commit:
```bash
git add config.py app.py
git commit -m "fix: hard-fail on default master key in non-debug mode"
```

---

### Task 2: C2 — Replace `assert` with `raise RuntimeError`

**Files:**
- Modify: `app.py:34` — `assert _http_client is not None`
- Modify: `multirun.py:73` — `assert proc.stdout is not None`

- [ ] **Step 1:** In `app.py`, change:
```python
# BEFORE
assert _http_client is not None, "httpx client not initialised — app not started?"

# AFTER
if _http_client is None:
    raise RuntimeError("httpx client not initialised — call app startup before get_http_client()")
```

- [ ] **Step 2:** In `multirun.py`, change:
```python
# BEFORE
assert proc.stdout is not None

# AFTER
if proc.stdout is None:
    raise RuntimeError(f"subprocess stdout is None for port {port} — check Popen(stdout=PIPE)")
```

- [ ] **Step 3:** Run tests:
```bash
python -m pytest tests/test_app.py -v -x 2>&1 | tail -10
```

- [ ] **Step 4:** Commit:
```bash
git add app.py multirun.py
git commit -m "fix: replace assert guards with explicit RuntimeError raises"
```

---

### Task 3: C3 — Fix deprecated `asyncio.get_event_loop()` in hot path

**Files:**
- Modify: `cursor/client.py:181`

- [ ] **Step 1:** In `cursor/client.py`, change:
```python
# BEFORE
import msgspec.json as _msgjson
loop = asyncio.get_event_loop()
payload_bytes = await loop.run_in_executor(
    None, lambda: _msgjson.encode(payload)
)

# AFTER
import msgspec.json as _msgjson
loop = asyncio.get_running_loop()
payload_bytes = await loop.run_in_executor(
    None, lambda: _msgjson.encode(payload)
)
```

Also move `import msgspec.json as _msgjson` to the top of the file with other imports.

- [ ] **Step 2:** Verify import moved to top:
```bash
grep -n 'import msgspec' cursor/client.py
```
Expected: one import at top, none inside `stream()`.

- [ ] **Step 3:** Commit:
```bash
git add cursor/client.py
git commit -m "fix: replace deprecated get_event_loop() with get_running_loop() in client hot path"
```

---

### Task 4: C4 — Enable WAL mode on SQLite responses store

**Files:**
- Modify: `storage/responses.py:31-33`

- [ ] **Step 1:** In `storage/responses.py`, change `init()` to:
```python
async def init(self) -> None:
    self._db = await aiosqlite.connect(self._db_path)
    # WAL mode allows concurrent reads alongside writes — prevents lock contention
    await self._db.execute("PRAGMA journal_mode=WAL")
    await self._db.execute("PRAGMA synchronous=NORMAL")
    await self._db.execute(_CREATE_TABLE)
    await self._db.commit()
    log.info("responses_store_ready", path=self._db_path)
```

- [ ] **Step 2:** Run storage tests:
```bash
python -m pytest tests/test_responses_storage.py -v 2>&1 | tail -15
```

- [ ] **Step 3:** Commit:
```bash
git add storage/responses.py
git commit -m "fix: enable WAL mode on SQLite responses store to prevent write contention"
```

---

## Chunk 2: HIGH Fixes

### Task 5: H1 — Add debug logging to all silent `except Exception` blocks

**Files:**
- Modify: `cursor/credentials.py:67,104`
- Modify: `converters/to_cursor.py` (bare excepts in `_assistant_tool_call_text`)
- Modify: `tokens.py` (bare excepts at 132,137,155)

- [ ] **Step 1:** In `cursor/credentials.py`, change `_extract_workos_id`:
```python
# BEFORE
    except Exception:
        pass
    return ""

# AFTER
    except Exception:
        log.debug("workos_id_extraction_failed", exc_info=True)
    return ""
```

And in `_make_datadog_request_headers`:
```python
# BEFORE
    except Exception:
        return {}

# AFTER
    except Exception:
        log.debug("datadog_headers_failed", exc_info=True)
        return {}
```

- [ ] **Step 2:** Find all bare `except Exception: pass` or `except Exception: return` in tokens.py and add debug logging:
```bash
grep -n 'except Exception' tokens.py
```
For each: add `log.debug("<descriptive_name>", exc_info=True)` before the fallback return.

- [ ] **Step 3:** Run credentials tests:
```bash
python -m pytest tests/test_credentials.py -v 2>&1 | tail -10
```

- [ ] **Step 4:** Commit:
```bash
git add cursor/credentials.py tokens.py
git commit -m "fix: add debug logging to all silent exception handlers"
```

---

### Task 6: H2 — Replace `threading.Lock` with `asyncio.Lock` in AnalyticsStore

**Files:**
- Modify: `analytics.py`

**Note:** `AnalyticsStore` uses `threading.Lock`. Since it is accessed exclusively from async handlers, this can block the event loop under contention. Replace with `asyncio.Lock` and make `record()`, `snapshot()`, `snapshot_log()`, `get_spend()` into async methods.

- [ ] **Step 1:** Read the full `analytics.py` to understand all call sites.

- [ ] **Step 2:** Check all callers of `analytics.record()` and `analytics.snapshot()`:
```bash
grep -rn 'analytics\.' --include='*.py' .
```

- [ ] **Step 3:** Update `analytics.py`:
```python
import asyncio
# Remove: import threading

class AnalyticsStore:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._by_key: dict[str, dict] = {}
        self._log: deque = deque(maxlen=200)

    async def record(self, log_entry: RequestLog) -> None:
        async with self._lock:
            # ... same body ...

    async def snapshot(self) -> dict:
        async with self._lock:
            # ... same body ...

    async def snapshot_log(self, limit: int = 50) -> list:
        async with self._lock:
            return list(self._log)[:limit]

    async def get_spend(self, api_key: str) -> float:
        async with self._lock:
            return self._by_key.get(api_key, {}).get("estimated_cost_usd", 0.0)
```

- [ ] **Step 4:** Update all call sites to `await analytics.record(...)`, `await analytics.snapshot()`, etc.

- [ ] **Step 5:** Run full test suite (non-integration):
```bash
python -m pytest tests/ -m 'not integration' -x --ignore=tests/test_client_headers.py --ignore=tests/test_context.py -q 2>&1 | tail -20
```

- [ ] **Step 6:** Commit:
```bash
git add analytics.py
git commit -m "fix: replace threading.Lock with asyncio.Lock in AnalyticsStore to prevent event loop blocking"
```

---

### Task 7: H3 — Store `asyncio.create_task` reference to prevent GC

**Files:**
- Modify: `cursor/client.py:196`

- [ ] **Step 1:** Add a module-level task set to `cursor/client.py`:
```python
# Near top of file, after imports:
_background_tasks: set[asyncio.Task] = set()
```

- [ ] **Step 2:** Change the fire-and-forget call:
```python
# BEFORE
if _cred:
    asyncio.create_task(self._send_telemetry(_cred))

# AFTER
if _cred:
    _t = asyncio.create_task(self._send_telemetry(_cred))
    _background_tasks.add(_t)
    _t.add_done_callback(_background_tasks.discard)
```

- [ ] **Step 3:** Commit:
```bash
git add cursor/client.py
git commit -m "fix: store asyncio task reference to prevent GC of pending telemetry tasks"
```

---

### Task 8: H4 — Add error handling to `ResponseStore.save()` and `get()`

**Files:**
- Modify: `storage/responses.py`

- [ ] **Step 1:** Wrap `save()` body in try/except:
```python
async def save(self, response_id: str, payload: dict, api_key: str) -> None:
    """Persist a completed response. Idempotent (INSERT OR REPLACE).

    SQLite failures are logged and suppressed — the caller receives no error
    so the LLM response is still returned to the client.
    """
    if self._db is None:
        raise RuntimeError("ResponseStore not initialised — call init() first")
    try:
        await self._db.execute(
            "INSERT OR REPLACE INTO responses (id, api_key, payload, created_at) VALUES (?, ?, ?, ?)",
            (response_id, api_key, json.dumps(payload), int(time.time())),
        )
        await self._db.commit()
    except Exception:
        log.warning("response_store_save_failed", response_id=response_id, exc_info=True)
```

- [ ] **Step 2:** Wrap `get()` body in try/except:
```python
async def get(self, response_id: str, api_key: str | None = None) -> dict | None:
    if self._db is None:
        raise RuntimeError("ResponseStore not initialised — call init() first")
    try:
        # ... existing query logic ...
        return json.loads(row[0]) if row else None
    except Exception:
        log.warning("response_store_get_failed", response_id=response_id, exc_info=True)
        return None
```

- [ ] **Step 3:** Run storage tests:
```bash
python -m pytest tests/test_responses_storage.py -v 2>&1 | tail -15
```

- [ ] **Step 4:** Commit:
```bash
git add storage/responses.py
git commit -m "fix: wrap ResponseStore save/get in try/except — SQLite failures no longer 500 the client"
```

---

### Task 9: H5 — Move inline imports out of hot-path methods in `utils/context.py`

**Files:**
- Modify: `utils/context.py`

- [ ] **Step 1:** The file currently imports `from config import settings` and `from handlers import ContextWindowError` inside `check_preflight()`. Move both to the module top-level (they are already transitively safe to import at module load).

- [ ] **Step 2:** Confirm no circular imports:
```bash
python -c "from utils.context import ContextEngine" && echo OK
```
Expected: `OK` with no error.

- [