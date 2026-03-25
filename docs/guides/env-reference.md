# Environment Variable Reference

All variables have sensible defaults unless marked **REQUIRED**.

> **Note:** All `SHINWAY_*` variables were previously prefixed `GATEWAY_*`. Update any old `.env` files.

---

## Server

| Variable | Default | Description |
|---|---|---|
| `HOST` | `0.0.0.0` | Bind address |
| `PORT` | `4000` | Listen port (local). Docker/Railway default is `8080` — set via env. |
| `LOG_LEVEL` | `info` | `debug` \| `info` \| `warning` \| `error` |
| `DEBUG` | `false` | FastAPI debug mode. **Never enable in production** — disables master key guard. |
| `WORKERS` | `1` | Instance count for `multirun.py`. Set equal to number of Cursor cookies for best throughput. |

---

## Auth

| Variable | Default | Description |
|---|---|---|
| `LITELLM_MASTER_KEY` | **REQUIRED** | Master API key. Clients send `Authorization: Bearer <key>`. Startup fails if this equals `sk-local-dev` and `DEBUG=false`. |
| `SHINWAY_API_KEYS` | _(empty)_ | Additional virtual keys in `key:label` format, comma-separated. e.g. `sk-agent-1:roocode,sk-agent-2:kilocode` |
| `SHINWAY_BUDGET_USD` | `0.0` | Global spend cap in USD. `0` = unlimited. |

### Managed keys (DB-based)

Keys can also be created and managed at runtime via the admin API (`POST /v1/admin/keys`). DB keys support per-key RPM/RPS limits, daily token caps, USD budgets, and model allowlists — configurable without restart.

---

## Cursor upstream

| Variable | Default | Description |
|---|---|---|
| `CURSOR_COOKIE` | **REQUIRED** | Single Cursor session cookie. Full value: `WorkosCursorSessionToken=<token>` |
| `CURSOR_COOKIES` | _(empty)_ | Multiple cookies for round-robin pool, comma or newline separated. Each entry is the full `WorkosCursorSessionToken=<token>` string. |
| `CURSOR_BASE_URL` | `https://cursor.com` | Cursor API base URL |
| `CURSOR_AUTH_HEADER` | _(empty)_ | Alternative auth header (advanced use only) |
| `CURSOR_CONTEXT_FILE_PATH` | `/workspace/project` | Context path sent to Cursor. Keeps requests away from `/docs` scoping. |
| `CURSOR_CONTEXT_FILE_PATH_TOOLS` | `/workspace/project` | Context path used when tools are present. |

### Getting your Cursor cookie

