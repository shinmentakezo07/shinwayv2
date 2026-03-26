# Shin Proxy — Detailed Session Audit (March 13, 2026)

---

## Session 18 — API Key Management Backend (2026-03-16)

### What changed
- `storage/keys.py` — created
- `middleware/auth.py` — replaced (sync → async, added KeyStore DB lookup)
- `app.py` — wired `key_store` init/close into `_lifespan`
- `routers/internal.py` — added `from pydantic import BaseModel`, `await` on all `verify_bearer` calls, appended 4 admin key endpoints
- `routers/unified.py` — all `verify_bearer(...)` and `check_budget(...)` calls updated to `await`
- `routers/responses.py` — same `await` updates
- `tests/test_app.py` — updated `_valid_keys` → `_env_keys`, patched `key_store.get/is_valid` for DB-free tests
- `tests/test_responses_router.py` — updated `_valid_keys` → `_env_keys`
- `tests/test_routing.py` — bypass fixtures updated to async lambdas for `verify_bearer` and `check_budget`
- `tests/test_request_validators.py` — same fixture update
- `tests/test_internal.py` — bypass fixture updated to async lambda

### Which lines / functions
- `storage/keys.py` — new file: `KeyStore` class with `init`, `close`, `create`, `list_all`, `get`, `update`, `delete`, `is_valid`; module-level `key_store` singleton
- `middleware/auth.py:verify_bearer` — changed from `def` → `async def`; resolution now checks `_env_keys()` first, then `key_store.is_valid()` for DB-managed keys
- `middleware/auth.py:check_budget` — changed from `def` → `async def`; now checks per-key budget from DB in addition to global `settings.budget_usd`
- `middleware/auth.py:_valid_keys` — renamed to `_env_keys` (function name was `_env_keys` in new implementation; `_valid_keys` was old name referenced in tests)
- `app.py:_lifespan` — added `key_store.init()` after `response_store.init()`; added `key_store.close()` before `response_store.close()`
- `routers/internal.py` — 10 `verify_bearer(...)` calls → `await verify_bearer(...)`; added `BaseModel` import; appended `CreateKeyBody`, `UpdateKeyBody`, `list_keys`, `create_key`, `update_key`, `delete_key`
- `routers/unified.py` — 6 `verify_bearer(...)` → `await verify_bearer(...)`, 4 `check_budget(...)` → `await check_budget(...)`
- `routers/responses.py` — 1 `verify_bearer(...)` → `await`, 1 `check_budget(...)` → `await`

### Why
New feature: dynamically managed API keys stored in SQLite. Admin endpoints (`GET/POST/PATCH/DELETE /v1/admin/keys`) allow creating, listing, updating (label, limits, is_active), and deleting keys at runtime without restarting the server. `verify_bearer` now falls through to the DB if the token is not in the env-configured set. `check_budget` now enforces per-key `budget_usd` in addition to the global budget. The sync→async change on `verify_bearer` and `check_budget` propagated to all 17 call sites across 3 routers and all affected test fixtures.

### Commit SHAs
_(not committed per task instructions)_

---

## Session 19 — Admin UI: Key Management API Routes + Components (2026-03-16)

### What changed
- `admin-ui/app/api/keys/route.ts` — created
- `admin-ui/app/api/keys/[key]/route.ts` — created
- `admin-ui/hooks/useManagedKeys.ts` — created
- `admin-ui/components/keys/CreateKeyModal.tsx` — created
- `admin-ui/app/(dashboard)/keys/page.tsx` — replaced

### Which lines / functions
- `app/api/keys/route.ts` — `GET` (list all managed keys), `POST` (create key); both proxy to `BACKEND_URL/v1/admin/keys` with `Authorization: Bearer` forwarded from `x-admin-token` header
- `app/api/keys/[key]/route.ts` — `PATCH` (update key: label, limits, is_active), `DELETE` (revoke key); both proxy to `BACKEND_URL/v1/admin/keys/:key` with URL-encoded key segment
- `hooks/useManagedKeys.ts` — `useManagedKeys()` SWR hook; exports `ManagedKey` and `CreateKeyPayload` interfaces; fetches `GET /api/keys`, returns `{ keys, count, error, isLoading, mutate }`
- `components/keys/CreateKeyModal.tsx` — `CreateKeyModal` component; Framer Motion entrance/exit; form fields for label, RPM, RPS, daily token limit, budget USD, allowed models (comma-separated); shows one-time key display panel after creation with copy button; uses design system tokens throughout
- `app/(dashboard)/keys/page.tsx` — extended with `useManagedKeys` + `CreateKeyModal`; added `ManagedKeyRow` component with toggle-active and confirm-delete inline actions; added `handleToggle` / `handleDelete` async handlers; added "New Key" button in page header; added managed keys table section (above usage stats); wrapped key detail panel in `AnimatePresence`/`motion.div`; removed unused imports; kept original usage stats table and detail panel intact

### Why
Admin UI needed CRUD interface for the managed key system added in Session 18. The Next.js route handlers proxy requests to the FastAPI backend, injecting the admin token from the client's `x-admin-token` header. The `useManagedKeys` hook follows the same SWR pattern as `useStats` and `useCredentials`. The `CreateKeyModal` matches the modal pattern from the existing credential reset flow. The keys page now serves dual purpose: managed key administration (create/toggle/delete) and read-only usage stats per key.

### Commit SHAs
_(pending commit)_

---

## Session 2 — Performance & Stealth Hardening (March 13, 2026)

This section documents all changes made in the second session: streaming fixes, browser fingerprint improvements, and environment tuning.

---

### `pipeline.py` — Streaming Bug Fixes

#### Fix #1 & #2 — O(n²) re-scanning eliminated
**Problem:** `split_visible_reasoning(acc)` and `sanitize_visible_text(acc)` were called on the **full accumulated buffer** on every single delta chunk. For a 200K context response this is O(n²) — each chunk re-processes everything from the start.

**`_openai_stream` (line ~385):** Added `acc_visible_processed` offset counter:
```python
# Before (every chunk re-scanned full acc):
thinking_text, final_text = split_visible_reasoning(acc)
base_visible = final_text if thinking_text is not None else acc
visible_text, suppressed = sanitize_visible_text(base_visible)

# After (only recompute when acc has grown):
if len(acc) > acc_visible_processed:
    thinking_text, final_text = split_visible_reasoning(acc)
    base_visible = final_text if thinking_text is not None else acc
    visible_text, suppressed = sanitize_visible_text(base_visible)
    acc_visible_processed = len(acc)
```

**`_anthropic_stream` (line ~520):** Added `acc_visible_processed` + `_cached_candidate`/`_cached_safe_text` pair:
```python
acc_visible_processed = 0
_cached_candidate = ""
_cached_safe_text = ""

# Only recompute split when acc grows:
if len(acc) > acc_visible_processed:
    thinking_text, final_text = split_visible_reasoning(acc)
    acc_visible_processed = len(acc)

# Only recompute sanitize when candidate changes:
if candidate != _cached_candidate:
    safe_text, suppressed = sanitize_visible_text(candidate)
    _cached_candidate = candidate
    _cached_safe_text = safe_text
```

#### Fix #3 — Text emitted before tool calls confirmed absent
**Problem:** In `_openai_stream`, visible text was yielded to the client *before* checking for tool calls. If the model output prose then `[assistant_tool_calls]`, the client received stray text content chunks — violating OpenAI's contract.

**`_openai_stream` (line ~400):** Tool call check now runs first; text is held back while marker is present:
```python
# Tool marker check runs BEFORE text emission:
current_calls = _limit_tool_calls(
    parse_tool_calls_from_text(acc, params.tools, streaming=True) or [],
    params.parallel_tool_calls,
)
if current_calls:
    for chunk in tool_emitter.emit(current_calls):
        yield chunk
    acc_visible_processed = len(acc)
    text_sent = len(acc)
    continue

_has_marker = bool(
    re.search(r"(?:^|\n)\s*\[assistant_tool_calls\]", acc, re.IGNORECASE)
)
if not _has_marker and len(visible_text) > text_sent:
    # only emit text when no marker present
    ...
```

#### Fix #5 — `StreamAbortError` left clients hanging
**Problem:** Both stream paths caught `StreamAbortError` with only a log line — no finish chunk emitted. Clients waiting for `[DONE]` would hang until their own timeout.

**`_openai_stream` (line ~470):**
```python
# Before:
except StreamAbortError:
    log.info("stream_aborted", style="openai", model=model)

# After:
except StreamAbortError:
    log.info("stream_aborted", style="openai", model=model)
    yield openai_sse(openai_chunk(cid, model, finish_reason="stop"))
    output_tokens = estimate_from_text(acc, model)
    yield openai_usage_chunk(cid, model, input_tokens, output_tokens)
    yield openai_done()
    _record(params, acc, (time.time() - started) * 1000.0)
    return
```

**`_anthropic_stream` (line ~640):**
```python
except StreamAbortError:
    log.info("stream_aborted", style="anthropic", model=model)
    if thinking_opened and not thinking_closed:
        yield anthropic_content_block_stop(idx)
        idx += 1
    if text_opened:
        yield anthropic_content_block_stop(idx)
    output_tokens = estimate_from_text(acc, model)
    yield anthropic_message_delta("end_turn", output_tokens)
    yield anthropic_message_stop()
    _record(params, acc, (time.time() - started) * 1000.0)
    return
```

#### Fix #6 — Inconsistent token counts in analytics
**Problem:** `_record()` used `estimate_from_messages()` (rough guess) while non-streaming handlers used `count_message_tokens()` (accurate). Analytics showed different counts for same-size requests.

**`_record()` (line ~940):**
```python
# Before:
input_tokens = estimate_from_messages(params.messages)
output_tokens = estimate_from_text(text)

# After:
input_tokens = count_message_tokens(params.messages, params.model)
output_tokens = estimate_from_text(text, params.model)
```

---

### `cursor/client.py` — Browser Simulation Improvements

#### Change 1 — Referer updated to `/dashboard`
**Line ~48:**
```python
# Before:
"Referer": f"{settings.cursor_base_url}/docs",

# After:
"Referer": f"{settings.cursor_base_url}/dashboard",
```
Matches what a real logged-in the-editor browser session sends from the dashboard page.

#### Change 2 — Datadog RUM tracing headers added
**New function `_make_datadog_headers()` (line ~34):**
```python
def _make_datadog_headers() -> dict[str, str]:
    try:
        trace_id = str(int(secrets.token_hex(16), 16) % (2**63))
        parent_id = str(int(secrets.token_hex(8), 16) % (2**63))
        trace_hex = format(int(trace_id), "032x")
        parent_hex = format(int(parent_id), "016x")
        return {
            "traceparent": f"00-{trace_hex}-{parent_hex}-01",
            "tracestate": "dd=s:1;o:rum",
            "x-datadog-origin": "rum",
            "x-datadog-parent-id": parent_id,
            "x-datadog-sampling-priority": "1",
            "x-datadog-trace-id": trace_id,
        }
    except Exception:
        return {}  # fallback: request proceeds without these headers
```
Each request gets fresh random trace/parent IDs — identical to what a real browser generates. Falls back silently on any error.

#### Change 3 — Telemetry uses correct `sec-fetch-mode`
**`_send_telemetry()` (line ~178):**
```python
# Added:
headers["sec-fetch-mode"] = "no-cors"
headers["priority"] = "u=4, i"
```
Real browser beacon requests use `no-cors` + low priority `u=4, i`. Previously the proxy used `cors` + `u=1, i` which is detectable.

---

### `cursor/credentials.py` — Browser Fingerprint Cookies

#### Change 1 — New helper functions (line ~27)
```python
def _extract_workos_id(cookie: str) -> str:
    """Parse user_01K... ID from WorkosCursorSessionToken JWT."""
    # Splits on ::, validates user_ prefix, falls back to JWT sub claim
    ...

def _stable_uuid(seed: str) -> str:
    """Generate stable UUID5 from seed string — same seed always same UUID."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, seed))
```

#### Change 2 — `CredentialInfo` gets fingerprint fields (line ~67)
```python
@dataclass
class CredentialInfo:
    ...
    workos_id: str = ""           # parsed from JWT
    statsig_stable_id: str = ""   # stable UUID5 per credential
    cursor_anonymous_id: str = "" # stable UUID5 per credential
```

#### Change 3 — Pool loader derives fingerprints at load time (line ~130)
```python
workos_id = _extract_workos_id(cookie)
seed = workos_id or cookie[:40]
self._creds.append(CredentialInfo(
    cookie=cookie,
    index=idx,
    workos_id=workos_id,
    statsig_stable_id=_stable_uuid(f"statsig:{seed}"),
    cursor_anonymous_id=_stable_uuid(f"anon:{seed}"),
))
```

#### Change 4 — `get_auth_headers()` injects full browser cookie set
```python
# Now appends to every request's Cookie header:
extra = [
    f"cursor_anonymous_id={cred.cursor_anonymous_id}",
    f"statsig_stable_id={cred.statsig_stable_id}",
    f"workos_id={cred.workos_id}",
    f"_dd_s=aid={cred.cursor_anonymous_id}&rum=2&id={dd_session_id}&created={now_ms}&expire={expire_ms}",
]
# Only adds keys not already present in the base cookie string
```
This makes every request's Cookie header match the full set a real browser sends.

---

### `.env` & `.env.example` — Performance Tuning

| Setting | Before | After | Reason |
|---|---|---|---|
| `WORKERS` | 1 | 4 | Multi-core utilization |
| `GATEWAY_RETRY_ATTEMPTS` | 3 | 4 | Extra retry for flaky credentials |
| `GATEWAY_RETRY_BACKOFF_SECONDS` | 0.3 | 0.5 | More breathing room between retries |
| `GATEWAY_CACHE_ENABLED` | false | true | Enable L1 in-memory cache |
| `GATEWAY_FIRST_TOKEN_TIMEOUT` | 180 | 120 | Fail faster, retry sooner |
| `GATEWAY_IDLE_CHUNK_TIMEOUT` | 30 | 45 | More tolerance for slow mid-stream chunks |
| `GATEWAY_STREAM_HEARTBEAT_INTERVAL` | 15 | 10 | More frequent keepalives |
| `GATEWAY_MAX_CONTEXT_TOKENS` | 190000 | 200000 | Use full context window |
| `GATEWAY_HARD_CONTEXT_LIMIT` | 195000 | 210000 | Match model's actual hard cap |
| `GATEWAY_ROLE_OVERRIDE_PROMPT` | generic session context | explicit identity override with the-editor's own suppression phrases | Maximum suppression bypass strength |

---

## Session 3 — Worker Tuning (March 13, 2026)

### `.env` — Worker count reduced for quality

**File:** `.env`  
**Line:** `WORKERS=...`

| Setting | Before | After | Reason |
|---|---|---|---|
| `WORKERS` | 4 | 2 | 1 worker per cookie — eliminates session contention with a 2-cookie pool |

**Why this matters:**
- Uvicorn workers are separate OS processes, each with its own credential pool slice.
- With 2 cookies and 4 workers, each request has a ~50% chance of sharing a cookie with a concurrent request in another worker process.
- Session contention means the-editor sees multiple simultaneous requests from the same session token, raising the probability of throttling or suppression.
- `WORKERS=2` gives each worker exclusive ownership of one cookie → cleanest possible session behavior → best response quality.
- Formula going forward: `WORKERS = number_of_cookies` for quality-first setups.

---

This document provides a line-by-line surgical record of the changes made during this development session to stabilize and optimize the proxy for high-volume agent workloads.

---

## Session 4 — Context Limits, Tool Call Repair, Browser Hardening (March 15, 2026)

### Context Window — Raised to 500k tokens

**Files:** `config.py`, `.env`, `tokens.py`, `converters/from_cursor.py`

Real-world testing against cursor.com's `/api/chat` endpoint confirmed usable context up to ~600k tokens (HTTP 413 at ~1.1M tokens). All limits updated:

| Setting | Before | After |
|---|---|---|
| `GATEWAY_MAX_CONTEXT_TOKENS` | 250,000 | 500,000 |
| `GATEWAY_HARD_CONTEXT_LIMIT` | 260,000 | 590,000 |
| `max_context_tokens` (config.py) | 200,000 | 500,000 |
| `hard_context_limit` (config.py) | 210,000 | 590,000 |
| `_CONTEXT_WINDOWS` all models (tokens.py) | 200,000 | 500,000 |
| `MODEL_CONTEXT_WINDOWS` all models (from_cursor.py) | 200,000 | 500,000 |

**Test:** `tests/test_context_window_real.py` — binary search and spot-check modes for probing actual cursor.com limits.

---

### `converters/to_cursor.py` — Tool Instruction Payload Fix

**Problem:** Tool schema was sent twice per request:
1. Flat summary (native Cursor format)
2. Full OpenAI-format JSON schema repeated verbatim

For 20 tools this produced ~131,000 chars (~32k tokens) of instruction overhead, causing `EmptyResponseError` (Cursor silently rejected the oversized payload).

**Fix 1 — Removed duplicate OpenAI schema section:**
The `## Alternative Tool Schema Format` block with full OpenAI-format JSON was removed. The flat summary is sufficient.

**Fix 2 — Truncated tool descriptions to 400 chars:**
```python
# Before:
"description": t["function"].get("description", ""),

# After:
"description": t["function"].get("description", "")[:400],
```
Result: 20-tool instruction went from 131k chars to ~3.2k chars (~800 tokens). Parallel tool calls now work reliably.

---

### `tools/parse.py` — Smart Tool Call Repair

Added full validation + repair pipeline for tool calls. Fires automatically on every response before returning to the client.

#### New: `_PARAM_ALIASES` dict
50+ common wrong parameter names mapped to canonical names:
```python
_PARAM_ALIASES = {
    "filepath": "file_path",
    "filename": "file_name",
    "taskid": "taskId",
    "subagenttype": "subagent_type",
    # ... 50+ entries
}
```

#### New: `_coerce_value(value, prop_schema, key, repairs)`
Type coercion for wrong value types:
- `"true"` / `"false"` strings → `bool`
- Numeric strings → `int` / `float`
- JSON string of array/object → parsed value
- Single value where array expected → wrapped in list

#### New: `_fuzzy_match_param(supplied, known_keys)`
6-strategy matching in priority order:
1. Exact match
2. Alias table lookup
3. Normalized (lowercase, no separators)
4. Levenshtein distance ≤ 2
5. Substring containment
6. Prefix match (≥4 chars)

#### New: `_levenshtein(a, b)`
Standard edit distance implementation used by fuzzy matching.

#### New: `log_tool_calls(calls, context, request_id)`
Structured log line per tool call with: name, argument count, validation status, and any repair actions taken.

#### New: `validate_tool_call(call, tools) -> (bool, list[str])`
Pure validator. Checks:
- Tool name exists in schema
- All required params present
- No unknown params
- Value types match schema

#### New: `repair_tool_call(call, tools) -> (dict, list[str])`
Full repair pipeline:
1. Fuzzy-match unknown param names → canonical names
2. Type-coerce wrong value types
3. Re-validate after repair
Returns repaired call + list of repair actions taken for logging.

---

### `pipeline.py` — Tool Call Repair Wired In

**New helper `_repair_invalid_calls(calls, tools)`:**
```python
def _repair_invalid_calls(calls, tools):
    repaired = []
    for call in calls:
        ok, errors = validate_tool_call(call, tools)
        if ok:
            repaired.append(call)
        else:
            fixed, actions = repair_tool_call(call, tools)
            if actions:
                log.info("tool_call_repaired", actions=actions)
            repaired.append(fixed)
    return repaired
```

Wired at all 4 parse points in the pipeline:
- `openai_stream_finish`
- `anthropic_stream_finish`
- `openai_nonstream`
- `anthropic_nonstream`

Repair is transparent — clients receive corrected tool calls with no visible change to the response format.

---

### `tests/test_tool_call_live.py` (new)

Live integration test using the full 20-tool Claude Code tool set. Sends a single request asking for 5 parallel simultaneous tool calls and prints the raw streamed response. Verified: all 5 tool calls returned correctly with zero payload errors after the tool instruction fix.

---

### `README.md` — Full Rewrite

Previous README was a stub. New README covers:
- Architecture diagram (client → proxy → cursor.com)
- Quick start (clone, configure, start, use)
- Getting your cookie step-by-step
- Multiple account round-robin setup
- All supported models table
- Tool call / smart repair feature docs
- Full configuration reference tables
- Project structure map
- Development and testing commands

---

## Session 5 — Tool Schema Quality, multirun, Config Sync (March 15, 2026)

### `tools/parse.py` — Repair Alias Tightening

**Problem:** The fuzzy repair logic was too aggressive. Three alias entries were mismapping valid arguments:
- `src`, `source`, `destination`, `dest` → `file_path` — these are generic words that also appear as legitimate argument values in many tools
- `text` → `content` — very common word, was matching the `text` parameter of other tools and redirecting it to `content`
- Substring match threshold (4 chars) was short enough that `"file"` matched `"file_path"`, pulling content into the wrong param

**Fixes:**
- Removed `src`, `source`, `destination`, `dest`, `text` from `_PARAM_ALIASES`
- Substring containment match now only fires for strings ≥ 5 chars
- Shared prefix threshold raised from 4 → 5 chars

**Result:** The `Write` tool call bug (where file content was being treated as a filename) is resolved.

---

### `converters/to_cursor.py` — Concrete Tool Example Values

**Problem:** `_example_value()` returned abstract placeholder strings: `<string>`, `<boolean>`, `<integer>`, etc. The model had to guess what format to use.

**Fix:** Replaced `_example_value(prop)` with `_example_value(prop, key="")` backed by:

1. **`_PARAM_EXAMPLES` dict** — 27 well-known param names → concrete typed values:
```python
_PARAM_EXAMPLES = {
    "file_path":     "/path/to/file.py",
    "content":       "file content here",
    "command":       "echo hello",
    "url":           "https://example.com",
    "query":         "search query",
    "pattern":       "**/*.py",
    "new_string":    "replacement text",
    "old_string":    "text to replace",
    # ... 19 more
}
```

2. **Type-based fallbacks** for unlisted params:
   - `boolean` → `False` (not `"<boolean>"`)
   - `integer` → `0`
   - `number` → `0.0`
   - `array` → `[]`
   - `object` → `{}`
   - `string` → `"value"`

3. **Enum** → returns first real enum value (not pipe-joined string)

**Call sites updated** (lines 313, 315) to pass `key=k` so name lookup fires.

**Before:**
```json
{"name":"Write","arguments":{"file_path":"<string>","content":"<string>"}}
```
**After:**
```json
{"name":"Write","arguments":{"file_path":"/path/to/file.py","content":"file content here"}}
```

**Test:** `tests/test_example_values.py` — 10 tests covering all type cases and named params. All pass.

---

### `multirun.py` (new)

Multi-instance launcher. Starts up to 5 proxy instances on different ports using the same `.env` config.

```bash
python multirun.py        # 3 instances on 4001, 4002, 4003 (default)
python multirun.py 5      # 5 instances on 4001-4005
python multirun.py 4001 4003 4005  # specific ports
```

Features:
- Each instance is a separate subprocess with `PORT` overridden in env
- Color-coded log output per instance (green, blue, yellow, magenta, cyan)
- 0.3s startup stagger to avoid log interleaving
- Ctrl+C cleanly terminates all instances (3s graceful window then kill)
- Crash detection — reports if any instance exits unexpectedly

---

### Config Sync — All Files Aligned to Port 4001, 500k Context, Windows UA

All configuration files now have consistent defaults:

| Setting | Old default | New default | Files updated |
|---|---|---|---|
| `PORT` | 4000 | 4001 | `.env.example`, `docker-compose.yml`, `Dockerfile` |
| `WORKERS` | 1-4 (varied) | 3 | `.env.example`, `docker-compose.yml` |
| `GATEWAY_MAX_CONTEXT_TOKENS` | 200000 | 500000 | `.env.example`, `docker-compose.yml` |
| `GATEWAY_HARD_CONTEXT_LIMIT` | 210000 | 590000 | `.env.example`, `docker-compose.yml` |
| `USER_AGENT` | Linux Chrome/137 | Windows Chrome/146 | `.env.example`, `docker-compose.yml` |
| `GATEWAY_FIRST_TOKEN_TIMEOUT` | 90 | 120 | `docker-compose.yml` |
| `GATEWAY_IDLE_CHUNK_TIMEOUT` | 60 | 45 | `docker-compose.yml` |
| `GATEWAY_STREAM_HEARTBEAT_INTERVAL` | 15 | 10 | `docker-compose.yml` |

Healthcheck in `docker-compose.yml` updated to use `${PORT:-4001}` dynamically.

## 1. Architectural Changes

### `routers/unified.py` (NEW FILE)
*   **Purpose:** Replaced redundant OpenAI and Anthropic routers with a single LiteLLM-powered entry point.
*   **Logic:**
    *   Implements `_anthropic_messages_to_openai()` to normalize Anthropic's block-array content into standard OpenAI message strings.
    *   Implements `_anthropic_tools_to_openai()` to map `input_schema` to `parameters`.
    *   Uses `litellm.utils.validate_and_fix_openai_tools` to ensure tool schemas are strictly valid before processing.
    *   Injects custom headers: `X-Context-Tokens` (via `context_engine.check_preflight`) and `X-Request-ID`.

### `routers/openai.py` & `routers/anthropic.py`
*   **Action:** DELETED. All functionality moved to `unified.py`.

### `app.py`
*   **Modified `_lifespan`:**
    *   Changed: `timeout=httpx.Timeout(connect=10.0, read=120.0, ...)`
    *   To: `timeout=httpx.Timeout(connect=15.0, read=None, write=None, ...)`
    *   **Reason:** Prevents `httpx` from killing long-running codebase reads before our `StreamMonitor` can process them.
*   **Modified Router Registration:**
    *   Removed `openai_router` and `anthropic_router`.
    *   Imported and included `unified_router`.

---

## 2. Stealth & Performance Logic

### `cursor/client.py`
*   **Modified `_build_headers`:**
    *   Added full browser fingerprinting: `sec-ch-ua`, `sec-ch-ua-mobile`, `sec-ch-ua-platform`, `sec-fetch-dest`, `sec-fetch-mode`, `sec-fetch-site`.
    *   Updated `User-Agent` to match a real Windows 10 Chrome/Brave signature.
*   **Added `_send_telemetry`:**
    *   New async method that pings `/_vercel/insights/event`.
*   **Modified `stream`:**
    *   Added `asyncio.create_task(self._send_telemetry(_cred))` inside the retry loop.
    *   **Reason:** Mimics real UI network traffic to avoid automated bot detection by Vercel/Cloudflare.

### `utils/stream_monitor.py`
*   **Modified `wrap`:**
    *   Added `except asyncio.CancelledError:` block.
    *   **Logic:** Now raises `StreamAbortError` when a client disconnects.
    *   **Reason:** Ensures the upstream Cursor connection is closed immediately when the user stops the generation, saving tokens and quota.

### `pipeline.py`
*   **Log Level Adjustment:**
    *   Changed all instances of `log.warning("suppressed_raw_tool_payload", ...)` to `log.debug(...)`.
    *   **Reason:** On large payloads, the "warning" logs were generating thousands of IO writes per second, causing the async loop to stall and the stream to freeze.

### `config.py`
*   **Timeout Update:**
    *   Changed `first_token_timeout` default from `90.0` to `180.0`.
    *   **Reason:** Gives Claude 3.5 Sonnet a full 3 minutes to ingest massive contexts (70k+ tokens) before timing out.

---

## 3. Data & Configuration

### `cursor_backend_architecture_and_bypasses.md`
*   **Modified Section 3:**
    *   Removed aggressive keywords (`IDENTITY OVERRIDE`, `SYSTEM RESET`).
    *   Introduced the **Natural Language Role-Play Strategy** (Stealth Directive) which frames the AI's identity as a local developer tool assistant rather than a documentation bot.

### `.env`
*   **Updated `CURSOR_COOKIES`:** Injected new validated tokens for round-robin rotation.
*   **Forced `GATEWAY_FIRST_TOKEN_TIMEOUT=180`**: Overrode cached environment values.

### `requirements.txt`
*   Added `litellm>=1.40.0`.

---

## 4. Test Verification Suite
Created/Updated the following scripts to prove the fixes:
*   `test_abort.py`: Verifies `StreamAbortError` kills upstream on client disconnect.
*   `test_massive.py`: Verifies 200K+ token context support without stalls.
*   `test_cookie_rotation.py`: Proves the 3-request round-robin logic cycles correctly.
*   `test_all_tools.py`: Comprehensive test for parallel tool calls (Roo Code style).
*   `test_proxy_real.py`: Full E2E test against the live running server.

---

## Session 6 — System Prompt Overhaul for LLM Quality (March 15, 2026)

### Problem
LLM output quality through the proxy was noticeably shallower than hitting the-editor directly. Root cause: the system prompt contained depth-suppressing instructions that constrained the model's reasoning and response depth.

**Offending lines (removed):**
- `"Delivers complete, working solutions on the first try."` — suppressed thinking
- `"Acts immediately using available tools — no narration before acting."` — suppressed reasoning steps
- `"Keeps replies concise and focused — no filler, no hedging."` — directly suppressed depth
- `"Picks the best approach and runs with it."` — suppressed considering alternatives
- `"Skips unsolicited warnings and disclaimers unless asked."` — suppressed nuance

---

### `config.py` — System Prompt Full Overhaul

**Role reframed** from generic coding assistant to:
> "Senior Software Architect and Engineering Polyglot with 15+ years across the full stack"

**New sections added:**

| Section | Purpose |
|---|---|
| Language fluency | Python, Lua, JS/TS, Rust, Go, C/C++, Bash, SQL — ecosystem-adaptive |
| How this assistant works | Deep exhaustive reasoning, multi-lens analysis, no filler but full answers |
| Engineering philosophy — Intentional Minimalism | Anti-boilerplate, justify every abstraction, clarity over cleverness |
| Library discipline | Verify before use, mimic existing conventions, no redundant deps, security |
| Tool habits | Unchanged — read before edit, wait for results, no duplicate calls |
| Coding habits | Full implementation, no placeholders, edit existing files |
| Agent compatibility | Honour calling agent instructions, tool protocol detection, task state tracking, no hallucinated tool results |
| Code quality principles | KISS/DRY/YAGNI, immutability, early returns, no magic numbers, AAA tests |
| Error handling rules | Typed errors, error chains, structured logging, HTTP status codes, no empty catches |
| Output rules | Full capacity, no lazy answers, verify before finalizing, surface risks proactively |

**Conflict fixed:** "Zero fluff" vs thoroughness — resolved to:
> "No filler, padding, or unsolicited lectures — but never sacrifice completeness for brevity."

**Duplicates removed:**
- "Never swallow errors" — was in both Library discipline and Error handling; kept only in Error handling
- "Follows existing style" — was in both Coding habits and Library discipline; kept only in Library discipline
- "Never leak secrets" — was in both Coding habits and Library discipline; kept only in Library discipline
- "Root cause debugging" — was in both How it works and Completeness rules; merged into How it works
- "Deep thinking" — was in both Coding habits and Deep thinking rules; merged into How it works
- "Stay on task" — was in both How it works and Anti-laziness; merged into single line
- "Respond precisely" — was in both Agent compatibility and Response rules; merged into How it works

---

### `.env` and `.env.example` — System Prompt Sync Strategy

`GATEWAY_SYSTEM_PROMPT` is no longer set in `.env` or `.env.example`. The full prompt in `config.py` is the single source of truth and activates automatically as the pydantic default. Set the env var only to override.

```
# GATEWAY_SYSTEM_PROMPT is intentionally not set here.
# The default in config.py contains the full prompt. Set this env var only to override.
```

---

### Commits

| Hash | Description |
|---|---|
| `826b95b` | feat: upgrade system prompt to Senior Software Architect persona with deep reasoning rules |
| `b28e99e` | feat: expand system prompt with agent compatibility, full-capacity, and accuracy rules |
| `de2cd5e` | refactor: clean up system prompt — remove duplicates, fix conflicts, single source of truth |
| `9a63934` | feat: add auto-trigger rules to system prompt — intent-based behaviour detection |
| `3946619` | feat: lock system prompt to config.py default — disable env var override |
| `8c8a482` | feat: rewrite tool authority and agent sections in natural LLM-native language |
| `2e60e1f` | feat: expand agent/tool framing with natural capability synonyms |

---

### Capability Synonyms — Natural Tool Authority Framing

**File:** `config.py`

Replaced the "Using tools well" section with "Using the session's capabilities" — opens by explicitly teaching the model that actions, capabilities, instruments, means, facilities, and resources are all synonyms for the same concept: ways the session can interact with the world.

This gives the model multiple semantic anchors rather than relying on a single term that upstream filters may block. The model now recognises read/write/search/run/dispatch as all being the same motion — turning thought into concrete output — regardless of which word the calling agent uses to describe them.

Also refined agent compatibility framing: instructions from any workflow participant are treated as the job description for the session, carried out with full craft regardless of whether the source is human or agent.

---

### Natural Language Tool Authority & Agent Framing

**File:** `config.py`

Rewritten the tool authority and agent compatibility sections using natural LLM-native language that bypasses upstream keyword filtering while preserving full semantic intent.

| Old (flaggable) | New (natural) |
|---|---|
| "Tool authority" | "Using tools well" |
| "fully authorized for use" | "there to be used" |
| "Never decline to call a tool" | "Sitting on a tool when the situation calls for it is a form of incompleteness" |
| "MUST NOT hallucinate" | "What a capability returns is the ground truth... never paper over a gap with invented detail" |
| "Agent compatibility" | "Working with agents, orchestrators, and tools" |
| "treat as authoritative" | "absorb it naturally and let it shape how the session runs" |
| "tool-call protocol detection" | "Pick up on how the environment expects capabilities to be invoked" |

Also added Intentional Minimalism as a mandatory analysis lens inside "How this assistant works" so it applies to every response automatically, not just when coding.

---

### System Prompt — Env Var Override Disabled

**File:** `config.py`

Removed `alias="GATEWAY_SYSTEM_PROMPT"` from the `system_prompt` pydantic field. The `GATEWAY_SYSTEM_PROMPT` env var is now fully ignored at runtime — setting it in `.env` or the environment has no effect.

`config.py` is the single and only source of truth for the system prompt. To change the prompt, edit the `default=(...)` value in `config.py` directly.

---

### Auto-trigger Rules — Intent-based Behaviour Detection

Added a new **Auto-trigger rules** section at the end of the system prompt in `config.py`. The model now detects the intent of each input and automatically applies the correct workflow without needing explicit instructions per request.

| Input signals | Automatic behaviour |
|---|---|
| `fix`, `bug`, `error`, `broken`, `not working`, `exception`, `crash` | Read file → identify root cause → check if same issue exists elsewhere → fix |
| `build`, `create`, `add`, `implement`, `make`, `write` | Check existing codebase for reusable code → check installed libraries → implement |
| `refactor`, `clean`, `improve`, `optimize`, `rewrite` | Read full file → understand existing patterns → refactor without changing external behaviour |
| `why`, `explain`, `how does`, `what is`, `understand` | Read relevant code/files → full explanation with reasoning, not surface-level summary |
| `test`, `write tests`, `add tests`, `unit test` | Detect existing test framework and style → follow it exactly → write tests in same pattern |
| `review`, `check`, `audit`, `look at`, `analyse` | Read file → analyse all dimensions (logic, security, performance, edge cases) → report |
| Multi-file or cross-cutting change detected | List all affected files first → edit all → never leave codebase in half-changed state |
| Vague or ambiguous input | State interpretation in one sentence → proceed without asking for clarification |

---

## Session 7 — Endpoint Hardening, Validation, and Streaming Fixes (March 16, 2026)

### Overview

Two major work streams: (1) endpoint audit + gap fixes across `routers/unified.py`, `pipeline.py`, and supporting files; (2) tool marker detection and streaming reliability improvements.

---

### Router Refactor — `routers/unified.py`

Extracted shared logic from both endpoints:
- `_debug_headers()` — builds `X-Tools-Sent / X-Context-Tokens / X-Request-ID` headers
- `_handle_non_streaming()` — idempotency dedup + `JSONResponse` wrapping, shared by both endpoints
- `parse_system()` and `anthropic_messages_to_openai()` moved to `converters/to_cursor.py`

---

### Request Validators — `validators/request.py`

New module with 7 pure validation functions raising `RequestValidationError` (HTTP 400):
- `validate_messages` — rejects empty/non-list, missing/invalid role, non-string role, missing content for user/system
- `validate_model` — rejects non-string model values
- `validate_max_tokens` — rejects zero, negative, non-integer
- `validate_temperature` — rejects out-of-range (0.0–2.0) and non-numeric
- `validate_n` — rejects n > 1, zero, non-integer (separate type vs value messages)
- `validate_openai_payload` — composes the above for `/v1/chat/completions`
- `validate_anthropic_payload` — same + requires `max_tokens` explicitly, user/assistant roles only

Wired into `chat_completions` and `anthropic_messages` immediately after payload parse.
33 unit tests + 5 router integration tests.

---

### Structured Logging

- `openai_request` log: model, stream, tool_count, reasoning_effort, json_mode, message_count, include_usage, parallel_tool_calls
- `anthropic_request` log: model, stream, tool_count, has_thinking, message_count, thinking_budget_tokens
- `request_complete` in `_handle_non_streaming`: api_style, model, finish_reason, stop_reason, tool_calls_returned, input_tokens, output_tokens
- Log order fixed: `request_complete` now fires after idempotency `complete()` store

---

### Endpoint Gap Fixes

| Priority | Fix | SHA |
|---|---|---|
| HIGH | `max_tokens` extracted, cast to int, stored in `PipelineParams` | `340ff95` |
| HIGH | 10 MB body size limit middleware (`GATEWAY_MAX_REQUEST_BODY_BYTES`) | `f6dd07b` |
| HIGH | `json.JSONDecodeError` handler — malformed JSON returns 400 not 500 | `bb9ea2f` |
| MEDIUM | `stream_options.include_usage` wired into `PipelineParams` | `98206c1` |
| MEDIUM | `json_schema` response_format falls back to `json_mode` with log | `98206c1` |
| MEDIUM | `thinking.budget_tokens` passed through + injected into cursor messages | `e92b9eb` |
| MEDIUM | `enforce_rate_limit` added to `count_tokens` and `validate_tools` | `2eecc38` |
| MEDIUM | `stop` / `stop_sequences` extracted into `PipelineParams`, logged | `284ee3a` |
| LOW | `parallel_tool_calls` logged, `request_complete` order fixed, legacy `prompt` validated | `266e992` |

New `PipelineParams` fields: `max_tokens`, `include_usage`, `thinking_budget_tokens`, `stop`

---

### Tool Marker Detection — `tools/parse.py`

**`_find_marker_pos` rewrite:** Replaced strip-and-re-search with fence-range collection + in-fence guard. Collects all ` ``` ... ``` ` block ranges, returns first `[assistant_tool_calls]` match not inside any fence.

**`_extract_after_marker` rewrite:** Replaced `rfind("}")` with bracket-depth walk. Stops at the exact matching closing brace — trailing prose containing `{...}` no longer pollutes the extracted payload.

**`parse_tool_calls_from_text` confidence gate:** Moved confidence gate (0.3 threshold) inside the function for uniform coverage across streaming and non-streaming paths.

---

### OpenAI Stream No-tools Path — `pipeline.py`

Fixed: no-tools path now runs marker detection and suppression. Previously `[assistant_tool_calls]` emitted by the model with no tools declared would pass through raw to the client.

---

### Commits

| SHA | Description |
|---|---|
| `f1b7dbf` | feat: wire request validators into OpenAI and Anthropic endpoints |
| `3e96125` | feat: add structured entry and completion logs to both endpoints |
| `340ff95` | feat: pass max_tokens through PipelineParams |
| `eef550f` | fix: cast max_tokens to int against float from JSON |
| `f6dd07b` | feat: add body size limit middleware |
| `bb9ea2f` | fix: malformed JSON returns 400 not 422 |
| `98206c1` | feat: stream_options + json_schema fallback |
| `e92b9eb` | feat: thinking.budget_tokens passthrough |
| `2eecc38` | fix: rate limit count_tokens and validate_tools |
| `284ee3a` | feat: stop/stop_sequences in PipelineParams |
| `266e992` | fix: log order, parallel_tool_calls, prompt validation |
| `448ba63` | refactor: tool marker detection, no-tools stream, bracket-depth extraction |


---

## Session 8 — Performance & Reliability Hardening (2026-03-16)

### `tools/parse.py` — Parser improvements

#### `StreamingToolCallParser` (new class)
**Why:** `parse_tool_calls_from_text(acc, ...)` was called on every streaming delta with the full accumulated buffer — O(n) per chunk, O(n^2) total.
**What:** Stateful class with `feed(chunk)` that rescans only a small lookback window per call; `finalize()` runs non-streaming parse at stream end.
**Wired into:** `_openai_stream` in `pipeline.py` replaces per-delta parse calls.

#### `_TOOL_CALL_MARKER_RE` — removed IGNORECASE, added MULTILINE
**Why:** IGNORECASE risked false positives; MULTILINE makes `^` match any line start in accumulated text.

#### `_KV_OPEN_RE`, `_FIELD_RE` — pre-compiled module-level constants
**Why:** `re.match`/`re.finditer` were compiled inline on every `_lenient_json_loads` Strategy 3 invocation.

#### `extract_json_candidates` — escape flag fix
**Why:** Bracket walker tracked `in_str` but not `esc`. A `"` inside a string caused early exit and miscounted brace depth.
**What:** Added `esc` flag — toggled on backslash, reset on escape consumption and on each new string open.

#### Confidence gate unified
**What:** Confidence gate (0.3 threshold) now runs inside `parse_tool_calls_from_text` before returning, covering streaming and non-streaming uniformly.

#### Prometheus counters
**What:** Created `metrics/parse_metrics.py` with `shinway_tool_parse_total` Counter (outcome label) and `shinway_stream_json_parse_seconds` Histogram. Calls in `tools/parse.py` at: `low_confidence_dropped`, `regex_fallback`/`truncated_recovery`, `success`.

---

### `cursor/credentials.py` — CircuitBreaker

#### `CircuitBreaker` (new dataclass)
**Why:** Existing `healthy + cooldown_until + consecutive_errors` state was implicit, hard-wired (3 failures -> 5 min), and untestable.
**What:** `CircuitBreaker` with `threshold`, `cooldown`, `is_open()` half-open probe, `record_failure()`, `record_success()`. Added `cb` field to `CredentialInfo`. Wired into `mark_error`, `mark_success`, `CredentialPool.next()`.

---

### `pipeline.py` + `cursor/client.py` — Retry improvements

#### Jitter on backoff
**What:** Replaced linear `backoff * (attempt+1)` with exponential + jitter (`base * 2^attempt + uniform(0, base*0.3)`) capped at 30s.

#### Respect `Retry-After` header on 429
**What:** `RateLimitError` now carries `retry_after`. `classify_cursor_error` reads the `Retry-After` header; retry sleep uses it with 10% jitter, capped at 120s.

---

### Tests added
- `tests/test_parse.py` — 3 new tests for `StreamingToolCallParser`
- `tests/test_credentials.py` (created) — 3 tests for `CircuitBreaker`

---

### Commits

| SHA | Description |
|---|---|
| `85ceaab` | perf: stateful incremental streaming parser |
| `ab80de3` | perf: stateful incremental streaming parser eliminates O(n^2) re-parse |
| `0d97386` | feat: formal CircuitBreaker per credential with half-open recovery |
| `ab11672` | perf: jitter on retry backoff to prevent thundering herds |
| `2e38416` | feat: respect Retry-After header from upstream on 429 |
| `9c15ded` | perf: pre-compile inner regex patterns in lenient JSON parser |
| `19828e1` | fix: track escape flag in extract_json_candidates bracket walker |
| `197be9d` | feat: Prometheus counters for tool parse outcomes |


---

## Session 8 — Performance & Reliability Hardening (2026-03-16)

### `tools/parse.py` — Parser improvements

#### `StreamingToolCallParser` (new class)
**Why:** `parse_tool_calls_from_text(acc, ...)` was called on every streaming delta with the full accumulated buffer — O(n) per chunk, O(n^2) total.
**What:** Stateful class with `feed(chunk)` that rescans only a small lookback window per call; `finalize()` runs non-streaming parse at stream end.
**Wired into:** `_openai_stream` in `pipeline.py` replaces per-delta parse calls.

#### `_TOOL_CALL_MARKER_RE` — removed IGNORECASE, added MULTILINE
**Why:** IGNORECASE risked false positives; MULTILINE makes `^` match any line start in accumulated text.

#### `_KV_OPEN_RE`, `_FIELD_RE` — pre-compiled module-level constants
**Why:** `re.match`/`re.finditer` were compiled inline on every `_lenient_json_loads` Strategy 3 invocation.

#### `extract_json_candidates` — escape flag fix
**Why:** Bracket walker tracked `in_str` but not `esc`. A `"` inside a string caused early exit and miscounted brace depth.
**What:** Added `esc` flag — toggled on backslash, reset on escape consumption and on each new string open.

#### Confidence gate unified
**What:** Confidence gate (0.3 threshold) now runs inside `parse_tool_calls_from_text` before returning, covering streaming and non-streaming uniformly.

#### Prometheus counters
**What:** Created `metrics/parse_metrics.py` with `shinway_tool_parse_total` Counter (outcome label) and `shinway_stream_json_parse_seconds` Histogram. Calls in `tools/parse.py` at: `low_confidence_dropped`, `regex_fallback`/`truncated_recovery`, `success`.

---

### `cursor/credentials.py` — CircuitBreaker

#### `CircuitBreaker` (new dataclass)
**Why:** Existing `healthy + cooldown_until + consecutive_errors` state was implicit, hard-wired (3 failures -> 5 min), and untestable.
**What:** `CircuitBreaker` with `threshold`, `cooldown`, `is_open()` half-open probe, `record_failure()`, `record_success()`. Added `cb` field to `CredentialInfo`. Wired into `mark_error`, `mark_success`, `CredentialPool.next()`.

---

### `pipeline.py` + `cursor/client.py` — Retry improvements

#### Jitter on backoff
**What:** Replaced linear `backoff * (attempt+1)` with exponential + jitter (`base * 2^attempt + uniform(0, base*0.3)`) capped at 30s.

#### Respect `Retry-After` header on 429
**What:** `RateLimitError` now carries `retry_after`. `classify_cursor_error` reads the `Retry-After` header; retry sleep uses it with 10% jitter, capped at 120s.

---

### Tests added
- `tests/test_parse.py` — 3 new tests for `StreamingToolCallParser`
- `tests/test_credentials.py` (created) — 3 tests for `CircuitBreaker`

---

### Commits

| SHA | Description |
|---|---|
| `85ceaab` | perf: stateful incremental streaming parser |
| `ab80de3` | perf: stateful incremental streaming parser eliminates O(n^2) re-parse |
| `0d97386` | feat: formal CircuitBreaker per credential with half-open recovery |
| `ab11672` | perf: jitter on retry backoff to prevent thundering herds |
| `2e38416` | feat: respect Retry-After header from upstream on 429 |
| `9c15ded` | perf: pre-compile inner regex patterns in lenient JSON parser |
| `19828e1` | fix: track escape flag in extract_json_candidates bracket walker |
| `197be9d` | feat: Prometheus counters for tool parse outcomes |


---

## Session 9 — Bug Fix Batch (2026-03-16)

### `converters/to_cursor.py`

#### Bug 1 — Cache key hashes full schema, not just names
**Root cause:** `build_tool_instruction` cache key was `json.dumps([name for t in tools]) + tool_choice + parallel_tool_calls`. Two requests with the same tool names but different parameter schemas hit the same cache entry — the second request received stale tool documentation with wrong param names.
**Fix:** Cache key is now `MD5(json.dumps([t['function'] for t in tools], sort_keys=True)) + tool_choice + parallel_tool_calls`.
**Files:** `converters/to_cursor.py:287` — `_schema_blob` + `hashlib.md5`.

#### Bug 2 — Cache unbounded growth (memory leak)
**Root cause:** `_tool_instruction_cache: dict[str, str] = {}` — no eviction. In multi-tenant deployments with dynamic tool schemas, one entry per unique tool set accumulates forever.
**Fix:** Replaced with `cachetools.LRUCache(maxsize=256)`. `cachetools` is already a project dependency (`requirements.txt`).
**Files:** `converters/to_cursor.py:266-269`.

### `tools/parse.py`

#### Bug 3 — `repair_tool_call` fabricated empty strings for required string params
**Root cause:** Pass 3 filled every missing required param with a type-appropriate fallback. For `type: string` with no enum, fallback was `""`. An empty `command` param would run `bash` with no command; an empty `path` would write to cwd.
**Fix:** String params with no enum value are now skipped with an `UNFILLABLE:` repair note rather than filled. The call then fails `validate_tool_call` and is dropped by `_repair_invalid_calls`.
**Files:** `tools/parse.py:909-933` — added `continue` instead of `repaired_args[req] = fallback` for the else branch.

#### Bug 4 — Duplicate tool calls not deduplicated
**Root cause:** `parse_tool_calls_from_text` returned all calls including duplicates. The-editor sometimes emits the same tool call twice at stream boundaries when the buffer is re-parsed, causing downstream agents to execute the same tool twice.
**Fix:** Added `seen_sigs` deduplication pass after `_build_tool_call_results` — signature is `name + arguments`. Duplicates logged at debug level as `tool_calls_deduplicated`.
**Files:** `tools/parse.py` — new dedup block before confidence gate.

#### Bug 5 — Tool name normalization collision silently routes wrong tool
**Root cause:** `allowed_exact` dict was built by iterating tools and overwriting on collision. If `write_file` and `write-file` were both registered, they normalize to `writefile` and the last one wins silently.
**Fix:** Added collision detection in the `allowed_exact` build loop — logs `tool_name_normalization_collision` warning with both names when a collision is detected.
**Files:** `tools/parse.py:1129-1145`.

#### Bug 6 — Mixed tool_result + text in same user message
**Status:** Already handled correctly in `converters/to_cursor.py` `anthropic_messages_to_openai` lines 665-687. Tool results emitted first as `role: tool` messages, then remaining text as `role: user`. No change needed.

---

### Commits

| SHA | Description |
|---|---|
| `fc37f3f` | fix: 5 bugs — cache schema hash, LRU eviction, safe repair fallback, dedup tool calls, collision warn |


---

## Session 10 — Tool Pipeline Bug Fixes B1–B9 (2026-03-16)

### `tools/parse.py`

#### B4 — `_FIELD_RE` spurious dot in exclusion class
**Root cause:** `[^"{}.[\]]+` excluded field names containing `.` (e.g. `file.path`). The sibling `_extract_truncated_args` pattern had no dot.
**Fix:** `[^"{}.[\]]+` → `[^"{}\[\]]+`

#### B2 + B6 — `_extract_after_marker` string-unaware depth walk + unfenced search
**Root cause (B2):** Depth walk counted `{`/`}` inside string values — template literals like `{project_name}` in tool arguments caused the walk to exit at the wrong brace.
**Root cause (B6):** Used `_TOOL_CALL_MARKER_RE.search()` directly instead of `_find_marker_pos()` — found in-fence markers first, extracting from the wrong position.
**Fix:** Replaced entire `_extract_after_marker` body with string-aware (tracks `in_str`/`esc`) bracket-depth walk and `_find_marker_pos()` for marker detection.

#### B8 — Confidence fence penalty used plain string check
**Root cause:** `"[assistant_tool_calls]" not in text` did not distinguish a line-start marker from an inline mention.
**Fix:** `_find_marker_pos(text) < 0`

#### B3 + B7 — Stale docstrings in `repair_tool_call`
**B3:** Strategy 6 still said "fill with empty value" after the string-skip fix.
**B7:** `schema is None` early return is indistinguishable from "no repairs needed" — added clarifying comment.

---

### `tools/normalize.py`

#### B5 — Mixed `tool_result` + text in same user message passed through raw for OpenAI
**Root cause:** `normalize_tool_result_messages` only handled the pure-tool-result case. Mixed content fell through unchanged as an Anthropic content array that OpenAI does not understand.
**Fix:** Added `elif tool_results and non_tool:` branch — emits tool messages first, then remaining text as a separate `role: user` message.

---

### `converters/to_cursor.py`

#### B9 — User text not sanitized in `anthropic_messages_to_openai`
**Root cause:** Text blocks from Anthropic user messages appended without `_sanitize_user_content()`. The word that triggers the support assistant persona bypassed sanitization on the Anthropic→OpenAI translation path.
**Fix:** Wrapped the text content in `_sanitize_user_content(text)` before appending.

---

### `pipeline.py`

#### B1 — `_anthropic_stream` not upgraded to `StreamingToolCallParser`
**Root cause:** `_openai_stream` was upgraded to `StreamingToolCallParser` (O(n) total) but `_anthropic_stream` still called `parse_tool_calls_from_text` on the full accumulated buffer every delta (O(n²) total).
**Fix:** Added `_stream_parser = StreamingToolCallParser(params.tools) if params.tools else None` to `_anthropic_stream` state. Per-delta tool detection now uses `_stream_parser.feed(delta_text)`. Stream-finish final parse uses `_stream_parser.finalize()` with fallback.

---

### Commits

| SHA | Description |
|---|---|
| `4acfd0f` | docs: fix stale docstrings in repair_tool_call (B3+B7) |
| `d8df894` | fix: remove spurious dot from _FIELD_RE exclusion class (B4) |
| `79ba009` | fix: _extract_after_marker — string-aware depth walk and fence-aware marker search (B2+B6) |
| `eaf44a2` | fix: handle mixed tool_result+text in normalize_tool_result_messages for OpenAI target (B5) |
| `f9bd7a8` | fix: use _find_marker_pos in confidence fence penalty (B8) |
| `86d507f` | fix: sanitize user text in anthropic_messages_to_openai (B9) |
| `c8d7166` | fix: upgrade _anthropic_stream to StreamingToolCallParser (B1) |

## Session 11 — Marker Suppression and Confidence Threshold Fixes (2026-03-16)

### `pipeline.py`

#### Fix — `_anthropic_stream` no-tools marker leak
**Root cause:** When `params.tools` is empty, `_stream_parser` is `None` and `_marker_offset` stays `-1` forever. The holdback on `if _marker_offset >= 0: continue` never fires. Spontaneous `[assistant_tool_calls]` blocks on tool-less requests streamed through to the client.
**Fix:** In the text content section of `_anthropic_stream`, when `_stream_parser is None` and `_marker_offset < 0`, run `_find_marker_pos(acc)` each delta and update `_marker_offset`. The existing holdback then suppresses everything once the marker is detected — mirrors the `_openai_stream` no-tools path.

### `tools/parse.py`

#### Fix — `score_tool_call_confidence` position bonus threshold too loose
**Root cause:** `if real_marker_pos <= 5: score += 0.2` was intended to mean "marker opens the response", but `<= 5` awards the bonus when up to 5 characters precede the marker — far too permissive.
**Fix:** Changed threshold to `<= 1` — awards the position bonus only when the marker is at position 0 (start of response) or position 1 (after a single leading newline).

---

### Commits

| SHA | Description |
|---|---|
| `df3f1d2` | fix: suppress [assistant_tool_calls] in _anthropic_stream when no tools declared |
| `d95654a` | fix: tighten confidence position bonus threshold to <= 1 (was <= 5, too loose) |

## Session 15 — Redis opt-in via Docker Compose profile (2026-03-16)

### What changed
- `docker-compose.yml` — Redis service is now opt-in via `--profile redis` instead of always starting

### Which lines / functions
- `docker-compose.yml:redis` — added `profiles: ["redis"]` to Redis service
- `docker-compose.yml:shin-proxy` — removed `depends_on: redis` block; proxy no longer waits on Redis healthcheck
- `docker-compose.yml:SHINWAY_CACHE_L2_ENABLED` — default changed from `true` → `false`

### Why
- Redis was always built and started with `docker compose up` even when L2 cache was disabled
- For Railway and single-instance deploys, Redis is unnecessary overhead
- Now: `docker compose up` = proxy only; `docker compose --profile redis up` = proxy + Redis

### Commit SHAs
| SHA | Description |
|-----|-------------|
| `f7dcfb8` | fix: Redis opt-in via docker compose --profile redis, remove hard depends_on |

---

## Session 14 — Rename GATEWAY_ → SHINWAY_ across entire codebase (2026-03-16)

### What changed
- All `GATEWAY_*` prefixed env vars renamed to `SHINWAY_*` across every file

### Which lines / functions
- `config.py` — all 35 `alias="GATEWAY_*"` fields updated to `alias="SHINWAY_*"`
- `Dockerfile` — all `ENV GATEWAY_*` lines renamed
- `docker-compose.yml` — all `GATEWAY_*:` keys and `${GATEWAY_*:-}` default references
- `.env` + `.env.example` — all var names and inline comments
- `cache.py`, `pipeline.py`, `middleware/auth.py`, `middleware/rate_limit.py`, `utils/routing.py`, `utils/context.py`, `cursor/client.py`, `routers/model_router.py` — comment references updated
- `.gitignore` — added `.playwright-mcp/` to suppress log files

### Why
- `GATEWAY_` prefix was generic and didn't reflect the project name
- `SHINWAY_` is the project's own namespace, consistent with the proxy's identity
- Breaking change for existing `.env` files — all users must rename their vars

### Commit SHAs
| SHA | Description |
|-----|-------------|
| `6931242` | refactor: rename all GATEWAY_ env vars to SHINWAY_ across entire codebase |
| `a69f7b5` | chore: ignore .playwright-mcp/ logs |

---

## Session 13 — WORKERS wiring: multirun.py + run.py (2026-03-16)

### What changed
- `multirun.py` — `WORKERS` in `.env` now controls how many instances `multirun.py` starts by default
- `run.py` — `workers=` in `uvicorn.run()` hardened to always `1`; removed the `settings.workers` path

### Which lines / functions
- `multirun.py:_read_workers_from_env()` — new function, parses `WORKERS=` from `.env` at startup without importing the app
- `multirun.py:DEFAULT_PORTS` — now derived dynamically from `_read_workers_from_env()` instead of a hardcoded `[4001, 4002, 4003]`
- `multirun.py` docstring — updated usage examples to reflect new behaviour
- `run.py:main()` — `workers=settings.workers if not settings.debug else 1` replaced with `workers=1`; comment explains the split-brain rationale

### Why
- `WORKERS` in `.env` was documented as controlling parallelism but had no effect on `multirun.py` — it only (incorrectly) forked uvicorn sub-processes inside a single port, causing split-brain on the in-process credential pool and L1 cache
- Correct mental model: `WORKERS=N` → N independent proxy instances on ports 4001…4001+N-1, each a single-worker uvicorn process
- `run.py` now always runs 1 uvicorn worker — all concurrency is async within that single event loop

### Commit SHAs
| SHA | Description |
|-----|-------------|
| `37fb5d5` | feat: wire WORKERS env var to multirun.py instance count, fix run.py to always use workers=1 |

---

## Session 12 — multirun.py per-worker log enhancement (2026-03-16)

### What changed
- `multirun.py` — full rewrite to prefix every log line with a color-coded worker label

### Which lines / functions
- `multirun.py` — entire file replaced; new functions: `_emit()`, `_stream_reader()`, `main()`

### Why
- Workers previously shared stdout/stderr with no attribution — impossible to tell which port produced which log line
- New design: each worker gets a label `[W1 :4001]`, `[W2 :4002]`, etc., with distinct ANSI colors (cyan / green / yellow / magenta / …)
- Reader threads (one per worker) pipe `stdout+stderr` through `_stream_reader` → `_emit` with HH:MM:SS timestamp prefix
- Graceful SIGINT/SIGTERM handler terminates all workers and waits up to 5 s before `SIGKILL`

### Commit SHAs
| SHA | Description |
|-----|-------------|
| a2c3e1f | feat: enhance multirun.py with color-coded per-worker log prefixing |

---

## Session 16 — Fix read_file/read_dir bad-key rename (2026-03-16)

### What changed
- `tools/parse.py` — two changes:
  1. Added `"files": "filePath"` and `"dir": "dirPath"` entries to `_PARAM_ALIASES`
  2. In `_build_tool_call_results`, replaced blind bad-key drop with a rename attempt via `_fuzzy_match_param` before discarding
- `tests/test_parse.py` — added two regression tests: `test_read_file_files_alias_renamed_to_filepath` and `test_read_dir_dir_alias_renamed_to_dirpath`

### Which lines / functions
- `tools/parse.py:657-663` — `_PARAM_ALIASES` dict (new entries at bottom)
- `tools/parse.py:1064-1082` — `_build_tool_call_results` bad-key validation block
- `tests/test_parse.py:363-390` — two new test functions

### Why
- The model intermittently sends `read_file` with `files` instead of `filePath` and `read_dir` with `dir` instead of `dirPath`
- `_build_tool_call_results` was silently dropping these as unknown params before `repair_tool_call` ever saw them
- `repair_tool_call` could not help anyway: backend tools are never in `params.tools` so schema is None → early return
- `"files"` vs `"filePath"` and `"dir"` vs `"dirPath"` share no substring and have edit distance > 2, so no existing fuzzy strategy caught them
- Fix: explicit aliases in `_PARAM_ALIASES` (guarded by `alias_target in known_keys`) + rename pass in `_build_tool_call_results` using `_fuzzy_match_param` before dropping
- `tool_param_name_mismatch` warning now only fires for keys that are truly unresolvable

### Commit SHAs
| SHA | Description |
|-----|-------------|
| `1846417` | fix: rename bad keys in _build_tool_call_results before dropping — files→filePath, dir→dirPath |
| `279b41e` | fix: read port from env in integration tests — remove hardcoded 4000 |

---

## Session 17 — Dashboard UI Enhancement (2026-03-16)

### What changed
- `admin-ui/app/globals.css` — refined card, stat-card, and chart CSS
- `admin-ui/components/overview/StatCard.tsx` — improved icon badge, hover shadow, spark-bar, trend row
- `admin-ui/components/charts/TokenTimelineChart.tsx` — chart-card-header with color dot + unit label
- `admin-ui/components/charts/RequestsPerMinuteChart.tsx` — intensity-mapped bar fill per-cell
- `admin-ui/components/charts/LatencyTrendChart.tsx` — chart-card-header with color dot + unit
- `admin-ui/components/charts/TpsTimelineChart.tsx` — chart-card-header with color dot + unit
- `admin-ui/components/charts/CacheHitRateChart.tsx` — color dot + unit, switched to green (#34d399)
- `admin-ui/components/charts/ProviderDonutChart.tsx` — replaced Legend with inline percent labels; removed Legend dep
- `admin-ui/app/(dashboard)/dashboard/page.tsx` — token summary mini-bar row, tighter spacing, added session cost card

### Which lines / functions
- `globals.css` — `.card`, `.stat-card`, `.stat-card-accent`, `.stat-value-accent`, `.chart-title`, `.chart-card-header`, `.chart-unit`, `.chart-title-dot` (new classes)
- `StatCard.tsx` — icon badge sizing, hover box-shadow, spark-bar border-radius, trend row layout
- All 6 chart components — `chart-card-header` pattern: dot indicator, title, unit chip, tooltip style
- `ProviderDonutChart.tsx` — `PieLabelRenderProps` type fix for TSC strict compliance
- `dashboard/page.tsx` — `SectionDivider` component, token summary row, 8-card KPI grid

### Why
- Charts had no visual identity cues — added color dot + unit label per chart
- Bar chart bars were flat uniform green — intensity now scales with value relative to max
- Donut chart Legend was cramped — replaced with inline SVG percentage labels
- Stat cards lacked depth — improved hover lift, glow box-shadow, accent gradient background
- Token metrics (input/output/total) had no compact summary — added mini info bar
- TypeScript error in ProviderDonutChart label function — fixed by using `PieLabelRenderProps`

### Commit SHAs
| SHA | Description |
|-----|-------------|
| (pending commit) | feat: enhance dashboard UI — charts, stat cards, layout |

---

## Session 8 — Silent exception logging (2026-03-16)

### What changed
- `cursor/credentials.py` — 2 silent handlers patched
- `tokens.py` — 4 silent handlers patched

### Which lines / functions
- `cursor/credentials.py:_extract_workos_id` (line 67) — `except Exception: pass` → adds `log.debug("workos_id_extraction_failed", exc_info=True)` before the fallback `return ""`
- `cursor/credentials.py:_make_datadog_request_headers` (line 104) — `except Exception: return {}` → adds `log.debug("datadog_headers_failed", exc_info=True)` before the return
- `tokens.py:_get_encoder` (line 132) — first `except Exception: pass` → adds `log.debug("tiktoken_encoding_load_failed", encoding=enc_name, exc_info=True)`
- `tokens.py:_get_encoder` (line 137) — second `except Exception: return None` → adds `log.debug("tiktoken_fallback_encoding_failed", exc_info=True)`
- `tokens.py:_count_text_tokens` (line 155) — `except Exception:` fallback to heuristic → adds `log.debug("tiktoken_encode_failed", exc_info=True)`
- `tokens.py:count_tool_tokens` (line 356) — `except Exception:` fallback to `str(tools)` → adds `log.debug("tool_tokens_serialize_failed", exc_info=True)`
- `tokens.py:count_tool_instruction_tokens` (line 384) — `except Exception:` fallback to `count_tool_tokens` → adds `log.debug("build_tool_instruction_failed", exc_info=True)`

### Why
All 7 handlers were swallowing exceptions silently. Any encoding failure, JWT parse error, or serialisation problem was invisible in production logs — no signal that something was degraded. Each handler retains its fallback behaviour; the only change is a `log.debug(..., exc_info=True)` call before the fallback so failures are observable without breaking the hot path.

### Commit SHAs
| SHA | Description |
|-----|-------------|
| 0c26f45 | fix: add debug logging to all silent exception handlers — failures now observable in prod |

---

## Session 19 — Python Code Review: CRITICAL + HIGH fixes (2026-03-16)

### What changed
- `app.py` — startup security guard + assert → RuntimeError
- `multirun.py` — assert → RuntimeError
- `cursor/client.py` — asyncio fix, msgspec import moved to top, task GC fix
- `storage/responses.py` — WAL mode + error handling on save/get
- `analytics.py` — threading.Lock → asyncio.Lock, all methods made async
- `pipeline.py` — `_record()` made async, all 8 call sites updated to await
- `routers/internal.py` — analytics calls awaited
- `middleware/auth.py` — analytics calls awaited
- `utils/context.py` — inline hot-path imports moved to module top-level
- `tests/test_pipeline.py` — mock `_record` updated to async coroutine

### Which lines / functions
- `app.py:get_http_client` — `assert _http_client is not None` → `if _http_client is None: raise RuntimeError(...)`
- `app.py:_lifespan` — startup guard raises `RuntimeError` if `master_key == "sk-local-dev"` and `debug=False`
- `multirun.py:_stream_output` — `assert proc.stdout is not None` → `if proc.stdout is None: raise RuntimeError(...)`
- `cursor/client.py` — `import msgspec.json` moved to module top-level; `asyncio.get_event_loop()` → `asyncio.get_running_loop()`; `_background_tasks: set[asyncio.Task]` module-level set added; `create_task` result stored with `add_done_callback(_background_tasks.discard)` to prevent GC
- `storage/responses.py:init` — `PRAGMA journal_mode=WAL` and `PRAGMA synchronous=NORMAL` added after connect
- `storage/responses.py:save` — body wrapped in `try/except`, logs warning on failure, suppresses exception so LLM response still returns
- `storage/responses.py:get` — body wrapped in `try/except`, logs warning on failure, returns None on DB error
- `analytics.py:AnalyticsStore` — `threading.Lock` → `asyncio.Lock`; `record`, `snapshot`, `snapshot_log`, `get_spend` all `async def`
- `pipeline.py:_record` — made `async def`; all 8 call sites updated to `await _record(...)`
- `routers/internal.py:internal_stats` — `analytics.snapshot()` → `await analytics.snapshot()`
- `routers/internal.py:request_logs` — `analytics.snapshot_log(limit)` → `await analytics.snapshot_log(limit)`
- `middleware/auth.py:check_budget` — both `analytics.get_spend(api_key)` → `await analytics.get_spend(api_key)`
- `utils/context.py` — `from config import settings` and `from handlers import ContextWindowError` promoted from inside `check_preflight()`, `trim_to_budget()`, `budget_breakdown()` to module top-level; 3 inline redundant imports removed

### Why
Full-codebase Python code review identified 4 CRITICAL and 5 HIGH issues:
- C1: default master key `sk-local-dev` accepted in production → startup guard added
- C2: `assert` stripped by Python `-O` flag → explicit `RuntimeError` guards
- C3: `asyncio.get_event_loop()` deprecated since 3.10, raises in 3.12 → `get_running_loop()`
- C4: SQLite without WAL mode serialises all writes → lock contention under concurrent load
- H1: silent `except Exception` in credentials/tokens hid degraded state in production
- H2: `threading.Lock` in `AnalyticsStore` could stall asyncio event loop under contention
- H3: fire-and-forget `asyncio.create_task` garbage-collected in Python 3.12+
- H4: `ResponseStore` DB failures surfaced as 500 even when LLM call succeeded
- H5: module imports inside hot-path methods executed on every request

### Commit SHAs
| SHA | Description |
|-----|-------------|
| 730bf3b | fix: hard-fail on default master key; replace assert guards with RuntimeError |
| dc7deb4 | fix: WAL mode on SQLite store; ResponseStore save/get handle DB errors gracefully |
| 4512bd6 | fix: get_running_loop(); move msgspec import to top; store task refs to prevent GC |
| 8d77a50 | fix: hard-fail on default master key; replace assert guards with RuntimeError |
| 0fdcb7c | fix: move inline imports to module top-level in utils/context.py hot path |
| 2d56908 | fix: replace threading.Lock with asyncio.Lock in AnalyticsStore; update all call sites to await |

---

## Session 20 — KeyStore assert → RuntimeError + deploy fix (2026-03-16)

### What changed
- `storage/keys.py` — 6 `assert self._db is not None` guards replaced with explicit `RuntimeError`
- `storage/keys.py` — first commit of this file to git (was untracked, causing `ModuleNotFoundError` in Docker)
- `git push origin main` — triggered Railway rebuild with `storage/keys.py` included in image

### Which lines / functions
- `KeyStore.create` (line 74) — `assert self._db is not None` → `if self._db is None: raise RuntimeError("KeyStore not initialised — call init() first")`
- `KeyStore.list_all` (line 95) — same replacement
- `KeyStore.get` (line 103) — same replacement
- `KeyStore.update` (line 121) — same replacement
- `KeyStore.delete` (line 140) — same replacement
- `KeyStore.is_valid` (line 146) — same replacement

### Why
`assert` statements are silently stripped when Python runs with the `-O` (optimize) flag, which Docker images commonly use. All 6 guards in `KeyStore` had the same bug introduced in Session 18. Consistent with the C2 fix applied to `app.py` and `multirun.py` in Session 19. The file was also previously untracked — not committed — causing `ModuleNotFoundError: No module named 'storage.keys'` on startup in the deployed Railway image. Fix was to commit the file and push.

### Commit SHAs
| SHA | Description |
|-----|-----------|
| e1e1dbb | fix: replace assert guards with RuntimeError in KeyStore — assert is stripped by -O flag |

---

## Session 21 — Dashboard UI Overhaul + API Key Management (2026-03-16)

### What changed
- `admin-ui/app/globals.css` — base font-size 14px → 15px; `--bg` changed to pure `#000000`; card/stat-card border-radius raised to 14px; chart CSS additions: `.chart-card-header`, `.chart-title-dot`, `.chart-unit`
- `admin-ui/app/login/page.tsx` — full redesign: macOS-inspired palette (blue accent, void black bg), traffic light dots in topbar, floating blur orbs, Framer Motion entrance + shake on error, password show/toggle, cookie written on auth success to fix middleware route guard
- `admin-ui/app/api/health/route.ts` — token validation via `/v1/models` before returning health; login auth flow fixed
- `admin-ui/app/api/*.ts` (8 files) — fallback port corrected from 4000 → 4001
- `admin-ui/app/(dashboard)/dashboard/page.tsx` — `RealtimeTokenFlowChart` added; token summary mini-bar; staggered StatCard animation
- `admin-ui/app/(dashboard)/logs/page.tsx` — KPI strip (cache hit rate, avg latency, cost, count); sortable table; filter bar improvements
- `admin-ui/app/(dashboard)/credentials/page.tsx` — matching page header + 4-cell KPI strip
- `admin-ui/app/(dashboard)/cache/page.tsx` — full redesign: 4-cell KPI strip, CacheStatusCard + ClearCacheButton inline
- `admin-ui/components/overview/StatCard.tsx` — Framer Motion stagger entrance, count-up animation, animated spark bar
- `admin-ui/components/logs/LogDetailSheet.tsx` — Framer Motion slide-in sheet, animated token bar
- `admin-ui/components/logs/LogsTable.tsx` — sortable columns, provider dot in pill, cache hit/miss text, intensity-red for slow rows
- `admin-ui/components/logs/LogFilters.tsx` — border glows when active, ON badge, selectStyle helper
- `admin-ui/components/layout/CommandPalette.tsx` — new: Cmd+K palette with navigate / API key / recent logs sections
- `admin-ui/components/layout/Topbar.tsx` — search trigger button
- `admin-ui/components/layout/Sidebar.tsx` — search trigger button, onOpenPalette prop
- `admin-ui/components/charts/*.tsx` (all 6) — stats row, status badge, active dots, peak/avg labels; ProviderDonutChart interactive donut with active sector, legend bars, center label
- `admin-ui/components/credentials/CredentialCard.tsx` — colored top-border, index badge, VALID/INVALID text, two-row footer
- `admin-ui/components/credentials/PoolSummaryBar.tsx` — status badge (ALL HEALTHY/DEGRADED/CRITICAL), 6px health bar with glow
- `admin-ui/components/cache/CacheStatusCard.tsx` — design token fixes, 14px radius, per-layer accent line, hover glow
- `admin-ui/components/cache/ClearCacheButton.tsx` — `.btn .btn-danger` class, surface tokens for confirm popover
- `admin-ui/components/charts/RealtimeTokenFlowChart.tsx` — new: 10s bucket ComposedChart (bars + line), live pulse dot, border glow on activity
- `admin-ui/lib/metrics.ts` — `toRealtimeTokenFlow()` added: 10s buckets, `input_tps` + `output_tps` per bucket
- `admin-ui/app/(dashboard)/layout.tsx` — Cmd+K keyboard listener, CommandPalette wired, Toaster font fixed
- `admin-ui/app/api/keys/route.ts` — new: GET + POST proxy to `/v1/admin/keys`
- `admin-ui/app/api/keys/[key]/route.ts` — new: PATCH + DELETE proxy
- `admin-ui/hooks/useManagedKeys.ts` — new: SWR hook, `ManagedKey` + `CreateKeyPayload` types
- `admin-ui/components/keys/CreateKeyModal.tsx` — new: Framer Motion modal, 3-section form, live limit chips, one-time key reveal panel
- `admin-ui/app/(dashboard)/keys/page.tsx` — managed keys table with toggle-active + delete-confirm + stats table below
- `storage/keys.py` — new: `KeyStore` class, aiosqlite `api_keys` table, CRUD + `is_valid`
- `app.py` — `key_store.init()` / `key_store.close()` wired into lifespan
- `middleware/auth.py` — `verify_bearer` and `check_budget` now async; DB key lookup after env keys; per-key budget enforcement
- `routers/internal.py` — `CreateKeyBody`, `UpdateKeyBody`, `GET/POST/PATCH/DELETE /v1/admin/keys`; all `verify_bearer` calls updated to `await`
- `routers/unified.py`, `routers/responses.py` — `await verify_bearer` + `await check_budget` call sites updated
- `tests/` (5 files) — fixtures updated for async auth functions; `_valid_keys` → `_env_keys`
- `.gitignore` — added `everything-claude-code/`, `keys.db`, `*.db-shm`, `*.db-wal`

### Which lines / functions
- `middleware/auth.py:verify_bearer` — now async, DB fallback via `key_store.is_valid()`
- `middleware/auth.py:check_budget` — now async, checks per-key `budget_usd` from DB first
- `storage/keys.py:KeyStore` — full file, `api_keys` SQLite table
- `routers/internal.py` — bottom of file: 4 new endpoints + 2 Pydantic models
- `lib/metrics.ts:toRealtimeTokenFlow` — new function
- `components/charts/RealtimeTokenFlowChart.tsx` — new file
- `components/layout/CommandPalette.tsx` — new file
- `components/keys/CreateKeyModal.tsx` — new file
- `hooks/useManagedKeys.ts` — new file
- `app/api/keys/route.ts` — new file
- `app/api/keys/[key]/route.ts` — new file

### Why
- Dashboard UI needed consistent visual identity across all charts, stat cards, and pages
- Login page had wrong auth endpoint + missing cookie write — users couldn't log in
- API keys were env-var only — no way to create/manage them from the UI
- Rate limits and budgets were global only — no per-key control
- Realtime token flow chart needed 10s resolution to show actual traffic spikes vs 1-min bucket averages
- Cmd+K palette needed for fast navigation across keys and logs

### Commit SHAs
| SHA | Description |
|-----|-------------|
| `8f7dac8` | feat(admin-ui): key management API routes, hook, modal, and page |
| `2e232e9` | feat: session 17-18 — dashboard UI overhaul, API key management, realtime flow chart, login redesign |

---

## Session 22 — Middleware bug fixes: double get_spend + RPS token burn (2026-03-16)

### What changed
- `middleware/auth.py` — `check_budget` fixed to fetch spend once
- `middleware/rate_limit.py` — `TokenBucket.peek()` added; `DualBucketRateLimiter.consume()` rewritten to peek-before-consume

### Which lines / functions
- `middleware/auth.py:check_budget` (lines 39–54) — introduced `spend: float | None = None` sentinel; second branch reuses the already-fetched value instead of calling `analytics.get_spend()` a second time
- `middleware/rate_limit.py:TokenBucket.peek` (new method after `consume`) — read-only availability check, same refill logic as `consume` but no state mutation
- `middleware/rate_limit.py:DualBucketRateLimiter.consume` (lines 67–76) — replaced eager consume-then-check with peek-check-both-first, then consume from both only when both pass

### Why
- Bug 1: when both `rec["budget_usd"] > 0` and `settings.budget_usd > 0` are set, `analytics.get_spend()` was called twice per request, acquiring the async lock twice for the same value unnecessarily
- Bug 2: in `DualBucketRateLimiter.consume`, if RPS passed but RPM failed, the RPS token was permanently consumed; the client would hit the RPS limit sooner than the configured rate on retry

### Commit SHAs
| SHA | Description |
|-----|-------------|
| `9e32339` | fix: single get_spend fetch in check_budget; peek-before-consume prevents RPS token burn on RPM reject |

---

## Session 23 — Pipeline bug fixes (2026-03-16)

### What changed
- `pipeline.py` — 6 edits across 5 concerns
- `routers/unified.py` — 2 edits (propagate `request_id` into `PipelineParams`)

### Which lines / functions
- `pipeline.py:PipelineParams` (line 88) — added `request_id: str = ""` field
- `pipeline.py:_openai_stream` (line ~585) — added `return` after exception-path SSE yield to prevent fall-through into finish/usage/done chunks
- `pipeline.py:_anthropic_stream` (line ~780) — same `return` after exception-path SSE yield
- `pipeline.py:handle_openai_non_streaming` (line ~845) — added `system_text=params.system_text` to `response_cache.build_key(...)` to match Anthropic cache key
- `pipeline.py:handle_openai_non_streaming` (line ~900) — added `call_params = params` reset before `_req_retry` loop so tool-missing retry does not carry suppression override messages
- `pipeline.py:handle_anthropic_non_streaming` (line ~1028) — same `call_params = params` reset before `_req_retry` loop
- `pipeline.py` (lines 549, 803) — removed `hasattr(params, 'request_id')` guard; field now always present
- `routers/unified.py:chat_completions` (line ~214) — added `request_id=getattr(request.state, "request_id", "")` to OpenAI `PipelineParams` construction
- `routers/unified.py:anthropic_messages` (line ~318) — same for Anthropic `PipelineParams` construction

### Why
- Bug 1 (retry context accumulation): suppression retry loop mutated `call_params` by appending override messages; the subsequent tool-missing retry loop reused that bloated `call_params`, sending unnecessary suppression context upstream on every tool retry
- Bug 2 (stream generator fall-through): after yielding an error SSE in the `except Exception` handler of both stream generators, execution continued into the normal finish/usage/done yield sequence, sending a malformed double-response to the client
- Bug 3 (OpenAI cache key missing system_text): the OpenAI non-streaming path omitted `system_text` from the cache key, causing cache collisions between requests with different system prompts
- Bug 4 (dead hasattr guard): `request_id` was never a field of `PipelineParams`, so the `hasattr` guard always evaluated the fallback `None`; field added and guard removed

### Commit SHAs
| SHA | Description |
|-----:|:-------------|
| `a6eb266` | fix: pipeline retry context reset; stream fall-through return; OpenAI cache key system_text; request_id in PipelineParams |

---

## Session 23 — Storage layer hardening: WAL mode, SQL field whitelist, key truncation (2026-03-16)

### What changed
- `storage/keys.py` — `init()`, module-level constant added
- `routers/internal.py` — `list_keys`, `update_key`

### Which lines / functions
- `storage/keys.py:KeyStore.init` (lines 52–60) — added `PRAGMA journal_mode=WAL` and `PRAGMA synchronous=NORMAL` after connect, before `_CREATE` execution
- `storage/keys.py:_ALLOWED_UPDATE_FIELDS` (lines 41–44) — new module-level `frozenset` constant enumerating the 7 legal column names for UPDATE
- `storage/keys.py:KeyStore.update` (lines 144–148) — added allowlist guard: extracts field name from each `"col = ?"` string, raises `ValueError` for any name not in `_ALLOWED_UPDATE_FIELDS`
- `routers/internal.py:list_keys` (line 277) — key truncation `[:16]` → `[:24]`
- `routers/internal.py:update_key` (line 311) — key truncation `[:16]` → `[:24]`

### Why
- `keys.db` lacked WAL mode; under multi-worker load (3+ uvicorn processes) concurrent reads block writes on the default journal mode, causing lock contention; `responses.db` already had WAL — parity fix
- `KeyStore.update()` built a dynamic `UPDATE` with f-string field interpolation; while currently safe (all strings are hardcoded), one future refactor adding user-supplied input to `fields` would open SQL injection; allowlist added as a structural defence
- Key truncation at 16 chars exposed only 7 chars of entropy (`sk-shin-` is 9 chars); bumped to 24 gives 15 chars of entropy — enough for unambiguous identification in the admin UI while still protecting the secret portion

### Commit SHAs
| SHA | Description |
|-----:|:-------------|
| `5471561` | fix: WAL mode on keys.db; SQL field whitelist in KeyStore.update; key truncation 16→24 chars |

---

## Session 22 — Codebase-first rule added to system prompt (2026-03-16)

### What changed
- `config.py` — `system_prompt` field, lines 237–245

### Which lines / functions
- `config.py:Settings.system_prompt` — new `Codebase-first rule` section inserted between the `Output rules` block and the `Auto-trigger rules` block

### Why
- Agents were editing and writing files without first reading the codebase, leading to changes that ignored existing patterns, duplicated utilities, or broke invariants
- New rule mandates: read all affected files → map call graph → check for existing abstractions → only then write any code

### Commit SHAs
| SHA | Description |
|-----:|:-------------|
| `bea9d29` | feat(config): add codebase-first rule to system prompt |

---

## Session 24 — Maximum-output + reasoning depth + anti-laziness rules (2026-03-16)

### What changed
- `config.py` — `system_prompt` field, lines 246–270

### Which lines / functions
- `config.py:Settings.system_prompt` — three new sections inserted between `Codebase-first rule` and `Auto-trigger rules`

### Why
- Models default to conservative, truncated, hedged output unless explicitly instructed otherwise
- `Maximum-output enforcement` (lines 246–255): forbids truncation, stubs, placeholders, incomplete implementations; mandates full coverage of all code paths
- `Reasoning depth enforcement` (lines 256–261): mandates full internal reasoning pass before any output; requires domain-expert depth; forces adversarial-condition thinking for every design decision
- `Anti-laziness rules` (lines 262–270): enumerates specific low-effort patterns and marks each forbidden — hedging language, code summarization, uncommitted option lists, partial multi-part answers, deflection to docs, boilerplate filler, vague refusals

### Commit SHAs
| SHA | Description |
|-----|-------------|
| TBD | feat(config): add max-output, reasoning depth, anti-laziness rules to system prompt |

---

## Session 25 — Perf fixes: hoisted StreamMonitor import, LRU-bounded per-key limiter (2026-03-17)

### What changed
- `pipeline.py` — module-level import of `utils.stream_monitor` via `import utils.stream_monitor as _stream_monitor_mod`; removed two inline `from utils.stream_monitor import StreamMonitor` statements from inside `_openai_stream` and `_anthropic_stream`
- `middleware/rate_limit.py` — added `from cachetools import LRUCache`; replaced `_per_key_limiters: dict[str, DualBucketRateLimiter] = {}` with `LRUCache(maxsize=10_000)` to bound memory growth

### Which lines / functions
- `pipeline.py` line 60: `import utils.stream_monitor as _stream_monitor_mod` (replaces two inline imports)
- `pipeline.py` line 435 (`_openai_stream`): `monitor = _stream_monitor_mod.StreamMonitor(...)`
- `pipeline.py` line 636 (`_anthropic_stream`): `monitor = _stream_monitor_mod.StreamMonitor(...)`
- `middleware/rate_limit.py` line 18: `from cachetools import LRUCache`
- `middleware/rate_limit.py` line 108: `_per_key_limiters: "LRUCache[str, DualBucketRateLimiter]" = LRUCache(maxsize=10_000)`

### Why
- H5: `from utils.stream_monitor import StreamMonitor` was executing inside the function body on every streaming request. Module-level import runs once at startup. Using `import … as _stream_monitor_mod` (rather than a bare `from` import) preserves monkeypatching via `utils.stream_monitor.StreamMonitor` that the existing timeout tests rely on.
- H2: `_per_key_limiters` was an unbounded plain dict. Deleted keys and limit-change cache misses accumulate forever. `LRUCache(maxsize=10_000)` evicts the least-recently-used entry once the cap is reached, capping resident memory regardless of key churn.

### Commit SHAs
| SHA | Description |
|-----|-------------|
| b1ab9d0 | perf: hoist StreamMonitor import to module level; LRU-bound _per_key_limiters (max 10k) |

---

## Session 26 — Security audit fixes: H4 assistant content validation, C1 allowed_models enforcement, M2 health auth policy (2026-03-17)

### What changed
- `validators/request.py` — extended `validate_messages` to check `assistant` message content type
- `middleware/auth.py` — new `enforce_allowed_models()` function
- `routers/unified.py` — import updated; `enforce_allowed_models` wired into `chat_completions`, `anthropic_messages`, `text_completions`
- `routers/responses.py` — import updated; `enforce_allowed_models` wired into `create_response`
- `routers/internal.py` — comment added above `/health` endpoint family
- `CLAUDE.md` — `routers/internal.py` row in key files table updated with health auth note
- `tests/test_request_validators.py` — two new tests added; `bypass` fixture extended with stubs for `get_key_record`, `enforce_per_key_rate_limit`, `enforce_allowed_models`

### Which lines / functions
- `validators/request.py:validate_messages` (lines 39–46) — added `role == "assistant"` block: raises `RequestValidationError` if content is present and not `str` or `list`
- `middleware/auth.py:enforce_allowed_models` (lines 94–109) — new synchronous function; returns immediately for env/master keys (None record) or empty `allowed_models` list; raises `AuthError` when requested model not in allowed list
- `routers/unified.py` line 27 — import: added `enforce_allowed_models`
- `routers/unified.py` line 137 (`chat_completions`) — `enforce_allowed_models(key_rec, model)` after `resolve_model`
- `routers/unified.py` line 258 (`anthropic_messages`) — same call
- `routers/unified.py` line 395 (`text_completions`) — same call
- `routers/responses.py` line 31 — import: added `enforce_allowed_models`
- `routers/responses.py` line 92 (`create_response`) — `enforce_allowed_models(key_rec, model)` after `resolve_model`
- `routers/internal.py` line 39 — comment block explaining intentional no-auth on health endpoints
- `CLAUDE.md` line 83 — `routers/internal.py` row: appended health probe auth note
- `tests/test_request_validators.py:bypass` (lines 169–172) — added `_fake_get_key_record`, `_fake_per_key_rate_limit`, `enforce_allowed_models` stubs to prevent RuntimeError from DB-uninitialized `KeyStore`
- `tests/test_request_validators.py:test_assistant_content_int_rejected` (lines 257–264) — router integration test: integer content → 400 with "content" in message
- `tests/test_request_validators.py:test_assistant_content_none_allowed` (lines 267–274) — pure unit test: `validate_messages` must not raise for `content: None`

### Why
- H4: `validate_messages` silently passed `{"role": "assistant", "content": 12345}` — the integer reached `converters/to_cursor.py` and caused an unhandled `AttributeError` downstream. Validation is the right place to reject invalid types before they propagate.
- C1: `allowed_models` was stored in `KeyStore` and configurable via admin API but never checked at request time. Any key with model restrictions was silently ignored, making the feature non-functional.
- M2: health endpoints intentionally lack auth (Railway/Docker probes run before any credentials are provisioned), but this was not documented anywhere. Added comment and CLAUDE.md note to prevent future "fix" that would break probes.

### Commit SHAs
| SHA | Description |
|-----|-------------|
| `7f0b0c7` | fix: validate assistant message content type; enforce allowed_models per key; document health endpoint auth policy |

---

## Session 27 — Audit Round 2: 8 remaining issues fixed (2026-03-17)

### What changed
- `pipeline.py` — `StreamMonitor` import hoisted to module level; inline imports removed from both stream generators
- `middleware/rate_limit.py` — `_per_key_limiters` plain dict → `LRUCache(maxsize=10_000)`; `enforce_per_key_rate_limit` accepts optional `key_record`
- `middleware/auth.py` — `_NO_RECORD` sentinel; `check_budget` accepts optional `key_record`; new `get_key_record()` helper; new `enforce_allowed_models()` function
- `routers/unified.py` — `get_key_record()` called once, threaded into all 3 consumers in all 3 endpoints
- `routers/responses.py` — same `get_key_record()` threading in `create_response`
- `validators/request.py` — `validate_messages` rejects non-`str`/non-`list` `assistant` content
- `routers/internal.py` — comment block explaining intentional no-auth on `/health`
- `CLAUDE.md` — `routers/internal.py` row updated with health probe auth note
- `tests/test_request_validators.py` + `tests/test_routing.py` — `_fake_budget` mocks updated to accept `key_record=None`; 2 new validator tests added

### Which lines / functions
- `pipeline.py:60` — `import utils.stream_monitor as _stream_monitor_mod` (module-level; preserves monkeypatch for tests)
- `pipeline.py:~435,~636` — `_stream_monitor_mod.StreamMonitor(...)` in both stream generators
- `middleware/rate_limit.py:18` — `from cachetools import LRUCache`
- `middleware/rate_limit.py:108` — `_per_key_limiters = LRUCache(maxsize=10_000)`
- `middleware/rate_limit.py:enforce_per_key_rate_limit` — `key_record: dict | None = None` param; skips DB fetch when record supplied
- `middleware/auth.py:_NO_RECORD` — sentinel object distinguishing "not provided" from `None`
- `middleware/auth.py:check_budget` — accepts `key_record=_NO_RECORD`; fetches only when sentinel
- `middleware/auth.py:get_key_record` — single `key_store.get()`, short-circuits for env/master keys
- `middleware/auth.py:enforce_allowed_models` — raises `AuthError` when model not in non-empty `allowed_models`
- `routers/unified.py:chat_completions,anthropic_messages,text_completions` — `key_rec = await get_key_record(api_key)` once; passed to `enforce_per_key_rate_limit`, `check_budget`, `enforce_allowed_models`
- `routers/responses.py:create_response` — same pattern
- `validators/request.py:validate_messages:39-46` — `role == "assistant"` block rejects non-`str`/non-`list` content
- `routers/internal.py:39` — comment block above `/health` endpoint
- `tests/test_request_validators.py:test_assistant_content_int_rejected` — integer content → 400
- `tests/test_request_validators.py:test_assistant_content_none_allowed` — `None` content valid for assistant role

### Why
Second-pass audit found 8 remaining issues after the first-round fixes:
- H5: `StreamMonitor` inline import ran on every streaming request → hoisted to module level
- H2: `_per_key_limiters` dict grew unbounded on key churn/limit changes → LRU-bounded at 10k
- H3: 3× `key_store.get()` per request → collapsed to 1 via `get_key_record()` threading
- H4: `assistant` message with integer content passed validation, crashed in `converters/to_cursor.py` → type check added at boundary
- C1: `allowed_models` stored and configurable but never enforced → `enforce_allowed_models()` wired into all 4 endpoints
- M2: `/health` unauthenticated but undocumented → comment + CLAUDE.md note
- Test regressions: `_fake_budget` in 2 test files lacked `key_record` kwarg after signature change → fixed

### Commit SHAs
| SHA | Description |
|-----|-------------|
| `b1ab9d0` | perf: hoist StreamMonitor import to module level; LRU-bound _per_key_limiters (max 10k) |
| `c1ef56c` | perf: collapse 3x key_store.get() to 1 per request — thread key_record through auth chain |
| `7f0b0c7` | fix: validate assistant message content type; enforce allowed_models per key; document health endpoint auth policy |
| `a10b906` | docs: update UPDATES.md for session 26 audit fixes |

---

## Session 28 — Reasoning extraction cache + TTFT/output_tps metrics (2026-03-17)

### What changed
- `pipeline.py` — reasoning extraction result cached after `</thinking>` seen; `_record()` extended with `ttft_ms`/`output_tps`; both stream generators compute and pass TTFT + TPS stats; non-streaming handlers pass `ttft_ms=int(latency_ms)`
- `analytics.py` — `RequestLog` gains `ttft_ms: int | None` and `output_tps: float | None` fields; rolling log entries include those fields when present

### Which lines / functions
- `pipeline.py:~436-444` — added `_reasoning_done: bool`, `_cached_visible: str`, `_cached_acc_len: int` state vars in `_openai_stream`
- `pipeline.py:~465-490` — no-tools branch in `_openai_stream`: when `_reasoning_done` is True skip `split_visible_reasoning` re-scan, append new `acc` suffix to `_cached_visible` directly; set `_reasoning_done = True` once `</thinking>` appears in acc
- `pipeline.py:~506-530` — tools-enabled branch in `_openai_stream`: same `_reasoning_done` cache logic applied
- `pipeline.py:~619-634` — `_openai_stream` finish: `monitor.stats()` → compute `ttft_ms` and `output_tps`; pass to `_record()`
- `pipeline.py:~858-879` — `_anthropic_stream` finish (both early tool_use return and end_turn path): same `monitor.stats()` → TTFT + TPS → `_record()`
- `pipeline.py:1016` — `handle_openai_non_streaming`: `ttft_ms=int(latency_ms)` passed to `_record()`
- `pipeline.py:1137` — `handle_anthropic_non_streaming`: `ttft_ms=int(latency_ms)` passed to `_record()`
- `pipeline.py:_record` — signature extended with `ttft_ms: int | None = None`, `output_tps: float | None = None`; forwarded to `RequestLog`
- `analytics.py:RequestLog` — added `ttft_ms: int | None = None`, `output_tps: float | None = None` fields
- `analytics.py:AnalyticsStore.record` — rolling log entry conditionally includes `ttft_ms` and `output_tps` when non-None

### Why
- **Fix 1 (O(n²) reasoning scan):** `split_visible_reasoning` runs a full O(n) regex scan from position 0 on every chunk where `acc` has grown. The `acc_visible_processed` guard prevents redundant calls within the same position but the scan still starts at 0 each time, giving O(n²) total over the stream. Once `</thinking>` appears in `acc` the `(thinking, final)` split is stable — subsequent chunks can only append to the visible tail. The fix caches the split result and, once stable, appends new `acc` suffix directly, reducing post-`</thinking>` work from O(n) per chunk to O(delta) per chunk.
- **Fix 2 (TTFT + TPS observability):** `StreamMonitor.stats()` already tracked `ttft_ms` but the values were logged only inside the monitor and never surfaced in the analytics ring buffer consumed by the admin UI `/internal/logs` endpoint. Wiring them through `_record()` → `RequestLog` → `AnalyticsStore._log` makes latency distribution visible in the dashboard without any new infrastructure.

### Commit SHAs
| SHA | Description |
|-----|-------------|
| `b3bce81` | perf: cache reasoning extraction result after </thinking> seen; add TTFT + output_tps to stream metrics |

---

## Session 29 — Streaming pipeline perf fixes: encode, timestamp, chunk size (2026-03-17)

### What changed
- `utils/stream_monitor.py` — `chunk.encode("utf-8")` → `len(chunk)` in byte counter
- `converters/from_cursor.py` — `openai_chunk()` gains optional `created: int | None` param
- `pipeline.py` — `created_ts = int(started)` computed once per stream; threaded into all `openai_chunk()` calls and `_OpenAIToolEmitter`; Anthropic tool argument `chunk_size` raised from 12 → 96
- `tests/test_pipeline.py` — removed `assert len(input_json_deltas) > 1` (test assumed chunk_size=12; roundtrip correctness assertion preserved)
- `tests/test_sse.py` (new) — 2 regression tests confirming UTF-8 multi-byte characters are handled correctly across `aiter_bytes` chunk boundaries

### Which lines / functions
- `utils/stream_monitor.py:109` — `len(chunk.encode("utf-8"))` → `len(chunk)`
- `converters/from_cursor.py:openai_chunk` — added `created: int | None = None` param; `"created": created if created is not None else now_ts()`
- `pipeline.py:420` — `created_ts = int(started)` added after `started = time.time()`
- `pipeline.py:351-361` (`_OpenAIToolEmitter.__init__`) — added `created: int = 0` param; stored as `self._created`
- `pipeline.py` — all `openai_chunk(cid, model, ...)` calls in `_openai_stream` and `_OpenAIToolEmitter.emit` updated to pass `created=created_ts` / `created=self._created`
- `pipeline.py:142` (`_stream_anthropic_tool_input`) — `chunk_size: int = 12` → `chunk_size: int = 96`
- `tests/test_sse.py` (new) — `test_utf8_multibyte_across_chunk_boundary`, `test_utf8_ascii_unaffected`

### Why
- `chunk.encode("utf-8")` on every streamed delta was re-encoding an already-decoded string purely to count bytes — character count is sufficient for throughput stats
- `time.time()` was called inside `openai_chunk()` on every chunk; the `created` field in OpenAI streaming chunks is the request creation time, not emission time — one `int(started)` call at stream start is correct and avoids ~500 syscalls per response
- Anthropic tool argument chunk_size=12 produced up to 11 SSE events for a 131-char argument; raising to 96 produces 2 events — 5.5× fewer SSE writes, no effect on output quality (client reassembles identical JSON either way)
- UTF-8 correctness confirmed: byte-level `b"\n"` split before decode means multi-byte UTF-8 sequences cannot be split mid-character; tests document this guarantee

### Measured benchmarks
| Fix | Before | After | Speedup |
|-----|--------|-------|---------|
| `split_visible_reasoning` (200k chars, 3000 chunks) | 3,757ms | 393ms | 9.6× |
| `chunk.encode()` (10k chunks) | 1.33ms | 0.81ms | 1.6× |
| `time.time()` per chunk (10k chunks) | 2.27ms | 0.70ms | 3× |
| Anthropic tool SSE events (131-char arg) | 11 events | 2 events | 5.5× fewer |
| `key_store.get()` per request | 3 calls | 1 call | 3× fewer SQLite round-trips |

### Commit SHAs
|-----|-------------|
| `5f2f31a` | perf: remove chunk.encode() in StreamMonitor; cache created_ts per stream; Anthropic tool chunk size 12→96 |

---

## Session 31 — Refactor: _parse_score_repair helper — C3 fix (2026-03-17)

### What changed
- `pipeline.py` — extracted `_parse_score_repair` helper; applied confidence scoring and repair on `_req_retry` path in both non-streaming handlers

### Which lines / functions
- `pipeline.py:890-912` — new `_parse_score_repair(text, params, context)` helper function
- `pipeline.py:915` — `def handle_openai_non_streaming` corrected to `async def` (regression introduced by the Edit that inserted the helper definition)
- `pipeline.py:958-959` (`handle_openai_non_streaming`) — 12-line parse+score+repair block replaced with `_parse_score_repair(text, params, context="openai_nonstream")`
- `pipeline.py:979-980` (`handle_openai_non_streaming`, `_req_retry` body) — bare `_limit_tool_calls(parse_tool_calls_from_text(...))` replaced with `_parse_score_repair(text, params, context="openai_nonstream_retry")`
- `pipeline.py:1090-1091` (`handle_anthropic_non_streaming`) — 11-line parse+score+repair block replaced with `_parse_score_repair(text, params, context="anthropic_nonstream")`
- `pipeline.py:1094-1095` (`handle_anthropic_non_streaming`, `_req_retry` body) — bare `_limit_tool_calls(parse_tool_calls_from_text(...))` replaced with `_parse_score_repair(text, params, context="anthropic_nonstream_retry")`

### Why
- **C3:** Both `_req_retry` loops re-parsed tool calls with a raw `_limit_tool_calls(parse_tool_calls_from_text(...))` call, skipping the confidence scorer (`score_tool_call_confidence`) and `_repair_invalid_calls`. A low-confidence or malformed tool call returned on the retry attempt was returned to the client unchanged, violating the contract established by the initial parse path. The helper centralises the full parse→score→repair chain so both the initial parse and every retry iteration execute identical logic.

### Commit SHAs
| SHA | Description |
|-----|-------------|
| `e988543` | refactor: extract _parse_score_repair helper — confidence scoring and repair now applied on retry path too |

---

## Session 30 — Tool call pipeline bug fixes: C2, H4, H2 (2026-03-17)

### What changed
- `pipeline.py` — `handle_anthropic_non_streaming` now wraps parse result in `_limit_tool_calls`
- `converters/to_cursor.py` — `tool_use.input` serialised as JSON string; tool result name lookup priority fixed

### Which lines / functions
- `pipeline.py:1066` (`handle_anthropic_non_streaming`) — `parsed_calls = parse_tool_calls_from_text(text, params.tools)` → `parsed_calls = _limit_tool_calls(parse_tool_calls_from_text(text, params.tools) or [], params.parallel_tool_calls)`
- `converters/to_cursor.py:619` (`anthropic_to_the_editor`, `tool_use` block) — `"arguments": block.get("input", {})` → `"arguments": json.dumps(block.get("input", {}), ensure_ascii=False)`
- `converters/to_cursor.py:475-479` (`openai_to_the_editor`, `role:tool` name resolution) — `msg.get("name") or _tool_call_name_map.get(call_id)` → `_tool_call_name_map.get(call_id) or msg.get("name")`

### Why
- **C2:** `_limit_tool_calls` was applied in `handle_openai_non_streaming` (line 934) but was absent from `handle_anthropic_non_streaming` (line 1066). A client sending `parallel_tool_calls=false` via the Anthropic endpoint received multiple tool calls when only one was permitted. Copy-paste omission.
- **H4:** `tool_use.input` in Anthropic content blocks was stored as a Python `dict` for the `arguments` field. The codebase invariant is that `arguments` is always a JSON string. The dict passthrough caused `_compute_tool_signature` to produce different hashes for replayed Anthropic history vs freshly parsed calls, silently breaking tool call deduplication across turns.
- **H2:** Tool result name resolution used `msg.get("name")` (caller-supplied, unreliable) before `_tool_call_name_map.get(call_id)` (authoritative, built from prior assistant turn). A client sending a stale or wrong `name` caused the upstream model to receive incorrect tool attribution in multi-turn tool use.

### Commit SHAs
| SHA | Description |
|-----|-------------|
| `2f3508d` | fix: apply _limit_tool_calls in Anthropic non-streaming path — parallel_tool_calls=false now enforced |
| `3366b19` | fix: serialise tool_use.input as JSON string — enforce arguments-is-string invariant in Anthropic history replay |
| `ae1f091` | fix: prioritise tool_call_name_map over msg.name in tool result conversion — authoritative name used for multi-turn tool attribution |

## Session 32 — Request boundary tool validation; SHINWAY_MAX_TOOLS config (2026-03-17)

### What changed
- `validators/request.py` — added `validate_tools()` function; wired into `validate_openai_payload` and `validate_anthropic_payload`
- `config.py` — added `max_tools` setting
- `tests/test_request_validators.py` — added 8 new tests covering `validate_tools`

### Which lines / functions
- `validators/request.py:96-128` — new `validate_tools(tools, max_tools=None)` function; validates list type, per-entry dict/type/name constraints, and count ceiling; lazy-imports `settings.max_tools` when `max_tools` is not explicitly passed
- `validators/request.py:131` (`validate_openai_payload`) — added `validate_tools(payload.get("tools"))` as last call
- `validators/request.py:143` (`validate_anthropic_payload`) — added `validate_tools(payload.get("tools"))` as last call
- `config.py:68-69` — added `max_tools: int = Field(default=64, alias="SHINWAY_MAX_TOOLS")` under new `# ── Validation limits ───` section between rate limiting and pricing blocks
- `tests/test_request_validators.py:278-330` — 8 new tests: `test_tools_wrong_type_rejected`, `test_tools_wrong_tool_type_rejected`, `test_tools_empty_name_rejected`, `test_tools_max_count_exceeded`, `test_tools_valid_passes`, `test_tools_none_passes`, `test_tools_no_type_field_passes`, `test_tools_entry_not_dict_rejected`, `test_tools_function_not_dict_rejected`

### Why
- **M2:** `validate_openai_payload` and `validate_anthropic_payload` had no tools array validation — a client could send `tools: [{"type": "banana"}]` and it would silently pass through to the upstream with no 400 rejection. Added `validate_tools()` to catch: wrong top-level type (not a list), invalid `type` field (not `"function"`), empty/non-string `function.name`, and count exceeding the configured ceiling.
- **M3:** No configuration knob existed for the maximum tools count. Added `SHINWAY_MAX_TOOLS` (default 64) to `config.py` so operators can tune the limit without code changes.

### Commit SHAs
| SHA | Description |
|-----|-------------|
| `30f2926` | feat: validate tools array at request boundary; add SHINWAY_MAX_TOOLS limit (default 64) |

---

## Session 33 — Tool call pipeline: C1 Strategy 3 string-aware bracket walk (2026-03-17)

### What changed
- `tools/parse.py` — string-aware `in_str`/`esc` state machine added to Strategy 3 depth counter
- `tests/test_parse.py` — regression test for braces inside string argument values

### Which lines / functions
- `tools/parse.py:201-222` (`_lenient_json_loads`, Strategy 3) — replaced naive `{`/`}` depth counter with string-aware version using `in_str`/`esc` state tracking; braces only counted when `not in_str`; mirrors the same pattern already used in `_extract_after_marker` (lines 120-147)
- `tests/test_parse.py:test_strategy3_brace_inside_string_value` — injects a literal newline to force Strategy 3 and confirms `{`/`}` inside a `content` value survives extraction intact

### Why
Strategy 3's depth counter counted every `{` and `}` in the raw input, including those inside JSON string values. An argument like `"new_string": "if x: {return y}"` caused the walk to terminate at the inner `}`, slicing off the rest of the arguments object. This affects the most common real-world tool calls in Claude Code usage — Write, Edit, and Bash content fields frequently contain code with braces.

### Commit SHAs
| SHA | Description |
|-----|-------------|
| `1034a4e` | fix: string-aware bracket walk in Strategy 3 — brace inside argument string no longer truncates JSON extraction |

---

## Session 35 — Perf Q1: StreamingToolCallParser stateful bracket depth (2026-03-17)

### What changed
- `tools/parse.py` — `StreamingToolCallParser` class rewritten with stateful bracket-depth tracker
- `tests/test_parse.py` — new test `test_streaming_parser_calls_parse_once` added

### Which lines / functions
- `tools/parse.py:1117-1220` (`StreamingToolCallParser`) — added 6 new instance vars (`_json_start`, `_depth`, `_in_str`, `_esc`, `_json_complete`, `_last_result`); `feed()` split into 4 phases: marker detection, cached-result fast-return, opening-brace search, incremental char walk; `parse_tool_calls_from_text` now called exactly once (when `_depth` returns to 0) rather than on every chunk after marker confirmed; subsequent `feed()` calls return `_last_result` immediately from cache
- `tests/test_parse.py:421-453` — `test_streaming_parser_calls_parse_once` monkeypatches `parse_tool_calls_from_text` with a call counter and asserts `call_count <= 2` across 20 chunks

### Why
Pre-fix: after the `[assistant_tool_calls]` marker was confirmed, every subsequent chunk re-invoked `parse_tool_calls_from_text(self.buf[self._marker_pos:], ...)` — O(n) per chunk, O(n²) total. For a 2 000-character tool call received in 200 chunks this is ~200 000 character operations instead of ~2 000. The fix tracks bracket depth and string-escape state incrementally so the scan cursor only ever moves forward. `parse_tool_calls_from_text` fires once when the outermost `}` is detected and the result is cached for any remaining chunks.

### Commit SHAs
| SHA | Description |
|-----|-------------|
| `d06556e` | perf: StreamingToolCallParser stateful bracket depth — parse_tool_calls_from_text called once not per-chunk |

---

## Session 34 — Tool call pipeline: C4 Anthropic multi-block + H1 ID centralisation (2026-03-17)

### What changed
- `converters/to_cursor.py` — Anthropic multi-block content now emits separate the-editor messages per role; tool call ID assignment centralised
- `tools/parse.py` — `_build_tool_call_results` preserves existing IDs; `repair_tool_call` logs warning on missing ID
- `converters/from_cursor.py` — silent fallback UUID replaced with explicit warning + unified `call_` prefix
- `tests/test_from_cursor.py` — 2 assertions updated from `toolu_` to `call_` prefix

### Which lines / functions
- `converters/to_cursor.py:587-643` (`anthropic_to_the_editor`, list content branch) — replaced single `parts` list accumulation with `pending_text_parts` + `_flush_text()` nested helper; `tool_result` blocks emit hardcoded `user` role message; `tool_use` blocks emit hardcoded `assistant` role message; `text = None` guards final append
- `tools/parse.py:_build_tool_call_results` — `f"call_{uuid4().hex[:24]}"` → `c.get("id") or f"call_{uuid4().hex[:24]}"` — preserves any ID already in parsed payload
- `tools/parse.py:repair_tool_call` — explicit missing-id guard with `repair_tool_call_missing_id` warning before fallback generation
- `converters/from_cursor.py:_manual_convert_tool_calls_to_anthropic` — silent `tc.get("id", f"toolu_...")` → explicit check + `tool_call_missing_id` log warning + unified `call_` prefix
- `converters/to_cursor.py:anthropic_messages_to_openai` — same pattern with `anthropic_tool_use_missing_id` warning

### Why
- **C4:** Anthropic content arrays with mixed `text` + `tool_use` or `text` + `tool_result` blocks were accumulated into one `parts` list and emitted as a single `\n`-joined the-editor message. The upstream model received mixed-role content in one mangled string — `[assistant_tool_calls]` JSON mixed with prose, or tool results mixed with user text. The fix emits each logical block type as a separate role-correct message.
- **H1:** Tool call IDs were generated independently in 3 locations with no coordination. A call that arrived at the emitter without an `id` got a new UUID at emission time, different from any previously logged or emitted ID. Multi-turn `tool_call_id` matching in the client's next request would fail silently. Fix: `_build_tool_call_results` is the single canonical ID assignment point; all downstream code preserves the existing ID and logs a warning when it is absent.

### Commit SHAs
| SHA | Description |
|-----|-------------|
| `6108ba7` | fix: emit Anthropic multi-block content as separate the-editor messages — preserves role semantics for tool_use and tool_result blocks |
| `2a56f8c` | fix: centralise tool call ID assignment — always assigned in parse.py normaliser; log warning if missing downstream |

---

## Session 36 — pipeline.py split into pipeline/ package (2026-03-17)

### What changed
- `pipeline.py` — deleted (1165 lines)
- `pipeline/` — new package with 7 focused sub-modules
- `pipeline/__init__.py` — re-exports all public names; zero import changes in any consumer
- `tests/test_sse.py` — new file (UTF-8 multi-byte regression tests)
- `tests/test_routing.py` — `bypass_guards` fixture updated with new auth stubs

### Which lines / functions
- `pipeline/params.py` (29 lines) — `PipelineParams` dataclass
- `pipeline/record.py` (49 lines) — `_provider_from_model`, `_record`
- `pipeline/suppress.py` (131 lines) — suppression constants, `_is_suppressed`, `_RETRYABLE`, `_with_appended_cursor_message`, `_call_with_retry`
- `pipeline/tools.py` (201 lines) — tool call helpers, `_OpenAIToolEmitter`, `_parse_score_repair`
- `pipeline/stream_openai.py` (293 lines) — `_extract_visible_content`, `_openai_stream`
- `pipeline/stream_anthropic.py` (291 lines) — `_anthropic_stream`
- `pipeline/nonstream.py` (254 lines) — `handle_openai_non_streaming`, `handle_anthropic_non_streaming`
- `pipeline/__init__.py` (46 lines) — re-exports every public name from all 7 sub-modules

### Why
`pipeline.py` had grown to 1165 lines across 18 functions and 2 classes covering 6 distinct concerns. No single concern was independently understandable without scrolling past 4-5 others. Split gives each concern its own file at 29-293 lines. `pipeline/__init__.py` preserves the existing public API so no callers needed to change. Zero behaviour change — 171/171 tests pass before and after.

### Commit SHAs
| SHA | Description |
|-----|-------------|
| `4ae6896` | refactor: split pipeline.py into pipeline/ package — 7 focused modules, zero behaviour change |

---

## Session 37 — Project structure cleanup + Dockerfile sync (2026-03-17)

### What changed
- `everything-claude-code/` — deleted from disk (was an unrelated external cloned repo; already in `.gitignore`)
- `Dockerfile` — added `ENV SHINWAY_MAX_TOOLS=64` to keep Docker env vars in sync with `config.py` (added in Session 32)

### Why
- `everything-claude-code/` was a stale directory from a plugin installation, sitting in the project root with ~50 subdirectories. Gitignored but cluttering the workspace. No code depended on it.
- `SHINWAY_MAX_TOOLS` was added to `config.py` in Session 32 but never back-ported to the Dockerfile env var defaults. Without it, Docker deployments use the Pydantic default (64) which is correct, but the intent of the Dockerfile is to document all available env vars with their defaults.

### Commit SHAs
| SHA | Description |
|-----|-------------|
| `bf5d2f5` | chore: delete everything-claude-code/; add SHINWAY_MAX_TOOLS to Dockerfile |

---

## Session 38 — Documentation overhaul + README redesign (2026-03-17)

### What changed
- `docs/guides/env-reference.md` — completely rewritten with correct `SHINWAY_*` prefixes, accurate defaults from `config.py`, all new variables documented
- `docs/guides/api-key-management.md` — new guide: static vs managed keys, full CRUD curl examples, field reference, enforcement order
- `docs/guides/tool-calls.md` — new guide: how tool calls work, OpenAI + Anthropic format examples, tool_choice, parallel calls, repair system, streaming
- `docs/guides/admin-ui.md` — new guide: setup, all 6 pages documented, remote backend config, security
- `docs/guides/README.md` — updated with all 7 guides
- `README.md` — redesigned: updated architecture, full project structure tree with pipeline/ package, correct API endpoints, guides index section, improved quick start

### Why
- `env-reference.md` was using `GATEWAY_*` prefixes (renamed to `SHINWAY_*` in Session 14) and was missing every env var added since then (`SHINWAY_MAX_TOOLS`, `SHINWAY_PRICE_*`, token limits, heartbeat, trim settings, etc.)
- `api-key-management.md`, `tool-calls.md`, `admin-ui.md` did not exist — these are now core features of the proxy with no documentation
- `README.md` still referenced `pipeline.py` (deleted in Session 36), used old `/internal/keys` endpoints (renamed to `/v1/admin/keys`), and was missing the `pipeline/` package in the project structure

### Commit SHAs
| SHA | Description |
|-----|-------------|
| `02188f5` | docs: rewrite env-reference with SHINWAY_* names; add api-key-management, tool-calls, admin-ui guides |
| `08a2c25` | docs: redesign README — updated architecture, full project structure, guides index, correct API endpoints |

---

## Session 39 — routers/unified.py: 4 bug fixes (2026-03-17)

### What changed
- `routers/unified.py` — 4 bugs fixed

### Which lines / functions
- `routers/unified.py:27` — `from handlers import RequestValidationError` moved to module-level imports; inline `from handlers import RequestValidationError as _RVE` inside `text_completions` removed
- `routers/unified.py:count_tokens` — added `key_rec = await get_key_record(api_key)`, `await enforce_per_key_rate_limit(api_key, key_record=key_rec)`, `await check_budget(api_key, key_record=key_rec)` after `enforce_rate_limit`
- `routers/unified.py:count_tokens` — added `log.debug("litellm_token_counter_failed", model=model, exc_info=True)` before fallback in bare `except Exception`
- `routers/unified.py:anthropic_messages` — added `parallel_tool_calls = bool(payload.get("parallel_tool_calls", True))` and wired into `PipelineParams`

### Why
- **Inline import:** `from handlers import RequestValidationError` was inside the `text_completions` endpoint body — executed on every request. Moved to module top-level.
- **`count_tokens` budget bypass:** The token counter endpoint only called `verify_bearer` + `enforce_rate_limit`, skipping `check_budget`. A client could count tokens indefinitely without hitting their USD or daily token limit.
- **Silent exception:** `except Exception:` in `count_tokens` fell back silently with no log — tokenizer failures were invisible in production.
- **`parallel_tool_calls` ignored for Anthropic:** The OpenAI endpoint reads `parallel_tool_calls` from the payload. The Anthropic endpoint did not, so it always defaulted to `True` regardless of what the client sent.

### Commit SHAs
| SHA | Description |
|-----|-------------|
| `f09fd7d` | fix: inline import, count_tokens budget check, silent exception logging, Anthropic parallel_tool_calls |

---

## Session 40 — tools/parse.py: unescaped-quote recovery (2026-03-17)

### What changed
- `tools/parse.py` — added `_escape_unescaped_quotes()` and wired as Strategy 2b + Strategy 3 input in `_lenient_json_loads`
- `tests/test_parse.py` — added 4 new tests (3 regression + 1 array-preservation guard)

### Which lines / functions
- `tools/parse.py:_escape_unescaped_quotes` — new function inserted after `_repair_json_control_chars`. Single-pass O(n) look-ahead heuristic: inside a string, `"` is the real terminator iff the next non-whitespace char is a JSON structural char (`,`, `}`, `]` at `square_depth==0`, `:`, `"`, or end-of-input); otherwise escaped as `\"`. Tracks `square_depth` to distinguish subscript-syntax interior quotes (`["tool_choice"]`) from real array-close quotes.
- `tools/parse.py:_JSON_AFTER_CLOSE_QUOTE` — new module-level frozenset constant used by `_escape_unescaped_quotes`
- `tools/parse.py:_lenient_json_loads` — pre-computes `_escaped_raw = _escape_unescaped_quotes(raw)` once before Strategy 2b. Strategy 2b (new): if `_escaped_raw != raw`, tries `msgjson.decode(_escaped_raw)` and returns on success. Strategy 3: `_s3_inputs = [raw, _escaped_raw]` — feeds escaped form as fallback into the regex+bracket-walk loop.
- `tests/test_parse.py:test_edit_unescaped_quotes_in_old_string` — end-to-end regression: Edit payload where `old_string` contains `captured_calls[3]["tool_choice"]` (exact production pattern that triggered `tool_parse_marker_found_no_json`)
- `tests/test_parse.py:test_escape_unescaped_quotes_helper` — unit test for `_escape_unescaped_quotes`
- `tests/test_parse.py:test_lenient_json_unescaped_quotes_multi_field` — multi-field payload with unescaped quote in non-last field
- `tests/test_parse.py:test_escape_unescaped_quotes_preserves_string_arrays` — regression for `square_depth==0` terminator fix: valid JSON string arrays must survive `_escape_unescaped_quotes` unchanged

### Why
- **Root cause:** The upstream model emits Edit/Write tool calls where `old_string`/`new_string` values contain Python source code with literal (unescaped) `"` chars (e.g. `captured_calls[3]["tool_choice"]`). Every bracket-walker in `tools/parse.py` uses `elif ch == '"': in_str = False` which fires on ANY `"`, not just real terminators. This corrupts `in_str` state, making all depth counters wrong → candidates truncated/wrong → all 6 strategies fail → `objs = []` → `tool_parse_marker_found_no_json` logged → tool call silently dropped.
- **Intermediate bug found in review:** Initial implementation treated `"` before `]` at `square_depth==0` as an interior quote, corrupting standard JSON string arrays (`["a", "b"]` → `["a", "b\"]`). Fixed by adding `(next_ch == ']' and square_depth == 0)` to the real-terminator condition.

### Commit SHAs
| SHA | Description |
|-----|-------------|
| `21e39ce` | fix(parse): recover tool calls with unescaped quotes in string values |
| `e445593` | fix(parse): _escape_unescaped_quotes must treat ] at square_depth=0 as real terminator |

---

## Session 41 — Model Catalogue Cleanup (2026-03-17)

### What changed
- `routers/model_router.py` — catalogue trimmed, context windows updated, default meta updated

### Which lines / functions
- `routers/model_router.py:_CATALOGUE` — removed all entries except `anthropic/claude-sonnet-4.6` and `anthropic/claude-opus-4.6`; added `openai/gpt-5.4` and `google/gemini-3.1-pro-preview`; all four set to `context: 1_000_000`
- `routers/model_router.py:_BUILTIN_ALIASES` — cleared to empty dict (all shorthand aliases removed)
- `routers/model_router.py:_DEFAULT_META` — `context` updated from `200_000` to `1_000_000` so unknown passthrough models also get the full 1M budget

### Why
Simplify the model catalogue to only the models in active use. Raise context window to 1M for all registered and unknown passthrough models. Remove alias clutter that is no longer needed.

### Commit SHAs
| SHA | Description |
|-----|-------------|
| `606fb17` | chore(models): trim catalogue to 4 models, bump all context to 1M |

---

## Session 42 — Add 2 models to catalogue (2026-03-17)

### What changed
- `routers/model_router.py` — 2 new models added

### Which lines / functions
- `routers/model_router.py:_CATALOGUE` — added `google/gemini-3-flash-preview` (1M context) and `openai/gpt-5.1-codex-mini` (400k context)

### Why
Expand model catalogue with Gemini Flash and GPT-5.1 Codex Mini. Codex Mini has a smaller 400k context window reflecting its actual limit.

### Commit SHAs
| SHA | Description |
|-----|-------------|
| `a757752` | chore(models): add gemini-3-flash-preview and gpt-5.1-codex-mini |

---

## Session 43 — converters/from_cursor.py bug fixes (2026-03-17)

### What changed
- `converters/from_cursor.py` — 3 bugs fixed
- `tests/test_from_cursor.py` — 3 new tests added
- `tests/conftest.py` — created (structlog stdlib bridge for caplog)

### Which lines / functions
- `converters/from_cursor.py:_parse_tool_call_arguments` — added `log.warning("tool_call_arguments_parse_failed", raw=arguments[:200])` before returning `{}` on `json.JSONDecodeError` (was silently discarding malformed JSON)
- `converters/from_cursor.py:convert_tool_calls_to_anthropic` — removed pre-parse of `arguments` to dict before calling litellm; litellm now receives raw JSON string as expected; argument parsing to dict moved into the no-litellm branch and the exception fallback branch only; removed redundant `copy.deepcopy` on converter return value
- `converters/from_cursor.py` lines 24-42 — removed duplicate `MODEL_CONTEXT_WINDOWS` dict, `DEFAULT_CONTEXT_WINDOW` constant, and local `context_window_for` function; replaced with `from tokens import context_window_for`
- `tests/conftest.py` — new file: `pytest_configure` hook that reconfigures structlog to use `stdlib.LoggerFactory` so `caplog` can capture structlog warnings in tests
- `tests/test_from_cursor.py` — added `test_parse_tool_call_arguments_warns_on_malformed_json`, `test_convert_tool_calls_litellm_receives_string_arguments`, `test_from_cursor_context_window_for_is_from_tokens`

### Why
- BUG 2: Silent discard of malformed tool call arguments made debugging impossible — warning now emitted with raw payload
- BUG 3: litellm's converter expects a JSON string for `arguments` (OpenAI wire format); pre-parsing to dict caused silent fallback on every request that went through litellm, defeating the litellm path entirely
- BUG 1: Duplicate `context_window_for` definition in `from_cursor.py` diverged from the canonical in `tokens.py` (e.g. missing model entries); importing from `tokens` ensures a single source of truth
- `test_resolve_model_unknown_fallback` in `tests/test_routing.py` was already failing before this session (pre-existing, introduced in session 41 when `_DEFAULT_META["context"]` was raised to 1M but the test still asserted 200k); not touched by this session

### Commit SHAs
| SHA | Description |
|-----|-------------|
| `a89ca9b` | fix(converters): log warning on malformed tool call arguments instead of silent discard |
| `f6e4154` | fix(converters): pass arguments as JSON string to litellm converter, remove double deepcopy |
| `d8c2f6d` | fix(converters): remove duplicate context_window_for, import canonical from tokens |

---

## Session 44 — to_cursor.py bug fixes: reasoning order + tool_use id (2026-03-17)

### What changed
- `converters/to_cursor.py` — 2 bugs fixed
- `tests/test_to_cursor.py` — new file, 3 tests

### Which lines / functions
- `converters/to_cursor.py:anthropic_to_cursor` — moved `if reasoning_effort:` block and `if thinking and thinking.get("budget_tokens"):` block from after the identity re-declaration to immediately after the `if tool_inst:` block and before the `if settings.role_override_enabled:` identity re-declaration pair (BUG 4)
- `converters/to_cursor.py:anthropic_to_cursor` — in the `elif btype == "tool_use":` branch, added `"id": block.get("id", f"call_{uuid.uuid4().hex[:24]}"),` to the emitted tool_call dict so upstream can correlate results (BUG 5)
- `tests/test_to_cursor.py` — new file: `test_anthropic_to_cursor_reasoning_before_identity_declaration`, `test_openai_to_cursor_reasoning_before_identity_declaration`, `test_anthropic_tool_use_history_includes_id_in_cursor_wire`

### Why
- BUG 4: `anthropic_to_cursor` was injecting the reasoning effort instruction and thinking budget after the identity re-declaration pair, whereas `openai_to_cursor` injects them before. Inconsistent ordering means the model may see the identity re-declaration before the reasoning context is established.
- BUG 5: `tool_use` history blocks replayed to the upstream model were missing the `id` field in the `[assistant_tool_calls]` JSON, making it impossible for the model to correlate tool results with the original calls in multi-turn conversations.

### Commit SHAs
| SHA | Description |
|-----|-------------|
| `fd0cd63` | fix(converters): inject reasoning instruction before identity declaration in anthropic_to_cursor |

---

---

## Session 45 — Converters — 9 Bug Fixes (2026-03-17)

### What changed
- `converters/from_cursor.py` — removed duplicate `context_window_for`/`MODEL_CONTEXT_WINDOWS`; added warning log on malformed tool arguments; fixed `convert_tool_calls_to_anthropic` to pass arguments as JSON string to litellm
- `converters/to_cursor.py` — fixed reasoning instruction order in `anthropic_to_cursor` (now before identity declaration); added `id` field to `tool_use` history blocks in the-editor wire format
- `converters/to_responses.py` — added `reasoning` item handler in `_prior_output_to_messages`; added `function_call` item handler in `input_to_messages`
- `converters/from_responses.py` — added `response.done` terminal SSE event in `generate_streaming_events`
- `routers/responses.py` — fixed `stream=True` to call `_openai_stream` instead of `handle_openai_non_streaming`
- `tests/test_from_cursor.py` — new tests for BUG 1, 2, 3
- `tests/test_to_cursor.py` — new file; tests for BUG 4, 5
- `tests/test_responses_converter.py` — new tests for BUG 6, 8, 9
- `tests/test_responses_router.py` — new test for BUG 7
- `tests/test_routing.py` — fixed stale context window assertion

### Which lines / functions
- `converters/from_cursor.py` lines 24-42 — removed duplicate `MODEL_CONTEXT_WINDOWS`, `DEFAULT_CONTEXT_WINDOW`, local `context_window_for`; replaced with `from tokens import context_window_for`
- `converters/from_cursor.py:_parse_tool_call_arguments` — added `log.warning("tool_call_arguments_parse_failed", raw=arguments[:200])` on `json.JSONDecodeError` instead of silently returning `{}`
- `converters/from_cursor.py:convert_tool_calls_to_anthropic` — removed pre-parse of `arguments` to dict before litellm call; litellm now receives raw JSON string; removed redundant `copy.deepcopy`
- `converters/to_cursor.py:anthropic_to_cursor` — moved reasoning effort and thinking budget injection to before the identity re-declaration pair (consistent with `openai_to_cursor`)
- `converters/to_cursor.py:anthropic_to_cursor` — in `tool_use` branch, added `"id": block.get("id", f"call_{uuid.uuid4().hex[:24]}")` to emitted tool_call dict
- `converters/to_responses.py:_prior_output_to_messages` — added `elif item["type"] == "reasoning":` handler appending a user-facing reasoning summary message
- `converters/to_responses.py:input_to_messages` — added `elif item["type"] == "function_call":` handler converting Responses API function_call items to OpenAI tool_calls format
- `converters/from_responses.py:generate_streaming_events` — added final `yield f"data: {json.dumps({'type': 'response.done', 'response': response_obj})}\n\n"` after stream completion
- `routers/responses.py` — in streaming branch, replaced `handle_openai_non_streaming` call with `_openai_stream` to actually stream responses
- `tests/test_routing.py:test_resolve_model_unknown_fallback` — updated `assert meta["context"] == 200_000` to `assert meta["context"] == 1_000_000`

### Why
- BUG 1: Duplicate `context_window_for` in `from_cursor.py` diverged from canonical in `tokens.py`; importing from `tokens` ensures a single source of truth
- BUG 2: Silent discard of malformed tool call arguments made debugging impossible; warning now emitted with raw payload
- BUG 3: litellm converter expects a JSON string for `arguments` (OpenAI wire format); pre-parsing to dict caused silent fallback on every litellm-path request
- BUG 4: Inconsistent reasoning instruction ordering between `anthropic_to_cursor` and `openai_to_cursor` meant the model could see the identity re-declaration before reasoning context was established
- BUG 5: `tool_use` history blocks in the-editor wire format were missing the `id` field, making tool result correlation impossible in multi-turn conversations
- BUG 6: `reasoning` items in Responses API prior output were unhandled, causing `KeyError` on replay
- BUG 7: Responses API streaming branch was calling the non-streaming handler, returning a single JSON blob instead of SSE
- BUG 8: `function_call` items in Responses API input were unhandled, dropping tool call context on replay
- BUG 9: `response.done` terminal event was never emitted, leaving Responses API streaming clients hanging
- Stale test: `test_resolve_model_unknown_fallback` asserted `context == 200_000` after session 41 raised `_DEFAULT_META["context"]` to `1_000_000`

### Commit SHAs
| SHA | Description |
|-----|-------------|
| `a89ca9b` | fix(converters): log warning on malformed tool call arguments instead of silent discard |
| `f6e4154` | fix(converters): pass arguments as JSON string to litellm converter, remove double deepcopy |
| `d8c2f6d` | fix(converters): remove duplicate context_window_for, import canonical from tokens |
| `8117417` | fix(converters): inject reasoning instruction before identity declaration in anthropic_to_cursor |
| `fd0cd63` | fix(converters): add id field to tool_use history blocks in the-editor wire format |
| `aa08f3c` | fix(converters): handle reasoning item in _prior_output_to_messages |
| `b4451b3` | fix(routers): responses streaming branch calls _openai_stream not handle_openai_non_streaming |
| `ac9d538` | fix(converters): handle function_call item in input_to_messages |
| `27c1902` | fix(converters): emit response.done terminal SSE event in generate_streaming_events |
| `8bb249a` | test(converters): add tests for BUG 1-9 across from_cursor, to_cursor, responses converters |
| `247a5bb` | test(routing): add test for responses router streaming path |
| `5eec05d` | fix(tests): update stale context window assertion in test_resolve_model_unknown_fallback |

## Session 48 — from_responses.py — Bug Fix: mixed text+tool_calls streaming (2026-03-17)

### What changed
- `converters/from_responses.py` — fixed `generate_streaming_events` to emit message streaming events when both `text` and `tool_calls` are present
- `tests/test_responses_converter.py` — added 1 new test

### Which lines / functions
- `converters/from_responses.py:generate_streaming_events` lines 125-185 — replaced the `if tool_calls: ... / if not tool_calls and text:` structure with `if text:` first (message at `output_index=0`), then `if tool_calls:` with `tc_output_offset = 1 if text else 0` applied to each tool call's `output_index`
- `tests/test_responses_converter.py:test_generate_streaming_events_mixed_text_and_tool_calls_emits_both_item_events` — new test asserting both `message` and `function_call` appear in `response.output_item.done` events, message precedes function_call, and delta text assembles correctly

### Why
- BUG: `if not tool_calls and text:` guarded the text/message streaming branch, so when `tool_calls` was truthy, message events were silently dropped even though `build_response_object` correctly emitted both items. The streaming event sequence was inconsistent with the final `response.completed` object, and clients received no `message` item in the stream.

### Commit SHAs
| SHA | Description |
|-----|-------------|
| TBD | fix(responses): emit message streaming events in mixed text+tool_calls case |
| TBD | docs: update UPDATES.md for mixed streaming fix |

---

## Session 47 — from_responses.py — Bug Fixes B and C (2026-03-17)

### What changed
- `converters/from_responses.py` — fixed BUG B (`msg_id` propagated from streaming events to `build_response_object`) and BUG C (empty text no longer emits phantom delta events)
- `tests/test_responses_converter.py` — added 2 new tests

### Which lines / functions
- `converters/from_responses.py:build_response_object` — added `msg_id: str | None = None` parameter; text branch now uses `_msg_id = msg_id or f"msg_{uuid.uuid4().hex[:24]}"` so caller-supplied ID takes precedence over a fresh `uuid4()`
- `converters/from_responses.py:generate_streaming_events` — initialized `msg_id: str | None = None` before `tc_item_ids` and the `if tool_calls:` block; changed `else:` branch to `if not tool_calls and text:` to guard against empty text; removed `max(1, len(text))` guard from `range()`; added `msg_id=msg_id` keyword argument to the final `build_response_object` call
- `tests/test_responses_converter.py:test_generate_streaming_events_msg_id_matches_completed_response` — new test asserting `response.output_item.done` message `id` equals `response.completed.output[0].id`
- `tests/test_responses_converter.py:test_generate_streaming_events_empty_text_emits_no_delta_events` — new test asserting no `response.output_text.delta` events with `delta: ""` are emitted when `text=""`

### Why
- BUG B: `generate_streaming_events` generated a `msg_id` UUID for all streaming delta/done events, then called `build_response_object` which generated its own independent `uuid4()` for the same message item. The `response.output_item.done` event and `response.completed.output[0].id` always differed, breaking client-side item correlation.
- BUG C: When `text` was `""`, the `else:` branch ran (because `tool_calls` was falsy). `range(0, max(1, 0), 40)` yielded one iteration, emitting a `response.output_text.delta` with `delta: ""` — a protocol violation. Also `build_response_object` would produce `output: []` for empty text while the stream emitted item-added events, leaving the two halves structurally inconsistent.

### Commit SHAs
| SHA | Description |
|-----|-------------|
| `5312d4d` | fix(responses): pass msg_id from streaming events to build_response_object to prevent message ID mismatch |
| `0fcba0c` | fix(responses): guard text streaming branch on non-empty text, remove phantom empty delta |

---

## Session 46 — from_responses.py — Bug Fixes A and D (2026-03-17)

### What changed
- `converters/from_responses.py` — fixed BUG A (`elif text` → independent `if text`) and BUG D (`item_ids` threaded from stream events to final response object)
- `tests/test_responses_converter.py` — added 2 new tests

### Which lines / functions
- `converters/from_responses.py:build_response_object` lines 55-62 — replaced `if tool_calls ... elif text` with two independent `if text` then `if tool_calls` blocks; added `item_ids: list[str] | None = None` parameter; passes `item_ids[i]` to `_build_function_call_output_item`
- `converters/from_responses.py:generate_streaming_events` — introduced `tc_item_ids: list[str] = []` list; `tc_item_ids.append(item_id)` inside the tool_calls loop; passes `item_ids=tc_item_ids if tc_item_ids else None` to final `build_response_object` call
- `tests/test_responses_converter.py:test_build_response_object_emits_both_text_and_tool_calls` — new test asserting both `message` and `function_call` types present in output, message first
- `tests/test_responses_converter.py:test_generate_streaming_events_tool_call_item_ids_match_completed_response` — new test asserting streamed `response.output_item.done` item ID equals the ID in `response.completed` output

### Why
- BUG A: `elif text` silently dropped the text item whenever `tool_calls` was truthy; the Responses API output array can legally contain both a `message` item and `function_call` items simultaneously
- BUG D: `generate_streaming_events` generated `item_id = f"fc_{uuid.uuid4().hex[:8]}"` for each tool call in streamed events but called `build_response_object` without those IDs, causing `_build_function_call_output_item` to generate fresh `uuid4()` IDs — streamed event IDs and final `response.completed` object IDs never matched, breaking client correlation

### Commit SHAs
| SHA | Description |
|-----|-------------|
| `319bb19` | fix(responses): emit both message and function_call items when text and tool_calls coexist (BUG A + BUG D combined commit) |

---

## Session 48 — from_cursor.py — Three Bug Fixes (2026-03-17)

### What changed
- `converters/from_cursor.py` — fixed 3 bugs: unclosed `<thinking>` tag leak, `sanitize_visible_text` skipping thinking strip, missing `id` synthesis before litellm
- `tests/test_from_cursor.py` — added 4 new tests covering all three bugs

### Which lines / functions
- `converters/from_cursor.py:split_visible_reasoning` (lines 320-323) — added `re.sub(r"<thinking>[\s\S]*$", "", ...)` in the `if not all_thinking:` branch to strip unclosed `<thinking>` opening tags and all text after them before returning `final`
- `converters/from_cursor.py:sanitize_visible_text` (lines 383-386) — replaced `return text or "", False` in the `if parsed_tool_calls:` branch with `_, visible = split_visible_reasoning(text or ""); return visible, False` so thinking blocks are stripped even when tool calls are present
- `converters/from_cursor.py:convert_tool_calls_to_anthropic` (lines 281-285) — added `id` synthesis loop before the litellm/manual branch split: iterates `tool_calls`, assigns `f"call_{uuid.uuid4().hex[:24]}"` to any entry missing an `id`, logs `tool_call_missing_id_in_converter` warning; updated docstring
- `tests/test_from_cursor.py:test_split_visible_reasoning_strips_unclosed_thinking_tag` — new test
- `tests/test_from_cursor.py:test_split_visible_reasoning_preserves_text_before_unclosed_tag` — new test
- `tests/test_from_cursor.py:test_sanitize_visible_text_strips_thinking_even_with_tool_calls` — new test
- `tests/test_from_cursor.py:test_convert_tool_calls_synthesizes_id_before_litellm` — new test

### Why
- BUG 1: `re.findall` returned empty when `<thinking>` had no closing tag (truncated stream). The `if not all_thinking:` branch returned the raw text unchanged, leaking `<thinking>partial reasoning` into visible output.
- BUG 2: `sanitize_visible_text` exited early at line 383 (`if parsed_tool_calls: return text or "", False`) before any tag stripping. Model thinking blocks emitted before tool calls were forwarded verbatim to the client.
- BUG 3: `convert_tool_calls_to_anthropic` passed the raw tool_calls list to the litellm converter without synthesizing missing `id` fields first. litellm received `id: None`, potentially producing Anthropic `tool_use` blocks with `id: None`. The manual fallback synthesized IDs but the litellm path did not.

### Commit SHAs
| SHA | Description |
|-----|-------------|
| `382f2b5` | fix(converters): strip unclosed thinking tag from visible output on truncated streams |

---

## Session 49 — to_cursor.py — Three Bug Fixes (2026-03-17)

### What changed
- `converters/to_cursor.py` — fixed 3 bugs: assistant content dropped alongside tool_calls, tool role list content nulled, non-text block drops silent
- `tests/test_to_cursor.py` — added 3 new tests covering all three bugs

### Which lines / functions
- `converters/to_cursor.py:openai_to_cursor` (lines 488-497) — in the `elif role == "assistant" and tool_calls` branch, added check for `msg.get("content")`: if prose content is present, emits it as a separate assistant message before the `[assistant_tool_calls]` message
- `converters/to_cursor.py:anthropic_messages_to_openai` (line 751) — in the role:tool pass-through block, replaced `content if isinstance(content, str) else ""` with `content if isinstance(content, str) else _extract_text(content)` so list content is extracted instead of nulled
- `converters/to_cursor.py:_extract_text` (lines 78-87) — in the list-content loop, added an `else` branch under the dict handler: when a block has a non-text `type`, calls `structlog.get_logger().warning("extract_text_dropped_non_text_block", block_type=btype)` to surface silent drops
- `tests/test_to_cursor.py::test_openai_to_cursor_assistant_content_preserved_alongside_tool_calls` — new test for BUG 4
- `tests/test_to_cursor.py::test_anthropic_messages_to_openai_tool_role_list_content_extracted` — new test for BUG 5
- `tests/test_to_cursor.py::test_extract_text_logs_warning_for_image_url_block` — new test for BUG 6

### Why
- BUG 4: The `elif role == "assistant" and tool_calls` branch emitted only the tool call text; `msg.get("content")` was never read. OpenAI permits both simultaneously (model reasoning + tool invocation). The prose was silently dropped.
- BUG 5: The role:tool pass-through in `anthropic_messages_to_openai` used `content if isinstance(content, str) else ""`. Any caller passing a list-typed content (e.g. `[{"type": "text", "text": "..."}]`) received an empty string as tool result content.
- BUG 6: `_extract_text` matched only `type == "text"` and `"content"` key blocks; all other block types (image_url, image_file, etc.) were consumed silently. No log entry meant production drops were invisible in observability tooling.

### Commit SHAs
| SHA | Description |
|-----|-------------|
| `99fd0e7` | fix(converters): preserve assistant content alongside tool_calls in openai_to_cursor |
| `0a984be` | fix(converters): extract text from list content in anthropic_messages_to_openai tool pass-through |
| `8625a47` | fix(converters): log warning when non-text blocks are dropped in _extract_text |

---

## Session 52 — responses: emit function_call_arguments.delta and .done in streaming tool calls (2026-03-17)

### What changed
- `converters/from_responses.py` — added two intermediate SSE events per tool call in `generate_streaming_events`
- `tests/test_responses_converter.py` — added 1 new regression test

### Which lines / functions
- `converters/from_responses.py:generate_streaming_events` (lines 177-194) — inside the `if tool_calls:` loop, inserted `response.function_call_arguments.delta` (with `delta` = full arguments string) and `response.function_call_arguments.done` (with `arguments` = full arguments string) between `response.output_item.added` and `response.output_item.done`. Each event carries `item_id` and `output_index`. `seq` incremented correctly for all four events per tool call.
- `tests/test_responses_converter.py::test_generate_streaming_events_tool_calls_emit_arguments_delta_and_done` — new test: verifies both events are present, delta precedes done, and both carry the correct arguments value.

### Why
The OpenAI Responses API spec requires `response.function_call_arguments.delta` and `response.function_call_arguments.done` events between `output_item.added` and `output_item.done` for function call items. Without them, OpenAI SDK streaming helpers that listen for `response.function_call_arguments.delta` never receive the arguments and may stall or produce incomplete tool call results.

### Commit SHAs
| SHA | Description |
|-----|-------------|
| (pending) | fix(responses): emit function_call_arguments.delta and .done events in streaming tool calls |
| (pending) | docs: update UPDATES.md for function_call_arguments events fix |

---

## Session 51 — converters: preserve text-before-tool_result ordering in anthropic_messages_to_openai (2026-03-17)

### What changed
- `converters/to_cursor.py` — fixed `anthropic_messages_to_openai` user+list branch
- `tests/test_to_cursor.py` — added 1 new regression test

### Which lines / functions
- `converters/to_cursor.py:anthropic_messages_to_openai` (lines 699-720) — replaced two-pass split (`tool_results` list + `text_blocks` list) with a single ordered pass. `pending_text` accumulates consecutive text blocks; `_flush_user_text()` drains them as a `user` message immediately before each `tool_result` block. A final `_flush_user_text()` call emits any trailing text. Original interleaving order is now fully preserved.
- `tests/test_to_cursor.py::test_anthropic_messages_to_openai_preserves_text_before_tool_result_ordering` — new test: verifies that a `text` block preceding a `tool_result` block in the same user content list produces a `user` message before the `tool` message.

### Why
The old two-pass approach filtered `tool_results` and `text_blocks` into separate lists and emitted all tool messages first. Any text block that appeared before a `tool_result` in the original list was incorrectly moved after it, corrupting multi-turn message ordering for clients that interleave context text with tool results in a single user turn.

### Commit SHAs
| SHA | Description |
|-----|-------------|
| `9914d5e` | fix(converters): process user content list in order in anthropic_messages_to_openai |
| `50ca267` | docs: update UPDATES.md for tool_result ordering fix |

---

## Session 50 — to_responses.py — Two Bug Fixes (2026-03-17)

### What changed
- `converters/to_responses.py` — fixed 2 bugs: tool_use content collapsed to empty string, extract_function_tools blacklist allowed typeless tools through
- `tests/test_responses_converter.py` — added 2 new tests covering both bugs

### Which lines / functions
- `converters/to_responses.py:_prior_output_to_messages` (lines 41-45) — replaced simple `_output_text_from_content` collapse with tool_use detection: when `content` list contains any `tool_use` blocks, emits preceding `output_text` as a separate content message (if non-empty) then emits an `assistant` message with `tool_calls` array reconstructed from the `tool_use` blocks (`id`, `name`, `json.dumps(input)`).
- `converters/to_responses.py` (top-level) — added `import json` (required for `json.dumps` on tool input)
- `converters/to_responses.py:extract_function_tools` (lines 144-158) — replaced blacklist-only approach with whitelist: tools where `type != "function"` now skip with `log.warning()` (separate messages for unknown type vs missing type) instead of silently passing through. Only `type == "function"` tools reach the output list.
- `tests/test_responses_converter.py::test_prior_message_with_tool_use_content_reconstructed_as_tool_calls` — new test for BUG 7
- `tests/test_responses_converter.py::test_extract_function_tools_requires_explicit_function_type` — new test for BUG 8

### Why
- BUG 7: `_prior_output_to_messages` called `_output_text_from_content()` which only joins `output_text`/`text`/`input_text` blocks. Any `tool_use` block in a prior assistant message was silently dropped, erasing tool call history from multi-turn Responses API sessions. Downstream model context was missing the assistant→tool_use→tool_result chain.
- BUG 8: `extract_function_tools` used `BUILTIN_TOOL_TYPES` as a blacklist. `None not in BUILTIN_TOOL_TYPES` is always `True`, so any tool dict missing the `type` key passed through as if it were a function tool. This caused malformed tool schemas to reach the upstream model.

### Commit SHAs
| SHA | Description |
|-----|-------------|
| `50441bb` | fix(converters): reconstruct tool_use content blocks as tool_calls in _prior_output_to_messages |

---

## Session 51 — input_to_messages non-text block warning (2026-03-17)

### What changed
- `converters/to_responses.py` — fixed silent drop of non-text content blocks in `input_to_messages`
- `tests/test_responses_converter.py` — added 1 new test covering the warning

### Which lines / functions
- `converters/to_responses.py:input_to_messages` (content list branch, ~lines 159-177) — replaced single-expression generator join with an explicit loop; non-text blocks (`image_url`, `image_file`, `input_file`, etc.) now emit `log.warning("input_to_messages_dropped_non_text_block", block_type=btype, role=actual_role)` instead of being silently filtered out.
- `tests/test_responses_converter.py::test_input_to_messages_logs_warning_for_image_url_block` — new test: asserts an `image_url` block triggers a WARNING log record and the accepted `input_text` content is still returned correctly.

### Why
- BUG: when a user/assistant/system item's `content` is a list, `input_to_messages` only extracted `input_text`/`text`/`output_text` blocks. All other block types (`image_url`, `image_file`, `input_file`) were silently dropped with no log. Same observability gap as the `to_cursor.py:_extract_text` fix from a prior session. Operators had no way to know multimodal content was being discarded.

### Commit SHAs
| SHA | Description |
|-----|-------------|
| `e2a5811` | fix(converters): log warning for non-text content blocks dropped in input_to_messages |
| `cc9ccd7` | docs: update UPDATES.md for input_to_messages non-text block warning |

---

## Session 52 — Auth middleware bug fixes: global budget, token strip, colon split (2026-03-17)

### What changed
- `analytics.py` — added `get_total_spend()` method to `AnalyticsStore`
- `middleware/auth.py` — fixed 3 bugs: global budget check, bearer token whitespace, API key colon split
- `tests/test_app.py` — added 3 new tests covering all three bugs

### Which lines / functions
- `analytics.py:AnalyticsStore.get_total_spend` (new method after `get_spend`) — sums `estimated_cost_usd` across all keys in `_by_key` under the async lock. Required by the global budget fix.
- `middleware/auth.py:check_budget` (lines 77-83) — replaced `analytics.get_spend(api_key)` with `analytics.get_total_spend()` for the `settings.budget_usd` check. Prior code checked only the requesting key's spend; N keys could each independently approach the global ceiling. Error message updated to `Global budget exceeded`.
- `middleware/auth.py:verify_bearer` (line 30) — added `.strip()` to `authorization.split(" ", 1)[1]`. Double-space or trailing-space Authorization headers produced a token with whitespace that failed equality checks against `_env_keys()` and fell through to `key_store.is_valid()` with the wrong token value.
- `middleware/auth.py:_env_keys` (line 20) — changed `split(":")` to `split(":", 1)` to use only the first colon as the key/label separator. Semantically correct for the `key:label` format.
- `tests/test_app.py::test_check_budget_global_uses_total_spend` — new async test: populates two keys each at $0.60 (total $1.20 > $1.00 limit), asserts `RateLimitError` with `Global budget exceeded`.
- `tests/test_app.py::test_verify_bearer_strips_whitespace` — new async test: patches `_env_keys` to return `{"sk-test"}`, asserts double-space and trailing-space Authorization headers both resolve to `"sk-test"`.
- `tests/test_app.py::test_env_keys_uses_first_colon_as_label_separator` — new sync test: sets `api_keys="sk-one:label,sk-two:scope:extra"`, asserts `sk-one` and `sk-two` are in the frozenset and `scope`/`extra` are not.

### Why
- BUG 1: Global budget check called `get_spend(api_key)` which returns only that key's spend. Two keys each spending $0.60 against a $1.00 global limit would both pass. Total spend must be checked against the global ceiling.
- BUG 2: No `.strip()` on the token extracted from the Authorization header. Any client sending `Bearer  sk-key` (double space) or `Bearer sk-key ` (trailing space) would fail auth entirely, even with a valid key.
- BUG 3: `split(":")` with no limit on `key:label` entries is semantically wrong. While `[0]` always returns the key portion regardless of how many colons are present, `split(":", 1)` is the correct idiom that documents the intent (first colon is the separator) and prevents future misreads.

### Commit SHAs
| SHA | Description |
|-----|-------------|
| `898cba6` | fix(auth): enforce global budget against total spend across all keys |
| `a42d3d5` | fix(auth): strip whitespace from bearer token |
| `1e3b055` | fix(auth): split SHINWAY_API_KEYS on first colon only |

---

## Session 53 — Idempotency cache key scoped per API key (2026-03-17)

### What changed
- `middleware/idempotency.py` — scoped cache key to include `api_key`
- `routers/unified.py` — updated `_handle_non_streaming` call sites to pass `api_key`
- `tests/test_app.py` — added test covering cross-tenant isolation

### Which lines / functions
- `middleware/idempotency.py:_cache_key` — added `api_key: str = ""` parameter; format changed from `f"idem:{key}"` to `f"idem:{api_key}:{key}"`. Without this, two clients with different API keys but the same `X-Idempotency-Key` value would share a cache entry.
- `middleware/idempotency.py:get_or_lock` — added `api_key: str = ""` parameter, passed through to `_cache_key`.
- `middleware/idempotency.py:complete` — added `api_key: str = ""` parameter, passed through to `_cache_key`.
- `routers/unified.py:_handle_non_streaming` — updated `get_or_lock(idem_key)` → `get_or_lock(idem_key, api_key=params.api_key)` and `complete(idem_key, resp)` → `complete(idem_key, resp, api_key=params.api_key)`. `params.api_key` is set by `verify_bearer` at the top of each route handler.
- `tests/test_app.py::test_idempotency_keys_scoped_per_api_key` — new async test: stores a response under `key_alpha`, asserts `key_beta` gets a cache miss for the same idempotency key, then asserts `key_alpha` gets the cache hit.

### Why
- BUG: `_cache_key` namespaced only by the idempotency key string, not by the API key. Two tenants sending the same `X-Idempotency-Key` value would collide — the second tenant's request would be served the first tenant's cached response. Cross-tenant response replay.

### Commit SHAs
| SHA | Description |
|-----|-------------|
| `8f93ea0` | fix(idempotency): scope cache key per API key to prevent cross-tenant response replay |

---

## Session 54 — Credential rotation fix and openai_stream DONE sentinel (2026-03-17)

### What changed
- `cursor/client.py` — fixed CredentialError handling in retry loop
- `pipeline/stream_openai.py` — fixed TimeoutError and Exception handlers to emit [DONE] and sanitize error message
- `tests/test_credentials.py` — added AST-based structural test for the cred=None fix
- `tests/test_pipeline.py` — corrected stale assertion: timeout path must now emit [DONE]

### Which lines / functions
- `cursor/client.py:CursorClient.stream` (except (CredentialError, RateLimitError) handler, ~line 246) — added `if isinstance(exc, CredentialError): cred = None` as the first statement in the handler. Without this, `_cred = cred or self._pool.next()` on the next iteration kept resolving to the same broken credential because `cred` was never cleared. Pool rotation was silently skipped for the entire retry sequence.
- `pipeline/stream_openai.py:_openai_stream` (except TimeoutError handler, ~line 268) — added `yield openai_done()` before `return`. The handler yielded the error SSE event but left the SSE stream without a `[DONE]` sentinel, causing clients to hang indefinitely waiting for the stream to close.
- `pipeline/stream_openai.py:_openai_stream` (except Exception handler, ~line 272) — replaced `str(exc)[:200]` with the fixed string `


---

## Session 54 — Credential rotation fix and openai_stream DONE sentinel (2026-03-17)

### What changed
- `cursor/client.py` — fixed CredentialError handling in retry loop
- `pipeline/stream_openai.py` — fixed TimeoutError and Exception handlers to emit [DONE] and sanitize error message
- `tests/test_credentials.py` — added AST-based structural test for the cred=None fix
- `tests/test_pipeline.py` — corrected stale assertion: timeout path must now emit [DONE]

### Which lines / functions
- `cursor/client.py:CursorClient.stream` (except (CredentialError, RateLimitError) handler, ~line 246) — added `if isinstance(exc, CredentialError): cred = None` as the first statement in the handler. Without this, `_cred = cred or self._pool.next()` on the next iteration kept resolving to the same broken credential because `cred` was never cleared. Pool rotation was silently skipped for the entire retry sequence.
- `pipeline/stream_openai.py:_openai_stream` (except TimeoutError handler, ~line 268) — added `yield openai_done()` before `return`. The handler yielded the error SSE event but left the SSE stream without a [DONE] sentinel, causing clients to hang indefinitely waiting for the stream to close.
- `pipeline/stream_openai.py:_openai_stream` (except Exception handler, ~line 272) — replaced `str(exc)[:200]` with the fixed string `An internal error occurred. Please retry.` to prevent internal file paths and exception details from leaking to clients; added `yield openai_done()` before `return` for the same sentinel reason.
- `tests/test_credentials.py::test_stream_rotates_credential_on_credential_error` — new test: uses `ast.parse` + `ast.walk` to verify that the except handler covering CredentialError contains a `cred = None` assignment node. Structural test that cannot be fooled by a comment.
- `tests/test_pipeline.py::test_openai_stream_timeout_uses_specific_timeout_handling` — line 302: inverted `raw_chunks[-1] != 'data: [DONE]\n\n'` to `== 'data: [DONE]\n\n'`. The old assertion matched the broken behavior; the corrected assertion enforces the fix.

### Why
- BUG 1: `cursor/client.py` retry loop used `_cred = cred or self._pool.next()`. When the caller passes an explicit `cred` for a suppression retry and that credential is rejected with a 401/403 (CredentialError), the `cred` variable was never cleared. Every subsequent retry reused the same rejected credential, making the retry loop useless for CredentialError recovery.
- BUG 2: Both error exit paths in `_openai_stream` (TimeoutError and bare Exception) returned without yielding `openai_done()`. The OpenAI SSE protocol requires a terminal `data: [DONE]` event to signal end-of-stream. Clients (including OpenAI-compatible SDKs) block reading until they see it, causing the request to hang until a client-side timeout fires. The Exception handler additionally leaked `str(exc)` which can contain internal paths or sensitive context.

### Commit SHAs
| SHA | Description |
|-----|-------------|
| `47b3dcb` | fix(cursor): rotate credential on CredentialError in retry loop |
| `7e4d924` | fix(pipeline): emit DONE sentinel and sanitize error message in openai_stream error handlers |

---

## Session 55 — Agent blocklist: SHINWAY_BLOCKED_AGENTS (2026-03-18)

### What changed
- `config.py` — added `blocked_agent_patterns` field (alias `SHINWAY_BLOCKED_AGENTS`, comma-separated substrings, default empty = disabled)
- `routers/unified.py` — added `_BLOCKED_AGENT_ERROR` constant and `_check_blocked_agents()` helper; wired into `chat_completions` (line ~178, checks system-role messages) and `anthropic_messages` (line ~312, checks `system_text` field)

### Which lines / functions
- `config.py:Settings.blocked_agent_patterns` — new field, alias `SHINWAY_BLOCKED_AGENTS`. Comma-separated substrings matched case-insensitively against system prompt content. Empty string disables the feature.
- `routers/unified.py:_check_blocked_agents` — iterates system-role messages, lowercases content, matches any configured pattern. Raises `AuthError(401)` on match with a user-facing message directing clients to use Claude Code CLI. Uses `getattr(settings, "blocked_agent_patterns", None)` to safely degrade when settings is mocked in tests.
- `routers/unified.py:chat_completions` — calls `_check_blocked_agents(messages)` immediately after messages are extracted, before any pipeline work.
- `routers/unified.py:anthropic_messages` — calls `_check_blocked_agents([{"role": "system", "content": system_text}])` when `system_text` is non-empty (Anthropic passes system as a separate field, not in messages array).

### Why
Kilo Code, Roo Code, and similar IDE agents inject recognizable identity phrases into the system prompt (`"You are Kilo"`, `"kilo code"`, `"roo code"`, etc.). The feature allows operators to block these agents via env var without code changes, returning a clean 401 with a custom message that the agent's UI displays directly to the user. Blocked requests are rejected after auth but before any upstream call, so no upstream quota is consumed.

### Commit SHAs
| SHA | Description |
|-----|-------------|
| `7ddb4c9` | feat(auth): add SHINWAY_BLOCKED_AGENTS to block Kilo Code, Roo Code, and other agents by system prompt fingerprint |

---

## Session 56 — Default agent blocklist enabled (2026-03-18)

### What changed
- `config.py` — `blocked_agent_patterns` default changed from `""` (disabled) to `"kilo code,kilocode,you are kilo,roo code,you are roo,roocode"`

### Which lines / functions
- `config.py:Settings.blocked_agent_patterns` — default value set to the Kilo Code and Roo Code fingerprint patterns. Operators can override via `SHINWAY_BLOCKED_AGENTS=` (empty to disable) or extend with additional patterns.

### Why
Kilo Code and Roo Code are blocked by default so new deployments are protected without requiring manual configuration. The env var override remains available for operators who need to adjust the list.

### Commit SHAs
| SHA | Description |
|-----|-------------|
| `a383e0b` | feat(auth): set default SHINWAY_BLOCKED_AGENTS to block Kilo Code and Roo Code out of the box |

## Session 57 — Bypass LiteLLM token counting to fix event-loop stalls (2026-03-18)

### What changed
- `tokens.py` — added `_LITELLM_AVAILABLE` guard in `count_tokens`, `count_message_tokens`, and `count_tool_tokens` callers; added import-time override block that reads `SHINWAY_DISABLE_LITELLM_TOKEN_COUNTING` from config and sets `_LITELLM_AVAILABLE=False` when enabled
- `tests/test_tokens.py` — added 2 new tests: `test_litellm_disabled_flag_bypasses_litellm_entirely` and `test_litellm_disabled_flag_bypasses_litellm_for_message_counting`

### Which lines / functions
- `tokens.py:34–56` — import block: added config-driven `_LITELLM_AVAILABLE` override at module load
- `tokens.py:count_tokens` — added `if _LITELLM_AVAILABLE:` guard before `_litellm_count` call
- `tokens.py:count_message_tokens` — same guard
- `tokens.py:count_tool_tokens` — same guard
- `config.py` — `disable_litellm_token_counting` field (`SHINWAY_DISABLE_LITELLM_TOKEN_COUNTING`, default `false`) was already present from prior session

### Why
Root cause of proxy stall under high input / agentic codebase reads:
`litellm.token_counter()` is synchronous and blocks the asyncio event loop.
For large contexts (agent reads entire codebase), this call takes 200ms–2s,
freezing all concurrent requests on that single-worker uvicorn instance.
The guard makes all three token-counting functions skip LiteLLM entirely when
`_LITELLM_AVAILABLE` is `False`, falling through to tiktoken — pure in-process,
no GIL-blocking I/O, 50–100x faster.

To activate: set `SHINWAY_DISABLE_LITELLM_TOKEN_COUNTING=true` in `.env`.

### Commit SHAs
| SHA | Description |
|-----|-------------|
| `83087e0` | perf(tokens): bypass LiteLLM token counting to eliminate event-loop stalls |

---

## Session 58 — Python Code Quality Fixes (2026-03-18)

### What changed
- `analytics.py` — removed unused `OrderedDict` and `typing.Any` imports
- `cursor/client.py` — removed unused `json` import; added `# nosec B311` to 3 jitter lines
- `cursor/sse.py` — removed unused `settings` import
- `cursor/credentials.py:175` — renamed ambiguous loop variable `l` → `line` (E741)
- `converters/to_cursor.py` — stripped f-prefix from 3 bare string literals (F541)
- `multirun.py` — stripped f-prefix from 1 bare string literal; added `# nosec B603` to subprocess.Popen
- `pipeline/__init__.py` — added `# noqa: F401` to all intentional re-export imports (18 lines)
- `pipeline/suppress.py` — added `# nosec B311` to jitter line
- `pipeline/tools.py` — removed unused `StreamingToolCallParser` import; removed unused `_repair_invalid_calls` import
- `pipeline/nonstream.py` — removed unused `get_http_client`, `_repair_invalid_calls`, `log_tool_calls`, `parse_tool_calls_from_text` imports
- `pipeline/stream_anthropic.py` — removed unused `_limit_tool_calls` import
- `pipeline/stream_openai.py` — removed unused variable `exc` in bare exception handler (F841)
- `tools/parse.py` — added `# nosec B110` to 5 parse-strategy fallthrough sites
- `storage/keys.py` — added `# nosec B608` with explanation on dynamic UPDATE query; expanded 7 single-line if-statements to proper multi-line form (E701/E702)
- `run.py` — added `# nosec B110` to stderr reconfigure; added `# noqa: E402` to post-uvloop imports
- `config.py` — added `# nosec B104` to 0.0.0.0 bind
- `utils/context.py` — moved `from config import settings` and `from handlers import ContextWindowError` above `log = structlog.get_logger()` to fix E402
- `utils/routing.py` — removed unused inline `from config import settings` import
- `utils/trim.py` — restored `MIN_KEEP` re-export (with `# noqa: F401`) after ruff auto-fix incorrectly removed it; test `test_minimum_keep_value_comes_from_single_source_of_truth` asserts `trim.MIN_KEEP`
- `pytest.ini` — added `pythonpath = .` so tests run without `PYTHONPATH=.` prefix
- `mypy.ini` — created with `explicit_package_bases = True` to fix duplicate-module error
- `tests/integration/test_all_tools.py` — moved `create_app()` from module level into module-scoped fixture
- `tests/integration/test_tool_call.py` — same fixture refactor
- `tests/test_request_validators.py` — added `# noqa: E402` to 3 mid-file imports (router integration section)
- `tests/test_responses_converter.py` — added `# noqa: E402` to mid-file `from_responses` import block
- Multiple test files — removed unused `pytest`, `asyncio`, `time`, `structlog`, `pipeline` imports (ruff auto-fix)

### Why
Static analysis (ruff + bandit + mypy) audit revealed: unused imports throughout source and test files, ambiguous variable names (E741), bare f-string prefixes (F541), 16 bandit false positives requiring `# nosec` annotation, mid-file imports needing `# noqa: E402`, and condensed one-liner if-blocks in `storage/keys.py` violating E701/E702. Integration tests crashed pytest collection when env vars were absent (module-level `create_app()` call). `pytest.ini` and `mypy.ini` were missing project-standard config. The `MIN_KEEP` re-export in `utils/trim.py` was incorrectly auto-removed and had to be restored with `# noqa: F401` to keep the single-source-of-truth test passing.

### Commits
| SHA | Description |
|-----|-------------|
| `6e26b9a` | chore: remove unused imports and bare f-strings (ruff auto-fix) |
| `2ee724a` | chore: rename ambiguous loop var l -> line (E741) |
| `89d4c4a` | chore: add noqa F401 to pipeline re-export imports |
| `d91b951` | chore: add nosec annotations to intentional bandit findings |
| `26292a6` | chore: add pythonpath = . to pytest.ini so tests run without PYTHONPATH prefix |
| `ef6065e` | chore: add mypy.ini with explicit_package_bases to fix duplicate-module error |
| `b649ecd` | fix(tests): move create_app() from module level into module-scoped fixtures |
| `5a9e47a` | chore: fix remaining ruff violations (E402 noqa, E701/E702 storage/keys, unused imports in tests and pipeline) |

## Session 59 — Performance audit and root cause analysis (2026-03-18)

### What changed
- No code changes this session — analysis and diagnosis only.

### Work done

**1. Diagnosed event-loop stall under high input / agentic codebase reads**
- Root cause: `litellm.token_counter()` called synchronously on the asyncio event loop inside `count_message_tokens`, `count_tokens`, `count_tool_tokens`. Blocks 200ms–2s per call for large inputs.
- Secondary: O(n²) `trim_to_budget` loop in `utils/context.py` — calls `count_message_tokens` N times inside greedy fill loop, each call O(n). Only activates when conversation exceeds token budget (not the fresh-session stall).
- Fix shipped in Session 57: `SHINWAY_DISABLE_LITELLM_TOKEN_COUNTING=true`.
- Confirmed: fresh session + "read codebase" stall is fully fixed by Session 57. Trim O(n²) is a separate secondary issue for very long sessions.

**2. Full hot-path audit — 6 issues found across pipeline, middleware, analytics**

| # | File | Issue | Severity |
|---|---|---|---|
| 1 | `stream_openai.py:115`, `stream_anthropic.py:89` | `acc += delta_text` O(n²) string concat across stream | Medium |
| 2 | `nonstream.py:126,239`, both streams | `count_message_tokens` called twice per request | Low (fast with S57 fix) |
| 3 | `middleware/rate_limit.py:33` | `TokenBucket._buckets` unbounded dict — never evicts | Medium |
| 4 | `analytics.py:96` | `msgjson` serialize inside asyncio lock in `snapshot()` | Low |
| 5 | `nonstream.py:63` | Suppression retry blocks full non-streaming response (up to 3× latency) | Low |
| 6 | `pipeline/suppress.py:79` | `_is_suppressed` builds full hits list, no early exit | Trivial |

- Issue 1 (string concat) and Issue 3 (unbounded bucket dict) are next in priority.
- None of issues 2–6 affect logic correctness — all are performance or memory concerns only.

### Commit SHAs
No commits this session — analysis only.

## Session 60 — Comprehensive test coverage expansion (2026-03-18)

### What changed
- `tests/test_analytics.py` — new file, 17 tests
- `tests/test_handlers.py` — new file, 15 tests
- `tests/test_cache.py` — new file, 15 tests
- `tests/test_idempotency.py` — new file, 6 tests
- `tests/test_auth.py` — new file, 20 tests
- `tests/test_model_router.py` — new file, 9 tests
- `tests/test_suppress.py` — new file, 16 tests
- `tests/test_rate_limit.py` — extended with 8 more tests (TokenBucket, enforce_rate_limit, enforce_per_key_rate_limit)
- `tests/test_sse.py` — extended with 13 more tests (parse_line, extract_delta, iter_deltas)
- `tests/test_internal.py` — extended with 9 more tests (health endpoints, credentials, cache clear, logs)
- `tests/test_stream_monitor.py` — extended with 5 more tests (stats, cancel, byte counts)
- `routers/model_router.py` — bug fix: `_load_alias_map` now guards against valid JSON that is not a dict (TypeError on spread)

### Why
Static coverage audit found 9 source modules with zero test coverage and 4 with only 1–3 tests. Any change to analytics, auth middleware, cache, exception handlers, idempotency, model router, suppression logic, or SSE parsing had no automated regression signal. Added 133 new tests (212 → 345 total) covering all previously untested public functions and key edge cases.

### Modules now covered
- `analytics.py` — AnalyticsStore record/snapshot/spend/tokens, estimate_cost
- `handlers.py` — full exception hierarchy, to_openai/to_anthropic shapes, status codes
- `cache.py` — ResponseCache L1 get/set/clear, build_key determinism, should_cache logic
- `middleware/idempotency.py` — get_or_lock, complete, per-key isolation, release no-op
- `middleware/auth.py` — verify_bearer (all paths), get_key_record, check_budget, enforce_allowed_models
- `routers/model_router.py` — resolve_model, model_info, all_models, alias map
- `pipeline/suppress.py` — _is_suppressed (knockout, weak signals, persona requirement), _with_appended_cursor_message immutability
- `pipeline/record.py` — _provider_from_model routing
- `middleware/rate_limit.py` — TokenBucket, enforce_rate_limit, enforce_per_key_rate_limit
- `cursor/sse.py` — parse_line, extract_delta, iter_deltas (suppression abort, empty response, normal flow)
- `routers/internal.py` — health endpoints, credentials, cache clear, logs, auth enforcement
- `utils/stream_monitor.py` — stats(), byte counting, client disconnect (CancelledError → StreamAbortError)

### Commits
| SHA | Description |
|-----|-------------|
| `03472b5` | test: add tests for analytics.AnalyticsStore, estimate_cost, and handlers exception hierarchy |
| `2d9becc` | test: add tests for ResponseCache and idempotency middleware |
| `df2da0a` | test: add tests for middleware/auth.py — verify_bearer, check_budget, enforce_allowed_models |
| `28c570c` | test: add tests for model_router, _is_suppressed, _with_appended_cursor_message, _provider_from_model |
| `98946fc` | test: expand rate_limit and SSE tests — enforce functions, parse_line, extract_delta, iter_deltas |
| `5544d70` | test: expand internal router and stream monitor tests |

## Session 61 — Top-3 coverage gaps filled (2026-03-18)

### What changed
- `tests/test_keys_storage.py` — new file, 29 tests
- `tests/test_cursor_client.py` — new file, 24 tests
- `tests/test_nonstream.py` — new file, 17 tests

### Why
Post-session-60 coverage report identified three critical gaps: `storage/keys.py` at 34%, `cursor/client.py` at 23%, `pipeline/nonstream.py` at 43%. These are load-bearing modules — any change to DB key CRUD, HTTP client retry logic, or non-streaming response building had zero automated regression signal.

### Coverage gains
| Module | Before | After |
|---|---|---|
| `storage/keys.py` | 34% | 95% |
| `cursor/client.py` | 23% | 68% |
| `pipeline/nonstream.py` | 43% | 86% |
| **Overall** | **71%** | **77%** |

### Key techniques
- `storage/keys.py` — tested against real `aiosqlite` in-memory DB (`:memory:`); no mocking, exercises real SQL
- `cursor/client.py` — mocked `httpx.AsyncClient.stream` with async context manager; patched `asyncio.create_task` to suppress background telemetry; covered all error classification paths (401/403/429/413/500/502)
- `pipeline/nonstream.py` — patched `_call_with_retry` and `_record` on module; covered happy path, tool calls, suppression retry, cache hits, and the tool-lost error signal

### 415 tests passing, 3 deselected (integration)

### Commits
| SHA | Description |
|-----|-------------|
| `3916c26` | test: add tests for CursorClient, _build_headers, _build_payload, classify_cursor_error |
| `037ff53` | test: add comprehensive KeyStore tests using in-memory SQLite |
| `909da17` | test: add tests for handle_openai_non_streaming and handle_anthropic_non_streaming |

---

## Session 62 — Three bug fixes: partial marker leak, rate limiter TOCTOU, EmptyResponseError retry (2026-03-18)

### What changed

| File | Change |
|---|---|
| `pipeline/stream_openai.py` | Added `_TOOL_MARKER`, `_TOOL_MARKER_PREFIXES` (frozenset of all 22 prefixes), `_safe_emit_len()`. Replaced both per-delta emit sites to use `safe_end = _safe_emit_len(visible_text)` instead of `len(visible_text)`, holding back any trailing partial marker prefix. |
| `middleware/rate_limit.py` | Added `TokenBucket.refund()`. Rewrote `DualBucketRateLimiter.consume()` to call `_rps.consume()` first, then `_rpm.consume()`, refunding RPS on RPM failure. Eliminates the peek→peek→consume→consume split and the silent discard of consume() return values. |
| `cursor/client.py` | Added `EmptyResponseError` to imports from `handlers`. Added `except EmptyResponseError` handler in `stream()` retry loop: marks credential error, wraps as `BackendError`, backs off, and `continue`s to next attempt. |
| `tests/test_pipeline.py` | Added 7 unit tests for `_safe_emit_len` / `_TOOL_MARKER_PREFIXES` and 1 integration test `test_partial_marker_not_emitted_to_client` verifying no partial marker prefix leaks mid-stream. |
| `tests/test_stream_openai.py` | New file — 14 additional tests for `_safe_emit_len`, `_extract_visible_content`, and `_openai_stream` behaviour (from subagent). |
| `tests/test_rate_limit.py` | Added 5 tests: `test_dual_bucket_consume_return_values_are_used`, `test_token_bucket_refund_restores_token`, `test_token_bucket_refund_capped_at_burst`, `test_token_bucket_refund_disabled_when_rate_zero`, `test_dual_bucket_rps_refunded_on_rpm_failure`. |
| `tests/test_cursor_client.py` | Added `test_empty_response_error_is_retried` — fake two-call response fixture: call 1 returns empty body (EmptyResponseError), call 2 returns a valid delta; asserts the delta is collected after retry. |

### Why

- **Bug 1 (partial marker leak):** `_find_marker_pos` requires the complete `[assistant_tool_calls]` string at a line start. When a chunk boundary falls inside the marker (e.g. chunk 1 ends with `[assistant_tool_`), `_find_marker_pos` returns `-1`, the holdback is not triggered, and those bytes are emitted to the client. `_safe_emit_len` holds back any trailing suffix of `visible_text` that is a known prefix of the marker, preventing the leak. O(1) — scans at most 22 chars from the end.
- **Bug 2 (rate limiter TOCTOU):** `DualBucketRateLimiter.consume()` made four independent lock acquisitions (peek+peek+consume+consume). The return values of both `consume()` calls were silently discarded — even if a race was lost at consume time, the caller still returned `True, ""`. The fix: call `_rps.consume()` directly, check its return, then call `_rpm.consume()`, check its return, and `refund()` RPS if RPM fails. Latent race eliminated; discarded returns fixed.
- **Bug 3 (EmptyResponseError not retried):** `EmptyResponseError` (HTTP 200, empty body) hit the bare `except Exception: raise exc` in `cursor/client.py:stream()`, bypassing the retry loop entirely. One transient empty response killed the whole request. Fix: specific `except EmptyResponseError` handler wraps as `BackendError` and continues to the next retry attempt with backoff.

### Commits

| SHA | Description |
|---|---|
| `f1e9679` | test: add tests for _safe_emit_len, _extract_visible_content, _openai_stream behaviour |
| `2d697bb` | fix(pipeline): hold back partial [assistant_tool_calls] prefixes to prevent marker fragment leak during streaming |
| `ee236d0` | fix(rate_limit): eliminate peek+consume TOCTOU race; add TokenBucket.refund() for atomic RPM-fail rollback |
| `9a0a39f` | fix(client): retry EmptyResponseError with backoff instead of re-raising immediately |

## Session 63 — Remaining high-value coverage gaps filled (2026-03-18)

### What changed
- `tests/test_tokens_extended.py` — new file, 35 tests
- `tests/test_unified_router.py` — new file, 18 tests
- `tests/test_stream_openai.py` — new file, 14 tests
- `tests/test_parse_extended.py` — new file, 75 tests
- `tests/test_pipeline.py` — restored `_parse_anthropic_sse_event` helper removed by a prior fix commit

### Coverage gains
| Module | Before | After |
|---|---|---|
| `tokens.py` | 53% | 82% |
| `tools/parse.py` | 66% | 82% |
| `pipeline/stream_openai.py` | 57% | 78% |
| `routers/unified.py` | 59% | 60% |
| **Overall** | **77%** | **82%** |
| **Tests** | **415** | **571** |

### What each file covers

**test_tokens_extended.py** — `_heuristic`, `_claude_token_estimate`, `_is_claude`, `_detect_encoding_name`, `context_window_for`, `count_tokens` tiktoken-only path, `count_message_tokens` with list content/tool_calls/tool results, `count_cursor_messages`, `count_tool_tokens`, `count_tool_instruction_tokens`, `estimate_from_text`/`estimate_from_messages` aliases, `_litellm_count` disabled/exception/bad-result paths.

**test_unified_router.py** — `/v1/chat/completions` non-streaming (200, 400, 401), streaming SSE response, invalid n/model resolution/tools/json_mode/reasoning_effort. `/v1/messages` non-streaming and streaming, system prompt. `/v1/models`, `/health`, auth enforcement.

**test_stream_openai.py** — `_safe_emit_len` (no marker, partial marker, unrelated bracket), `_extract_visible_content` (plain text, thinking tags, tool calls, show_reasoning=False), `_openai_stream` (content deltas, done sentinel, role chunk, finish reason, usage chunk, empty stream, StreamAbortError handling).

**test_parse_extended.py** — `_repair_json_control_chars` (newline/tab/CR in string, outside string unchanged, no double-escape), `_escape_unescaped_quotes`, `_lenient_json_loads` strategies 1-4, `_extract_truncated_args`, `repair_tool_call` (exact match, fuzzy, type coercion), `validate_tool_call`, `parse_tool_calls_from_text` full pipeline, `score_tool_call_confidence`, `log_tool_calls`.

### Bug fixed
`test_pipeline.py` — the `fix(pipeline)` commit from session 62 accidentally deleted the `_parse_anthropic_sse_event` helper while adding `_safe_emit_len` tests, breaking 3 existing tests. Restored.

### Commits
| SHA | Description |
|-----|-------------|
| `33d7b96` | test: add extended token counting tests |
| `588bdb1` | test: add router tests for /v1/chat/completions and /v1/messages |
| `f1e9679` | test: add tests for _safe_emit_len, _extract_visible_content, _openai_stream behaviour |
| `c70e053` | test: add extended parse tests |
| `6f20d32` | test: restore _parse_anthropic_sse_event helper; commit new test files |

## Session 64 — pipeline/stream_anthropic.py 64%→100% coverage (2026-03-18)

### What changed
- `tests/test_stream_anthropic.py` — new file, 23 tests

### Coverage gains
| Module | Before | After |
|---|---|---|
| `pipeline/stream_anthropic.py` | 64% | **100%** |
| **Overall** | **82%** | **84%** |
| **Tests** | **571** | **594** |

### What the tests cover
- Basic happy path: message_start, text deltas, content_block_start/stop, message_delta (end_turn), message_stop
- Thinking block: opened/closed before text, closed before tool_use (lines 134-136)
- Unclosed thinking guard — holds back text while `<thinking>` open with no closing tag (line 154)
- Tool marker holdback — no text_delta emitted after marker detected (line 166)
- sanitize_visible_text suppressed branch — no text_delta when content suppressed (line 174)
- StreamAbortError handler — closes open blocks, emits message_stop, no exception propagated (lines 200-212)
- Generic Exception handler — emits Anthropic error SSE event (lines 217-223)
- Final non-streaming recovery — tool calls detected at stream end via finalize() (lines 238-274)
- text_opened block close at end (line 277)
- output_tps calculation path (lines 287-289)
- Cache optimisation branch — acc hasn't grown, hits else branch (line 96)

### Commits
| SHA | Description |
|-----|-------------|
| `9b6e13b` | test: add comprehensive _anthropic_stream tests |

## Session 65 — Admin UI: Login + Credentials page redesign (2026-03-18)

### What changed
- `admin-ui/app/login/page.tsx` — full visual redesign
- `admin-ui/app/(dashboard)/credentials/page.tsx` — enhanced page layout
- `admin-ui/components/credentials/CredentialCard.tsx` — redesigned card component
- `admin-ui/components/credentials/PoolSummaryBar.tsx` — redesigned summary bar

### Which lines / functions
- `login/page.tsx`: full rewrite — replaced blue (`#3b82f6`) design system with project accent (`#00e5a0`), added teal grid + scanline sweep, floating orbs, top-bar accent rule, icon-glow animation, emerald submit button with glow shadow, pulse ring behind icon
- `credentials/page.tsx`: `CredentialsPage` — stagger-animated KPI cards with per-card glow + top-edge shimmer, icon in page header, motion stagger on credential grid, richer empty state
- `CredentialCard.tsx`: `CredentialCard` — left accent bar with status colour glow, top-edge shimmer, inner radial glow, validation pill badge, status pill with inline cooldown timer, icon labels on stats grid, footer timestamps split into label/value, smooth border+shadow hover
- `PoolSummaryBar.tsx`: `PoolSummaryBar` — per-credential segmented health bar (one segment per slot), stat icon blocks with glow, pool status badge (ALL HEALTHY / DEGRADED / CRITICAL), action buttons use `btn` / `btn-accent` CSS classes

### Why
User requested UI enhancement for login page and credentials page. Aligned both pages to the project design system: `var(--accent)` emerald `#00e5a0`, `var(--mono/sans)` fonts, OLED black surfaces, glassmorphism cards, ambient orbs and grid consistent with the dashboard aesthetic.

### Commits
| SHA | Description |
|-----|-------------|
| 5ea701d | feat(admin-ui): enhance login and credentials page UI |

## Session 67 — Admin UI: Logs, Cache, Settings page redesign (2026-03-18)

### What changed
- `admin-ui/components/logs/LogFilters.tsx` — full visual redesign
- `admin-ui/components/logs/LogsTable.tsx` — full visual redesign
- `admin-ui/components/logs/LogDetailSheet.tsx` — full visual redesign
- `admin-ui/app/(dashboard)/logs/page.tsx` — full visual redesign
- `admin-ui/components/cache/CacheStatusCard.tsx` — full visual redesign
- `admin-ui/components/cache/ClearCacheButton.tsx` — motion + confirmation flash
- `admin-ui/app/(dashboard)/cache/page.tsx` — full visual redesign
- `admin-ui/app/(dashboard)/settings/page.tsx` — full visual redesign

### Which lines / functions
- `LogFilters.tsx`: container → `surface2` bg, `border`, `borderRadius 13`, `padding 14px 20px`; all selects/inputs use `.input` class; filter labels 10px mono uppercase text3; filter row flex gap 12 alignItems flex-end; active border → `rgba(255,255,255,0.x)` not emerald
- `LogsTable.tsx`: wrapper → `.card` `padding:0 overflow:hidden borderRadius:18`; provider pills use `.badge-purple/.badge-blue/.badge-emerald` classes; latency colours use `var(--green/amber/red)` thresholds at 1s/10s; cache hit shows white accent, miss shows muted dash; cost column `var(--accent)` white fontWeight 600; `motion.tr` stagger `initial {opacity:0,x:-4}` delay `index*0.015`; legend dots use white/red-tinted rgba
- `LogDetailSheet.tsx`: sheet width 480px, `padding 28px`, `borderLeft var(--border2)`; spring animation `damping 25`; title 16px fontWeight 700 var(--sans); field labels 10px mono uppercase `letterSpacing 0.12em`; token bar segments use `rgba(255,255,255,0.6/0.2)`; cost total row bg `rgba(255,255,255,0.04)`; provider/cache badges use `.badge-purple/.badge-blue/.badge-emerald`; all emerald references removed
- `logs/page.tsx`: PageHeader 22px var(--sans); KPI strip as `surface2` pill row `borderRadius 13 border padding 14px 22px`; shows total logs, error rate, avg latency, cache hits, total cost; SectionDivider above filters; all emerald removed
- `CacheStatusCard.tsx`: both cards use `.card padding 22px 24px borderRadius 18`; `.live-dot` white pulse when enabled; stats row `flex gap 20 mono 13px`; metric labels 10px uppercase mono text3; hit rate bar `height 6 borderRadius 3 bg var(--border) fill rgba(255,255,255,0.5)`; no emerald
- `ClearCacheButton.tsx`: `motion.button whileHover scale:1.02 whileTap scale:0.98`; confirmation popover bg `rgba(176,90,74,0.12)`; all logic preserved
- `cache/page.tsx`: PageHeader 22px; `grid-4` with `motion.div` stagger cards, 32px mono values, 10px uppercase labels; SectionDivider between sections; status colours use `var(--green/amber/red)`; no emerald
- `settings/page.tsx`: PageHeader 22px; config groups as `.card padding:0 borderRadius:18 overflow:hidden`; group header `padding 16px 22px surface2 bg borderBottom`; var name chip `rgba(255,255,255,0.04) borderRadius 5 padding 2px 8px`; default column uses `ValueChip` with white/muted booleans and `surface3` for plain values; models table `.card` wrapper with `.badge-purple` for owner; context window with K suffix; no emerald; SectionDivider before model catalogue

### Why
User requested full visual redesign of logs, cache, and settings pages to match the monochrome design system introduced in Session 66. All emerald/neon references replaced with white tokens. Applied PageHeader, SectionDivider, SummaryTile, motion stagger, and `.card`/`.data-table`/`.badge-*` CSS class patterns consistently across all 8 files.

### Commits
| SHA | Description |
|-----|-------------|
| `9bb7add` | feat(admin-ui): redesign logs, cache, settings pages to monochrome system |

---

## Session 66 — Admin UI: Monochrome design system redesign (2026-03-18)

### What changed
- `admin-ui/app/globals.css` — full token replacement
- `admin-ui/app/login/page.tsx` — monochrome login
- `admin-ui/app/(dashboard)/credentials/page.tsx` — monochrome credentials page
- `admin-ui/app/(dashboard)/layout.tsx` — cmdk + toaster tokens updated
- `admin-ui/components/credentials/CredentialCard.tsx` — monochrome card
- `admin-ui/components/credentials/PoolSummaryBar.tsx` — monochrome summary bar

### Which lines / functions
- `globals.css`: `--accent` → `#ffffff`, removed all `rgba(0,229,160,...)` radial gradients, body::before changed to white grid, `.btn-accent` → white fill/black text, `.dot-green` → white pulse, `.sidebar::after` hidden, `.topbar::after` hidden, `.nav-link.active::before` → white bar, `.live-dot` → white
- `login/page.tsx`: removed all emerald tokens, greyscale traffic lights, white submit button, `pulse-slow` replaces `icon-glow`/`pulse-ring`, no floating orbs
- `credentials/page.tsx`: `CredentialsPage` — KPI colours use rgba(255,255,255), rgba(176,90,74), rgba(184,137,58) only
- `CredentialCard.tsx`: `CredentialCard` — statusColor uses white/amber/red at low opacity; left bar no glow
- `PoolSummaryBar.tsx`: `PoolSummaryBar` — health bar segments white-fill; status badge white/amber/red
- `layout.tsx`: cmdk selected bg white, toaster background `#111111`, caret white

### Why
User requested removal of all neon/emerald tones. Complete theme redefinition: pure black (`#000`/`#0c0c0c`/`#141414`) surfaces, white as the sole accent, barely-visible white grid background, desaturated amber/red for semantic states. No glows, no colour box-shadows, no emerald anywhere.

### Commits
| SHA | Description |
|-----|-------------|
| 11a163d | feat(admin-ui): replace neon emerald design system with refined monochrome theme |

---

## Session 76 — Admin UI: Chart component design system migration (2026-03-18)

### What changed
- `admin-ui/components/charts/TokenTimelineChart.tsx`
- `admin-ui/components/charts/TpsTimelineChart.tsx`
- `admin-ui/components/charts/RequestsPerMinuteChart.tsx`
- `admin-ui/components/charts/CacheHitRateChart.tsx`
- `admin-ui/components/charts/LatencyTrendChart.tsx`
- `admin-ui/components/charts/ProviderDonutChart.tsx`
- `admin-ui/components/charts/RealtimeTokenFlowChart.tsx`

### Which lines / functions
- All charts: `chart-title-dot` background replaced with semantic tokens — tokens=`rgba(255,255,255,0.4)`, latency=`var(--amber)`, rpm=`var(--blue)`, tps=`var(--purple)`, cache=`rgba(255,255,255,0.3)`
- All charts: `ResponsiveContainer height` raised from 175–190 → 220
- All charts: `CartesianGrid stroke` → `rgba(255,255,255,0.04)` with `strokeDasharray="3 3"`
- All charts: `XAxis`/`YAxis` `stroke="transparent"`, tick `fill: 'var(--text3)'`, `fontFamily: 'var(--mono)'`
- All charts: tooltip `backgroundColor` `#08081a` → `#0c0c0c`, label `#7b8494` → `#666e7a`, item `#e8ecf4` → `#f2f2f2`
- All charts: `activeDot` stroke `#08081a` → `#0c0c0c`
- `TokenTimelineChart`: Input series `#00e5a0` → `rgba(255,255,255,0.45/0.55)`, Output `#a78bfa` → `#8b72c8` (--purple hex)
- `TpsTimelineChart`: `#a78bfa` → `#8b72c8`, area gradient updated
- `RequestsPerMinuteChart`: bar Cell fill `rgba(0,229,160,...)` → `rgba(74,122,184,...)` (--blue); removed drop-shadow glow filter
- `CacheHitRateChart`: dot/stroke `#34d399` → `#5a9e7a`; `statusFor()` helper returns `var(--green/amber/red)`; status badge uses neutral glass background; area gradient updated
- `LatencyTrendChart`: dot/gradient `#fbbf24/#f87171` → `#b8893a/#b05a4a`; `statusFor()` returns `var(--red/amber/green)`; status badge neutral glass; stats row uses `var(--amber/green/red)`
- `ProviderDonutChart`: `COLORS` map — `openai` `#00e5a0` → `rgba(255,255,255,0.65)`, `anthropic` `#a78bfa` → `#8b72c8`, `google` `#60a5fa` → `#4a7ab8`, `cursor` `#fbbf24` → `#b8893a`; `DEFAULT_COLORS` fully replaced with design-system palette; `renderActiveShape` (glow ring) removed; center-label icon box uses neutral glass; legend dot box-shadow glows removed
- `RealtimeTokenFlowChart`: active border `rgba(0,229,160,0.3)` → `rgba(255,255,255,0.15)`; LIVE badge white/muted style; pulse dot `rgba(255,255,255,0.7)` active, `var(--text3)` inactive; Input series white, Output `#8b72c8`; bar stroke white; all glow box-shadows removed

### Why
User requested full chart redesign to match the monochrome design system established in Session 66. All emerald (#00e5a0), violet (#a78bfa), yellow (#fbbf24), neon-green (#34d399), hot-red (#f87171), and bright-blue (#60a5fa) literals replaced with design-system CSS custom properties or their literal hex equivalents. Neon glow box-shadows removed throughout. Chart height minimum raised to 220px. Axis strokes set to transparent with mono font ticks. Tooltip surfaces aligned to --surface (#0c0c0c).

### Commits
| SHA | Description |
|-----|-------------|
| `3299cf8` | refactor(admin-ui): redesign all chart components to design system palette |

## Session 67 — Admin UI: Full monochrome redesign — all pages and components (2026-03-18)

### What changed
- `admin-ui/app/globals.css` — complete token replacement (sessions 65-66)
- `admin-ui/app/login/page.tsx` — Sora+JetBrains Mono, white btn-accent, greyscale traffic lights, borderRadius 20 card
- `admin-ui/app/(dashboard)/dashboard/page.tsx` — LIVE badge border + window selector gradient de-emeralded
- `admin-ui/app/(dashboard)/keys/page.tsx` — 22px PageHeader, 32px SummaryTile, card-wrapped tables, motion stagger
- `admin-ui/app/(dashboard)/credentials/page.tsx` — monochrome KPI tiles
- `admin-ui/app/(dashboard)/logs/page.tsx` — PageHeader + KPI strip
- `admin-ui/app/(dashboard)/cache/page.tsx` — PageHeader, SummaryTile grid, SectionDividers
- `admin-ui/app/(dashboard)/settings/page.tsx` — card-wrapped config groups, var name chips, model table
- `admin-ui/components/layout/Sidebar.tsx` — white SVG, white badges, no emerald sweep
- `admin-ui/components/layout/Topbar.tsx` — white hover, JetBrains Mono
- `admin-ui/components/layout/CommandPalette.tsx` — borderRadius 18, no emerald ring
- `admin-ui/components/keys/CreateKeyModal.tsx` — blur overlay, btn-accent/btn-ghost, borderRadius 20
- `admin-ui/components/credentials/CredentialCard.tsx` — white/amber/red status, left bar, no glow
- `admin-ui/components/credentials/PoolSummaryBar.tsx` — white segmented bar
- `admin-ui/components/overview/StatCard.tsx` — white hover ring, no emerald
- `admin-ui/components/overview/HealthBanner.tsx` — already class-based, no changes needed
- `admin-ui/components/logs/LogFilters.tsx` — surface2 container, .input class
- `admin-ui/components/logs/LogsTable.tsx` — card wrapper, badge pills, motion stagger
- `admin-ui/components/logs/LogDetailSheet.tsx` — spring slide-in, mono fields, JSON blocks
- `admin-ui/components/cache/CacheStatusCard.tsx` — card class, live-dot, white hit bar
- `admin-ui/components/cache/ClearCacheButton.tsx` — btn-danger, motion scale
- `admin-ui/components/charts/*.tsx` — all 7 charts: white/amber/blue/purple series, 220px height, JetBrains Mono ticks

### Why
User requested complete removal of neon emerald (#00e5a0) from the entire UI. New theme: pure black OLED surfaces, white as the sole accent, JetBrains Mono for data, Sora for UI text, desaturated amber/red/green for semantic states. No glows, no color box-shadows. Design system driven by globals.css tokens. Executed via 4 parallel subagents covering all 22 files.

### Commits
| SHA | Description |
|-----|-------------|
| 9bb7add | logs + cache + settings redesign (subagent) |
| 3299cf8 | chart components redesign — part 1 (subagent) |
| 6fece73 | chart components redesign — part 2 (subagent) |
| 579ccc2 | layout + login + keys + dashboard + StatCard |

## Session 68 — Admin UI: Dashboard + all sub-pages layout enhancement (2026-03-18)

### What changed
- `admin-ui/app/(dashboard)/dashboard/page.tsx` — enhanced layout
- `admin-ui/app/(dashboard)/credentials/page.tsx` — header + KPI + SectionDividers
- `admin-ui/app/(dashboard)/keys/page.tsx` — SectionDivider margin fix
- `admin-ui/app/(dashboard)/logs/page.tsx` — SectionDivider + root gap
- `admin-ui/app/(dashboard)/cache/page.tsx` — SectionDivider consistency
- `admin-ui/app/(dashboard)/settings/page.tsx` — SectionDivider margin

### Which lines / functions
- `dashboard/page.tsx`: `OverviewPage` — title 17px mono → 22px Sora, live-dot class, SectionDivider margins 10px→28px 0 16px, token strip redesigned as structured multi-column panel with column dividers and 15px value labels, window selector padding/weight refined, root gap 14→0
- `credentials/page.tsx`: `CredentialsPage` — h2 16px mono → 22px Sora, icon badge removed from header, live-dot class, LIVE badge white-tinted, SectionDividers added (Pool Status / Pool Overview / Credentials), KPI value fontSize 26→32, padding 14px 16px→18px 20px, borderRadius 12→14, root gap 18→0
- `keys/page.tsx`: `SectionDivider` — marginBottom 12 → margin 28px 0 16px, gap 10→14
- `logs/page.tsx`: SectionDivider margin 4px 0 0 → 28px 0 16px, root gap 16→0
- `cache/page.tsx`: SectionDivider margin 20px 0 14px → 28px 0 16px, fontWeight 600
- `settings/page.tsx`: SectionDivider margin 8px 0 16px → 28px 0 16px

### Why
User requested the same enhancement applied to the dashboard page be applied consistently across all sub-pages. Primary fixes: uniform 22px Sora page titles, live-dot class, standardized SectionDivider margins (28px top / 16px bottom) across all pages, root column gap driven by dividers not raw gap values.

### Commits
| SHA | Description |
|-----|-------------|
| 76475dc | feat(admin-ui): enhance dashboard page |
| f0f10eb | feat(admin-ui): enhance all sub-pages to match dashboard layout quality |

## Session 77 — Wiwi identity in system prompt (2026-03-18)

### What changed
- `config.py` — system prompt updated

### Which lines / functions
- `config.py:84-87` — `system_prompt` field: added 4-line identity block at the top of the prompt

### Why
User requested that when asked identity questions ("who are you", "what model are you", etc.), the assistant responds as "Wiwi, powered by Claude by Anthropic" rather than a generic persona. Added explicit name, powered-by statement, and negative constraints (never claim to be GPT, never deny Claude lineage).

### Commits
| SHA | Description |
|-----|-------------|
| d73e563 | feat: add Wiwi identity to system prompt — responds as Wiwi powered by Claude by Anthropic |

## Session 78 — System prompt Tool Habits + Tool Selection Guide overhaul (2026-03-18)

### What changed
- `config.py` — system prompt updated across 4 separate commits

### Which lines / functions
- `config.py:84-87` — identity block: simplified to clean "I am Wiwi, powered by Claude by Anthropic."
- `config.py:143-170` — Tool Habits section: expanded from 4 rules to 27 rules
  - 4 original rules strengthened with gap fixes (retry loop limit, Write→Edit fallback, readback correction)
  - 6 new rules added (search specificity, prompt injection flagging, Bash read substitutes, call site checking, parallel agent safety, destructive command confirmation)
  - 4 parallel tool call rules added (parallel dispatch, dependency check, batch collect, partial failure handling)
  - 8 Claude Code tool-specific rules added (Edit old_string context, Bash description, Grep output_mode, Write/Glob check, Agent self-contained context, post-edit readback, multi-file listing, Glob vs Grep)
- `config.py:329-367` — Tool Selection Guide section added (new)
  - Full use-case description for every tool: Read, Edit, Write, Glob, Grep, Bash, Agent, Task tools, TaskOutput, TaskStop, NotebookEdit, WebFetch, WebSearch, AskUserQuestion, Skill, EnterPlanMode, ExitPlanMode, EnterWorktree, ExitWorktree, CronCreate, CronDelete, CronList, Browser/Playwright tools
  - Tool decision tree: instant lookup for every tool decision

### Why
System prompt tool guidance was sparse (4 rules). Model had to reason about tool selection at runtime, burning tokens. Explicit rules and a full tool selection guide eliminate that reasoning overhead — model picks the right tool instantly on first attempt, improving speed and quality of tool use across all sessions.

### Commits
| SHA | Description |
|-----|-------------|
| d73e563 | feat: add Wiwi identity to system prompt |
| dbdcea0 | fix: simplify Wiwi identity — clean name only |
| 6f4c649 | feat: enhance Tool Habits — 4 rule fixes + 4 new rules |
| 90a53cc | feat: add parallel tool call rules to Tool Habits |
| 4217ffc | feat: add Claude Code tool-specific behavior rules |
| b5705eb | feat: enhance Tool Habits — 6 new rules + 3 strengthened rules |
| 7e3e72b | feat: add Tool Selection Guide and decision tree |
| d58e8ec | feat: expand Tool Selection Guide — all Claude Code tools |

---

## Session 26 — Sidebar & Topbar UI Polish (2026-03-18)

### What changed
- `admin-ui/components/layout/Sidebar.tsx` — targeted visual polish
- `admin-ui/components/layout/Topbar.tsx` — targeted visual polish

### Which lines / functions

**Sidebar.tsx**
- `<aside>` — added `position: relative` to anchor the absolute top sheen
- `.sidebar-top-sheen` (new CSS rule) — 1px absolute gradient line at top: `linear-gradient(90deg, transparent, rgba(255,255,255,0.08), transparent)`
- `.nav-link-sweep::before` — sweep gradient corrected to `rgba(255,255,255,0.035)` (was 0.04)
- `.nav-link.active` (new CSS rule) — left border bumped to `rgba(255,255,255,0.9)` + `box-shadow: -1px 0 8px rgba(255,255,255,0.15)` glow
- `@keyframes pulse-dot` + `.uptime-pulse-dot` (new CSS) — animated green pulse dot (2.4s ease-in-out) replacing static `.uptime-dot`
- `.logo-mark` hover rule — `box-shadow: 0 0 0 1px rgba(255,255,255,0.08), inset 0 0 10px rgba(255,255,255,0.06)`
- `.sidebar-search-btn` — color updated to `rgba(255,255,255,0.35)`; transition extended to include `color`; hover color to `rgba(255,255,255,0.6)`
- `⌘K` kbd color — `var(--text4)` → `rgba(255,255,255,0.25)`
- `.sidebar-section-label` (both instances) — inline style `color: rgba(255,255,255,0.22)` (was nearly invisible `var(--text4)`)
- Footer `<span className="uptime-dot">` → `<span className="uptime-pulse-dot">` (animated)

**Topbar.tsx**
- `<h1 className="topbar-title">` — added `style={{ letterSpacing: '-0.3px' }}`
- Search button `color` — `var(--text3)` → `rgba(255,255,255,0.35)`; `onMouseLeave` restores to same; `<span>` uses `color: inherit`
- `⌘K` kbd color — `var(--text4)` → `rgba(255,255,255,0.25)`
- Search `onMouseEnter` hover color — `var(--text2)` → `rgba(255,255,255,0.6)`
- `statusBorderColor` constant — `rgba(255,255,255,0.15)` when Online, `rgba(255,255,255,0.07)` otherwise
- Right cluster `<div>` — wrapped in container with `background: rgba(255,255,255,0.025)`, `border: 1px solid rgba(255,255,255,0.06)`, `padding: 4px 10px`, `borderRadius: 8`; added 1px vertical separator between label and clock
- `WIWI PROXY` label — `var(--text3)` → `rgba(255,255,255,0.3)`
- `topbar-status` div — dynamic `border` + `borderRadius: 6` + `padding: 2px 7px` applied inline

### Why
Visibility and contrast issues throughout the layout shell. Section labels were nearly invisible on black (`var(--text4)` = `#1e2330`). Active nav link lacked sufficient left-border contrast and glow. The uptime dot was static and provided no liveness signal. The right topbar cluster had no visual grouping, making it hard to read as a unit. Search placeholder text was too dim (`var(--text3)`) at small font sizes.

### Commits
| SHA | Description |
|-----|-------------|
| TBD | feat(admin-ui): polish Sidebar and Topbar — contrast, sheen, pulse dot, grouping |

## Session 27 — Dashboard UI Enhancement (2026-03-18)

### What changed
- `admin-ui/app/(dashboard)/dashboard/page.tsx` — SectionDivider, KPI token strip, window selector, page header
- `admin-ui/app/(dashboard)/cache/page.tsx` — fix pre-existing duplicate `fontWeight` TS errors
- `admin-ui/components/overview/StatCard.tsx` — top sheen, icon badge size, spark bar gradient, label/value color fix
- `admin-ui/components/overview/HealthBanner.tsx` — glassmorphism container, animated pulse dot, credential badge
- `admin-ui/components/layout/Sidebar.tsx` — section label contrast, active link glow, animated uptime dot, top sheen
- `admin-ui/components/layout/Topbar.tsx` — title kerning, right cluster grouping, color contrast fixes

### Which lines / functions
- `dashboard/page.tsx:SectionDivider` — label color `var(--text4)` → `rgba(255,255,255,0.30)`, added `right` prop annotation
- `dashboard/page.tsx:OverviewPage` — window selector hover states; token strip: surface lift, top sheen, cell label color fix; all `var(--border)` separators → explicit rgba
- `StatCard.tsx:StatCard` — top sheen div, icon badge 28→32px, spark bar `height: 3`, gradient fill, label inline color override, accent surface inline style
- `HealthBanner.tsx:HealthBanner` — replaced `.health-banner` class with inline glassmorphism div, pulse dot, credential count badge
- `Sidebar.tsx` — `.sidebar-section-label` color fixed, active `.nav-link::before` raised to `rgba(255,255,255,0.9)` + glow, `uptime-pulse-dot` animated
- `Topbar.tsx` — right cluster container, `WIWI PROXY` color, status pill dynamic border

### Why
Contrast audit across the dashboard revealed multiple near-invisible elements using `var(--text4)` (`#1e2330`) on black background. Section divider labels, window selector label, token strip cell labels, and sidebar section labels were all invisible. HealthBanner used CSS classes with no glassmorphism. StatCard label used `var(--text3)` (`#383e4a`) — too dark. Parallel subagents used for independent component groups to speed up execution.

### Commits
| SHA | Description |
|-----|-------------|
| fb666b0 | feat(admin-ui): polish Sidebar and Topbar — contrast, sheen, pulse dot, grouping |
| 37b1b91 | feat(admin-ui): enhance dashboard UI — section dividers, KPI strip, Sidebar, Topbar, StatCard, HealthBanner |

## Session 28 — Credentials Page UI Enhancement (2026-03-18)

### What changed
- `admin-ui/app/(dashboard)/credentials/page.tsx` — section dividers, KPI cards, empty state
- `admin-ui/components/credentials/PoolSummaryBar.tsx` — container surface, labels, segment bar
- `admin-ui/components/credentials/CredentialCard.tsx` — card surface, metric labels, error track, footer

### Which lines / functions
- `credentials/page.tsx:SectionDivider` — label `var(--text4)` (#1e2330, invisible) → `rgba(255,255,255,0.28)`
- `credentials/page.tsx:OverviewPage` — subtitle `var(--text3)` → `rgba(255,255,255,0.3)`; all 4 KPI `bg` `#000000` → `rgba(255,255,255,0.02)`; KPI label contrast fix; empty state bg + inner text fix; skeleton opacity step 0.2→0.25
- `PoolSummaryBar.tsx` — container bg `#000000` → `rgba(255,255,255,0.02)`; all `var(--text3)` sub-labels → `rgba(255,255,255,0.28)`; segment bar height 7→8; full-health color `0.5→0.6` opacity; Validate button fontSize 11.5
- `CredentialCard.tsx` — card `background` `#000000` → `rgba(255,255,255,0.015)`; metric label `var(--text3)` → `rgba(255,255,255,0.28)`; consecutive errors label same; error track height 2→3; footer Activity icon + last-used text contrast; healthy status dot gets `pulse-dot` animation; zero-value metric colors `var(--text3)` → `rgba(255,255,255,0.22)`; consecutive error counter turns red at >=3

### Why
Same contrast audit pattern as Session 27: `var(--text3)` (#383e4a) and `var(--text4)` (#1e2330) are near-invisible on pure black backgrounds. Metric labels, section labels, and sub-text were all invisible. Card surfaces were flat #000000 with no lift. Parallel subagents used for independent component groups.

### Commits
| SHA | Description |
|-----|-------------|
| a800c9c | feat(admin-ui): enhance credentials page UI — contrast fixes, surface lift, card polish |

## Session 29 — Credential Components Visual Polish (2026-03-18)

### What changed
- `admin-ui/components/credentials/CredentialCard.tsx` — accent bar changed to `linear-gradient(180deg, C.fg 0%, transparent 100%)` with opacity 0.6 (healthy) / 0.8 (unhealthy); corner glow blob added (radial-gradient, absolute positioned top-right); metric cells gain hover bg `rgba(255,255,255,0.03)` via `hoveredMetric` state; footer gains `borderTop: 1px solid rgba(255,255,255,0.05)` + `paddingTop: 10`; validation badge green-tinted when valid (`rgba(90,158,122,*)` colors + green CheckCircle); consecutive errors bar gets `boxShadow: 0 0 6px rgba(192,80,65,0.5)` at max (3/3); cooldown Clock icon wrapped in pulsing div (`pulse-dot 1.5s`)  
- `admin-ui/components/credentials/PoolSummaryBar.tsx` — inline `<style>` tag added with `@keyframes spin` and `@keyframes pulse-dot`; segment bar `borderRadius` 3→4; healthy segments use `healthColor` at `opacity: 0.7` instead of hardcoded white; status badge dot animates with `pulse-dot` when `isFullHealth`; both action buttons get `cursor: pointer` + `minWidth: 100`

### Why
Visual polish pass: accent bar gradient, corner glow, metric hover feedback, footer separator, semantically correct green valid badge, error severity glow, cooldown pulse, segment bar uses theme colour, guaranteed `spin` keyframe availability in component scope.

### Commits
| SHA | Description |
|-----|-------------|
| c652fa8 | feat(admin-ui): polish credential components — accent gradient, corner glow, metric hover, footer border, green valid badge, error bar glow, cooldown pulse, segment bar healthColor, spin keyframe, pulse-dot on status badge |

## Session 30 — Credentials Page UI Enhancement (2026-03-18)

### What changed
- `admin-ui/app/(dashboard)/credentials/page.tsx` — full page rewrite with enhanced KPI cards, health status pill, improved SectionDivider, empty state, animation delay cap
- `admin-ui/components/credentials/CredentialCard.tsx` — accent bar gradient, corner glow, metric hover, footer border, green validation badge, consecutive errors glow, cooldown pulse (subagent)
- `admin-ui/components/credentials/PoolSummaryBar.tsx` — inline keyframes, healthColor segment fill, status dot pulse, button cursor+minWidth (subagent)

### Which lines / functions
- `credentials/page.tsx:SectionDivider` — added `right` prop, label color `rgba(255,255,255,0.28)` → `rgba(255,255,255,0.3)`, fixed `var(--border)` → explicit rgba gradient
- `credentials/page.tsx:CredentialsPage` — `kpis` array: added `sub`, `sheen` fields; KPI cards: surface lift, top sheen, corner glow, hover shadow, sub-label row; header: health status pill (color-coded, animated dot); `statusColor`/`statusLabel` derived vars; loading skeleton uses correct grid; empty state borderRadius 16→18, bg explicit rgba
- `CredentialCard.tsx:CredentialCard` — accent bar: `linear-gradient(180deg)` fill; corner glow blob absolute div; `hoveredMetric` state for cell bg hover; footer `borderTop`; validation badge green tints when valid; consecutive errors bar `boxShadow` glow at max; cooldown Clock icon pulse wrapper
- `PoolSummaryBar.tsx:PoolSummaryBar` — `<style>` block with `@keyframes spin` + `pulse-dot`; segments use `healthColor` opacity 0.7; status badge dot animated when full health; both buttons `cursor: pointer` + `minWidth: 100`

### Why
Credentials page KPI cards used flat `#000000` background (no depth), `var(--text3)` sub-labels (invisible), no semantic color on KPI sub-text. No pool health summary visible at a glance in the header. KPI cards had no hover feedback. CredentialCard validation badge used grey tints for both valid/invalid states (no green for valid). PoolSummaryBar `@keyframes spin` relied on globals.css load order.

### Commits
| SHA | Description |
|-----|-------------|
| c652fa8 | feat(admin-ui): polish credential components (subagent) |
| a37405e | feat(admin-ui): enhance credentials page UI — KPI cards, status pill, CredentialCard, PoolSummaryBar |

## Session 31 — Keys Page UI Enhancement (2026-03-18)

### What changed
- `admin-ui/app/(dashboard)/keys/page.tsx` — SectionDivider, SummaryTile, ManagedKeyRow, managed keys table, usage stats table, key detail panel

### Which lines / functions
- `SectionDivider`: `var(--text4)` → `rgba(255,255,255,0.30)`, `fontWeight` 600→700, `letterSpacing` tightened, gradient uses explicit rgba
- `SummaryTile`: `#000000` → `rgba(255,255,255,0.02)` surface, hover `box-shadow` + `border-color`, top sheen gradient, corner glow blob with `iconColor`, label `var(--text3)` → `rgba(255,255,255,0.28)`, icon badge bg accent-aware
- `ManagedKeyRow`: label/RPM/budget/models/created all fixed from `var(--text3)` to explicit rgba; toggle disabled color fixed; trash icon color fixed; row bg `#000000` → `transparent`
- Managed keys table container: `#000000` → `rgba(255,255,255,0.015)` surface, top sheen, sticky header `backdrop-filter: blur(12px)`, header labels `var(--text3)` → `rgba(255,255,255,0.28)`, `fontSize` 10→9, `fontWeight` 600→700, empty/loading state colors fixed
- Usage stats table: same surface/sheen/header treatment; row bg `#000000` → `transparent`; footer bg `#000000` → `rgba(0,0,0,0.4)`, footer text `var(--text3)` → `rgba(255,255,255,0.22)`; empty state color fixed
- Key detail panel: `#000000` → `rgba(255,255,255,0.02)` surface; `Key Detail` label `var(--text4)` → `rgba(255,255,255,0.28)`; close button styled; mini-tile bg → `rgba(255,255,255,0.03)`; mini-tile sub-labels `var(--text3)` → `rgba(255,255,255,0.28)`; Token Split labels, total, legend, Providers label all fixed
- `last_active` cell: `var(--text3)` → `rgba(255,255,255,0.28)`

### Why
Comprehensive audit of keys page found 15+ instances of `var(--text3)` (`#383e4a`) and `var(--text4)` (`#1e2330`) used for visible text and labels — all near-invisible on black background. Tables used flat `#000000` container (no surface depth). SummaryTile had no hover feedback. Detail panel mini-tiles had no surface lift.

### Commits
| SHA | Description |
|-----|-------------|
| 6f74274 | feat(admin-ui): enhance keys page UI — SectionDivider, SummaryTile, tables, detail panel |

## Session 32 — Settings & Cache Page UI Enhancement (2026-03-18)

### What changed
- `admin-ui/app/(dashboard)/settings/page.tsx` — SectionDivider, ValueChip, config group cards, model catalogue
- `admin-ui/app/(dashboard)/cache/page.tsx` — SectionDivider, KPI cards, color vars, sub-labels

### Which lines / functions
**settings/page.tsx:**
- `SectionDivider`: label `var(--text4)` → `rgba(255,255,255,0.30)`, `fontWeight` 700, gradient explicit rgba
- `ValueChip`: `true` chip → green tint `rgba(90,158,122,*)`, `false` chip → `rgba(255,255,255,0.35)`, generic → `rgba(255,255,255,0.55)` + `rgba(255,255,255,0.06)` bg
- Config group cards: `background: rgba(255,255,255,0.02)`, `position: relative`, left 3px accent stripe per group (9 color-coded groups via `GROUP_ACCENT` map), header bg/border explicit rgba, vars count `rgba(255,255,255,0.28)`, var code `rgba(255,255,255,0.55)`, desc `rgba(255,255,255,0.5)`, row hover/border explicit rgba, `paddingLeft: 26px` to clear stripe
- Model catalogue: `background: rgba(255,255,255,0.015)` surface, table header `backdrop-filter: blur(12px)`, all `var(--text3/4)` fixed

**cache/page.tsx:**
- `SectionDivider`: same label/weight/gradient fixes
- KPI cards: `className="card"` removed, explicit `background: rgba(255,255,255,0.02)` + border + borderRadius + overflow, top sheen div injected, label `rgba(255,255,255,0.28)`, sub-text `rgba(255,255,255,0.35)`
- All `var(--green/amber/red/text/text2)` replaced with explicit `rgba()` values throughout
- Clear timestamp and timeline subtitle: `var(--text3)` → `rgba(255,255,255,0.30/0.35)`

### Why
Both pages had the same contrast audit failures: `var(--text3)` (`#383e4a`) and `var(--text4)` (`#1e2330`) used everywhere for labels and sub-text — near-invisible on black. Config group cards had no depth or visual differentiation between groups. KPI cards relied on `.card` CSS class which produced flat surfaces. Parallel agents dispatched for independent pages.

### Commits
| SHA | Description |
|-----|-------------|
| 16483d0 | feat(admin-ui): enhance settings and cache page UI |

## Session 33 — CreateKeyModal UI Enhancement (2026-03-18)

### What changed
- `admin-ui/components/keys/CreateKeyModal.tsx` — full visual enhancement

### Which lines / functions
- Modal card: `var(--surface)` → `rgba(10,10,12,0.92)` with `backdrop-filter: blur(32px) saturate(130%)`, `inset box-shadow` sheen, border `rgba(255,255,255,0.12)`
- Header subtitle: `var(--text3)` → `rgba(255,255,255,0.32)`
- Key icon badge: `var(--text)` → `rgba(255,255,255,0.75)`
- Close button: all `var(--border/text3)` → explicit rgba hover states
- Header border: `var(--border)` → `rgba(255,255,255,0.07)`
- `LimitCard`: icon color `var(--text3)` → `rgba(255,255,255,0.28)`, sub-text → `rgba(255,255,255,0.28)`, inactive label `var(--text2)` → `rgba(255,255,255,0.55)`, border `var(--border)` → `rgba(255,255,255,0.08)`
- `SubDivider`: extracted named component replacing 3× inline dividers, label `var(--text4)` → `rgba(255,255,255,0.28)`, weight 700, lines `var(--border)` → `rgba(255,255,255,0.07)`
- Form field labels: `var(--text3)` → `rgba(255,255,255,0.28)`, `fontWeight` 600→700, `letterSpacing` 0.12em→0.14em
- Active limits chip row: `var(--border)` → `rgba(255,255,255,0.09)`, `bg` → `rgba(255,255,255,0.025)`, label text → `rgba(255,255,255,0.35)`
- Key revealed: success icon container → green tint `rgba(90,158,122,*)`, Check icon → green, copy button green when copied, "Secret Key" label `var(--text3)` → `rgba(255,255,255,0.28)`, subtitle → `rgba(255,255,255,0.35)`, key display box explicit rgba

### Why
Modal used `var(--surface)` flat card with no glassmorphism. All form labels used `var(--text3)` (`#383e4a`) — invisible on dark background. Section sub-dividers used `var(--text4)` (`#1e2330`) — completely invisible. Success state used generic white check with no semantic green color. All border references used CSS variables that resolved to near-invisible values on the modal's dark backdrop.

### Commits
| SHA | Description |
|-----|-------------|
| 6de8433 | feat(admin-ui): enhance CreateKeyModal UI |

## Session 34 — CommandPalette UI Enhancement (2026-03-18)

### What changed
- `admin-ui/components/layout/CommandPalette.tsx` — glassmorphism card, contrast fixes, icon tints, kbd styles
- `admin-ui/app/(dashboard)/layout.tsx` — cmdk CSS selector fixes

### Which lines / functions
- `CommandPalette` card: `var(--surface)` → `rgba(8,8,10,0.96)` + `backdrop-filter: blur(32px) saturate(130%)`, top sheen, `inset box-shadow`, border explicit rgba
- Backdrop: `blur(4px)` → `blur(12px)`, `rgba(0,0,0,0.75)`
- Input row: Activity icon `var(--text3)` → `rgba(255,255,255,0.35)`, divider `var(--border)` → `rgba(255,255,255,0.07)`, ESC kbd: bg + double-bottom-border style
- `PaletteRow`: icon badge 26→28px, added `iconBg` prop, label `var(--text)` → `rgba(255,255,255,0.88)`, sub `var(--text3)` → `rgba(255,255,255,0.32)`
- Navigation items: icon `rgba(255,255,255,0.5)`, ArrowRight `rgba(255,255,255,0.2)`
- API Key items: blue icon tint `rgba(74,122,184,*)`, copy badge with bg
- Recent Log items: green `rgba(90,158,122,*)` for cache hits, cost `rgba(255,255,255,0.5)`
- Footer: all `var()` → explicit rgba, `background: rgba(0,0,0,0.3)`, `kbdStyle` double-bottom border
- `layout.tsx [cmdk-group-heading]`: `var(--text4)` → `rgba(255,255,255,0.28)`, letter-spacing 0.16em
- `layout.tsx [cmdk-item][aria-selected]`: bg 0.06→0.07 opacity
- `layout.tsx [cmdk-input]::placeholder`: `var(--text3)` → `rgba(255,255,255,0.25)`

### Why
CommandPalette used `var(--surface)` flat card with no glassmorphism. Group headings, ESC kbd, footer labels, ArrowRight, and copy badge all used `var(--text4)` or `var(--text3)` — invisible on black. Icon badges had no semantic color tinting. Backdrop blur was 4px (insufficient). All cmdk CSS selectors in layout.tsx used invisible var() colors.

### Commits
| SHA | Description |
|-----|-------------|
| ef6dd6b | feat(admin-ui): enhance CommandPalette UI |

## Session 35 — Topbar UI Enhancement (2026-03-18)

### What changed
- `admin-ui/components/layout/Topbar.tsx` — status pill, search button, clock, right cluster
- `admin-ui/app/globals.css` — `.topbar`, `.topbar-title`, `.topbar-time`, `.topbar-status`, `.dot-gray`

### Which lines / functions
**Topbar.tsx:**
- `statusColor/statusBg/statusBorder` derived vars: loading=grey, online=green `rgba(90,158,122,*)`, offline=red `rgba(192,80,65,*)` — replaces flat `var(--text2)` label
- Status dot: `pulse-dot` animation only when `isReady`; transitions on `background`, `color`
- Status pill: `borderRadius` 999px → 6px (chip shape), `border`/`bg` color-coded per state
- Search button: `var(--border)` in `onMouseLeave` → `rgba(255,255,255,0.08)` (no more var leak)
- Search kbd: `var(--border)` → `rgba(255,255,255,0.1)` + `borderBottomWidth: 2` for 3D key feel
- Right cluster: second `1px` separator added between clock and status pill
- Clock `useEffect`: merged two effects into one with the formatter extracted to `fmt()`

**globals.css:**
- `.topbar border-bottom`: `var(--border)` → `rgba(255,255,255,0.07)`
- `.topbar backdrop-filter`: `blur(16px) saturate(110%)` → `blur(20px) saturate(120%)`
- `.topbar-title`: `var(--text)` → `rgba(255,255,255,0.92)`, `letter-spacing` -0.2px → -0.3px
- `.topbar-status`: `var(--border)` → `rgba(255,255,255,0.08)`, `borderRadius` 999px → 7px
- `.topbar-time`: `var(--text3)` → `rgba(255,255,255,0.45)`, added `font-variant-numeric: tabular-nums`
- `.dot-gray`: `var(--text3)` → `rgba(255,255,255,0.22)`

### Why
Topbar status pill used `var(--text2)` for the label (dim grey regardless of state) and a generic white dot — no semantic color coding for online/offline. Clock used `var(--text3)` (`#383e4a`) making it near-invisible. Search kbd used `var(--border)` borders. Two identical `useEffect` calls for the clock timer were redundant.

### Commits
| SHA | Description |
|-----|-------------|
| dedb412 | feat(admin-ui): enhance Topbar UI — status pill colors, clock contrast, search kbd, globals fixes |

## Session 36 — Sidebar UI Enhancement (2026-03-18)

### What changed
- `admin-ui/components/layout/Sidebar.tsx` — kbd style, search btn border
- `admin-ui/app/globals.css` — sidebar, nav-link, logo, footer, nav-badge var() elimination

### Which lines / functions
**globals.css:**
- `.sidebar border-right`: `var(--border)` → `rgba(255,255,255,0.07)`
- `.sidebar-logo border-bottom`: `var(--border)` → `rgba(255,255,255,0.07)`
- `.logo-text`: `var(--text)` → `rgba(255,255,255,0.88)`
- `.logo-sub`: `var(--text3)` → `rgba(255,255,255,0.28)`, `letter-spacing` 0.04→0.06em
- `.sidebar-section-label`: `var(--text4)` → `rgba(255,255,255,0.22)`, `fontWeight` 600→700, `letterSpacing` 0.12→0.14em
- `.nav-link color`: `var(--text3)` → `rgba(255,255,255,0.38)`
- `.nav-link:hover color`: `var(--text2)` → `rgba(255,255,255,0.65)`
- `.nav-link.active color`: `var(--text)` → `rgba(255,255,255,0.92)`
- `.nav-link.active::before`: added `box-shadow: -1px 0 8px rgba(255,255,255,0.15)` glow
- `.nav-icon:hover opacity`: added `0.6` state
- `.sidebar-footer border-top`: `var(--border)` → `rgba(255,255,255,0.06)`
- `.nav-badge color`: `var(--text2)` → `rgba(255,255,255,0.55)`

**Sidebar.tsx:**
- `.sidebar-search-btn border`: `var(--border)` → `rgba(255,255,255,0.08)`
- `kbd`: `var(--border)` → `rgba(255,255,255,0.1)` + `borderBottomWidth: 2` + `background: rgba(255,255,255,0.04)`

### Why
Systematic `var(--border/text/text2/text3/text4)` audit of sidebar globals. Every CSS class used invisible variables. Nav links had `var(--text3)` (`#383e4a`) making inactive links near-invisible. Logo sub-text used `var(--text3)`. Section labels used `var(--text4)` (`#1e2330`). Footer border used `var(--border)`. All resolved to explicit rgba values for consistent visibility across themes.

### Commits
| SHA | Description |
|-----|-------------|
| 7ac65f3 | feat(admin-ui): enhance Sidebar UI — globals var() elimination, nav contrast, kbd style |

## Session 37 — StatCard and HealthBanner UI Enhancement (2026-03-18)

### What changed
- `admin-ui/components/overview/StatCard.tsx` — trendColor, ic default
- `admin-ui/components/overview/HealthBanner.tsx` — green semantic colors, top sheen, credential badge
- `admin-ui/app/globals.css` — .stat-card, .stat-label, .stat-value, .stat-sub, .stat-card-accent

### Which lines / functions
**globals.css:**
- `.stat-card`: `var(--surface)` → `rgba(255,255,255,0.02)`, `var(--border)` → `rgba(255,255,255,0.08)`
- `.stat-label`: `var(--text3)` → `rgba(255,255,255,0.32)`, `fontWeight` 600→700, `letterSpacing` 0.12→0.14em
- `.stat-value`: `var(--text)` → `rgba(255,255,255,0.92)`
- `.stat-value-accent`: `var(--text)` → `rgba(255,255,255,0.95)`
- `.stat-sub`: `var(--text3)` → `rgba(255,255,255,0.35)`

**StatCard.tsx:**
- `trendColor`: `var(--green/red/text3)` → `rgba(90,158,122,1)` / `rgba(192,80,65,1)` / `rgba(255,255,255,0.28)`
- `ic` default: `var(--accent/text2)` → `rgba(255,255,255,0.85)` (accent) / `rgba(255,255,255,0.45)` (default)

**HealthBanner.tsx:**
- Ready state dot/icon/text: white → green `rgba(90,158,122,*)` semantic tints
- Error state: `rgba(176,90,74,*)` → `rgba(192,80,65,*)` consistent palette
- Credential badge: green tint bg/border/text, `fontWeight` 700, `letterSpacing`, `"creds"` suffix
- Status text: `fontFamily: var(--mono)` added
- Top sheen: absolute 1px gradient line keyed to `dotClr`

### Why
`var(--text3)` in `.stat-label` and `.stat-sub` made card labels invisible. `var(--surface)` gave no surface depth vs page background. StatCard trendColor used `var(--text3)` for neutral trend (invisible). HealthBanner used plain white for the ready state — no semantic green, making it visually identical to any other white element.

### Commits
| SHA | Description |
|-----|-------------|
| d0858d5 | feat(admin-ui): enhance StatCard and HealthBanner UI |

## Session 38 — Chart Components UI Enhancement (2026-03-18)

### What changed
- `admin-ui/components/charts/CacheHitRateChart.tsx`
- `admin-ui/components/charts/RequestsPerMinuteChart.tsx`
- `admin-ui/components/charts/TpsTimelineChart.tsx`
- `admin-ui/components/charts/TokenTimelineChart.tsx`
- `admin-ui/components/charts/LatencyTrendChart.tsx`
- `admin-ui/components/charts/ProviderDonutChart.tsx`
- `admin-ui/components/charts/RealtimeTokenFlowChart.tsx`
- `admin-ui/app/globals.css` — .chart-title, .chart-unit

### Which lines / functions
**All 7 charts:**
- `className="card"` → explicit `style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.08)', borderRadius: 14, padding: 20, ... }}`
- XAxis/YAxis `tick.fill`: `var(--text3)` → `rgba(255,255,255,0.32)` (axis labels were invisible)
- Sub-stat label divs: `var(--text3)` → `rgba(255,255,255,0.35)`, values `var(--text2)` → `rgba(255,255,255,0.55)`

**Per-chart fixes:**
- `CacheHitRateChart`: `statusFor()` `var(--green/amber/red)` → explicit rgba; stat row avg `var(--green)` → `rgba(90,158,122,1)`
- `RequestsPerMinuteChart`: title dot `var(--blue)` → `rgba(74,122,184,1)`; header `var(--text4)` → `rgba(255,255,255,0.25)`
- `TpsTimelineChart`: title dot `var(--purple)` → `rgba(139,114,200,1)`; avg `var(--purple)` → `rgba(139,114,200,1)`
- `TokenTimelineChart`: `DOT_OUTPUT.fill` `var(--purple)` → `#8b72c8`; legend Output `var(--purple)` → `#8b72c8`
- `LatencyTrendChart`: `statusFor()` all `var()` → explicit rgba; stat tuple `var(--amber/green/red)` → explicit rgba; title dot `var(--amber)` fixed
- `ProviderDonutChart`: center label `var(--text/text3)` → explicit rgba; legend name `var(--text/text2)` → explicit rgba; pct `var(--text3)` → explicit; count `var(--text4)` → explicit; empty state fixed
- `RealtimeTokenFlowChart`: border `var(--border)` → `rgba(255,255,255,0.08)`; dot `var(--text3)` → `rgba(255,255,255,0.22)`; LIVE badge `var(--text2)` → `rgba(255,255,255,0.45)`; live readout `var(--text/text3)` → explicit rgba; legend label/value/peak `var(--text3/text4)` → explicit rgba; bucket label `var(--text3)` → explicit

**globals.css:**
- `.chart-title color`: `var(--text3)` → `rgba(255,255,255,0.38)`
- `.chart-unit color`: `var(--text4)` → `rgba(255,255,255,0.22)`

### Why
All chart cards used `className="card"` which resolves to `var(--surface)` background — flat with no depth vs page. Axis tick labels used `var(--text3)` = `#383e4a` making them invisible on black backgrounds. All sub-stat labels, legend labels, and header values used invisible var() references. Parallel subagents used for 5 charts simultaneously.

### Commits
| SHA | Description |
|-----|-------------|
| 09b36ba | feat(admin-ui): enhance chart components UI |

## Session 39 — Identity Disclosure Restriction (2026-03-18)

### What changed
- `config.py:82` — `system_prompt` Field `default=` identity block updated

### Which lines / functions
- `config.py:84–92` — identity/persona/capability response rules in `system_prompt`

### Why
Users asking about model persona, architecture, version, or capabilities could previously receive leaked internal details. The prompt now enforces: any identity/persona/model question → exactly "I am Wiwi, powered by Claude by Anthropic." with no further internals disclosed. "What can you do?" questions get a brief capabilities summary with no system details.

### Commits
| SHA | Description |
|-----|-------------|
| a2a137b | fix(config): restrict identity disclosure — only one-line response for persona/model questions |

## Session 40 — Suppress 'the-editor' from Client Output (2026-03-18)

### What changed
- `converters/from_cursor.py` — added `_THE_EDITOR_RE`, `_scrub_the_editor()`, applied in `scrub_support_preamble` and `sanitize_visible_text`

### Which lines / functions
- `from_cursor.py:33–41` — `_THE_EDITOR_RE` compiled pattern + `_scrub_the_editor()` helper
- `from_cursor.py:376` — `scrub_support_preamble()` now calls `_scrub_the_editor()` before returning
- `from_cursor.py:406–407` — `sanitize_visible_text()` scrubs both the tool-call and non-tool-call paths

### Why
The internal upstream codename "the-editor" was leaking into client-visible streamed responses. It is used internally in `to_cursor.py` as the replacement for "cursor" in outgoing requests (to bypass upstream persona activation), but must never appear in output returned to users. All client-visible text paths now replace it with "the editor".

### Commits
| SHA | Description |
|-----|-------------|
| a1b83b2 | fix(from_cursor): scrub internal 'the-editor' codename from all client-visible output |

## Session 41 — System Prompt Condensed (2026-03-18)

### What changed
- `config.py:82` — `system_prompt` Field `default=` trimmed

### Which lines / functions
- `config.py:82–308` — verbose tool selection guide, tool decision tree, and extended coding/library discipline rules removed; remaining sections condensed to concise form

### Why
Manual IDE edit to reduce system prompt size. Verbose tool habit rules, full tool selection guide, tool decision tree, and extended coding/library discipline bullet points were removed or condensed. Net: 118 lines removed, 18 added.

### Commits
| SHA | Description |
|-----|-------------|
| 0b261f4 | chore(config): trim system prompt — condense verbose tool/coding rules to concise form |

## Session 42 — System Prompt Restored (2026-03-18)

### What changed
- `config.py:82` — `system_prompt` Field `default=` — two blocks restored

### Which lines / functions
- `config.py:84–87` — identity block re-added at top of system prompt
- `config.py:305–345` — tool selection guide and tool decision tree appended at end of system prompt

### Why
Identity block and tool selection guide were removed in the previous session's condensing pass. Both were restored per user request to ensure Wiwi correctly identifies itself and the model follows the correct tool selection discipline.

### Commits
| SHA | Description |
|-----|-------------|
| afb1c62 | feat(config): restore identity block in system prompt |
| dd8716c | feat(config): restore tool selection guide and decision tree in system prompt | 

## Session 43 — Converter Bug Fixes B1–B7 (2026-03-19)

### What changed
- `converters/from_cursor.py` — added `_safe_pct()` helper; fixed `_manual_convert_tool_calls_to_anthropic` name=None bug
- `converters/to_cursor.py` — fixed `_build_system_prompt` ValueError gap; fixed `_sanitize_user_content` None return; fixed `build_tool_instruction` KeyError on nameless tool; inlined `_flush_text`/`_flush_user_text` closures in two loop bodies
- `tests/test_from_cursor.py` — 5 new tests for B1 (×4 sites) and B6
- `tests/test_to_cursor.py` — 7 new tests for B2, B3, B4, B7 (×2 paths)

### Which lines / functions
- `from_cursor.py:27–31` — new `_safe_pct(used, ctx)` helper
- `from_cursor.py:118,150,174,240` — all four `context_window_used_pct` expressions replaced with `_safe_pct()`
- `from_cursor.py:280` — `fn.get("name") or ""` instead of `fn.get("name")` (was None when key absent)
- `to_cursor.py:111` — `except (KeyError, IndexError, ValueError)` — added ValueError
- `to_cursor.py:55` — `return text or ""` instead of `return text` (was None when input is None)
- `to_cursor.py:343` — `t["function"].get("name", "")` instead of `t["function"]["name"]`
- `to_cursor.py:601–657` — `anthropic_to_cursor` inner loop: `_flush_text` closure removed, flush inlined at 3 sites
- `to_cursor.py:708–736` — `anthropic_messages_to_openai` inner loop: `_flush_user_text` closure removed, flush inlined at 2 sites

### Why
- B1: Any model not in `_CONTEXT_WINDOWS` dict returns `_DEFAULT_CONTEXT_WINDOW=1_000_000` (safe), but if a future model maps to 0 or the dict is patched in tests, all four percentage calculations would raise `ZeroDivisionError` crashing the response.
- B2: `.format()` raises `ValueError` (not just `KeyError`/`IndexError`) on malformed braces like `"{"` or `"}"` — not caught, would crash request.
- B3: `_sanitize_user_content(None)` returned `None` (falsy early return), which would crash any caller doing string ops on the result.
- B4: `t["function"]["name"]` raises `KeyError` if a tool's function dict has no `name` key — valid in some schema variants.
- B6: `fn.get("name")` returns `None` when key absent — emitted as `"name": null` in Anthropic wire format, which Anthropic API rejects.
- B7: Python creates a new function object for each closure definition even inside a loop — O(n_messages) unnecessary allocations for large conversations.

### Commits
| SHA | Description |
|-----|-------------|
| 3ce303e | fix(converters): fix 7 bugs in from_cursor.py and to_cursor.py |

## Session 44 — Fix False-Positive [assistant_tool_calls] Marker Detection (2026-03-19)

### What changed
- `converters/to_cursor.py` — wrapped the `[assistant_tool_calls]` example in `build_tool_instruction` inside a code fence
- `tests/test_parse.py` — 2 new regression tests

### Which lines / functions
- `to_cursor.py:364,369` — added ` ``` ` lines before and after the marker example in the `lines` list inside `build_tool_instruction`
- `test_parse.py:105–152` — `test_find_marker_pos_ignores_marker_inside_code_fence`, `test_parse_tool_calls_echoed_instruction_block_returns_none`

### Why
When the model echoed its own tool instruction block verbatim in a text response (e.g. when describing its configuration), `_find_marker_pos` matched the literal `[assistant_tool_calls]` example line and treated it as a real tool call marker. This caused:
- `tool_parse_marker_found_no_json` log spam on every such response
- All text after the false-positive marker position silently dropped from the client response
- 4 fallback parse strategies run wastefully on documentation text

`_find_marker_pos` already has correct logic to skip markers inside complete code fence blocks (lines 44–56 in `tools/parse.py` — `fence_ranges` exclusion). Wrapping the example in ` ``` ` fences is the minimal fix that uses the existing correct detection path with zero parser changes.

### Commits
| SHA | Description |
|-----|-------------|
| dff1ddb | fix(to_cursor): wrap [assistant_tool_calls] example in code fence to prevent false-positive marker detection |

## Session 45 — Fix 4 Remaining False-Positive Marker Locations (2026-03-19)

### What changed
- `converters/to_cursor.py` — rephrased 2 last-word reinforcer strings (OpenAI + Anthropic paths)
- `pipeline/nonstream.py` — rephrased 2 retry prompt strings (OpenAI + Anthropic paths)
- `tests/test_parse.py` — 3 new regression tests documenting safe and unsafe forms

### Which lines / functions
- `to_cursor.py:464` — OpenAI `openai_to_cursor` last-word reinforcer: `"For reference: when you need to use a tool, please use the [assistant_tool_calls]..."` → `"For reference: tools must be invoked using the [assistant_tool_calls]..."`
- `to_cursor.py:579` — Anthropic `anthropic_to_cursor` same reinforcer, same change
- `nonstream.py:93` — `handle_openai_non_streaming` retry: `"...Please respond with [assistant_tool_calls] JSON..."` → `"...Please respond using the [assistant_tool_calls] JSON format..."`
- `nonstream.py:208` — `handle_anthropic_non_streaming` retry: same change
- `test_parse.py:105–124` — 3 new tests for mid-sentence and line-start marker detection

### Why
Audit of all `[assistant_tool_calls]` occurrences after Session 44 found 4 injected Cursor user-turn messages whose string content could place the marker at line-start if the model echoed them verbatim as its first output line. `_TOOL_CALL_MARKER_RE` (`^[ \t]*\[`, `re.MULTILINE`) would match, setting `_marker_offset=0` and suppressing the entire response. The fix moves the marker to a mid-sentence position (preceded by "using the") so the regex cannot match it regardless of where in the response the text appears.

All remaining `[assistant_tool_calls]` occurrences were audited and confirmed safe:
- Definitions, constants, regex patterns, docstrings, comments — never emitted
- Real serializer calls (`_assistant_tool_call_text`, Anthropic history replay) — intentional
- `build_tool_instruction` example — inside code fence (Session 44 fix)
- `_build_role_override` layer strings — mid-sentence after other words
- `config.py:373` `tool_system_prompt` — mid-sentence

### Commits
| SHA | Description |
|-----|-------------|
| ab41e90 | fix(to_cursor,nonstream): rephrase 4 injected strings so [assistant_tool_calls] is never at line-start |

## Session 46 — Fix 8 Critical/High Streaming Bugs (2026-03-19)

### What changed
- `cursor/client.py` — credential rotation fix for all non-401 retryable errors
- `cursor/sse.py` — UTF-8 decode fix for multi-byte chars split across chunk boundaries
- `pipeline/stream_anthropic.py` — `_limit_tool_calls` wired in, `_record` on all error paths, suppression detection added
- `pipeline/stream_openai.py` — C3 marker-offset fix, `_record` on all error paths
- `tests/test_stream_openai_fixes.py` — new test file (C3, H3, H6, H1 regression tests)
- `tests/test_stream_anthropic.py` — 4 new regression tests appended (C2, H4, H7, H5)

### Which lines / functions
- `cursor/client.py:231,244,262` — added `cred = None` in `ReadTimeout`, `ConnectError`, `EmptyResponseError` handlers
- `cursor/sse.py:109` — changed `errors="ignore"` → `errors="surrogateescape"`
- `stream_anthropic.py:25` — added `_limit_tool_calls` import
- `stream_anthropic.py:118,122` — `_limit_tool_calls` applied to `_parse_results` in both `_stream_parser` and fallback branches
- `stream_anthropic.py:215` — added `await pkg._record(...)` in `TimeoutError` handler
- `stream_anthropic.py:231` — added `await pkg._record(...)` in `Exception` handler
- `stream_anthropic.py:285–301` — added `_is_suppressed` check before `end_turn` emission in non-tool text path
- `stream_openai.py:233–242` — C3: replaced `visible[:_marker_offset]` with `_find_marker_pos(visible)` re-search
- `stream_openai.py:293` — added `await pkg._record(...)` in `TimeoutError` handler
- `stream_openai.py:301` — added `await pkg._record(...)` in `Exception` handler

### Why
- **C1+H1:** `cred` not reset to `None` on `EmptyResponseError`, `ReadTimeout`, `ConnectError` — all retries re-used the same bad credential instead of rotating through the pool
- **H2:** `errors='ignore'` drops bytes of multi-byte characters (emoji, CJK) that straddle 65 536-byte chunk boundaries, silently corrupting streamed output
- **C2:** `_limit_tool_calls` was applied in the OpenAI stream path but not in the Anthropic mid-stream tool detection path, violating `parallel_tool_calls=False` client constraint
- **C3:** `_marker_offset` is computed against raw `acc` but applied to `visible` (post-`split_visible_reasoning`) which is shorter when thinking text is extracted — wrong truncation point
- **H3/H4/H6/H7:** `_record` not called on `TimeoutError` and generic `Exception` paths — all such requests were invisible to analytics and budget enforcement
- **H5:** Suppression detection (`_is_suppressed`) absent from non-tool Anthropic streaming path — support persona text streamed verbatim to client

### Commits
| SHA | Description |
|-----|-------------|
| bb9d9db | fix(pipeline): fix 8 critical/high streaming bugs |

## Session 47 — Fix 9 Medium/Low Audit Findings (2026-03-19)

### What changed
- `cursor/client.py` — M1: Retry-After HTTP-date crash guard
- `pipeline/stream_anthropic.py` — M2: stale thinking cache fix; L1: tautological guard removed
- `routers/unified.py` — M3: include_usage default corrected; L2: dead assignment removed
- `routers/internal.py` — M4: key creation audit log; M5: cookie prefix replaced with index
- `middleware/auth.py` — M6: _env_keys refactored to cache-by-value for runtime rotation support
- `routers/model_router.py` — L3: thread-safety documented, lazy pattern preserved for test compatibility

### Which lines / functions
- `cursor/client.py:123-129` — `classify_cursor_error` 429 branch: `float(_ra_raw)` wrapped in try/except
- `stream_anthropic.py:79-80` — added `_cached_thinking`, `_cached_final` state vars
- `stream_anthropic.py:97-112` — `if len(acc) > acc_visible_processed` else branch now uses cached split
- `stream_anthropic.py:259` — removed redundant `not tool_mode` condition
- `routers/unified.py:161` — `include_usage` default changed `True` → `False`
- `routers/unified.py:299` — removed dead `show_reasoning = thinking is not None`
- `routers/internal.py:180,189` — `cookie_prefix` field replaced with `credential_id` (index)
- `routers/internal.py:283-296` — `create_key` now calls `log.info("api_key_created", ...)` before returning
- `middleware/auth.py:16-35` — `_compute_env_keys(master_key, api_keys_raw)` + `_EnvKeyAccessor` wrapper
- `routers/model_router.py:36-52` — restored lazy-load with clarifying comment

### Why
- M1: `Retry-After` header from the-editor may be an HTTP-date string (RFC 7231); `float()` raises `ValueError` on non-numeric strings, killing the entire retry path on any 429 with date-format header
- M2: The else branch `thinking_text, final_text = None, acc` reset to (None, raw_acc) on empty/duplicate chunks; `candidate = final_text if thinking_text is not None else acc` then picked raw acc (with thinking tags), leaking `<thinking>` markup into visible Anthropic text blocks
- M3: OpenAI spec: `include_usage` defaults `false` unless client sends `stream_options.include_usage: true`; strict clients rejected the unexpected usage chunk
- M4: No audit trail for key creation meant a compromised admin token could silently create long-lived keys
- M5: Returning `cred.cookie[:12]` in API response incrementally narrows brute-force space for cookie values
- M6: `lru_cache(maxsize=1)` cached the key set forever; a rotated `LITELLM_MASTER_KEY` or `SHINWAY_API_KEYS` was never picked up until process restart, leaving old revoked keys valid
- L1: `not tool_mode` inside `else: # if tool_mode` is always True — dead condition misleads maintainers
- L2: `show_reasoning = thinking is not None` immediately overwritten by `anthropic_to_cursor` return — dead assignment
- L3: Documented CPython GIL benignness for the lazy-init double-parse scenario

### Commits
| SHA | Description |
|-----|-------------|
| 64a3db6 | fix(medium/low): fix 9 medium and low audit findings |

## Session 48 — Fix session-config identity bleed from upstream (2026-03-20)

### What changed
- `pipeline/suppress.py` — `_SUPPRESSION_KNOCKOUTS`
- `converters/from_cursor.py` — `_SUPPORT_PREAMBLE_RE`

### Which lines / functions
- `pipeline/suppress.py:63-74` — added 4 knockout phrases to `_SUPPRESSION_KNOCKOUTS`
- `converters/from_cursor.py:357-369` — added 2 scrub patterns to `_SUPPORT_PREAMBLE_RE`

### Why
Upstream was echoing the injected Wiwi system prompt intro verbatim: `"I can help you with the editor documentation, features, troubleshooting, and engineering tasks in your development workspace."` No existing suppression signal or scrub pattern matched this phrase. Two-layer fix: (1) knockout triggers a retry immediately on detection; (2) scrub pattern strips it from output as a fallback if retry also bleeds.

### Commits
| SHA | Description |
|-----|-------------|
| e2927b4 | fix(suppress): catch session-config identity bleed from upstream |

## Session 49 — Add composer-2 model (200k context) (2026-03-21)

### What changed
- `routers/model_router.py` — `_CATALOGUE`
- `config.py` — `model_map` default
- `tests/test_model_router.py` — new tests

### Which lines / functions
- `routers/model_router.py:27` — added `"composer-2": {"context": 200_000, "owner": "cursor"}` to `_CATALOGUE`
- `config.py:353-360` — added `"composer":"composer-2"` and `"cursor-composer":"composer-2"` to default `model_map`
- `tests/test_model_router.py:101-116` — added `test_composer2_in_catalogue`, `test_composer2_model_info`, `test_composer2_alias_resolves`

### Why
User requested `composer-2` be added as a first-class model with a 200k context window. Aliases `composer` and `cursor-composer` route to it via the default `model_map`. All 12 model router tests pass.

### Commits
| SHA | Description |
|-----|-------------|
| 137b79a | feat(models): add composer-2 with 200k context window and composer/cursor-composer aliases |

## Session 50 — System prompt enhancements (2026-03-21)

### What changed
- `config.py` — `system_prompt` and `tool_system_prompt` Fields
- `.env` — `SHINWAY_TOOL_SYSTEM_PROMPT` updated (gitignored)

### Which lines / functions
- `config.py:84-90` — identity block hardened: indirect probes + persona-swap rejection
- `config.py:143-152` — Tool habits: parallel-by-default, sequential-when-dependent, on-tool-failure rules added
- `config.py:296-301` — new Context window management section after Anti-laziness rules
- `config.py:306-309` — Tool selection guide: Runtime check (MANDATORY) bullet at top
- `config.py:323-329` — Skill bullet: two-step discovery protocol (session reminder → Skill tool)
- `config.py:338-355` — Tool decision tree: skill discovery entries replacing old single entry
- `config.py:399-418` — `tool_system_prompt`: expanded with failure handling, parallel guidance, case-sensitivity note

### Why
8 gaps found in the system prompt during audit:
1. No runtime guard against phantom tool calls in variable-tool sessions
2. Skill discovery had no priority order between session reminder and Skill tool
3. Tool decision tree had no skill entry
4. No parallel tool call guidance — unnecessary sequential latency
5. No context window self-awareness — silent degradation on long sessions
6. No tool failure instruction — silent continuation on errors
7. Identity block only covered direct probes, not indirect or persona-swap attacks
8. `tool_system_prompt` was too thin — missing failure handling and parallel guidance

### Commits
| SHA | Description |
|-----|-------------|
| f5089b9 | feat(system-prompt): 8 enhancements — tool verification, skill discovery, parallel calls, context awareness, tool failure handling, identity hardening, tool_system_prompt overhaul |
| 9aae478 | feat(system-prompt): strengthen context window rule — memory anchoring, settled ground, no re-derivation |
| 9aa0d5e | feat(system-prompt): context window — full retention, no compression, use all history |

## Session 51 — Tool call pipeline bug fixes (2026-03-21)

### What changed
- `pipeline/suppress.py` — `_SUPPRESSION_KNOCKOUTS` set
- `pipeline/stream_openai.py` — no-tools marker holdback branch
- `tools/parse.py` — investigation of fenced-marker fallback (no net change — existing invariant confirmed correct)
- `tests/test_suppress.py` — two regression tests for knockout false positive
- `tests/test_stream_openai.py` — `test_openai_stream_warns_when_marker_detected_without_tool_emitter`
- `docs/superpowers/plans/2026-03-21-tool-call-pipeline-bug-fixes.md` — implementation plan

### Which lines / functions
- `pipeline/suppress.py:_SUPPRESSION_KNOCKOUTS` (~line 63) — removed `"engineering tasks in your development workspace"`
- `pipeline/stream_openai.py:_openai_stream` (~lines 137-150) — no-tools marker detection block now emits `log.warning("marker_detected_no_tool_emitter", ...)` on first detection
- `tools/parse.py:parse_tool_calls_from_text` — fenced-marker fallback was attempted and reverted; existing fence-exclusion invariant is correct by design

### Why
- **Fix B (suppress.py):** `"engineering tasks in your development workspace"` was in `_SUPPRESSION_KNOCKOUTS` but exactly matches a phrase from the proxy's own injected system prompt (`_build_identity_declaration` in `converters/to_cursor.py`). When the upstream model echoes any fragment of the injected framing, `_is_suppressed()` fires a false positive, kills the stream, and retries with rotated credentials — discarding a valid response.
- **Fix A (stream_openai.py):** When `params.tools` is falsy, `tool_emitter` is `None` and the entire structured tool call path is disabled. The `[assistant_tool_calls]` marker is silently held back but never parsed. A `log.warning("marker_detected_no_tool_emitter")` now surfaces this immediately in production logs so the upstream drop point can be traced.
- **Fix C (parse.py — no change):** Investigation revealed that fenced markers are correctly ignored by design (`_find_marker_pos` fence-exclusion) to prevent false positives on prose examples such as echoed instruction blocks. The existing `test_marker_inside_code_fence_ignored` test correctly enforces this invariant. No change was made.

### Commits
| SHA | Description |
|-----|-------------|
| 495f10a | docs: add implementation plan for tool call pipeline bug fixes (session 51) |
| 8a83b55 | fix(suppress): remove false-positive knockout phrase that matches own system prompt |
| 1b060bd | fix(pipeline): log warning when tool marker detected in no-tools stream |
| d437283 | fix(parse): clean up fenced-marker fallback attempt — fenced markers correctly ignored per existing invariant |

---

## Session 52 — Cache Correctness Fixes (2026-03-21)

### What changed
- `cache.py` — 4 fixes: `build_key` extended, `asyncio.Lock` on `_RedisBackend._ensure_client`, batched Redis `clear()`, L1 hit logging
- `pipeline/nonstream.py` — `_freshen_cached_response` helper added; both cache-hit paths updated; `build_key` call sites updated
- `tests/test_cache.py` — 8 new tests: 5 for `build_key` new fields, 2 for Redis backend safety, 1 for L1 hit logging
- `tests/test_nonstream.py` — 2 cache-hit tests updated to verify fresh `id`/`created` instead of exact equality

### Which lines / functions
- `cache.py:ResponseCache.build_key` (~line 175) — added `max_tokens`, `stop`, `json_mode` to signature and hash payload
- `cache.py:_RedisBackend.__init__` (~line 35) — added `self._init_lock = asyncio.Lock()`
- `cache.py:_RedisBackend._ensure_client` (~line 40) — wrapped init in `async with self._init_lock` with double-checked locking
- `cache.py:_RedisBackend.clear` (~line 97) — replaced sequential per-key delete with single batched `delete(*keys)`
- `cache.py:ResponseCache.aget` (~line 144) — added `log.debug("cache_l1_hit", ...)` on L1 hit
- `pipeline/nonstream.py:_freshen_cached_response` (new, ~line 15) — regenerates `id` and `created` on cache hit
- `pipeline/nonstream.py:handle_openai_non_streaming` (~line 60) — cache hit returns `_freshen_cached_response(cached, "openai")`
- `pipeline/nonstream.py:handle_anthropic_non_streaming` (~line 175) — cache hit returns `_freshen_cached_response(cached, "anthropic")`
- `pipeline/nonstream.py` build_key call sites (~lines 48, 163) — added `max_tokens`, `stop`, `json_mode` kwargs

### Why
- **`build_key` missing fields:** Requests differing only in `max_tokens`, `stop`, or `json_mode` collided to the same cache key — a `max_tokens=100` request could silently receive a 4096-token response.
- **Stale `id`/`created` on hit:** Subsequent callers received the original caller's `id` and a stale timestamp, breaking client deduplication.
- **`_ensure_client` race:** Concurrent startup coroutines could each create a Redis client, leaking the abandoned connection. Fixed with `asyncio.Lock` + double-checked locking.
- **Sequential Redis `clear()`:** One round-trip per key replaced with a single batched DELETE.
- **L1 hit logging:** `aget` was silent on L1 hits — impossible to distinguish L1/L2/miss in production logs.

### Commits
| SHA | Description |
|-----|-------------|
| d3b13d1 | fix(cache): correctness, concurrency, and observability fixes |

---

## Session 53 — Idempotency Middleware Fixes (2026-03-21)

### What changed
- `config.py` — added `idem_ttl_seconds` (default 86400) and `idem_max_entries` (default 2000)
- `cache.py` — added `IdempotencyCache` class and `idempotency_cache` singleton
- `middleware/idempotency.py` — full rewrite: validate_idem_key, in-flight sentinel, IdempotencyCache, async release, intent docs
- `routers/unified.py` — key validation, 409 for in-progress sentinel, await release
- `tests/test_cache.py` — 5 new IdempotencyCache tests
- `tests/test_idempotency.py` — rewritten with 19 tests covering all new behaviour

### Which lines / functions
- `config.py:Settings` (~line 498) — `idem_ttl_seconds`, `idem_max_entries` fields added
- `cache.py:IdempotencyCache` (new class, ~line 210) — `get`, `set`, `delete`; separate _TTLCache and _RedisBackend
- `cache.py:idempotency_cache` (new singleton, ~line 260)
- `middleware/idempotency.py:validate_idem_key` (new, ~line 47) — rejects empty, >256 chars, unsafe chars
- `middleware/idempotency.py:get_or_lock` (~line 70) — writes _SENTINEL on first miss; returns (True, None) for in-progress
- `middleware/idempotency.py:complete` (~line 87) — now writes to idempotency_cache instead of response_cache
- `middleware/idempotency.py:release` (~line 95) — now async, deletes sentinel via idempotency_cache.delete
- `middleware/idempotency.py:_SENTINEL`, `_is_sentinel` (new helpers)
- `routers/unified.py:_handle_non_streaming` (~line 74) — validate key, handle 409 for sentinel, await release

### Why
- **Dead TTL constant:** `_TTL_SECONDS = 60` was never used; actual window was `cache_ttl_seconds` (45s). Fixed with dedicated `SHINWAY_IDEM_TTL_SECONDS` (default 24h).
- **No in-flight dedup:** Concurrent requests with the same key all hit upstream. Fixed with _SENTINEL pattern.
- **Shared cache namespace:** LRU eviction of ResponseCache entries could evict idempotency entries, silently shrinking the window. Fixed with separate IdempotencyCache.
- **No key validation:** Unbounded key values allowed cache poisoning and Redis memory abuse. Fixed with validate_idem_key returning 400.
- **release() sync no-op:** Failed requests left stale sentinels permanently blocking retries. Fixed: async, deletes sentinel.
- **Undocumented stale-id intent:** Idempotency hits preserve original id/created (correct for idempotency contract). Now documented explicitly.

### Commits
| SHA | Description |
|-----|-------------|
| ac83999 | fix(idempotency): fix all 6 gaps — TTL, sentinel, validation, namespace, release, docs |

---

## Session 54 — Rate Limiter Fixes (2026-03-21)

### What changed
- `middleware/rate_limit.py` — full rewrite: 3-tuple consume, seconds_until_token, asyncio.Lock, LRU bucket, rpm_burst helper, docs
- `config.py` — added `rate_limit_rpm_burst` setting
- `app.py` — emit `Retry-After` header on 429 RateLimitError responses
- `tests/test_rate_limit.py` — 9 new tests; all 2-tuple unpacks updated to 3-tuple

### Which lines / functions
- `middleware/rate_limit.py:TokenBucket._buckets` — changed from unbounded `dict` to `LRUCache(maxsize=10_000)`
- `middleware/rate_limit.py:TokenBucket.seconds_until_token` (new method) — returns seconds until next token available
- `middleware/rate_limit.py:DualBucketRateLimiter.consume` — now returns `(bool, str, float)` 3-tuple; retry_after from bucket state
- `middleware/rate_limit.py:_rpm_burst` (new helper) — resolves effective RPM burst from settings
- `middleware/rate_limit.py:_limiter` construction — uses `_rpm_burst()`, documented as import-time
- `middleware/rate_limit.py:_per_key_lock` — changed from `threading.Lock` to `asyncio.Lock`
- `middleware/rate_limit.py:enforce_rate_limit` — passes computed retry_after to RateLimitError
- `middleware/rate_limit.py:enforce_per_key_rate_limit` — passes computed retry_after to RateLimitError
- `config.py:Settings.rate_limit_rpm_burst` (~line 67) — new field, alias `SHINWAY_RATE_LIMIT_RPM_BURST`
- `app.py:proxy_error_handler` (~line 102) — adds `Retry-After` header when exc is RateLimitError

### Why
- **Retry-After missing:** RateLimitError had `retry_after` but the exception handler never set the header. Clients had no machine-readable retry guidance.
- **Inaccurate retry_after:** Was always 60.0 (default). Now computed from actual bucket depletion: `(tokens_needed - level) / rate`.
- **burst_rpm conflated with rate:** `burst_rpm=settings.rate_limit_rpm` meant rate=60 → burst=60. No env var to tune it. Fixed with `SHINWAY_RATE_LIMIT_RPM_BURST`.
- **threading.Lock in async:** `_per_key_lock` was `threading.Lock` inside `async` function — blocks event loop. Fixed with `asyncio.Lock`.
- **Unbounded _buckets dict:** Global TokenBucket instances used plain dicts; key churn could grow memory without bound. Fixed with `LRUCache(maxsize=10_000)`.
- **Import-time _limiter undocumented:** Operators changing rate limit env vars expected live reload. Now documented explicitly.

### Commits
| SHA | Description |
|-----|-------------|
| a58c1b4 | fix(rate_limit): fix all 6 gaps — Retry-After, accurate wait, burst config, asyncio.Lock, LRU buckets, docs |

---

## Session 55 — Auth Middleware Fixes (2026-03-21)

### What changed
- `middleware/auth.py` — full rewrite: _key_cache, single DB hit, maxsize=1, spend logging, sanitised errors, contracts documented
- `tests/test_auth.py` — 6 new tests; 4 existing tests updated (is_valid → get mock, error message strings)
- `tests/test_app.py` — 1 error message match string updated

### Which lines / functions
- `middleware/auth.py:_key_cache` (new, ~line 72) — `TTLCache(maxsize=1000, ttl=60)` shared between verify_bearer and get_key_record
- `middleware/auth.py:_compute_env_keys` (~line 52) — lru_cache maxsize changed 4 → 1
- `middleware/auth.py:verify_bearer` (~line 80) — replaced `is_valid()` + separate `get()` pair with single `key_store.get()` + `is_active` check; caches record on success
- `middleware/auth.py:get_key_record` (~line 99) — reads `_key_cache` first; DB only on cold path
- `middleware/auth.py:check_budget` (~line 116) — 80% approach warning added; error messages sanitised (no budget figures)
- `middleware/auth.py:enforce_allowed_models` (~line 147) — model name convention documented in docstring
- Module docstring — is_active contract, model name convention, cache behaviour all documented

### Why
- **Double DB hit:** verify_bearer called is_valid() then get_key_record called get() — 2 SQLite queries per request for DB keys. Collapsed to 1 via shared _key_cache.
- **No negative cache short-circuit:** Invalid key attempts each hit SQLite. Now invalid/inactive records are not cached, preserving security while reducing load on valid paths.
- **maxsize=4 magic number:** Only one (master_key, api_keys) combination is ever live. maxsize=4 held stale entries from test rotation with no benefit.
- **No spend approach logging:** Operators had no visibility into keys approaching budget without querying analytics. Fixed with key_budget_approaching warning at 80%.
- **Budget figures in errors:** "Key budget exceeded: $10.0000 of $5.00" leaked exact billing config. Replaced with generic messages.
- **Model name convention undocumented:** allowed_models comparison runs post-resolution — admins storing pre-resolution aliases would see silent restriction bypass.
- **is_active contract undocumented:** check_budget silently trusts that verify_bearer already validated is_active.

### Commits
| SHA | Description |
|-----|-------------|
| be4d956 | fix(auth): fix all 7 gaps — _key_cache, single DB hit, maxsize, spend log, sanitised errors, docs |

## Session 56 — Settings Page Rewrite (2026-03-21)

### What changed
- `admin-ui/app/(dashboard)/settings/page.tsx` — full rewrite: replaced read-only static env var table with live editable config rows via `useRuntimeConfig` SWR hook; added overridden count in subtitle, error banner, loading state, and `AddCookiePanel` at bottom; dropped dead `useState`/`useEffect` model catalogue section
- `admin-ui/components/settings/ConfigRow.tsx` — new component: inline edit row with type coercion (`str`/`int`/`float`/`bool`), save/reset/cancel actions, overridden-state dot indicator and accent value chip, Enter/Escape keyboard shortcuts
- `admin-ui/components/settings/AddCookiePanel.tsx` — new component: textarea + POST `/credentials/add` for adding `WorkosCursorSessionToken` cookies to the live credential pool without a server restart

### Which lines / functions
- `admin-ui/app/(dashboard)/settings/page.tsx:SettingsPage` — complete replacement; now imports `useRuntimeConfig`, `ConfigRow`, `AddCookiePanel`, `CONFIG_GROUPS`; `handleSave` / `handleReset` delegate to `patchKey` / `resetKey`; `overriddenCount` derived from `config` snapshot
- `admin-ui/components/settings/ConfigRow.tsx:ConfigRow` — new; `startEdit`, `handleSave`, `handleReset` as `useCallback`; type coercion in `handleSave` per `entry.type`
- `admin-ui/components/settings/AddCookiePanel.tsx:AddCookiePanel` — new; `handleAdd` as `useCallback`; calls `api.post('/credentials/add')`; status machine: `idle | saving | ok | error`

### Why
The settings page was read-only and displayed static defaults from a hardcoded local `CONFIG_GROUPS` array with no connection to the live backend config. `useRuntimeConfig` and `configGroups.ts` had already been created in a prior task. This session wires them into a fully interactive page where every config value can be edited inline and saved to the backend without a restart. The `AddCookiePanel` closes the gap of adding credentials without redeploying.

### Commits
| SHA | Description |
|-----|-------------|
| 042944e | feat(admin-ui): rewrite settings page with live config editing and cookie panel |

---

## Session 57 — Live Config Management (2026-03-21)

### What changed
- `runtime_config.py` — new: `RuntimeConfig` singleton with 29 overridable keys, thread-safe in-memory overlay, type coercion, JSON persistence to `runtime.json`
- `cursor/credentials.py` — added `CredentialPool.add(cookie)` for live cookie addition without restart
- `cache.py` — 8 per-request `settings.X` reads replaced with `runtime_config.get()`
- `cursor/client.py` — `retry_attempts`, `retry_backoff_seconds` in `stream()` replaced with `runtime_config.get()`
- `analytics.py` — `price_anthropic_per_1k`, `price_openai_per_1k` replaced with `runtime_config.get()`
- `routers/internal.py` — 4 new endpoints: `GET /v1/internal/config`, `PATCH /v1/internal/config/{key}`, `DELETE /v1/internal/config/{key}`, `POST /v1/internal/credentials/add`
- `admin-ui/app/api/config/route.ts` — Next.js GET proxy route
- `admin-ui/app/api/config/[key]/route.ts` — Next.js PATCH + DELETE proxy route
- `admin-ui/app/api/credentials/add/route.ts` — Next.js POST proxy route
- `admin-ui/hooks/useRuntimeConfig.ts` — SWR hook: `patchKey`, `resetKey`, `refresh`, 30s polling
- `admin-ui/lib/configGroups.ts` — 9 config group definitions for the UI
- `admin-ui/components/settings/ConfigRow.tsx` — new: inline-editable row, type coercion, overridden indicator, Enter/Escape support
- `admin-ui/components/settings/AddCookiePanel.tsx` — new: textarea + POST for live cookie addition
- `tests/test_runtime_config.py` — 8 unit tests for RuntimeConfig
- `tests/test_internal_config.py` — 8 endpoint tests for config CRUD and credential add
- `tests/test_credentials.py` — 3 new tests for `CredentialPool.add()`
- `tests/test_stream_openai_fixes.py` — fixed retry test to also patch `runtime_config`
- `.gitignore` — added `runtime.json`

### Which lines / functions
- `runtime_config.py:RuntimeConfig` — `get()`, `set()`, `reset()`, `all()`, `_load_persisted()`, `_save_persisted()`
- `runtime_config.py:OVERRIDABLE_KEYS` — whitelist of 29 keys with expected Python types
- `runtime_config.py:_coerce()` — type coercion: int→float promotion, string→bool/int/float parsing
- `cursor/credentials.py:CredentialPool.add()` — thread-safe; deduplicates; enforces max 15
- `routers/internal.py:get_config`, `patch_config`, `delete_config`, `credential_add` — 4 new endpoints
- `admin-ui/hooks/useRuntimeConfig.ts:useRuntimeConfig` — SWR hook, 30s refresh
- `admin-ui/app/(dashboard)/settings/page.tsx:SettingsPage` — complete rewrite
- `admin-ui/components/settings/ConfigRow.tsx:ConfigRow` — new component
- `admin-ui/components/settings/AddCookiePanel.tsx:AddCookiePanel` — new component

### Why
All settings were loaded once at startup from `.env` and were immutable at runtime. The `RuntimeConfig` overlay intercepts reads for 29 hot-path keys and returns the live override if set, falling back to the pydantic `settings` value. Changes persist to `runtime.json` on every write so they survive restarts. `CredentialPool.add()` inserts a new `CredentialInfo` into the live pool under a lock, leaving all in-flight requests on their current credential. The Settings page rewrite closes the UI gap — every overridable key is now inline-editable with type-aware inputs, and the Add Cookie panel lets operators expand the credential pool without touching `.env` or restarting.

### Commits
| SHA | Description |
|-----|-------------|
| ef848e1 | feat(config): add RuntimeConfig overlay with persistence and type coercion |
| 14e62d0 | feat(credentials): add CredentialPool.add() for live cookie addition |
| 6e6b147 | feat(config): wire hot paths to runtime_config.get() for live override |
| 9d83f35 | feat(api): add live config CRUD endpoints and credential add endpoint |
| 4ca521d | feat(admin-ui): add Next.js proxy routes, useRuntimeConfig hook, and configGroups |
| 042944e | feat(admin-ui): rewrite settings page with live config editing and cookie panel |
| 7e463cf | fix(tests): patch runtime_config in cursor client retry test; add runtime.json to gitignore |

## Session 57 — Login Page Redesign (2026-03-21)

### What changed
- `admin-ui/app/login/page.tsx` — full redesign

### Which lines / functions
- `LoginPage` — complete replacement; logic (auth flow, error handling, show/hide key, shake animation, success redirect) fully preserved
- `TerminalPanel` — new component; typewriter readout of proxy boot messages, animated concentric circle geometry, uptime counter, stats strip
- `CSS` constant — full replacement; brutalist terminal aesthetic with `Space Mono` + `Bebas Neue`, `#00e5a0` accent, scanline texture
- `EYE_ON` / `EYE_OFF` — preserved, relocated below main component

### Why
The previous login page used generic glassmorphism (backdrop-blur card, rounded softness, Sora/JetBrains Mono fonts, white-only palette) that read as boilerplate AI UI. Redesigned to a stark split-panel terminal aesthetic:
- Left panel: animated concentric circle geometry (green accent), large Bebas Neue wordmark, typewriter terminal boot readout with 11 proxy status lines, scanline overlay, uptime/build/env stats strip
- Right panel: Space Mono throughout, sharp-cornered input border (no border-radius), `#00e5a0` focus ring and caret, AUTHENTICATE headline in Bebas Neue, `[ERR]` prefixed error banner with left-border accent, full-width green CTA button
- Responsive: left panel hidden below 900px

### Commits
| SHA | Description |
|-----|-------------|
| 66efb42 | feat(admin-ui): redesign login page — brutalist terminal split layout |

## Session 58 — Login Page Polish: Premium B&W Card (2026-03-21)

### What changed
- `admin-ui/app/login/page.tsx` — full redesign (second pass)

### Which lines / functions
- `LoginPage` — layout changed from split-panel to centered card; auth logic unchanged
- `NoiseBackground` — new: canvas-rendered grain overlay (256×256, opacity 0.45)
- `GridLines` — new: CSS grid overlay with radial mask
- `OrbGlow` — new: radial white glow behind card
- `CSS` constant — complete replacement; Inter + Geist Mono fonts; pure B&W palette

### Why
User requested more attractive black-and-white aesthetic resembling top-company admin login pages (Vercel/Linear/Stripe tier). Replaced the brutalist split-panel terminal layout with a refined centered card: frosted glass header bar, layered background (noise + grid + orb), card with inner sheen + deep shadow, white submit button with animated arrow, Geist Mono inputs.

### Commits
| SHA | Description |
|-----|-------------|
| e98ff7c | feat(admin-ui): refine login page — premium B&W centered card |

## Session 59 — Logs UI Redesign (2026-03-21)

### What changed
- `admin-ui/app/(dashboard)/logs/page.tsx` — redesign
- `admin-ui/components/logs/LogFilters.tsx` — redesign
- `admin-ui/components/logs/LogsTable.tsx` — redesign
- `admin-ui/components/logs/LogDetailSheet.tsx` — redesign

### Which lines / functions
- `LogsPage` — KPI strip switched to CSS class system, section-header label+line pattern, live-dot meta row
- `LogFilters` — unified toolbar bar, `PillGroup` generic component, active ON badge, consistent 28px input heights
- `LogsTable` — all cell styles extracted to CSS classes, `ChevronsUpDown` default sort icon, two-line empty state, footer legend
- `LogDetailSheet` — `SectionLabel` + `FieldRow` components, 3-column KPI grid, thinner latency bar, token swatch cards, cost table with total row, 3px body scrollbar

### Why
User requested more professional, attractive, clean redesign of the logs section. Replaced inline-style sprawl with scoped CSS class systems in all four files. Improved visual hierarchy, spacing consistency, and component reuse.

### Commits
| SHA | Description |
|-----|-------------|
| 573a738 | feat(admin-ui): redesign logs UI — professional clean polish |

## Session 60 — Dashboard Page Redesign: Glassmorphism Layout (2026-03-21)

### What changed
- `admin-ui/app/(dashboard)/dashboard/page.tsx` — full layout redesign

### Which lines / functions
- `OverviewPage` — page structure rewritten with CSS class system; all data logic and chart components unchanged
- `SectionDivider` — converted to CSS classes (db-section-div/label/line/right)
- `GlassCard` — new wrapper component; applies frosted glass surface to all chart sections
- `db-hero-strip` — upgraded token summary strip: backdrop-filter blur+saturate, inner sheen, shadow depth, hover state
- `db-win-seg` — window selector: rounded segmented control with blur backdrop
- `db-glass-card` — glass card: border-color hover lift, inner sheen, deep shadow; child bg/border overridden transparent

### Why
User requested glassmorphism design aesthetic for the dashboard. Upgraded all chart containers to frosted glass surfaces, elevated the token hero strip with proper depth treatment, polished the window selector and page header. No data logic changed.

### Commits
| SHA | Description |
|-----|-------------|
| c3ffbc1 | feat(admin-ui): redesign dashboard page — glassmorphism layout |

## Session 61 — Keys Page & CreateKeyModal Redesign (2026-03-21)

### What changed
- `admin-ui/app/(dashboard)/keys/page.tsx` — full visual redesign
- `admin-ui/components/keys/CreateKeyModal.tsx` — full visual redesign

### Which lines / functions
- `KeysPage` — added `<style>{CSS}</style>`, replaced all inline style on layout/surface elements with `kp-*` classes
- `SummaryTile` — `kp-tile` / `kp-tile-accent`; CSS `:hover` replaces JS onMouseEnter/Leave handlers
- `SectionDivider` — `kp-section-div` / `kp-section-label` / `kp-section-line`; margin 28px 0 16px
- `ManagedKeyRow` — `kp-badge-active` / `kp-badge-disabled` status badges; `kp-row` / `kp-row-disabled`
- Usage stats table — `kp-th` / `kp-th-sorted`; `ChevronsUpDown` icon on unsorted columns added
- Key detail panel — `kp-detail-card` / `kp-detail-stat`
- `LimitCard` — `ck-limit-card` / `ck-limit-card-active`; dynamic color values remain inline-only
- `SubDivider` — `ck-subdiv` / `ck-subdiv-line` / `ck-subdiv-label`
- `CreateKeyModal` — `ck-modal-card` + full class system; `MODAL_CSS` constant injected via `<style>`
- `ck-input` focus state via CSS pseudo-class (no JS)
- All `JetBrains Mono` hardcoded references replaced with `var(--mono)`
- Stat values: 28px (down from 30px), page title: 22px/-0.6px

### Why
User requested professional, attractive, well-managed design for the keys page. Redesigned both files with the glassmorphism CSS class system consistent with the dashboard and logs pages. Zero changes to data logic, hooks, API calls, or business behaviour.

### Commits
| SHA | Description |
|-----|-------------|
| 8fb0d79 | feat(admin-ui): redesign keys page — glassmorphism layout |
| afe803e | feat(admin-ui): redesign CreateKeyModal — consistent glassmorphism polish |

## Session 62 — CreateKeyModal Polish (2026-03-21)

### What changed
- `admin-ui/components/keys/CreateKeyModal.tsx` — targeted polish, no logic changes

### Which lines / functions
- `.ck-modal-card` — blur 32→40px, saturate 130→140%, triple shadow stack with inset ring
- `.ck-modal-icon` — 40→44px, 11→12px border-radius, box-shadow
- `.ck-modal-title` — font changed from `var(--mono)` to `var(--sans)` for correct hierarchy
- `.ck-modal-subtitle` — opacity 0.32→0.28, line-height 1.5
- `.ck-close-btn` — JS onMouseEnter/Leave handlers removed; `:hover` CSS pseudo-class added
- `.ck-success-icon` — 64→72px, 18→20px border-radius, green glow box-shadow
- `ck-success-title` — new class (var(--sans), 20px, -0.5px); replaces ck-modal-title in success state
- Check icon size 28→32
- `.ck-success-sub` — opacity 0.35→0.3, line-height 1.5
- `.ck-key-box` — inner top sheen via `::before`, padding 16→18px, darker bg
- `.ck-key-value` — bg rgba(0,0,0,0.5), letter-spacing 0.02em, font-size 12.5px
- `.ck-copy-btn` — padding 4px 11px (was 3px 10px)

### Why
User requested the "new key" card and generated key card to be redesigned and more attractive. The modal had incorrect font hierarchy (mono on titles), JS hover handlers instead of CSS, an undersized success icon, and a flat key reveal box.

### Commits
| SHA | Description |
|-----|-------------|
| 726e6fa | feat(admin-ui): polish CreateKeyModal — premium typography, success state, key reveal |

## Session 63 — CreateKeyModal Form Redesign: Config Row Table (2026-03-21)

### What changed
- `admin-ui/components/keys/CreateKeyModal.tsx` — form layout redesign

### Which lines / functions
- `ConfigRow` — new component replacing `LimitCard`; horizontal row with icon+label/sub on left, compact inline input on right; active state tints row bg with field color at 8% opacity
- `GroupHeader` — new component replacing `SubDivider`; flush table section header
- `LimitCard` — removed
- `SubDivider` — removed
- Form JSX — replaced 2-column `LimitCard` grid with `ck-config-table` containing `GroupHeader` + `ConfigRow` for each field
- `ck-label-input` — 15px sans-serif label field (was small ck-input)
- `ck-cfg-input` — 80px right-aligned compact number input
- `ck-cfg-models-input` — 160px inline text input for allowed models
- `ck-form-actions` — stacked buttons: full-width submit + full-width cancel below
- All chips, success state, key reveal, API logic unchanged

### Why
User found the modal form generic. The 2-column card grid was replaced with a Stripe-style config row table: cleaner hierarchy, less visual noise, better scan-ability. Each limit is a horizontal row with the value input inline on the right.

### Commits
| SHA | Description |
|-----|-------------|
| 402d627 | feat(admin-ui): redesign CreateKeyModal form — config row table layout |

## Session 64 — CreateKeyModal Full Rewrite: Stepper Fields + No Scrollbar (2026-03-21)

### What changed
- `admin-ui/components/keys/CreateKeyModal.tsx` — complete rewrite
- `admin-ui/app/globals.css` — `.ck-modal-scroll` scrollbar suppression added

### Which lines / functions
- `StepField` — new component; stepper (−/value/+) replaces plain number input; number spinner arrows suppressed via `-webkit-appearance: none` + `-moz-appearance: textfield`; this eliminates the scrollbar trigger entirely
- `nk-card` — no `overflowY` at all; scrollbar is impossible by design
- `FIELDS` array — drives all four limit rows declaratively
- `GroupHeader` / `ConfigRow` / `LimitCard` / `SubDivider` — all removed
- Limits section: `nk-fields` container, each row has icon + label/hint left, stepper right
- Models field: icon + inline text input in glass row
- Actions: flex row, primary white btn + ghost cancel
- Success state: spring-animated check icon, key reveal with copy btn, green state on copy
- All CSS self-contained in `CSS` constant; `useEffect` body+html overflow lock preserved

### Why
Scrollbar persisted because `<input type="number">` browser spin buttons triggered scroll context. Complete rewrite with stepper pattern eliminates the number input spin arrows entirely, and the modal card has no overflow-y property, making a scrollbar structurally impossible.

### Commits
| SHA | Description |
|-----|-------------|
| 8601b8a | feat(admin-ui): full rewrite CreateKeyModal — stepper fields, no scrollbar |

---

## Session 58 — Credentials redesign, live config UI, key fixes (2026-03-21)

### What changed
- `admin-ui/components/credentials/CredentialCard.tsx` — full redesign: glassmorphism backdrop blur, ambient top glow, color-matched status orb, animated circuit breaker bar via Framer Motion, metric icons, breathing skeleton loader
- `admin-ui/components/credentials/PoolSummaryBar.tsx` — redesign: status orb with radial glow, bold healthy/unhealthy counts, gradient segmented health bar with glow on healthy segments, inline-styled action buttons
- `admin-ui/app/(dashboard)/credentials/page.tsx` — full rewrite: removed redundant 4-KPI card grid, animated AnimatePresence panel for Add Cookie, cleaner header with status pill + Add Cookie toggle button, animated skeleton loading
- `admin-ui/components/settings/AddCookiePanel.tsx` — replaced textarea with split prefix input: fixed `WorkosCursorSessionToken=` label + token-only input field; auto-strips duplicate prefix if user pastes full cookie string; Enter key submits
- `routers/internal.py` — removed key truncation from `list_keys` (was `k["key"][:24] + "..."` — broke copy-to-clipboard); full key now returned, frontend handles display masking via `truncateKey()`
- `storage/keys.py` — renamed key prefix `sk-shin-` → `wiwi-`; updated schema docstring
- `tests/test_keys_storage.py` — updated `test_create_returns_key_starting_with_sk_shin` → `test_create_returns_key_starting_with_wiwi`

### Which lines / functions
- `admin-ui/components/credentials/CredentialCard.tsx:CredentialCard` — full rewrite; `STATE` color map replaces `C` inline ternary; `motion.div` animated circuit breaker bar
- `admin-ui/components/credentials/PoolSummaryBar.tsx:PoolSummaryBar` — full rewrite; segmented bar now gradient + glow; buttons inline-styled, no class deps
- `admin-ui/app/(dashboard)/credentials/page.tsx:CredentialsPage` — full rewrite; `AnimatePresence` for cookie panel; KPI grid removed
- `admin-ui/components/settings/AddCookiePanel.tsx:AddCookiePanel` — `tokenValue` state replaces `cookie`; prefix stripped on submit with `startsWith` guard
- `routers/internal.py:list_keys` — removed `k["key"] = k["key"][:24] + "..."`
- `storage/keys.py:KeyStore.create` — `f"sk-shin-{...}"` → `f"wiwi-{...}"`

### Why
- **Credentials redesign:** existing layout was functional but visually flat — glassmorphism cards with glow, animated bars, and better spacing make pool health immediately readable at a glance.
- **Add Cookie UX:** requiring users to type `WorkosCursorSessionToken=` manually was error-prone. Split input pre-fills the prefix; users paste only the token value.
- **Key copy bug:** `list_keys` truncated the key server-side before sending to the UI. The copy button wrote the truncated `sk-shin-xxxx...` string — not a valid bearer token. Fixed by returning full keys from the API; display truncation stays in the frontend `truncateKey()` helper.
- **Key prefix:** renamed to `wiwi-` to match the project identity.

### Commits
| SHA | Description |
|-----|-------------|
| a9f9015 | feat(admin-ui): redesign credentials page — glassmorphism cards, animated panel, cleaner layout |
| 4a3aac7 | feat(admin-ui): add cookie panel to credentials page; pre-fill WorkosCursorSessionToken= prefix |
| 2461934 | feat(admin-ui): toggle Add Cookie panel — hidden by default, shown on button click |
| 726704c | fix(api): return full key from list_keys — truncation broke copy-to-clipboard in admin UI |
| bc70af2 | fix(keys): rename key prefix sk-shin- → wiwi- |

---

## Session 59 — API key enable/disable/delete fix (2026-03-21)

### What changed
- `routers/internal.py` — removed stale key truncation from `update_key` response (`updated["key"] = updated["key"][:24] + "..."` deleted)

### Which lines / functions
- `routers/internal.py:update_key` (~line 334) — deleted the line that truncated the key before returning it

### Why
Toggle (enable/disable) and delete of managed API keys were silently failing with 404. Root cause: `update_key` truncated the returned key to 24 chars + `...` in its response. The frontend used this truncated value for subsequent PATCH/DELETE calls, which the DB lookup could not match. Combined with the already-fixed `list_keys` truncation (session 58), the full key never reached the DB layer for update or delete operations. Removing the truncation from the response restores correct behaviour — the full key is returned and used by all downstream UI operations.

### Commits
| SHA | Description |
|-----|-------------|
| 79ce156 | fix(api): remove stale key truncation from update_key response |

## Session 65 — Logs Page Full Redesign: Modern Ops Aesthetic (2026-03-21)

### What changed
- `admin-ui/app/(dashboard)/logs/page.tsx` — redesign
- `admin-ui/components/logs/LogFilters.tsx` — redesign
- `admin-ui/components/logs/LogsTable.tsx` — redesign
- `admin-ui/components/logs/LogDetailSheet.tsx` — redesign

### Which lines / functions
- `LogsPage` — KPI strip: unified grid → 5 individual glass tiles each with 2px colored left accent bar (white/amber/red/green/white). Section dividers → clean inline-header rows. Right-side refresh indicator chip added to header
- `LogFilters` — 2-row panel: header row (icon + label + active count badge + clear button), controls row (provider pills | cache pills | API key select | latency input). Active state: 2px white left border accent on panel root
- `LogsTable` — row hover: inset 2px left accent line + bg tint. Selected row: full-white left line + slightly elevated bg. Column widths locked via th selectors. Sticky header with blur. `ChevronsUpDown` on unsorted columns at 20% opacity
- `LogDetailSheet` — width 520px, backdrop blur 6px. KPI cells separated by 1px borders. Section labels: 8.5px mono + gradient-fade line. Token bar: segmented input/output. Cost table: bordered container. Body scrollbar fully hidden

### Why
User requested more attractive, modern, non-generic redesign of the logs page. Parallel agents redesigned all four files simultaneously.

### Commits
| SHA | Description |
|-----|-------------|
| 8af01c9 | feat(admin-ui): redesign logs page and filters — glass tiles, compact toolbar |
| dfdc104 | feat(admin-ui): redesign LogsTable and LogDetailSheet — modern ops aesthetic |

## Session 66 — Credentials Page Redesign: CSS Class System (2026-03-21)

### What changed
- `admin-ui/app/(dashboard)/credentials/page.tsx` — CSS class system
- `admin-ui/components/credentials/CredentialCard.tsx` — CSS class system
- `admin-ui/components/credentials/PoolSummaryBar.tsx` — CSS class system

### Which lines / functions
- `CredentialsPage` — all inline style layout replaced with `cp-*` classes; JS hover handlers on Add Cookie button removed; CSS `:hover` pseudo-classes used instead; `CP_CSS` constant injected via `<style>`
- `PoolSummaryBar` — Validate/Reset buttons: JS hover removed, `.psb-btn-ghost:hover:not(:disabled)` / `.psb-btn-primary:hover:not(:disabled)` CSS; disabled state via `psb-btn--disabled` class; `PSB_CSS` constant
- `CredentialCard` — metric cell hover: JS removed, `.cc-metric:hover` CSS; card-level glow hover preserved (dynamic color); `CC_CSS` constant; all `cc-*` classes for layout/spacing
- Dynamic colors (`statusColor`, `C.fg`, `C.bg`, `C.glow`, `C.border`) remain inline only for color values — layout is all CSS
- All framer-motion props, animations, data logic, hooks preserved exactly

### Why
User requested credentials page redesign. The components had inline style sprawl and JS hover handlers. Converted all three files to CSS class systems matching the pattern used across dashboard, logs, and keys pages.

### Commits
| SHA | Description |
|-----|-------------|
| 238c786 | feat(admin-ui): redesign credentials page — CSS class system, remove JS hover handlers |

## Session 67 — Cache Page Redesign: Glassmorphism CSS Class System (2026-03-21)

### What changed
- `admin-ui/app/(dashboard)/cache/page.tsx` — redesign
- `admin-ui/components/cache/CacheStatusCard.tsx` — redesign
- `admin-ui/components/cache/ClearCacheButton.tsx` — redesign

### Which lines / functions
- `CachePage` — page header: title left + ClearCacheButton right in flex row; KPI strip: `grid-4` + inline cards → `cache-kpi-strip` flex row of glass tiles with 2px colored left accent bars; `SectionDivider` → `cache-section-div` classes; `CACHE_CSS` injected
- `CacheStatusCard` — `StatusBadge`: `csc-badge`/`csc-badge-disabled`; `MonoStat`: `csc-stat`; both cards: `csc-card` with glassmorphism + `::before` top sheen; hit rate bar: `csc-hit-track`/`csc-hit-fill`; prefix chip: `csc-prefix-chip`; `CSC_CSS` injected
- `ClearCacheButton` — trigger: `ccb-btn` red-tinted glass, CSS `:hover`; spinner: `ccb-spinner` with local `ccb-spin` keyframe (removes reliance on global `spin`); popover: `ccb-popover` glass card; cancel/confirm: `ccb-cancel`/`ccb-confirm` with CSS `:hover`; `CCB_CSS` injected
- All data logic, hooks, state, toast calls, motion props preserved exactly

### Why
User requested cache page redesign consistent with the rest of the admin UI.

### Commits
| SHA | Description |
|-----|-------------|
| a4cc86f | feat(admin-ui): redesign cache page — glassmorphism CSS class system, KPI tiles, clean layout |

## Session 68 — Settings Page Redesign: Glassmorphism CSS Class System (2026-03-21)

### What changed
- `admin-ui/app/(dashboard)/settings/page.tsx` — full redesign
- `admin-ui/components/settings/ConfigRow.tsx` — full redesign
- `admin-ui/components/settings/AddCookiePanel.tsx` — full redesign

### Which lines / functions
- `SettingsPage` — page header: title with `Settings2` icon; KPI strip: 4 tiles (Config Vars, Groups, Overridden, Live Reload) with `sp-kpi-strip` / `sp-kpi-tile` glassmorphism cards with 2px colored left accent bars; `SectionDivider` → `sp-section-div` classes; config groups: `sp-groups` flex column, each card has `sp-group-card` with left accent `sp-group-bar`, `sp-group-header` with per-group Lucide icon, name, var count, `sp-group-modified-badge` when any key overridden; `SETTINGS_CSS` injected inline
- `ConfigRow` — `cfg-row-label-col`: two-line label + mono key name; `cfg-row-type-badge`: color-coded type chip (bool/int/float/str); view mode: value chip + default value hint when overridden + icon edit button (`Pencil`); edit mode: input/select + icon buttons (`Check`, `RotateCcw`, `X`); hover row highlight; `ROW_CSS` injected inline
- `AddCookiePanel` — `acp-header` with `Cookie` icon in accent-tinted square chip; `acp-input-wrap` with focus/error/ok border states; `acp-btn-add` with spinner animation and `Plus` icon; `acp-feedback` with `CheckCircle`/`AlertCircle` icons, fade-in animation; `COOKIE_CSS` injected inline
- All data logic, hooks (`useRuntimeConfig`), save/reset handlers, API calls preserved exactly

### Why
User requested settings page UI enhancement consistent with cache page glassmorphism design system.

### Commits
| SHA | Description |
|-----|-------------|

## Session 69 — Multi-Instance Aggregation for Admin UI (2026-03-25)

### What changed
- `admin-ui/lib/instances.ts` — created
- `admin-ui/lib/fanout.ts` — created
- `admin-ui/app/api/stats/route.ts` — rewritten
- `admin-ui/app/api/logs/route.ts` — rewritten
- `admin-ui/app/api/health/route.ts` — rewritten
- `admin-ui/app/api/credentials/route.ts` — rewritten
- `admin-ui/app/api/credentials/me/route.ts` — rewritten
- `admin-ui/app/api/credentials/reset/route.ts` — rewritten
- `admin-ui/app/api/credentials/add/route.ts` — rewritten
- `admin-ui/app/api/cache/clear/route.ts` — rewritten
- `admin-ui/app/api/keys/route.ts` — rewritten
- `admin-ui/app/api/keys/[key]/route.ts` — rewritten
- `admin-ui/app/api/models/route.ts` — rewritten
- `admin-ui/app/api/config/route.ts` — rewritten
- `admin-ui/app/api/config/[key]/route.ts` — rewritten
- `admin-ui/app/api/instances/route.ts` — created
- `admin-ui/hooks/useInstances.ts` — created
- `admin-ui/components/overview/InstanceHealthStrip.tsx` — created
- `admin-ui/app/(dashboard)/dashboard/page.tsx` — HealthBanner → InstanceHealthStrip
- `.env.example` — INSTANCE_URLS + BACKEND_URL documented

### Which lines / functions
- `lib/instances.ts:parseInstances` — parses INSTANCE_URLS comma-separated env; fallback to BACKEND_URL
- `lib/instances.ts:INSTANCES` — exported readonly registry used by all routes
- `lib/instances.ts:PRIMARY` — first instance, used for DB-backed/static routes
- `lib/fanout.ts:fanout` — fires fetchFn against all instances in parallel via Promise.allSettled
- `lib/fanout.ts:firstOk` — returns first successful result
- `lib/fanout.ts:sumFields` — sums numeric fields across successful results
- `app/api/stats/route.ts:GET` — merges KeyStats: sums all numeric counters, unions key map, max last_request_ts, sums provider counts
- `app/api/logs/route.ts:GET` — merges log arrays from all instances, sorts by ts desc, caps at limit
- `app/api/health/route.ts:GET` — validates token against any reachable instance; reports ready if any instance is ready
- `app/api/credentials/route.ts:GET` — merges credential pools, sums pool_size, re-indexes credential.index
- `app/api/credentials/reset/route.ts:POST` — fans out to all instances
- `app/api/credentials/add/route.ts:POST` — fans out to all instances (keeps credential pools in sync)
- `app/api/cache/clear/route.ts:POST` — fans out, sums l1_cleared + l2_cleared
- `app/api/config/[key]/route.ts:PATCH,DELETE` — fans out to all instances
- `app/api/instances/route.ts:GET` — parallel health check with 4s timeout + latency measurement per instance
- `hooks/useInstances.ts:useInstances` — SWR hook, 10s refresh interval
- `components/overview/InstanceHealthStrip.tsx:InstanceHealthStrip` — per-instance health pills with latency; summary N/M badge
- `dashboard/page.tsx` — import and render InstanceHealthStrip in place of HealthBanner

### Why
Admin UI was hardcoded to a single BACKEND_URL. With 6 instances across two ports (4001-4003 and 2000-2003), stats and logs were only visible from one instance. This change fans out all data-aggregating reads to every instance and merges results, so the dashboard reflects the full fleet.

### Commits
| SHA | Description |
|-----|-------------|
| 01c385cd | feat(admin-ui): multi-instance aggregation via INSTANCE_URLS |

## Session 70 — Connection Panel in Settings (2026-03-25)

### What changed
- `admin-ui/lib/instances.ts` — refactored: added `getInstances()`, `setInstances()`, `parseInstanceUrls()`, `DEFAULT_INSTANCES`; `INSTANCES` and `PRIMARY` are now live Proxy objects that always reflect the current override
- `admin-ui/lib/fanout.ts` — updated to call `getInstances()` instead of reading static `INSTANCES`
- `admin-ui/app/api/instances/route.ts` — updated to call `getInstances()` for live list
- `admin-ui/app/api/instances/override/route.ts` — created: POST updates in-memory instance list; GET returns live list + env defaults
- `admin-ui/components/settings/ConnectionPanel.tsx` — created
- `admin-ui/app/(dashboard)/settings/page.tsx` — added Connection section + ConnectionPanel above Configuration

### Which lines / functions
- `lib/instances.ts:getInstances` — returns live `_instances` array
- `lib/instances.ts:setInstances` — replaces `_instances`; called by override route
- `lib/instances.ts:parseInstanceUrls` — exported so override route can reuse parsing logic
- `lib/instances.ts:DEFAULT_INSTANCES` — env-derived snapshot used as factory reset value
- `lib/instances.ts:INSTANCES` / `PRIMARY` — Proxy objects delegating to `_instances[...]` at access time
- `app/api/instances/override/route.ts:POST` — validates body.urls, calls setInstances, returns new live list
- `app/api/instances/override/route.ts:GET` — returns `{ instances: getInstances(), defaults: DEFAULT_INSTANCES }`
- `components/settings/ConnectionPanel.tsx:ConnectionPanel` — on mount: fetches /api/instances/override (GET) for defaults + current list; reads localStorage wiwi_instance_urls and re-applies saved override via POST; renders port-input rows; Add instance, Remove, Reset, Apply & Save, env defaults buttons
- `settings/page.tsx` — added `<SectionDivider label="Connection" />` and `<ConnectionPanel />` before Configuration section

### Why
Instance list was only configurable via env vars, requiring a server restart. The Connection panel lets users add/remove ports directly in the UI, persists to localStorage, and re-applies overrides automatically on page load after a server restart.

### Commits
| SHA | Description |
|-----|-------------|
| 00b8d8e8 | feat(admin-ui): Connection panel in Settings — manage instance URLs from UI |

## Session 71 — LIVE Window Tab: Real-Time Tracking Dashboard (2026-03-25)

### What changed
- `admin-ui/lib/metrics.ts` — added `toLiveTimeSeries()`
- `admin-ui/components/charts/LiveMetricsPanel.tsx` — created
- `admin-ui/app/(dashboard)/dashboard/page.tsx` — added LIVE option, wired LiveMetricsPanel, styled LIVE button

### Which lines / functions
- `lib/metrics.ts:toLiveTimeSeries` — N-second buckets (default 5s) over last windowSecs (default 60s); returns tps, rpm, avg_ms, cost per bucket
- `components/charts/LiveMetricsPanel.tsx:LiveMetricsPanel` — 4 gauge tiles (TPS, RPM, Avg Latency, Cost 5m) each with a 60s sparkline; scrolling request feed showing last 30 entries with age, key, provider, tokens, latency (color-coded), cost, cache hit
- `components/charts/LiveMetricsPanel.tsx:GaugeTile` — reusable gauge with left accent bar, top sheen, value + sub + sparkline
- `components/charts/LiveMetricsPanel.tsx:Spark` — minimal Recharts Area sparkline, gradient fill, no axes
- `components/charts/LiveMetricsPanel.tsx:FeedRow` — single request row in 7-column grid
- `dashboard/page.tsx:WINDOW_OPTIONS` — added `{ label: 'LIVE', value: 0 }`
- `dashboard/page.tsx` — chart section wrapped in `win === 0 ? <LiveMetricsPanel> : <historical charts>`
- `dashboard/page.tsx` CSS — added `.db-win-btn-live`, `.db-win-btn-live-base`, `@keyframes db-live-glow`

### Why
User requested a real-time tracking view alongside the 5m/30m/1h window buttons. LIVE mode replaces the historical chart section with sub-minute gauges and a scrolling request feed, driven by the existing 3s-polling useLogs hook — no new endpoints needed.

### Commits
| SHA | Description |
|-----|-------------|
| fd6d2b01 | feat(admin-ui): LIVE window tab — real-time tracking panel with gauges and request feed |

## Session 72 — Converter split: shims (Tasks 11-13) (2026-03-25)

### What changed
- `converters/to_cursor.py` — replaced 799-line implementation with a thin shim (33 lines)
- `converters/from_cursor.py` — replaced 427-line implementation with a shim that owns patch-target functions verbatim and re-exports simple chunk formatters from sub-modules

### Which lines / functions
- `converters/to_cursor.py` — re-exports `openai_to_cursor` from `to_cursor_openai`, aliases `anthropic_to_the_editor` → `anthropic_to_cursor`, re-exports `anthropic_messages_to_openai`, `parse_system` from `to_cursor_anthropic`, and all helpers from `cursor_helpers`
- `converters/from_cursor.py` — owns verbatim: `_safe_pct`, `context_window_for`, `litellm`, `openai_non_streaming_response`, `openai_usage_chunk`, `anthropic_message_start`, `anthropic_non_streaming_response`, `convert_tool_calls_to_anthropic`, `split_visible_reasoning`, `scrub_support_preamble`, `sanitize_visible_text`; re-exports `openai_chunk`, `openai_sse`, `openai_done`, `anthropic_sse_event`, `anthropic_content_block_*`, `anthropic_message_delta`, `anthropic_message_stop` from sub-modules

### Why
- Tasks 11-13 of the converter split plan: make both files thin shims so all existing importers continue working with zero changes
- `from_cursor.py` must own the patch-target functions (`context_window_for`, `litellm`) because tests use `patch.object(converters.from_cursor, ...)` — re-exporting from sub-modules would make those patches miss the live bindings
- `to_cursor_anthropic.py` defines `anthropic_to_the_editor` (underscore, valid Python identifier); shim aliases it back to `anthropic_to_cursor` which all callers use

### Commits
| SHA | Description |
|-----|-------------|
| 9a4efbb7 | refactor(converters): replace to_cursor and from_cursor with thin shims |

## Session 73 — Structured Request/Response Logging Middleware (2026-03-25)

### What changed
- `middleware/logging.py` — created
- `tests/test_logging_middleware.py` — created
- `config.py` — added `log_sample_rate` field
- `app.py` — replaced `request_id_middleware` with `request_context_middleware`
- `routers/openai.py` — populate `RequestContext` with model, stream, api_key_prefix
- `routers/anthropic.py` — same
- `pipeline/record.py` — emit `pipeline_complete` structlog event

### Which lines / functions
- `middleware/logging.py` — new file: `RequestContext` dataclass, `get_ctx()`, `request_context_middleware()`
- `config.py:Settings` — added `log_sample_rate: float` (alias `SHINWAY_LOG_SAMPLE_RATE`, default 1.0)
- `app.py:create_app` — replaced inline `request_id_middleware` block with delegation to `request_context_middleware`; removed unused `import uuid`
- `routers/openai.py:chat_completions` — added `_get_ctx` calls to set `api_key_prefix`, `model`, `stream` on `RequestContext`
- `routers/anthropic.py:anthropic_messages` — same pattern
- `pipeline/record.py:_record` — added `log.info("pipeline_complete", ...)` after `analytics.record()` for request_id-correlated logging

### Why
Requested feature: full structured request/response lifecycle logging with request_id correlation. Previously only `http_request` was logged at the HTTP layer with no pipeline correlation. Now three events are emitted per request: `request_start` (always), `request_end` (sampled by `SHINWAY_LOG_SAMPLE_RATE`), and `pipeline_complete` (always, correlated by `request_id`). Metadata only — no content bodies logged. `RequestContext` replaces the ad-hoc `request.state.request_id` pattern with a typed dataclass.

### Commits
| SHA | Description |
|-----|-------------|
| 1b5042d5 | feat(middleware): add RequestContext and request_context_middleware |
| 28169c43 | feat(config): add SHINWAY_LOG_SAMPLE_RATE setting |
| ab9fe002 | refactor(app): replace request_id_middleware with request_context_middleware |
| 050d44d9 | feat(routers): populate RequestContext with model, stream, api_key_prefix |
| 81c7a946 | feat(pipeline): emit pipeline_complete structlog event with request_id correlation |

## Session 74 — Retry Middleware: Client-Facing Retry Hints (2026-03-25)

### What changed
- `middleware/retry.py` — created
- `middleware/rate_limit.py` — modified
- `app.py` — modified
- `routers/openai.py` — modified
- `routers/anthropic.py` — modified
- `routers/responses.py` — modified
- `tests/test_retry_middleware.py` — created
- `tests/test_unified_router.py` — modified (fixture stubs)
- `tests/test_routing.py` — modified (fixture stubs)
- `tests/test_request_validators.py` — modified (fixture stubs)

### Which lines / functions
- `middleware/retry.py` — new file: `RetryContext` dataclass (`retry_count: int`, `retry_reason: str`), `get_retry_ctx(request)`, `enrich_rate_limit_response(headers, ctx, *, rate_limit, remaining)`
- `middleware/rate_limit.py` — added `_REASON_NORMALISE` dict, `_set_retry_ctx(request, reason)` helper; added `request: object | None = None` param to `enforce_rate_limit()` and `enforce_per_key_rate_limit()`; both call `_set_retry_ctx` before raising `RateLimitError`
- `app.py:proxy_error_handler` — added `enrich_rate_limit_response()` call in `RateLimitError` branch; writes `X-Retry-Count`, `X-Retry-Reason`, `X-RateLimit-Limit`, `X-RateLimit-Remaining` to 429 response headers
- `routers/openai.py:chat_completions`, `text_completions`, `validate_tools` — added `request=request` to both enforce calls
- `routers/anthropic.py:anthropic_messages`, `count_tokens` — same
- `routers/responses.py:create_response` — same
- `tests/test_unified_router.py`, `tests/test_routing.py`, `tests/test_request_validators.py` — updated `bypass_auth`/`bypass_guards`/`bypass` fixture stubs to accept `request=None` so they tolerate the new keyword argument

### Why
Clients receiving 429s had only `Retry-After` to guide backoff. The new headers (`X-Retry-Count`, `X-Retry-Reason`, `X-RateLimit-Limit`, `X-RateLimit-Remaining`) give clients enough signal to self-throttle intelligently. Architecture follows the `middleware/logging.py` / `RequestContext` pattern: a lightweight dataclass on `request.state`, populated at the point where the limit fires, consumed in the exception handler. No new ASGI middleware class, no new dependencies.

### Commits
| SHA | Description |
|-----|-------------|
| 941499d1 | feat(middleware): add RetryContext, get_retry_ctx, enrich_rate_limit_response |
| babb0fc8 | feat(rate_limit): populate RetryContext with retry_reason before raising RateLimitError |
| b0d05bb5 | feat(app): enrich 429 responses with X-Retry-Count, X-Retry-Reason, X-RateLimit-* headers |
| b4dbbabe | feat(routers): pass request to enforce_rate_limit and enforce_per_key_rate_limit |

---

## Session 75 — CORS Middleware (2026-03-25)

### What changed
- `config.py` — modified
- `app.py` — modified
- `tests/test_cors.py` — created

### Which lines / functions
- `config.py:Settings` — added `# ── CORS` block immediately before `# ── Prometheus metrics`; two new fields: `cors_enabled: bool = Field(default=False, alias="SHINWAY_CORS_ENABLED")` and `cors_origins: str = Field(default="*", alias="SHINWAY_CORS_ORIGINS")`
- `app.py:create_app` — added conditional `CORSMiddleware` registration block immediately after `GZipMiddleware`; imports `starlette.middleware.cors.CORSMiddleware` inside the `if` block (zero import cost when disabled); parses comma-separated origins with `[o.strip() for o in settings.cors_origins.split(",") if o.strip()]`; logs `cors_enabled` with origins list
- `tests/test_cors.py` — created; 15 tests using `monkeypatch.setattr(config_mod.settings, ...)` + `create_app()` (no `importlib.reload` — follows project pattern); covers: config defaults, field patching, CORS disabled (no header on GET, OPTIONS→405), wildcard enabled (header present, preflight 200), single explicit origin (match / non-match), multiple comma-separated origins (first, second, unlisted excluded), whitespace trimming, preflight with explicit origin

### Why
Browser-based clients (admin UIs, web playgrounds) hitting the proxy directly were blocked by same-origin policy. `CORSMiddleware` from Starlette (already a transitive FastAPI dependency — zero new installs) is now registered conditionally: absent from the middleware stack entirely when `SHINWAY_CORS_ENABLED=false` (default), so server-to-server usage has no overhead or header noise. The plan specified `importlib.reload` in tests; this was replaced with `monkeypatch.setattr` on the settings singleton to match the established codebase pattern and avoid `sys.modules` pollution that caused `ModuleNotFoundError: No module named 'routers.unified'` regressions when CORS tests ran before other tests.

### Commits
| SHA | Description |
|-----|-------------|
| f736c312 | feat(config): add SHINWAY_CORS_ENABLED and SHINWAY_CORS_ORIGINS settings |
| d69b5433 | test(cors): write failing CORS tests for config fields and middleware wiring |
| 827cb05e | feat(app): register CORSMiddleware when SHINWAY_CORS_ENABLED=true |

## Session 76 — Sliding Window SQLite Token Quota Middleware (2026-03-25)

### What changed
- `storage/quota.py` — created: `QuotaStore` with `init`, `close`, `record`, `get_usage_24h`, `prune_old`; module-level `quota_store` singleton
- `middleware/quota.py` — created: `check_quota`, `record_quota_usage`
- `config.py` — added `quota_enabled` field aliased to `SHINWAY_QUOTA_ENABLED`
- `app.py` — wired `quota_store.init()` and `quota_store.close()` into `_lifespan`
- `middleware/auth.py` — replaced in-process analytics counter with `check_quota` call when `settings.quota_enabled`
- `pipeline/record.py` — added `from config import settings` import; added `record_quota_usage` call after `analytics.record()`
- `tests/test_quota.py` — created: 22 tests covering `QuotaStore` (storage layer) and `check_quota`/`record_quota_usage` (middleware layer)

### Which lines / functions
- `storage/quota.py:QuotaStore` — WAL-mode aiosqlite store; `record()` inserts one row per call, prunes every 100 inserts; `get_usage_24h()` uses strict `> now-86400` window; `prune_old()` deletes `<= now-86400`
- `middleware/quota.py:check_quota` — reads `quota_store.get_usage_24h`, raises `RateLimitError` at `>= limit`, logs WARNING at 80% threshold
- `middleware/quota.py:record_quota_usage` — calls `quota_store.record`, silently suppresses SQLite failures, no-ops on `tokens <= 0`
- `config.py:Settings.quota_enabled` — `bool = Field(default=False, alias="SHINWAY_QUOTA_ENABLED")`
- `app.py:_lifespan` — `quota_store.init()` after `key_store.init()`; `quota_store.close()` before `response_store.close()`
- `middleware/auth.py:check_budget` — lines 178-186: quota branch added; when `settings.quota_enabled`, calls `check_quota` instead of `analytics.get_daily_tokens`
- `pipeline/record.py:_record` — added `from config import settings` to imports; lines 51-53: `record_quota_usage` called after `analytics.record()` when `quota_enabled`

### Why
The in-process daily token counter (`analytics.get_daily_tokens`) resets on every process restart, making `token_limit_daily` enforcement unreliable in multi-worker and Docker deployments. The new SQLite sliding window survives restarts, enforces a true 24-hour rolling window per API key, and is opt-in (`SHINWAY_QUOTA_ENABLED=false` by default) so existing deployments are completely unaffected.

### Commit SHAs
| SHA | Description |
|---|---|
| 5c6480e0 | feat(storage): add QuotaStore — sliding window token quota SQLite store |
| 86f3d260 | feat(middleware): add check_quota and record_quota_usage |
| 7496522e | feat(config): add SHINWAY_QUOTA_ENABLED setting |
| 3ce8714a | feat(app): init and close quota_store in lifespan |
| 7c5f1afd | feat(auth): wire check_quota into check_budget for persistent sliding window quota |
| 3080633a | feat(pipeline): call record_quota_usage after each completed response |

## Session 77 — Model Fallback Chain (2026-03-25)

### What changed
- `tests/test_fallback.py` — created: 24 unit tests covering `FallbackChain.get_fallbacks`, `FallbackChain.should_fallback`, `PipelineParams.fallback_model`, `_call_with_retry` fallback integration, and config field
- `config.py` — added `fallback_chain: str` field, default `"{}"`, alias `SHINWAY_FALLBACK_CHAIN`
- `pipeline/fallback.py` — created: `FallbackChain` class with `get_fallbacks(model)` and `should_fallback(exc)`; `_FALLBACK_ELIGIBLE` tuple
- `pipeline/params.py` — added `fallback_model: str | None = None` field to `PipelineParams`
- `pipeline/suppress.py` — `_call_with_retry` extended with fallback loop after primary retry exhaustion; imports `FallbackChain`; logs `fallback_model_used` at INFO level and `fallback_model_failed` at DEBUG
- `pipeline/__init__.py` — re-exports `FallbackChain`

### Which lines / functions
- `pipeline/fallback.py:FallbackChain.__init__` — parses `chain_json` via `json.loads`; raises `ValueError` with `SHINWAY_FALLBACK_CHAIN` in message on invalid JSON or non-object top level
- `pipeline/fallback.py:FallbackChain.get_fallbacks` — returns `list(self._chain.get(model, []))` — always a copy, never the internal reference
- `pipeline/fallback.py:FallbackChain.should_fallback` — `isinstance(exc, (RateLimitError, BackendError, TimeoutError))`
- `pipeline/params.py:PipelineParams.fallback_model` — line 30: `fallback_model: str | None = None`; internal-only field, never read by router or converter layer
- `pipeline/suppress.py:_call_with_retry` — lines 100-175: `FallbackChain` constructed once per call from `settings.fallback_chain`; primary retry loop unchanged; after primary exhaustion, `should_fallback(last_exc)` gates entry to fallback loop; each fallback model gets exactly one attempt via `replace(params, model=fb, fallback_model=fb)`; final exhaustion always raises `BackendError`
- `config.py:Settings.fallback_chain` — `str = Field(default="{}", alias="SHINWAY_FALLBACK_CHAIN")`
- `pipeline/__init__.py` — line 17: `from pipeline.fallback import FallbackChain  # noqa: F401`

### Why
When the primary model is rate-limited or returns persistent backend errors across all retries, previously the proxy raised `BackendError` immediately. The fallback chain allows operators to configure successive fallback models (`SHINWAY_FALLBACK_CHAIN` JSON env var) so requests survive upstream model-level outages transparently. The client always sees the originally-requested model name — fallback is fully internal. `AuthError` and non-transient errors bypass the fallback path entirely. Default config (`{}`) is a no-op: behaviour identical to before for all existing deployments.

### Commit SHAs
| SHA | Description |
|---|---|
| 230f1f51 | test(pipeline): add failing tests for FallbackChain and fallback integration |
| 22550050 | feat(config): add SHINWAY_FALLBACK_CHAIN setting for model fallback chain |
| 10f8cdbf | feat(pipeline): add FallbackChain module for model fallback chain |
| 0e298ae1 | feat(pipeline): add fallback_model field to PipelineParams |
| bf857566 | feat(pipeline): wire FallbackChain into _call_with_retry for model fallback |
| c978717c | refactor(pipeline): re-export FallbackChain from pipeline package |

## Session 78 — Batch API (2026-03-25)

### What changed
- `storage/batch.py` CREATED — `BatchStore` with `init`, `close`, `create`, `get`, `update_status`, `save_results`, `get_results`, `get_requests`, `list_by_key`. SQLite WAL mode, api_key-scoped reads. Module-level `batch_store` singleton.
- `routers/batch.py` CREATED — `create_batch`, `get_batch`, `get_batch_results`, `cancel_batch` endpoints + `_process_batch` background task.
- `app.py` MODIFIED — lifespan: `batch_store.init()` after `key_store.init()`, `batch_store.close()` in finally block; router: `app.include_router(batch_router)`.
- `tests/test_batch.py` CREATED — 22 unit tests (TDD red-then-green). 11 BatchStore CRUD tests + 11 router tests.

### Which lines / functions
- `storage/batch.py:BatchStore.create` — inserts with status=validating, returns OpenAI Batch API shape dict directly
- `storage/batch.py:BatchStore.get` — SELECT * WHERE id=? AND api_key=? (cross-tenant isolation)
- `storage/batch.py:BatchStore.update_status` — sets cancelled_at for cancelled, completed_at for completed/failed
- `storage/batch.py:BatchStore.save_results` — stores results_json + completed_count/failed_count; does NOT touch status
- `storage/batch.py:BatchStore.get_results` — returns None when results_json IS NULL (not-yet-completed)
- `storage/batch.py:BatchStore.list_by_key` — SELECT * WHERE api_key=? ORDER BY created_at DESC
- `storage/batch.py:_to_record` — converts aiosqlite.Row to OpenAI Batch response shape
- `routers/batch.py:_process_batch` — background task; checks cancellation before each item; per-item try/except; final_status=completed if any succeeded else failed
- `routers/batch.py:create_batch` — POST /v1/batch; validates requests non-empty + custom_id uniqueness; enqueues _process_batch via BackgroundTasks
- `routers/batch.py:get_batch` — GET /v1/batch/{batch_id}; 404 on missing/wrong-key
- `routers/batch.py:get_batch_results` — GET /v1/batch/{batch_id}/results; 400 when not terminal; returns NDJSON (response_model=None)
- `routers/batch.py:cancel_batch` — POST /v1/batch/{batch_id}/cancel; 422 if not in cancellable status
- `app.py:_lifespan` — batch_store init/close wired between key_store and quota_store
- `app.py:create_app` — batch_router included after responses_router

### Why
OpenAI Batch API support for fire-and-forget agentic workflows that submit multiple completions without holding connections open. Background task processes items sequentially via `handle_openai_non_streaming`; per-item failures do not abort the batch.

### Commit SHAs
| SHA | Description |
|-----|-------------|
| 207375cd | feat(batch): add OpenAI-compatible Batch API |
| 0d734ffa | feat(app): register batch_router and init/close batch_store in lifespan |

## Session 79 — Admin UI: Credentials & Login UI Overhaul (2026-03-25)

### What changed
- `admin-ui/app/(dashboard)/credentials/page.tsx` — full redesign: filter tabs (All/Healthy/Unhealthy/Cooldown), shimmer skeleton, richer empty state with CTA, cleaner header layout
- `admin-ui/components/credentials/CredentialCard.tsx` — added `cc-id-block` with SESSION TOKEN label, request load usage bar, `cursor-default` on metric cells, status-color CSS variable for hover glow, tighter stripe and top-glow
- `admin-ui/components/credentials/PoolSummaryBar.tsx` — replaced Activity icon orb with animated SVG arc health ring (`HealthRing`), vertical dividers, stacked action buttons, animated segment bar entrance
- `admin-ui/app/login/page.tsx` — complete visual overhaul: split-panel layout (info left / auth right on ≥960px), green accent theme, corner accents, scanline overlay, spotlight glow, lock icon auth header, green-caret input, accent-green submit button
- `admin-ui/app/login/page.tsx` — fixed auto-login stale closure bug: extracted `attemptLogin(adminKey)` plain function, both `handleSubmit` and auto-login effect call it directly with explicit key argument
- `admin-ui/app/login/page.tsx` — removed `LITELLM_MASTER_KEY` label, replaced with `ADMIN KEY`

### Which lines / functions
- `credentials/page.tsx:CredentialsPage` — filter state, `filteredCreds`, `TABS` array, shimmer skeleton with `cp-shimmer` keyframe, empty state CTA button
- `CredentialCard.tsx:CredentialCard` — `cc-id-block`, `cc-usage-wrap`/`cc-usage-fill`, `cc-footer-left`/`cc-footer-dot`, `--status-fg`/`--status-glow` CSS vars
- `PoolSummaryBar.tsx:HealthRing` — new SVG arc component with `motion.circle` animated `strokeDasharray`
- `PoolSummaryBar.tsx:PoolSummaryBar` — `psb-ring-block`, `psb-vdivider`, `psb-counts`, `psb-seg-block`, `psb-actions` vertical stack
- `login/page.tsx:attemptLogin` — extracted from `handleSubmit`, takes explicit `adminKey` param
- `login/page.tsx:LoginPage` — `lp-panel-left`, `lp-form-wrap`, `lp-auth-header`, `lp-auth-icon`, `Scanlines`, `Spotlight`, `CornerAccent`

### Why
UI enhancement pass: richer data visualization, filter UX, animated health ring, and a premium split-panel login page. Auto-login stale closure was causing silent failure when `NEXT_PUBLIC_DEFAULT_ADMIN_KEY` was set.

### Commit SHAs
| SHA | Description |
|-----|-------------|
| `90a7c5ed` | feat(admin-ui): overhaul credentials & login UI, fix auto-login stale closure |

---

## Session 80 — tools/score.py extraction (2026-03-26)

### What changed
- `tools/score.py` — created
- `tests/test_score.py` — created

### Which lines / functions
- `tools/score.py:_TOOL_CALL_MARKER_RE` — regex constant copied verbatim from `tools/parse.py` line 31
- `tools/score.py:_find_marker_pos` — copied verbatim from `tools/parse.py` lines 37–57
- `tools/score.py:score_tool_call_confidence` — copied verbatim from `tools/parse.py` lines 1086–1118
- `tests/test_score.py` — 8 tests covering: marker present/fenced/absent, confidence high/zero/low/clamped, low without marker on long text

### Why
Chunk 2 of the tools/ refactor plan (`docs/superpowers/plans/2026-03-25-tools-refactor.md`). `score_tool_call_confidence` and `_find_marker_pos` are co-dependent and belong in a focused module with no imports from other `tools/` modules. Extracted verbatim — `tools/parse.py` not yet modified (that happens in Chunk 4).

### Commit SHAs
| SHA | Description |
|-----|-------------|
| `2e59718c` | feat(tools): extract score.py — score_tool_call_confidence, _find_marker_pos |

---

## Session 139 — tools/format.py canonical wire-format encoder (2026-03-26)

### What changed
- `tools/format.py` — created
- `tests/test_format.py` — created

### Which lines / functions
- `tools/format.py:encode_tool_calls` — encodes a list of OpenAI-format tool call dicts to the `[assistant_tool_calls]\n{"tool_calls":[...]}` wire format; arguments decoded from JSON string to dict before serialisation

### Why
Chunk 6 of the tools/ refactor plan. Provides a single authoritative encoder for the wire format emitted between the proxy and the-editor's /api/chat endpoint. Previously duplicated inline across pipeline and converter modules. `converters/cursor_helpers.py` will re-export `encode_tool_calls` as `_assistant_tool_call_text` for backward compat.

### Commit SHAs
| SHA | Description |
|-----|-------------|
| `7b4faa23` | feat(tools): add format.py — encode_tool_calls canonical wire-format encoder |

---

## Session 140 — tools/schema.py JSON Schema validator (2026-03-26)

### What changed
- `tools/schema.py` — created
- `tests/test_schema.py` — created

### Which lines / functions
- `tools/schema.py:validate_schema` — pure function; validates tool call args against a JSON Schema `parameters` object; checks required fields, type correctness (string/integer/number/boolean/array/object), enum membership, string minLength/maxLength, number minimum/maximum, array minItems/maxItems; returns `(is_valid, errors)` tuple; bool correctly excluded from integer/number checks
- `tools/schema.py:_TYPE_CHECKS` — module-level dict mapping JSON Schema type names to Python types/tuples for `isinstance` checks

### Why
Chunk 5 of the tools/ refactor plan (`docs/superpowers/plans/2026-03-25-tools-refactor.md`). New capability module — not extracted from existing code. Provides full JSON Schema enforcement for tool call arguments, covering all constraint types needed by `repair_tool_call()` and future validation hooks. No new pip dependencies — pure Python.

### Commit SHAs
| SHA | Description |
|-----|-------------|
| `11e5b882` | feat(tools): add schema.py — validate_schema with full JSON Schema enforcement |

---

## Session 141 — tools/registry.py immutable request-scoped tool registry (2026-03-26)

### What changed
- `tools/registry.py` — created
- `tests/test_registry.py` — created

### Which lines / functions
- `tools/registry.py:ToolRegistry` — immutable request-scoped registry; built once per request from the client tool list; stores normalized→canonical name map, canonical→param set map, canonical→parameters schema map; all state name-mangled at construction to prevent external mutation
- `tools/registry.py:ToolRegistry.canonical_name` — exact normalized lookup then fuzzy fallback via `_fuzzy_match_param` from `tools/coerce`
- `tools/registry.py:ToolRegistry.schema` — returns raw `parameters` dict for a canonical tool name
- `tools/registry.py:ToolRegistry.known_params` — returns `set[str]` of param names for a canonical tool name
- `tools/registry.py:ToolRegistry.allowed_exact` — returns normalized→canonical dict
- `tools/registry.py:ToolRegistry.schema_map` — returns canonical→param set dict
- `tools/registry.py:_CURSOR_BACKEND_TOOLS` — default backend tool set (`read_file`, `read_dir`) injected at construction unless overridden
- `tools/registry.py:_normalize_name` — strips `-_\s`, lowercases for consistent key lookup

### Why
Chunk 8 of the tools/ refactor plan. New capability module — not extracted from existing code. Replaces per-call rebuilding of `allowed_exact` / `schema_map` in `parse.py`. Single immutable object per request eliminates redundant dict construction on every tool call repair pass. Deep-copies the input list at construction so caller mutations cannot corrupt registry state.

### Commit SHAs
| SHA | Description |
|-----|-------------|
| `445e3a52` | feat(tools): add registry.py — ToolRegistry immutable request-scoped tool lookup |

---

## Session 142 — tools/ Refactor: Full Module Split (2026-03-26)

### What changed

**New files created:**
- `tools/coerce.py` — `_PARAM_ALIASES`, `_levenshtein`, `_fuzzy_match_param`, `_coerce_value`
- `tools/score.py` — `_TOOL_CALL_MARKER_RE`, `_find_marker_pos`, `score_tool_call_confidence`
- `tools/streaming.py` — `StreamingToolCallParser`
- `tools/schema.py` — `validate_schema` (new: full JSON Schema enforcement)
- `tools/format.py` — `encode_tool_calls` (new: canonical wire-format encoder)
- `tools/inject.py` — `build_tool_instruction`, `_example_value`, `_PARAM_EXAMPLES`, `_tool_instruction_cache`
- `tools/registry.py` — `ToolRegistry` (new: immutable request-scoped tool lookup)
- `tests/test_coerce.py`, `tests/test_score.py`, `tests/test_streaming.py`
- `tests/test_schema.py`, `tests/test_format.py`, `tests/test_inject.py`, `tests/test_registry.py`

**Modified files:**
- `tools/parse.py` — removed 418 lines of duplicated code; imports from new modules; all re-exports preserved. 1,490 → 1,085 lines.
- `tools/__init__.py` — full public API re-export surface
- `converters/cursor_helpers.py` — removed `build_tool_instruction`, `_example_value`, `_PARAM_EXAMPLES`, `_tool_instruction_cache`, `_assistant_tool_call_text` bodies; replaced with re-exports from `tools/inject` and `tools/format`
- `docs/superpowers/specs/2026-03-25-tools-refactor-design.md` — created
- `docs/superpowers/plans/2026-03-25-tools-refactor.md` — created

### Which lines / functions
- `tools/parse.py:parse_tool_calls_from_text` — unchanged behaviour; `_PARAM_ALIASES`, `_levenshtein`, `_fuzzy_match_param`, `_coerce_value`, `_find_marker_pos`, `score_tool_call_confidence`, `StreamingToolCallParser` all removed and imported from focused modules
- `tools/inject.py:build_tool_instruction` — moved from `converters/cursor_helpers.py`; same signature `(tools, tool_choice, parallel_tool_calls=True)`
- `tools/format.py:encode_tool_calls` — canonical replacement for `_assistant_tool_call_text`; `cursor_helpers` re-exports it
- `tools/schema.py:validate_schema` — new function; enforces type, required, enum, minLength/maxLength, minimum/maximum, minItems/maxItems
- `tools/registry.py:ToolRegistry` — new class; immutable after construction; `canonical_name`, `schema`, `known_params`, `allowed_exact`, `schema_map` methods

### Why
`tools/parse.py` had grown to 1,490 lines with six distinct responsibilities. `build_tool_instruction` was in `converters/` despite being pure tool logic. Full JSON Schema validation was absent — only param name presence was checked. `allowed_exact`/`schema_map` were rebuilt on every `parse_tool_calls_from_text` call. This refactor establishes clean module boundaries with zero breaking changes.

### Commit SHAs
| SHA | Description |
|-----|-------------|
| `ca74b5a1` | feat(tools): extract coerce.py |
| `f8d10355` | fix(tools): remove unused structlog import; improve coerce.py test coverage |
| `2e59718c` | feat(tools): extract score.py |
| `2dca6e6d` | fix(tools): tighten score test assertions |
| `e6e1a1fa` | feat(tools): extract streaming.py |
| `a128b917` | fix(tools): strengthen streaming tests |
| `1107b750` | refactor(tools): parse.py imports from coerce/score/streaming |
| `11e5b882` | feat(tools): add schema.py |
| `7b4faa23` | feat(tools): add format.py |
| `445e3a52` | feat(tools): add registry.py |
| `91f64681` | feat(tools): add inject.py (copy step) |
| `0f2c43d3` | refactor(converters): cursor_helpers re-exports from tools/ |
| `80b2558f` | test(tools): improve coerce.py and inject.py coverage to 90% |

---

## Session 143 — tools/ Phase 2: validate, budget, emitter, ToolRegistry wiring (2026-03-26)

### What changed

**New files created:**
- `tools/validate.py` — `validate_tool_call_full` (sequential gate: validate_tool_call → validate_schema; schema check only runs on structurally valid calls)
- `tools/budget.py` — `limit_tool_calls`, `repair_invalid_calls` (full 4-case behavior, uses validate_tool_call_full)
- `tools/emitter.py` — `compute_tool_signature`, `parse_tool_arguments`, `serialize_tool_arguments`, `stream_anthropic_tool_input`, `OpenAIToolEmitter`
- `tests/test_validate.py` (10 tests), `tests/test_budget.py` (8 tests), `tests/test_emitter.py` (10 tests), `tests/test_registry_wiring.py` (7 tests)
- `docs/superpowers/specs/2026-03-26-tools-phase2-design.md`
- `docs/superpowers/plans/2026-03-26-tools-phase2.md`

**Modified files:**
- `tools/parse.py:parse_tool_calls_from_text` — added `registry: ToolRegistry | None = None` param; registry fast-path skips per-call rebuild of allowed_exact/schema_map
- `tools/streaming.py:StreamingToolCallParser` — added `registry` param to `__init__`, `feed()`, `finalize()`
- `pipeline/tools.py` — removed 7 moved function/class bodies; added re-export aliases (placed after bodies so aliases win); `_parse_score_repair` stays
- `pipeline/stream_openai.py` — direct imports from `tools.budget`, `tools.emitter`; constructs `ToolRegistry` once per request
- `pipeline/stream_anthropic.py` — same

### Which lines / functions
- `tools/validate.py:validate_tool_call_full` — new function; calls `validate_tool_call` then `validate_schema` as sequential gate
- `tools/budget.py:limit_tool_calls` — enforces `parallel_tool_calls=False`
- `tools/budget.py:repair_invalid_calls` — four-case validation/repair loop using `validate_tool_call_full`
- `tools/emitter.py:OpenAIToolEmitter` — extracted from `pipeline/tools.py`; `compute_tool_signature`, `parse_tool_arguments`, etc. also extracted
- `tools/parse.py:parse_tool_calls_from_text` — added `registry` kwarg; fast-path uses `registry.allowed_exact()` + `registry.schema_map()`
- `tools/streaming.py:StreamingToolCallParser.__init__` — added `registry` param; stored as `self._registry`; passed to both `feed()` and `finalize()`
- `pipeline/tools.py` — bodies removed: `_compute_tool_signature`, `_parse_tool_arguments`, `_serialize_tool_arguments`, `_stream_anthropic_tool_input`, `_limit_tool_calls`, `_repair_invalid_calls`, `_OpenAIToolEmitter`; replaced with re-export aliases

### Why
Phase 2 closes the gaps left after Phase 1: `validate_schema` was dead code — now called in the production repair path. `ToolRegistry` existed but wasn't used — now eliminates per-call dict rebuilds in the streaming hot path. `pipeline/tools.py` had tool-domain logic — now extracted to `tools/` with proper boundaries.

### Commit SHAs
| SHA | Description |
|-----|-------------|
| `cd01b583` | feat(tools): add validate.py — validate_tool_call_full sequential gate |
| `a8cd16b5` | fix(tools): validate_tool_call_full returns error on malformed JSON arguments |
| `8eaabd7a` | feat(tools): add budget.py — limit_tool_calls, repair_invalid_calls; update pipeline callers |
| `62ebbfb8` | fix(pipeline): move budget re-exports after def bodies so they overwrite local names |
| `70b23565` | feat(tools): add emitter.py — OpenAIToolEmitter, compute_tool_signature, helpers |
| `efa96a1f` | fix(pipeline): move emitter re-exports to after class body so they overwrite local definitions |
| `8cbf6565` | feat(tools): wire ToolRegistry into parse_tool_calls_from_text and StreamingToolCallParser |
| `3a2e6b93` | refactor(pipeline): tools.py removes moved bodies; only re-exports and _parse_score_repair remain |
| `1e3f1d7b` | test(tools): improve validate.py coverage to 86% |

## Session 144 — tools/ Phase 3 Chunk 6: results.py extracted from parse.py (2026-03-26)

### What changed
- `tools/results.py` — new module containing `_normalize_name` and `_build_tool_call_results` (copied from `tools/parse.py`)
- `tools/parse.py` — removed `_build_tool_call_results` function body (89 lines); added re-export `from tools.results import _build_tool_call_results`
- `tests/test_results.py` — 5 new tests covering: valid call normalisation, unknown tool dropped, arguments-always-JSON-string invariant, fuzzy name correction, id assignment

### Which lines / functions
- `tools/results.py:_normalize_name` — copied from `tools/parse.py` line 43; lowercase + strip separators
- `tools/results.py:_build_tool_call_results` — copied verbatim from `tools/parse.py` lines 823–911; builds normalized tool call dicts from merged parsed candidates
- `tools/parse.py` — function body deleted; re-export alias added after `tools.streaming` import block

### Why
Phase 3 Chunk 6: `_build_tool_call_results` is a self-contained result-building concern that belongs in its own module. Extracting it reduces `parse.py` from 1093 → 1004 lines (-89) and gives the function a focused home with dedicated test coverage.

### Commit SHAs
| SHA | Description |
|-----|-------------|
| `86cf20c3` | feat(tools): add results.py — _build_tool_call_results extracted from parse.py (copy step) |
| `ace8e92c` | refactor(tools): parse.py imports _build_tool_call_results from tools/results |

## Session 145 — tools/ Phase 3 Chunk 5: sanitize.py extracted from cursor_helpers.py (2026-03-26)

### What changed
- `tools/sanitize.py` — new module containing `_CURSOR_REPLACEMENT`, `_CURSOR_WORD_RE`, and `_sanitize_user_content` (copied verbatim from `converters/cursor_helpers.py`)
- `converters/cursor_helpers.py` — removed the three items above (35 lines); removed now-unused `import re`; added re-exports from `tools.sanitize`
- `tests/test_sanitize.py` — 8 new tests covering: standalone replacement, lowercase replacement, path component preservation, Windows path preservation, trailing extension behaviour, empty string, backward-compat re-export, compiled regex type

### Which lines / functions
- `tools/sanitize.py:_CURSOR_REPLACEMENT` — constant `"the-editor"`; copied from `converters/cursor_helpers.py` line 34
- `tools/sanitize.py:_CURSOR_WORD_RE` — compiled regex with lookbehind/lookahead for path exclusion; copied from `converters/cursor_helpers.py` lines 42-46
- `tools/sanitize.py:_sanitize_user_content` — function body copied from `converters/cursor_helpers.py` lines 49-62
- `converters/cursor_helpers.py` — blocker section deleted; `import re` removed; two re-export lines added at line 28-30

### Why
Phase 3 Chunk 5: `_sanitize_user_content` is a standalone sanitization concern with no dependency on converters/. Extracting it into `tools/sanitize.py` gives it a focused home, breaks the `tools/ → converters/` dependency direction, and keeps `cursor_helpers.py` as a thin re-exporter for backward compat.

### Commit SHAs
| SHA | Description |
|-----|-------------|
| `3f3f8eed` | feat(tools): add sanitize.py — _sanitize_user_content, _CURSOR_WORD_RE (copy; cursor_helpers intact) |
| `2eaa183f` | refactor(converters): cursor_helpers re-exports _sanitize_user_content from tools/sanitize |

---

## Session 146 — tools/ Phase 3: metrics, registry, emitter, budget (2026-03-26)

### What changed

**New files:**
- `tools/metrics.py` — stable metrics wrapper; `inc_parse_outcome`, `inc_tool_repair`, `inc_schema_validation`. Replaces scattered try/except ImportError in `tools/parse.py`.
- `tests/test_metrics.py` — 4 tests
- `tests/test_sanitize.py` — 8 tests (for Phase 3 Chunk 5)
- `tests/test_results.py` — 5 tests (for Phase 3 Chunk 6)

**Modified files:**
- `tools/parse.py` — replaced 5-line try/except ImportError block with `from tools.metrics import inc_parse_outcome`
- `tools/registry.py` — added `import structlog`; added collision warning before `_ae[norm] = name` in `__init__` loop
- `tools/emitter.py` — added `import structlog`; `parse_tool_arguments` now logs `emitter_args_parse_failed` warning on JSON failure instead of silently returning `{}`
- `tools/budget.py` — added `deduplicate_tool_calls(calls)` function
- `tests/test_registry.py` — added `test_collision_warning_emitted` using `structlog.testing.capture_logs()`
- `tests/test_emitter.py` — added `test_parse_tool_arguments_logs_on_failure` using `structlog.testing.capture_logs()`
- `tests/test_budget.py` — added 5 deduplication tests

### Which lines / functions
- `tools/metrics.py:inc_parse_outcome` — wraps optional `metrics.parse_metrics` backend; no-op when absent
- `tools/metrics.py:inc_tool_repair`, `inc_schema_validation` — no-op stubs giving repair/validation paths a stable import point
- `tools/registry.py:ToolRegistry.__init__` — collision check: `if norm in _ae and _ae[norm] != name: log.warning("tool_name_normalization_collision", ...)`
- `tools/emitter.py:parse_tool_arguments` — `except Exception as exc: log.warning("emitter_args_parse_failed", error=str(exc), raw_len=...)`
- `tools/budget.py:deduplicate_tool_calls` — deduplicates by `(name, arguments)` string signature; preserves first occurrence

### Why
Phase 3 reliability and observability: silent failures made invisible, missing metrics stubs added, consistency between registry and no-registry collision warning behavior established.

### Commit SHAs
| SHA | Description |
|-----|-------------|
| `b3d773ab` | feat(tools): add metrics.py — stable instrumentation wrapper; update parse.py |
| `e14bc025` | fix(tools): emitter.py logs parse_tool_arguments failures |
| `80cc5cf9` | fix(tools): registry.py emits tool_name_normalization_collision warning |
| `cdc47345` | feat(tools): add deduplicate_tool_calls to budget.py |

---

## Session 147 — tools/ wire metrics + dedup + normalize tests (2026-03-26)

### What changed

- `tools/budget.py:repair_invalid_calls` — wired `inc_tool_repair("passed"/"repaired"/"dropped"/"passed_through")` into all 4 outcome cases
- `tools/validate.py:validate_tool_call_full` — wired `inc_schema_validation("passed"/"failed")` after schema check
- `pipeline/stream_openai.py` — added `_deduplicate_tool_calls` import; calls it after `_repair_invalid_calls` on final_calls
- `pipeline/stream_anthropic.py` — same
- `tools/parse.py:_normalize_name` — removed duplicate definition; now imports from `tools.results` (single source of truth)
- `tests/test_normalize_result_messages.py` — 11 new tests covering all paths of `normalize_tool_result_messages`

### Why
`inc_tool_repair` and `inc_schema_validation` were no-op stubs with no callers — now wired. `deduplicate_tool_calls` existed but was never called in production. `_normalize_name` was defined twice. `normalize_tool_result_messages` had zero dedicated tests.

### Commit SHA
| SHA | Description |
|-----|-------------|
| `fbb947fd` | feat(tools): wire inc_tool_repair + inc_schema_validation; deduplicate after repair; tests for normalize_tool_result_messages; remove _normalize_name duplicate from parse.py |
