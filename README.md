<div align="center">

```
███████╗██╗  ██╗██╗███╗   ██╗██╗    ██╗ █████╗ ██╗   ██╗
██╔════╝██║  ██║██║████╗  ██║██║    ██║██╔══██╗╚██╗ ██╔╝
███████╗███████║██║██╔██╗ ██║██║ █╗ ██║███████║ ╚████╔╝
╚════██║██╔══██║██║██║╚██╗██║██║███╗██║██╔══██║  ╚██╔╝
███████║██║  ██║██║██║ ╚████║╚███╔███╔╝██║  ██║   ██║
╚══════╝╚═╝  ╚═╝╚═╝╚═╝  ╚═══╝ ╚══╝╚══╝╚═╝  ╚═╝   ╚═╝
```

**High-performance OpenAI-compatible API gateway powered by Cursor.com**

[![Python](https://img.shields.io/badge/Python-3.12+-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-latest-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Redis](https://img.shields.io/badge/Redis-L2_Cache-DC382D?style=flat-square&logo=redis&logoColor=white)](https://redis.io)
[![License](https://img.shields.io/badge/License-MIT-22c55e?style=flat-square)](LICENSE)

</div>

---

## What is Shinway?

Shinway is a local API proxy that sits between your AI coding tools and Cursor.com's backend. Send standard OpenAI or Anthropic format requests and get access to Claude Opus, Claude Sonnet, GPT-4o, Gemini, and other frontier models — no separate API keys required.

```
┌──────────────────────┐       ┌─────────────────────┐       ┌─────────────────────┐
│  Your App            │       │  Shinway            │       │  Cursor.com         │
│                      │       │                     │       │                     │
│  OpenAI SDK    ──────┼──────▶│  FastAPI proxy ─────┼──────▶│  Claude Opus 4.6    │
│  Roo Code      ◀─────┼───────┼─ Streaming SSE ◀────┼───────│  Claude Sonnet 4.6  │
│  Continue.dev        │       │  Tool repair        │       │  GPT-4o / o3        │
│  LiteLLM             │       │  Redis cache        │       │  Gemini 2.5 Pro     │
└──────────────────────┘       └─────────────────────┘       └─────────────────────┘
```

---

## Features

| Feature | Details |
|---|---|
| **OpenAI-compatible** | Drop-in for `/v1/chat/completions`, `/v1/models`, `/v1/responses` |
| **Anthropic-compatible** | `/v1/messages` with streaming and tool calls |
| **Full streaming** | Real-time SSE with per-token delivery |
| **Tool calls** | Parallel tools, smart argument repair, confidence scoring |
| **Stateful Responses API** | `previous_response_id` multi-turn with SQLite persistence |
| **Credential pool** | Round-robin across multiple Cursor accounts with circuit breaker |
| **Two-level cache** | L1 in-memory TTLCache + optional Redis L2 |
| **Context management** | Auto-trim to 1M token soft limit, 1.1M hard limit |
| **API key management** | Per-key RPM/RPS/token/budget limits via SQLite + Admin UI |
| **Rate limiting** | Per-key RPS/RPM with burst allowance |
| **Idempotency** | `X-Idempotency-Key` header deduplication |
| **Prometheus metrics** | Optional `/metrics` endpoint |
| **Admin UI** | Next.js 16 dashboard for keys, credentials, logs, cache |

---

## Quick Start

### Option A — Local (Python)

```bash
# 1. Clone
git clone https://github.com/shinmentakezo07/shinway.git
cd shinway

# 2. Install
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 3. Configure — minimum required
echo 'LITELLM_MASTER_KEY=sk-your-key' >> .env
echo 'CURSOR_COOKIE=WorkosCursorSessionToken=...' >> .env

# 4. Run
python run.py
```

### Option B — Docker Compose

```bash
git clone https://github.com/shinmentakezo07/shinway.git
cd shinway
# Edit .env with your credentials
docker compose up -d
```

### Option C — Multi-instance

```bash
# Start 3 workers on ports 4001–4003
python multirun.py 3
```

Each worker is an independent process with its own credential slot. Use one cookie per worker for maximum throughput.

### Verify

```bash
curl http://localhost:4001/health
# {"ok": true}

curl http://localhost:4001/v1/chat/completions \
  -H "Authorization: Bearer sk-your-key" \
  -H "Content-Type: application/json" \
  -d '{"model": "gpt-4o", "messages": [{"role": "user", "content": "Hello!"}]}'
```

---

## Getting Your Cursor Cookie

1. Open [cursor.com](https://cursor.com) and log in
2. Press `F12` → **Application** → **Cookies** → `https://cursor.com`
3. Find `WorkosCursorSessionToken` and copy the full value
4. Add to `.env`:

```env
CURSOR_COOKIE=WorkosCursorSessionToken=user_01YOUR_TOKEN_HERE
```

### Multiple accounts (round-robin pool)

```env
CURSOR_COOKIES=WorkosCursorSessionToken=token1,WorkosCursorSessionToken=token2
WORKERS=2
```

Each worker uses a different cookie — N cookies = N× the rate limit.

---

## Supported Models

| Model ID | Provider | Notes |
|---|---|---|
| `anthropic/claude-opus-4-6` | Anthropic | Best reasoning |
| `anthropic/claude-sonnet-4-6` | Anthropic | Fast and capable |
| `anthropic/claude-haiku-4-5-20251001` | Anthropic | Fastest |
| `openai/gpt-4o` | OpenAI | Flagship multimodal |
| `openai/gpt-4.1` | OpenAI | Latest GPT-4 |
| `openai/o3` | OpenAI | Reasoning model |
| `google/gemini-2.5-pro` | Google | Long context |
| `x-ai/grok-3` | xAI | — |
| `cursor-small` | Cursor | Fast lightweight |

Model aliases (e.g. `gpt-4o` → `cursor-small`) are configurable via `SHINWAY_MODEL_MAP`.

```bash
# List all models at runtime
curl http://localhost:4001/v1/models -H "Authorization: Bearer sk-your-key"
```

---

## Connecting Your Tools

### Roo Code / Kilo Code

1. Settings → Model Provider → **Add Provider**
2. Provider: `OpenAI Compatible`
3. Base URL: `http://localhost:4001/v1`
4. API Key: your `LITELLM_MASTER_KEY`
5. Model: `anthropic/claude-opus-4-6`

### Continue.dev

```json
{
  "models": [{
    "title": "Claude Opus via Shinway",
    "provider": "openai",
    "model": "anthropic/claude-opus-4-6",
    "apiBase": "http://localhost:4001/v1",
    "apiKey": "your-key"
  }]
}
```

### OpenAI Python SDK

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:4001/v1",
    api_key="your-key",
)

response = client.chat.completions.create(
    model="anthropic/claude-opus-4-6",
    messages=[{"role": "user", "content": "Write a Python web scraper"}],
    stream=True,
)
for chunk in response:
    print(chunk.choices[0].delta.content or "", end="", flush=True)
```

### LiteLLM

```yaml
model_list:
  - model_name: claude-opus
    litellm_params:
      model: openai/anthropic/claude-opus-4-6
      api_base: http://localhost:4001/v1
      api_key: your-key
```

---

## API Reference

| Endpoint | Method | Description |
|---|---|---|
| `/v1/chat/completions` | `POST` | OpenAI-compatible chat completions |
| `/v1/messages` | `POST` | Anthropic-compatible messages |
| `/v1/messages/count_tokens` | `POST` | Anthropic token counter |
| `/v1/responses` | `POST` | Responses API — stateful multi-turn |
| `/v1/completions` | `POST` | Legacy text completions |
| `/v1/tools/validate` | `POST` | Validate and inspect tool schemas |
| `/v1/models` | `GET` | List available models |
| `/health` | `GET` | Basic health check |
| `/internal/stats` | `GET` | Per-key usage analytics |
| `/internal/logs` | `GET` | Recent request logs |
| `/internal/cache/clear` | `POST` | Clear L1 + L2 cache |
| `/internal/credentials` | `GET` | Credential pool status |
| `/internal/credentials/me` | `GET` | Validate all cookies live |
| `/internal/credentials/reset` | `POST` | Reset credentials to healthy |
| `/v1/admin/keys` | `GET/POST` | List / create managed API keys |
| `/v1/admin/keys/{key}` | `PATCH/DELETE` | Update / revoke a managed key |

---

## Tool Calls

Full function calling with **smart repair**:

- **Fuzzy matching** — `filepath` → `file_path`, `fileName` → `file_path`
- **Type coercion** — `"true"` → `true`, `"42"` → `42`
- **Alias table** — common wrong names mapped to correct ones
- **Levenshtein repair** — catches typos in parameter names
- **Confidence scoring** — drops accidental JSON (score < 0.3)
- **Parallel calls** — multiple simultaneous tools supported
- **Retry on miss** — auto-retries when `tool_choice=required` returns text
- **Max tools** — configurable limit (default 64 per request)

See [docs/guides/tool-calls.md](./docs/guides/tool-calls.md) for full tool call documentation.

---

## API Key Management

Create managed keys with per-key limits at runtime:

```bash
curl -X POST http://localhost:4001/v1/admin/keys \
  -H "Authorization: Bearer $MASTER_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "label": "roocode",
    "rpm_limit": 60,
    "rps_limit": 2,
    "token_limit_daily": 100000,
    "budget_usd": 5.0,
    "allowed_models": ["anthropic/claude-sonnet-4.6"]
  }'
```

See [docs/guides/api-key-management.md](./docs/guides/api-key-management.md) for full reference.

---

## Architecture

```
FastAPI router
  └─ Auth + rate limit + budget check
  └─ Context trimmer (1M token soft limit)
  └─ converters/to_cursor.py       OpenAI/Anthropic → Cursor format
  └─ cursor/client.py              Round-robin cookie pool + circuit breaker
  └─ cursor/sse.py                 SSE stream → iter_deltas()
  └─ utils/stream_monitor.py       First-token + idle timeout
  └─ tools/parse.py                Parse + validate + repair tool calls
  └─ converters/from_cursor.py     Cursor delta → OpenAI/Anthropic SSE chunk
  └─ cache.py                      L1 TTLCache + L2 Redis
  └─ storage/responses.py          SQLite — Responses API state
  └─ storage/keys.py               SQLite — managed API keys
```

---

## Project Structure

```
shinway/
├── app.py                    FastAPI app + lifespan
├── config.py                 All settings via pydantic-settings
├── handlers.py               Exception hierarchy
├── analytics.py              Request log ring buffer + cost estimation
├── cache.py                  L1 TTLCache + L2 Redis
├── tokens.py                 Token counting (tiktoken/litellm)
├── run.py                    Single-instance entrypoint
├── multirun.py               Multi-instance launcher
│
├── pipeline/                 Streaming orchestration (7 modules)
│   ├── params.py             PipelineParams dataclass
│   ├── suppress.py           Suppression detection + retry
│   ├── tools.py              Tool call helpers + emitter
│   ├── stream_openai.py      OpenAI SSE stream generator
│   ├── stream_anthropic.py   Anthropic SSE stream generator
│   ├── nonstream.py          Non-streaming handlers
│   └── record.py             Analytics recording
│
├── routers/
│   ├── unified.py            /v1/chat/completions, /v1/messages
│   ├── responses.py          /v1/responses (Responses API)
│   ├── internal.py           /health, /internal/*
│   └── model_router.py       Model alias resolution
│
├── converters/
│   ├── to_cursor.py          OpenAI/Anthropic → Cursor format
│   ├── from_cursor.py        Cursor SSE → OpenAI/Anthropic SSE
│   ├── to_responses.py       Responses API input converter
│   └── from_responses.py     Responses API output + SSE events
│
├── cursor/
│   ├── client.py             HTTP/2 client with retry + jitter
│   ├── sse.py                SSE line parser + delta iterator
│   └── credentials.py        Cookie pool + circuit breaker
│
├── tools/
│   ├── parse.py              Tool call parsing (4 strategies) + repair
│   └── normalize.py          Tool schema normalization
│
├── storage/
│   ├── responses.py          SQLite — Responses API state (WAL mode)
│   └── keys.py               SQLite — managed API keys (WAL mode)
│
├── middleware/
│   ├── auth.py               Bearer token auth + budget + model allowlist
│   ├── rate_limit.py         Global + per-key RPS/RPM limiting
│   └── idempotency.py        X-Idempotency-Key deduplication
│
├── utils/
│   ├── context.py            Token budget + context trimming
│   ├── stream_monitor.py     First-token + idle hang detection
│   ├── routing.py            URL routing utilities
│   └── trim.py               Message trimming helpers
│
├── validators/
│   └── request.py            Input validation (messages, tools, limits)
│
├── metrics/
│   └── parse_metrics.py      Prometheus counters for tool parsing
│
├── admin-ui/                 Next.js 16 dashboard
├── tests/                    171 unit + integration tests
├── docs/guides/              User guides
├── Dockerfile
└── docker-compose.yml
```

---

## Configuration

### Essential settings

```env
# Auth
LITELLM_MASTER_KEY=sk-your-secret-key     # REQUIRED

# Cursor
CURSOR_COOKIE=WorkosCursorSessionToken=…  # REQUIRED — single account
CURSOR_COOKIES=token1,token2,token3       # optional — multiple accounts

# Server
PORT=4001
WORKERS=3                                 # match to number of cookies

# Cache
SHINWAY_CACHE_ENABLED=true
SHINWAY_CACHE_L2_ENABLED=true
SHINWAY_REDIS_URL=redis://localhost:6379/0

# Timeouts
SHINWAY_FIRST_TOKEN_TIMEOUT=180
SHINWAY_IDLE_CHUNK_TIMEOUT=60

# Context trimming
SHINWAY_TRIM_CONTEXT=true
SHINWAY_MAX_CONTEXT_TOKENS=1000000
```

See [docs/guides/env-reference.md](./docs/guides/env-reference.md) for all environment variables.

---

## Documentation

| Guide | Description |
|---|---|
| [local-setup.md](./docs/guides/local-setup.md) | Run locally with Python |
| [docker.md](./docs/guides/docker.md) | Run with Docker Compose + Redis |
| [env-reference.md](./docs/guides/env-reference.md) | Every environment variable |
| [api-usage.md](./docs/guides/api-usage.md) | API examples and SDK usage |
| [api-key-management.md](./docs/guides/api-key-management.md) | Managed keys: limits, budgets, allowlists |
| [tool-calls.md](./docs/guides/tool-calls.md) | Tool call formats, streaming, repair |
| [admin-ui.md](./docs/guides/admin-ui.md) | Admin dashboard setup and usage |

---

## Development

```bash
# Run unit tests (no live server required)
pytest tests/ -m 'not integration' -q

# Run a single test
pytest tests/test_parse.py::test_lenient_json_loads -v

# Run integration tests (require live server on :4001)
pytest tests/integration/ -v

# Admin UI
cd admin-ui && npm install && npm run dev
```

---

## Requirements

- Python 3.12+
- A valid [Cursor.com](https://cursor.com) account (free tier works)
- Redis *(optional — for L2 cache)*

---

## License

MIT