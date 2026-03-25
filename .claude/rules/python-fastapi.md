---
paths:
  - "**/*.py"
  - "routers/**/*.py"
  - "middleware/**/*.py"
  - "converters/**/*.py"
  - "cursor/**/*.py"
  - "tools/**/*.py"
  - "storage/**/*.py"
  - "utils/**/*.py"
---
# Python / FastAPI Rules

> Project: Shinway FastAPI reverse proxy — async-first, streaming-critical, credential-pooled.

## Code Style

- Follow PEP 8. Snake_case for files, functions, variables. PascalCase for classes.
- Maximum line length: 100 characters.
- Use `def` for pure synchronous functions, `async def` for any I/O-bound operation.
- Type hints on every function signature including return type (use `None` explicitly).
- Descriptive variable names with auxiliary verbs: `is_active`, `has_permission`, `should_retry`.

## FastAPI Patterns

- Use functional route handlers (plain `async def`), not class-based views.
- Use Pydantic `BaseModel` for all request/response schemas — never raw `dict`.
- Use FastAPI's dependency injection (`Depends`) for auth, rate limiting, DB sessions.
- Prefer lifespan context managers (`@asynccontextmanager`) over `@app.on_event`.
- Use `HTTPException` for expected HTTP errors with explicit `status_code` and `detail`.
- Return type-annotate all route handlers: `-> StreamingResponse`, `-> dict`, etc.
- Use `APIRouter` with `prefix` and `tags` — never register routes directly on `app`.

## Error Handling

- Handle errors at the top of functions with early returns (guard clauses).
- Never use bare `except:`; catch specific exception types.
- Never swallow exceptions silently — log with `structlog` and re-raise or convert.
- Use custom exception classes for domain errors (e.g., `ContextWindowError`, `CredentialExhaustedError`).
- Distinguish client errors (4xx) from server errors (5xx) — never return 500 for bad input.

## Async / Streaming

- All DB calls, HTTP calls, and cache operations must be `await`ed — no blocking I/O in async paths.
- Streaming routes must use `StreamingResponse` with an `async_generator`.
- Never call `asyncio.run()` inside a running event loop.
- Use `asyncio.Lock` (not `threading.Lock`) for async-shared state.
- SSE generators must `yield` each chunk immediately — no buffering the full response.

## Pydantic

- Use Pydantic v2 (`model_config`, `model_validator`, `field_validator`).
- Define all settings in `config.py` using `pydantic-settings` `BaseSettings`.
- Never use `Optional[X]`; prefer `X | None` (Python 3.10+ union syntax) in new code.
- Use `model_dump(exclude_none=True)` when serializing to upstream APIs.

## Imports

- Absolute imports only; no relative imports.
- Group: stdlib → third-party → local. Separated by blank lines.
- Import at module level; never inside functions unless for circular-import avoidance (document why).

## File Organization

```
router / endpoint
  └── dependency injection
  └── validation (validators/)
  └── business logic (pipeline.py, converters/)
  └── data access (storage/, cursor/)
  └── utilities (utils/)
```

- Files ≤ 400 lines. Extract to submodules when exceeding this.
- One router per file. One responsibility per module.

## Docstrings & Comments

- Public functions and classes get Google-style docstrings.
- Comments explain *why*, not *what*. Code explains what.
- Never comment out dead code — delete it.

## RORO Pattern

- Receive an Object, Return an Object — route handlers and service functions accept typed Pydantic
  models and return typed Pydantic models or explicit primitives. Never accept or return raw `dict`.
- Group related parameters into a single input model rather than long positional argument lists.

## Performance

- Minimize blocking I/O: every database call, HTTP call, and cache operation must be async.
- Use `asyncio.gather()` for independent concurrent operations — no sequential await chains when
  parallelism is safe.
- Implement caching for static and frequently accessed data (L1 `TTLCache`, L2 Redis opt-in).
- Use lazy loading for large datasets — never load unbounded result sets into memory.
- Use `background tasks` (`BackgroundTasks`) for work that doesn't need to block the response.
- Prefer list comprehensions over loops for simple transformations.

## Dependency Injection Patterns

- Use `Depends()` for: auth verification, rate limiting, DB session acquisition, budget checks.
- Keep dependency functions small and single-purpose — compose them rather than nesting logic.
- Never perform I/O directly inside route handler bodies if it can be lifted into a dependency.

## OpenAPI & Documentation

- All route handlers declare `summary`, `description`, and `response_model` for auto-generated docs.
- Use `responses={}` to document non-200 HTTP status codes on each endpoint.
- Tag routers with domain-specific `tags` so the OpenAPI UI groups them logically.

## Security (Python-specific)

- Never log request bodies, API keys, or cookie values.
- All SQL queries use parameterized statements — never f-string interpolation into SQL.
- Validate field names against a whitelist before interpolating into UPDATE queries.
- Secrets come from env vars only — never hardcoded, never in source.
- Implement CORS with an explicit allowlist — never `allow_origins=["*"]` in production.
- Use FastAPI's security utilities (`HTTPBearer`, `OAuth2PasswordBearer`) as the auth interface layer.
- Rate-limit all public endpoints before any upstream or DB call.
