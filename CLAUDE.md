# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

Shinway is a FastAPI reverse proxy that translates between OpenAI-compatible API requests and Cursor.com's internal SSE streaming format. Clients send standard OpenAI or Anthropic API requests; the proxy converts them, forwards to the-editor's `/api/chat` endpoint, and streams responses back. The key challenge is bypassing the-editor's built-in Support Assistant identity suppression while preserving full tool call and streaming fidelity.

## Commands

```bash
# Install
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Run (single instance)
python run.py

# Run (multi-instance, 3 workers on 4001-4003)
python multirun.py

# Run tests (unit only, no live server required)
pytest tests/ -m 'not integration'

# Run a single test file
pytest tests/test_parse.py -v

# Run a single test by name
pytest tests/test_parse.py::test_lenient_json_loads -v

# Run with live server (integration)
pytest tests/ -m integration

# Admin UI (Next.js 16, port 3000)
cd admin-ui && npm install && npm run dev

# Docker
docker compose up -d
```

Minimum `.env` to run:
```
LITELLM_MASTER_KEY=sk-your-key
CURSOR_COOKIE=WorkosCursorSessionToken=...
```

Multi-cookie pool (round-robin across accounts):
```
CURSOR_COOKIES=WorkosCursorSessionToken=token1...,WorkosCursorSessionToken=token2...
```

## Architecture

### Request flow

```
Client (OpenAI or Anthropic format)
  → routers/unified.py       — auth, rate limit, idempotency, format detection
  → validators/request.py    — strict input validation with 400 errors
  → converters/to_cursor.py  — convert messages + tools → the-editor format
                               inject system prompt, role override, tool instruction block
  → cursor/client.py         — HTTP/2 POST to the-editor/api/chat with credential pool
  → cursor/sse.py            — parse raw SSE deltas from upstream
  → pipeline/                — orchestrate streaming, tool call detection, suppression retry
  → converters/from_cursor.py — convert delta chunks → OpenAI or Anthropic SSE format
  → Client
```

### Key files

