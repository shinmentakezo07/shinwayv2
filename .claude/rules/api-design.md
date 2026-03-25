---
paths:
  - "routers/**/*.py"
  - "admin-ui/app/api/**/*.ts"
---
# API Design Rules

> Applies to FastAPI route handlers and Next.js API route handlers.

## HTTP Methods & Status Codes

- `GET` — read, idempotent, no body
- `POST` — create or action
- `PUT`/`PATCH` — update (PUT = full replace, PATCH = partial)
- `DELETE` — remove

Status codes:
- `200` — success with body
- `201` — created
- `204` — success, no body
- `400` — bad request / validation failure
- `401` — unauthenticated (missing/invalid credentials)
- `403` — unauthorized (valid credentials, insufficient permission)
- `404` — not found
- `409` — conflict (duplicate key label, etc.)
- `422` — unprocessable entity (Pydantic validation)
- `429` — rate limit exceeded
- `500` — internal server error (never for client mistakes)

## Request/Response Shape

- All endpoints use Pydantic models for request body and response schema.
- Error responses: `{ "detail": "human-readable message" }` (FastAPI default).
- Never return raw exceptions or stack traces.
- Paginated responses include `total`, `page`, `limit` fields.

## Resource Naming

- Plural nouns for collections: `/internal/keys`, `/v1/responses`.
- Kebab-case paths: `/v1/chat/completions`, `/v1/messages/count_tokens`.
- Avoid verbs in paths — use HTTP method to express action.
  - `/internal/keys/{id}` + `DELETE` not `/internal/keys/delete/{id}`
  - `/internal/cache/clear` is acceptable for non-CRUD actions.

## Versioning

- Public API uses `/v1/` prefix — matches OpenAI/Anthropic conventions.
- Internal admin API uses `/internal/` prefix — gated by `x-admin-token`.
- Breaking changes require a new version prefix.

## Consistency Rules (Shinway-specific)

- All `/v1/` endpoints check auth via `verify_bearer` before executing.
- All `/v1/` endpoints check budget via `check_budget` before executing.
- Rate limiting (`enforce_rate_limit`, `enforce_per_key_rate_limit`) applied before upstream call.
- Idempotency header `X-Idempotency-Key` checked in `middleware/idempotency.py`.
- `request_id` injected by middleware and threaded through `PipelineParams` for tracing.

## Next.js API Routes (Admin UI)

- All `admin-ui/app/api/` routes proxy to FastAPI — no business logic.
- Read `x-admin-token` from request header, forward to FastAPI.
- Return FastAPI's response unchanged except for status code normalization.
- Handle network errors from FastAPI — return `503` not an unhandled exception.
