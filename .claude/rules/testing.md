---
paths:
  - "tests/**/*.py"
  - "**/*_test.py"
  - "**/*.test.ts"
  - "**/*.test.tsx"
  - "**/*.spec.ts"
---
# Testing Rules

> Test stack: pytest + pytest-asyncio (backend), Playwright (E2E admin UI).

## Minimum Coverage: 80%

Required test types:
1. **Unit** — individual functions, parsers, converters, validators
2. **Integration** — API endpoints (with TestClient), middleware, storage
3. **E2E** — critical admin UI flows (Playwright)

## Python / pytest

- All tests under `tests/`. Mirror source structure: `tests/test_pipeline.py`, `tests/test_parse.py`.
- Use `pytest` only — no `unittest`. Annotate all test functions with return type `None`.
- Use `@pytest.mark.asyncio` for async tests.
- Use `pytest.fixture` for shared setup — no global test state.
- Use `pytest-mock` (`mocker`) for mocking — no `unittest.mock` patches in test signatures.
- Parametrize with `@pytest.mark.parametrize` instead of loops.
- Test error paths explicitly — assert correct exception type and message.
- Use `httpx.AsyncClient` with `app` for endpoint integration tests.

## TDD Workflow

1. Write test first (RED) — run it, confirm it fails.
2. Write minimal implementation (GREEN) — run it, confirm it passes.
3. Refactor (IMPROVE) — run again, confirm still passes.
4. Verify coverage: `pytest --cov=. --cov-report=term-missing`

## Test Naming

- `test_<what>_<condition>_<expected>` pattern.
- Examples: `test_repair_tool_call_wrong_param_name_fuzzy_corrects`, `test_stream_abort_signal_detected_retries`.
- Descriptive names — readable as a specification.

## What to Test (Shinway-specific)

- `tools/parse.py`: all 4 parsing strategies, repair, validate
- `converters/to_cursor.py`: system prompt injection, role override, tool instruction
- `converters/from_cursor.py`: sanitize, scrub, split reasoning
- `middleware/auth.py`: master key, env key, DB key, budget check
- `middleware/rate_limit.py`: RPM, RPS, daily token limit enforcement
- `storage/keys.py`: CRUD operations, field whitelist validation
- `utils/context.py`: trim preserves tool pairs atomically
- `validators/request.py`: all 7 validation functions, all error paths

## Test Isolation

- Each test is fully isolated — no shared mutable state between tests.
- Mock external calls: `cursor/client.py` (HTTP/2), Redis, aiosqlite.
- Use `tmp_path` fixture for any file/DB operations.
- Reset global singletons (e.g., `CredentialPool`) in teardown.