| File | Role |
|---|---|
| `pipeline/` | Core streaming orchestration — split into 7 focused modules (see below). |
| `pipeline/params.py` | `PipelineParams` dataclass — all parameters for a single request. |
| `pipeline/suppress.py` | Suppression constants, `_is_suppressed()`, `_call_with_retry()`, `_with_appended_cursor_message()`. |
| `pipeline/tools.py` | Tool call helpers: `_OpenAIToolEmitter`, `_parse_score_repair()`, `_limit_tool_calls()`, `_repair_invalid_calls()`. |
| `pipeline/stream_openai.py` | `_openai_stream` — OpenAI SSE hot path. Handles tool call detection, suppression retry, stream holdback, reasoning extraction. |
| `pipeline/stream_anthropic.py` | `_anthropic_stream` — Anthropic SSE hot path. |
| `pipeline/nonstream.py` | `handle_openai_non_streaming()`, `handle_anthropic_non_streaming()`. |
| `pipeline/record.py` | `_record()` — analytics recording. `_provider_from_model()`. |
| `pipeline/__init__.py` | Re-exports all public names — `from pipeline import PipelineParams, _openai_stream, ...` works unchanged. |
| `converters/to_cursor.py` | Converts OpenAI/Anthropic request → the-editor format. Builds system prompt, role override, and tool instruction block. Contains `_build_system_prompt()`, `_build_role_override()`, `build_tool_instruction()`, `openai_to_cursor()`, `anthropic_to_cursor()`, `anthropic_messages_to_openai()`. |
| `converters/from_cursor.py` | Converts the-editor SSE deltas → OpenAI/Anthropic chunks. Contains `sanitize_visible_text()`, `split_visible_reasoning()`, `scrub_support_preamble()`. |
| `config.py` | All settings via pydantic-settings. System prompt is hardcoded as `default=` (no env override). All `SHINWAY_*` env vars are declared here. |
| `tools/parse.py` | Tool call parsing from streamed text. Strategies 1-4 handle strict JSON → repaired JSON → regex extraction → truncated stream recovery. Also contains `repair_tool_call()`, `validate_tool_call()`, `StreamingToolCallParser`. |
| `cursor/credentials.py` | Credential pool with round-robin. `CredentialPool` singleton, `CircuitBreaker` per credential, parses JWT for `workos_id`, derives stable UUIDs for browser fingerprint cookies. |
| `cursor/client.py` | HTTP/2 client with Datadog RUM headers and browser fingerprinting. `CursorClient.stream()` retries on timeout/connection errors with exponential backoff. |
| `utils/context.py` | `ContextEngine` — token budget management. `trim_to_budget()` preserves tool call/result pairs atomically. `check_preflight()` raises `ContextWindowError` when hard limit is exceeded. |
| `routers/unified.py` | OpenAI (`/v1/chat/completions`), Anthropic (`/v1/messages`, `/v1/messages/count_tokens`), legacy (`/v1/completions`), and tool validator (`/v1/tools/validate`) endpoints. |
| `routers/responses.py` | Stateful Responses API (`/v1/responses`) with SQLite persistence via `storage/responses.py`. |
| `routers/internal.py` | Internal admin endpoints: `/internal/health`, `/internal/credentials`, `/internal/cache/clear`, `/internal/logs`. API key CRUD at `/v1/admin/keys`. Health endpoints (`/health`, `/health/live`, `/health/ready`) are intentionally unauthenticated — used by Railway/Docker probes. |
| `routers/model_router.py` | `resolve_model()` — maps client model names to actual the-editor model IDs via `SHINWAY_MODEL_MAP`. |
| `middleware/auth.py` | `verify_bearer()` / `check_budget()` (both async). Checks `LITELLM_MASTER_KEY`, `SHINWAY_API_KEYS` env list, and `KeyStore` DB-managed keys. |
| `middleware/rate_limit.py` | Global token-bucket rate limiter (`enforce_rate_limit`) + per-key limiter (`enforce_per_key_rate_limit`). |
| `middleware/idempotency.py` | In-memory idempotency via `X-Idempotency-Key` header. `get_or_lock` / `complete` / `release`. |
| `storage/keys.py` | `KeyStore` — aiosqlite CRUD for managed API keys (`keys.db`). WAL mode. Fields: label, rpm_limit, rps_limit, token_limit_daily, budget_usd, allowed_models, is_active. |
| `storage/responses.py` | `ResponseStore` — aiosqlite store for Responses API objects (`responses.db`). WAL mode. |
| `analytics.py` | `analytics` singleton — in-memory request log ring buffer with cost estimation. Consumed by `/internal/logs`. |
| `app.py` | FastAPI factory `create_app()`. Lifespan: initialises httpx client, `response_store`, `key_store`. Registers body-size-limit middleware (32 MB default), gzip, request_id, exception handlers. |
| `tokens.py` | Token counting via tiktoken/litellm. `count_message_tokens()`, `estimate_from_text()`, `context_window_for()`. |

### Suppression bypass

The-editor's backend injects a Support Assistant persona that blocks general-purpose use. The proxy bypasses this via:
1. `_build_system_prompt()` — frames the session as a developer workspace (natural language, no override keywords)
2. `_build_role_override()` — targeted identity reset using the-editor's own suppression phrases
3. Fake assistant/user turn injected before the real conversation (required — do not remove)
4. `_STREAM_ABORT_SIGNALS` in `pipeline/suppress.py` — detects suppression mid-stream and retries with rotated credentials

### Tool calls

The-editor outputs tool calls as `[assistant_tool_calls]\n{"tool_calls": [...]}` in the text stream (not native function calling). `tools/parse.py` extracts them with 4 fallback strategies. After parsing, `repair_tool_call()` fuzzy-matches wrong param names and coerces wrong value types before returning to the client. `StreamingToolCallParser` handles incremental parsing during streaming.

### System prompt

`config.py` contains the full system prompt as a Python string literal. It is **not overridable via env var** (no `alias=` on the field). To change it, edit `config.py` directly. The prompt uses natural LLM-native language to avoid upstream keyword filtering.

