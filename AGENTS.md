# Shin Proxy — Agent Instructions

This document provides instructions for AI agents working on the Shin Proxy codebase.
Adhering to these guidelines is critical for maintaining code quality, consistency, and stability.

---

## 1. Project Overview

Shin Proxy is a FastAPI-based reverse proxy that exposes the-editor's internal `/api/chat`
endpoint as standard **OpenAI** and **Anthropic** compatible APIs. It is designed for AI coding
agents (Roo Code, Kilo Code, Cline) that expect standard LLM API contracts.

**Request pipeline:** `Route → Convert → Pipeline → the-editor API → Convert → Response`

**Entry point:** `run.py` → `app.py:create_app()` → uvicorn at `0.0.0.0:4000`

---

## 2. Development Environment

### Setup
```bash
pip install -r requirements.txt
cp .env.example .env
# Fill in CURSOR_COOKIE and LITELLM_MASTER_KEY at minimum
```

### Run the server
```bash
python run.py
```
Available at `http://0.0.0.0:4000`.

---

## 3. Build, Lint, and Test Commands

### Run all tests
```bash
python -m pytest tests/ -v
```

### Run a single test file
```bash
python -m pytest tests/test_parse.py -v
```

### Run a single test by name
```bash
python -m pytest tests/test_parse.py::test_lenient_json_loads_strict -v
```

### Run tests matching a keyword
```bash
python -m pytest tests/ -k "tool_call" -v
```

### Known test state
- **62 tests pass**, 2 errors in `tests/test_routing.py` (stale imports referencing
  `routers.openai` which was merged into `routers/unified.py`). Do not regress the 62
  passing tests. Fix the 2 routing errors if touching `routers/`.
- Root-level `test_*.py` files (e.g. `test_abort.py`, `test_massive.py`) are **manual**
  integration scripts that require a live server and valid credentials. Do not run them
  in CI or automated contexts.

### Linting
`ruff` is the preferred linter but is not installed in the current environment.
Run it when available:
```bash
ruff check .
ruff format --check .
```
Type-check with `mypy` when unsure about type correctness.

### Manual verification
```bash
curl http://localhost:4000/health
curl http://localhost:4000/v1/models
```

---

## 4. Code Style and Conventions

### General Principles
- **Clarity over cleverness.** Write clear, concise, well-documented code.
- **Type safety.** All function signatures and local variables must have type hints.
- **Async everywhere.** Use `async/await` for all I/O-bound operations without exception.
- **No hardcoded values.** All configuration goes in `config.py` via `pydantic-settings`.
  Access via `from config import settings`.

### Imports
Organize into exactly three groups separated by a blank line:

```python
# 1. Standard library
from __future__ import annotations
import asyncio
import time

# 2. Third-party
import httpx
import structlog
from fastapi import APIRouter

# 3. Internal
from config import settings
from handlers import ProxyError
from cursor.client import CursorClient
```

### Formatting
- **Line length:** 88 characters maximum.
- **Strings:** Double quotes (`"`) everywhere; single quotes only when inner double
  quotes would require escaping.
- **Docstrings:** Triple double-quotes (`"""`) for all module, class, and function
  docstrings. Modules get a top-level docstring stating purpose and key invariants.
- **Section separators:** Use `# ── Section Name ──────` (em-dash + spaces) for
  grouping related blocks inside a file, consistent with `config.py`.

### Naming Conventions
| Kind | Style | Example |
|---|---|---|
| Variables / functions | `snake_case` | `request_id`, `build_headers` |
| Classes | `PascalCase` | `PipelineParams`, `CursorClient` |
| Constants | `UPPER_SNAKE_CASE` | `_RETRYABLE`, `MAX_RETRIES` |
| Private members | `_single_underscore` prefix | `_http_client`, `_lifespan` |
| Async generators | `snake_case`, verb prefix | `_openai_stream`, `_anthropic_stream` |

---

## 5. Error Handling and Logging