1. Log in to [cursor.com](https://cursor.com) in your browser
2. Open DevTools (`F12`) → **Application** tab → **Cookies** → `https://cursor.com`
3. Find `WorkosCursorSessionToken` and copy the full value
4. Set: `CURSOR_COOKIE=WorkosCursorSessionToken=<paste-here>`

### Multi-cookie pool

For higher throughput, add multiple accounts:
```
CURSOR_COOKIES=WorkosCursorSessionToken=token1...,WorkosCursorSessionToken=token2...
```
Set `WORKERS` to match the number of cookies. The proxy round-robins across credentials with automatic circuit-breaking on failures.

---

## Retry

| Variable | Default | Description |
|---|---|---|
| `SHINWAY_RETRY_ATTEMPTS` | `2` | Max upstream retry attempts per request |
| `SHINWAY_RETRY_BACKOFF_SECONDS` | `0.6` | Backoff multiplier (attempt × backoff seconds) |

---

## Cache — L1 (in-memory)

| Variable | Default | Description |
|---|---|---|
| `SHINWAY_CACHE_ENABLED` | `true` | Enable response caching |
| `SHINWAY_CACHE_TTL_SECONDS` | `45` | Cache entry TTL in seconds |
| `SHINWAY_CACHE_MAX_ENTRIES` | `500` | Max L1 entries (LRU eviction) |
| `SHINWAY_CACHE_TOOL_REQUESTS` | `false` | Cache tool-call responses? Default off — tool results should always be fresh. |

---

## Cache — L2 (Redis)

Optional. Enable via Docker Compose `--profile redis` or set env vars manually.

| Variable | Default | Description |
|---|---|---|
| `SHINWAY_CACHE_L2_ENABLED` | `false` | Enable Redis L2 cache |
| `SHINWAY_REDIS_URL` | `redis://localhost:6379/0` | Redis connection URL. Docker Compose default: `redis://redis:6379/0` |

---

## Rate Limiting

Global limits apply to all keys. Per-key limits are set via the admin API and stored in `keys.db`.

| Variable | Default | Description |
|---|---|---|
| `SHINWAY_RATE_LIMIT_RPS` | `0` | Global max requests per second per key. `0` = unlimited. |
| `SHINWAY_RATE_LIMIT_RPM` | `0` | Global max requests per minute per key. `0` = unlimited. |
| `SHINWAY_RATE_LIMIT_BURST` | `100` | Burst allowance above rate limit |

---

## Stream Timeouts

| Variable | Default | Description |
|---|---|---|
| `SHINWAY_FIRST_TOKEN_TIMEOUT` | `180` | Seconds to wait for the first token before timing out |
| `SHINWAY_IDLE_CHUNK_TIMEOUT` | `60` | Seconds allowed between chunks before stream is considered stalled |
| `SHINWAY_STREAM_HEARTBEAT_INTERVAL` | `15` | Heartbeat check interval in seconds |

---

## Context Window

| Variable | Default | Description |
|---|---|---|
| `SHINWAY_MAX_CONTEXT_TOKENS` | `1000000` | Soft token limit — triggers context trimming when exceeded |
| `SHINWAY_HARD_CONTEXT_LIMIT` | `1100000` | Hard token limit — requests above this are rejected with 400 |
| `SHINWAY_TRIM_CONTEXT` | `true` | Automatically trim old messages when context is too large |
| `SHINWAY_TRIM_PRESERVE_TOOL_RESULTS` | `true` | Never trim tool result messages (tool call/result pairs are atomic) |
| `SHINWAY_TRIM_MIN_KEEP_MESSAGES` | `4` | Minimum number of messages to always keep |
| `SHINWAY_CONTEXT_HEADROOM` | `8000` | Token headroom reserved for the model's output |

---

## Request Limits

| Variable | Default | Description |
|---|---|---|
| `SHINWAY_MAX_REQUEST_BODY_BYTES` | `33554432` | Max request body size in bytes (default 32 MB). `0` = unlimited. |
| `SHINWAY_MAX_TOOLS` | `64` | Max tools allowed per request. Requests with more tools return 400. |

---

## Tool Behaviour

| Variable | Default | Description |
|---|---|---|
| `SHINWAY_DISABLE_PARALLEL_TOOLS` | `false` | Force single tool call per turn (overrides client `parallel_tool_calls`) |
| `SHINWAY_TOOL_RETRY_ON_MISS` | `true` | Retry if `tool_choice=required` but no tool call was returned |

---

## Model Routing

| Variable | Default | Description |
|---|---|---|
| `SHINWAY_MODEL_MAP` | _(see below)_ | JSON map of model name aliases sent by clients → actual model IDs |

Default model map:
```json
{
  "gpt-4o": "cursor-small",
  "gpt-4": "cursor-small",
  "claude-3-5-sonnet-20241022": "anthropic/claude-sonnet-4.6",
  "claude-3-5-sonnet": "anthropic/claude-sonnet-4.6",
  "claude-3-opus": "anthropic/claude-opus-4.6",
  "claude-3-haiku": "anthropic/claude-haiku-4.6"
}
```

---

## Role Override

Injects a developer identity message before the conversation to prevent Cursor's built-in support assistant persona from firing.

| Variable | Default | Description |
|---|---|---|
| `SHINWAY_ROLE_OVERRIDE_ENABLED` | `true` | Enable role override injection |
| `SHINWAY_ROLE_OVERRIDE_PROMPT` | _(workspace prompt)_ | The injected context message content |

---

## System Prompts

> The main `system_prompt` is **not** configurable via env var by design — it is hardcoded in `config.py` to prevent upstream keyword filtering from stripping it. Edit `config.py` directly to change it.

| Variable | Default | Description |
|---|---|---|
| `SHINWAY_TOOL_SYSTEM_PROMPT` | _(tool format prompt)_ | Additional system prompt injected when tools are present. Controls `[assistant_tool_calls]` format instructions. |

---

## Logging

| Variable | Default | Description |
|---|---|---|
| `SHINWAY_LOG_REQUEST_BODIES` | `false` | Log full request bodies. **Warning: logs sensitive data including prompts and tokens.** |

---

## Prometheus Metrics

| Variable | Default | Description |
|---|---|---|
| `SHINWAY_METRICS_ENABLED` | `false` | Enable Prometheus `/metrics` endpoint |
| `SHINWAY_METRICS_PATH` | `/metrics` | Path for the metrics endpoint |

---

## MCP Gateway

| Variable | Default | Description |
|---|---|---|
| `SHINWAY_MCP_SERVERS` | `[]` | JSON array of MCP server configs: `[{"name":"filesystem","url":"http://..."}]` |

---

## Pricing (cost estimation only)

Used for the analytics ring buffer and per-key budget tracking. Does not affect billing.

| Variable | Default | Description |
|---|---|---|
| `SHINWAY_PRICE_ANTHROPIC_PER_1K` | `0.015` | Estimated cost per 1k tokens for Anthropic models (USD) |
| `SHINWAY_PRICE_OPENAI_PER_1K` | `0.01` | Estimated cost per 1k tokens for OpenAI models (USD) |

---

## User-Agent

| Variable | Default | Description |
|---|---|---|
| `USER_AGENT` | Chrome 146 Windows UA | User-Agent string sent to Cursor API. Used for browser fingerprinting. Change only if Cursor starts rejecting requests. |

---

## Minimum .env

```env
LITELLM_MASTER_KEY=sk-your-secret-key
CURSOR_COOKIE=WorkosCursorSessionToken=your-token-here
```

## Multi-cookie .env

```env
LITELLM_MASTER_KEY=sk-your-secret-key
CURSOR_COOKIES=WorkosCursorSessionToken=token1...,WorkosCursorSessionToken=token2...
WORKERS=2
```