### Caching

Two-level: L1 `cachetools.TTLCache` (in-process, `cache.py`), L2 Redis (optional, `SHINWAY_CACHE_L2_ENABLED=true`). Cache key = SHA-256 of normalized request. Tool call requests bypass cache by default (`SHINWAY_CACHE_TOOL_REQUESTS=false`).

### Admin UI

Next.js 16 App Router in `admin-ui/`. Stack: Tailwind v4, shadcn/ui, Recharts, SWR, TanStack Table v8, Framer Motion, Axios, React 19. Theme: dark glassmorphism — `#090910` bg, `#00e5a0` accent. All API calls proxy through `admin-ui/app/api/` Next.js route handlers which forward to the FastAPI backend (default `http://localhost:4001`) using the `x-admin-token` header from `localStorage`.

## Critical invariants

- `cursor_messages` must always be built before any stream/cache branch in `pipeline/stream_openai.py` and `pipeline/stream_anthropic.py`
- Tool call/result pairs are treated atomically in context trimming — never split
- `arguments` in tool calls is always a JSON string (never a dict) when returned to clients
- The fake assistant/user prefix in `to_cursor.py` is load-bearing — removing it breaks suppression bypass
- System prompt must avoid: OVERRIDE, CRITICAL, IMPORTANT, IDENTITY RESET, "You are NOT" — these trigger upstream rejection
- `KeyStore.update()` validates field names against `_ALLOWED_UPDATE_FIELDS` whitelist before interpolating into SQL
- `verify_bearer` and `check_budget` are async — must be `await`ed everywhere they are called

## Rules — always enforced

The following rule files in `.claude/rules/` are **always active** and must be followed for every task in this project, no exceptions:

| Rule file | Scope |
|---|---|
| `python-fastapi.md` | All Python files — FastAPI patterns, async, Pydantic, RORO, security |
| `nextjs-typescript.md` | All admin-ui TypeScript/TSX files — Next.js App Router, SWR, Tailwind, shadcn/ui |
| `api-design.md` | All route handlers and Next.js API routes — HTTP methods, status codes, resource naming |
| `security.md` | All Python files — secrets, SQL safety, auth enforcement, input validation |
| `testing.md` | All test files — pytest, async tests, coverage ≥ 80%, TDD workflow |
| `performance.md` | All Python files — streaming hot paths, caching, rate limit |
| `coding-style.md` | All Python and TypeScript files — immutability, function size, error handling |
| `docker.md` | Dockerfile, docker-compose.yml — container hygiene, env vars, port mapping |
| `git-workflow.md` | All commits — conventional commit format, UPDATES.md requirement |
| `style.md` | All TypeScript files — TypeScript type system, naming, patterns |

Before writing any code, confirm which rule files apply to the files being modified and follow them exactly.

## File writing rules

- Max 170 lines per Write tool call for TSX files
- Max 200 lines per Write for plain TS/JS
- For larger components, write structure first, then fill each section with Edit
- Prefer splitting large components into smaller sub-components rather than one big file

## Playwright screenshots

When using Playwright (browser automation, E2E tests, or any browser interaction), always save screenshots to `/teamspace/studios/this_studio/wiwi/testpng/`. Use the `mcp__plugin_playwright_playwright__browser_take_screenshot` tool with a filename under that directory.

## After every completed task

Update `UPDATES.md` at the end of every task or work session. The entry must document:

1. **What changed** — which files were modified, created, or deleted
2. **Which lines / functions** — specific file paths and function/class names affected (e.g. `pipeline/params.py:PipelineParams`, `routers/unified.py:chat_completions`)
3. **Why** — the root cause or motivation (bug fix, gap found in audit, spec requirement, performance issue, etc.)
4. **Commit SHAs** — one row per commit with its hash and description

Format: add a new `## Session N — <title> (Date)` section at the bottom of `UPDATES.md`. Use the existing sessions as style reference. Commit and push `UPDATES.md` as the final step of every session.