### Exception Hierarchy (`handlers.py`)
All proxy errors **must** inherit from `ProxyError`. Never raise bare `Exception` or
`ValueError` from pipeline or router code.

| Class | HTTP | When to use |
|---|---|---|
| `AuthError` | 401 | Invalid or missing API key |
| `RequestValidationError` | 400 | Malformed request body |
| `ContextWindowError` | 400 | Context exceeds model limit |
| `CredentialError` | 401 | the-editor cookie invalid/expired |
| `RateLimitError` | 429 | Token-bucket quota exceeded |
| `BackendError` | 502 | Upstream the-editor API failure |
| `TimeoutError` | 504 | TTFT or idle stream timeout |
| `EmptyResponseError` | 502 | Zero-length response from upstream |
| `StreamAbortError` | 499 | Client disconnected mid-stream |
| `ToolParseError` | 200 | Tool JSON unparseable (handled inline) |

All exceptions are caught by the app-level exception handlers in `app.py` and rendered
as OpenAI or Anthropic error JSON automatically based on the request path.

### Structured Logging
Use `structlog` exclusively. Never use `print()` or the stdlib `logging` module directly.
Always bind relevant context:

```python
log = structlog.get_logger()
log.info("request_started", request_id=request_id, model=model, path=path)
log.warning("suppression_detected", request_id=request_id, preview=text[:80])
log.error("upstream_error", request_id=request_id, status=resp.status_code)
```

---

## 6. Architecture and Design

### Configuration
All settings live in `config.py` as a single `Settings` class. The module-level
`settings` singleton is the **only** way to access config. Never read `os.environ`
directly.

### Data Validation
Use `pydantic` models for all API request/response bodies exposed over HTTP.
Use `dataclasses` for internal data transfer objects (e.g. `PipelineParams`).

### Pipeline Architecture
When adding new functionality, preserve the existing layer structure in `pipeline.py`:

1. **Suppress detection** — detect the-editor's persona, inject role override, retry
2. **Retry logic** — exponential backoff on `CredentialError`, `TimeoutError`,
   `RateLimitError`, `BackendError`
3. **Response scrubber** — strip support preamble from output text
4. **Confidence scorer** — discard accidental tool JSON below 0.3 threshold
5. **Context path spoofer** — set `filePath=/workspace/project` when tools are present
6. **SSE early-exit** — abort stream on suppression signal in first 300 chars

### Caching
`cache.py` provides a two-level cache: L1 (in-memory, `cachetools`) and L2 (Redis).
Cache keys are derived from the full request body. Only deterministic, non-streaming
responses are cached.

### Adding a New Endpoint
1. Add the route to `routers/unified.py` (public) or `routers/internal.py` (admin).
2. Validate input with a `pydantic` model.
3. Pass through `pipeline.py` — do not call `cursor/client.py` directly from a router.
4. Render errors via the `ProxyError` hierarchy; never return raw dicts for errors.
5. Add a test in `tests/` before merging.

---

## 7. Documentation Duty (Mandatory After Every Task)

After completing **any non-trivial task**, you must:

1. **Append a new section to `UPDATES.md`** with:
   - Session date and short title
   - Every file changed, the exact line/setting modified, before/after values
   - The reasoning behind each change
   - A table for config changes, code snippets for code changes

2. **Do not modify `AGENTS.md`** unless the user explicitly asks — it is the stable reference for agents.

This ensures the next agent always has full context without reading git history.

---

## 8. Key Invariants (Do Not Break)

- `cursor_messages` **must** be fully built before any branch on `stream`/`cache`
  (see module docstring in `pipeline.py`).
- The `api_style` field in `PipelineParams` (`"openai"` or `"anthropic"`) controls all
  output formatting. Never branch on the request path string instead.
- Credential rotation is handled exclusively by `cursor/credentials.py`. Never pass
  a raw cookie string outside of that module.
- `utils/trim.py` and `utils/routing.py` are **compatibility shims** — new code should
  import from `utils/context.py` and `routers/model_router.py` respectively.
