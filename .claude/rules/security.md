---
paths:
  - "**/*.py"
  - "middleware/**/*.py"
  - "storage/**/*.py"
  - "routers/**/*.py"
---
# Security Rules

> This is a proxy gateway handling third-party credentials and user API keys.
> Security failures here are high-impact — enforce these rules without exception.

## Mandatory Pre-Commit Checks

- [ ] No hardcoded secrets, API keys, tokens, or cookies in source
- [ ] All user inputs validated via Pydantic before processing
- [ ] No f-string interpolation into SQL — parameterized queries only
- [ ] SQL field names validated against `_ALLOWED_UPDATE_FIELDS` whitelist
- [ ] Auth middleware (`verify_bearer`, `check_budget`) called on every protected route
- [ ] Rate limiting enforced before any upstream call
- [ ] Error responses never expose stack traces, internal paths, or DB details
- [ ] No secrets or PII logged at any level

## Secret Management

- All credentials come from env vars — `LITELLM_MASTER_KEY`, `CURSOR_COOKIE`, `SHINWAY_*`.
- Validate required secrets are present at startup — fail fast with a clear error.
- Never log cookie values, API key values, or bearer tokens (even truncated).
- Rotate any secret that appears in logs or error output immediately.
- API key display: truncate to first 8 + last 4 chars for display only (`sk-live-abcd...ef12`).

## Authentication

- `verify_bearer()` and `check_budget()` are `async` — always `await` them.
- Auth checks happen in middleware/dependency before route handler executes.
- Master key, env keys, and DB-managed keys all valid — checked in that order.
- Budget check is a separate gate after auth — both must pass.
- 401 for missing/invalid credentials. 403 for valid key with insufficient budget.

## Input Validation

- Validate at every system boundary: API endpoints, internal functions receiving external data.
- Use `validators/request.py` for all request-level validation — raise `RequestValidationError` (400).
- Never trust upstream SSE data without sanitization (`converters/from_cursor.py`).
- Body size hard limit: 32 MB (`SHINWAY_MAX_REQUEST_BODY_BYTES`).

## SQL Safety

- All aiosqlite queries use `?` placeholders — never string interpolation.
- `KeyStore.update()` validates field names against `_ALLOWED_UPDATE_FIELDS` before using in SQL.
- Never expose raw SQLite errors to API clients — wrap and return 500.

## Upstream Credential Isolation

- Each upstream credential is isolated per request — no cross-request credential bleed.
- `CircuitBreaker` per credential — tripped credentials are not retried until cooldown.
- Credential pool round-robin ensures no single cookie is overloaded.
- Browser fingerprint cookies are derived deterministically from `workos_id` — never stored in plaintext alongside the session token.

## Security Response Protocol

If a security issue is found:
1. Stop immediately.
2. Do not commit.
3. Fix the root cause — not just the symptom.
4. Rotate any exposed secrets.
5. Audit the entire codebase for the same pattern.
