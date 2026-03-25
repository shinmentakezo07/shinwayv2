# Endpoint Gap Fixes Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix all HIGH and MEDIUM endpoint gaps identified in the audit of `routers/unified.py` and supporting files.

**Architecture:** Changes are additive and surgical — no pipeline rewrites. HIGH items (max_tokens passthrough, body size limit, Content-Type guard) land first. MEDIUM items (stream_options, json_schema, thinking.budget_tokens, rate limits on utility endpoints, stop sequences) land second. LOW items last. Each task is independently testable and commitable.

**Tech Stack:** Python 3.12, FastAPI, Starlette, structlog, existing `handlers.RequestValidationError`, `handlers.ProxyError`

---

## Task 1: Pass `max_tokens` through to `PipelineParams` (HIGH)

**Files:**
- Modify: `pipeline.py` — add `max_tokens` field to `PipelineParams`
- Modify: `routers/unified.py` — extract and pass `max_tokens` in both endpoints
- Modify: `validators/request.py` — already validates max_tokens; no change needed
- Test: `tests/test_request_validators.py` — add integration test confirming max_tokens in params

### Step 1 — Write failing test

Append to `tests/test_request_validators.py`:

```python
# ── max_tokens passthrough ───────────────────────────────────────────────────

def test_openai_max_tokens_passed_to_params(app_client, bypass):
    captured = {}

    async def fake_handler(client, params, anthropic_tools):
        captured['max_tokens'] = params.max_tokens
        return {
            'id': 'x', 'choices': [{'message': {'content': 'ok'}, 'finish_reason': 'stop'}], 'usage': {}
        }

    import routers.unified as ru
    original = ru.handle_openai_non_streaming
    ru.handle_openai_non_streaming = fake_handler
    try:
        app_client.post(
            '/v1/chat/completions',
            headers={'Authorization': 'Bearer test-key'},
            json={'model': 'cursor-small', 'messages': [{'role': 'user', 'content': 'hi'}],
                  'max_tokens': 512, 'stream': False},
        )
    finally:
        ru.handle_openai_non_streaming = original

    assert captured.get('max_tokens') == 512


def test_anthropic_max_tokens_passed_to_params(app_client, bypass):
    captured = {}

    async def fake_handler(client, params, anthropic_tools):
        captured['max_tokens'] = params.max_tokens
        return {
            'id': 'x', 'content': [{'type': 'text', 'text': 'ok'}],
            'model': 'x', 'role': 'assistant', 'stop_reason': 'end_turn', 'usage': {}
        }

    import routers.unified as ru
    original = ru.handle_anthropic_non_streaming
    ru.handle_anthropic_non_streaming = fake_handler
    try:
        app_client.post(
            '/v1/messages',
            headers={'Authorization': 'Bearer test-key'},
            json={'model': 'x', 'messages': [{'role': 'user', 'content': 'hi'}],
                  'max_tokens': 1024, 'stream': False},
        )
    finally:
        ru.handle_anthropic_non_streaming = original

    assert captured.get('max_tokens') == 1024
```

### Step 2 — Run tests to confirm they fail

```bash
cd /teamspace/studios/this_studio/wiwi
python -m pytest tests/test_request_validators.py -k 'max_tokens_passed' -x -q
```
Expected: 2 FAILED (`PipelineParams` has no `max_tokens`)

### Step 3 — Add `max_tokens` to `PipelineParams` in `pipeline.py`

In `pipeline.py`, in the `PipelineParams` dataclass, add after `system_text`:

```python
    max_tokens: int | None = None  # pass-through from client request
```

### Step 4 — Extract and pass `max_tokens` in `chat_completions`

In `routers/unified.py`, in `chat_completions`, after `json_mode = (...)`, add:

```python
    max_tokens: int | None = payload.get("max_tokens")
```

Then in the `PipelineParams(...)` constructor call, add:

```python
        max_tokens=max_tokens,
```

### Step 5 — Extract and pass `max_tokens` in `anthropic_messages`

In `routers/unified.py`, in `anthropic_messages`, after `messages_raw = payload.get("messages", [])`, add:

```python
    max_tokens: int | None = payload.get("max_tokens")
```

Then in the `PipelineParams(...)` constructor call, add:

```python
        max_tokens=max_tokens,
```

### Step 6 — Run tests

```bash
python -m pytest tests/test_request_validators.py -k 'max_tokens_passed' -x -q
```
Expected: 2 PASSED

```bash
python -m pytest tests/ -x -q --ignore=tests/integration
```
Expected: all pass.

### Step 7 — Commit

```bash
git add pipeline.py routers/unified.py tests/test_request_validators.py
git commit -m "feat: pass max_tokens through PipelineParams from both endpoints"
```

---

## Task 2: Body size limit middleware (HIGH)

**Files:**
- Modify: `app.py` — add body size limit middleware
- Modify: `config.py` — add `max_request_body_bytes` setting
- Test: `tests/test_app.py` (create if not exists)

### Step 1 — Check if test_app.py exists

```bash
ls /teamspace/studios/this_studio/wiwi/tests/
```

### Step 2 — Add config field to `config.py`

In `config.py`, find the settings class and add:

```python
    max_request_body_bytes: int = Field(
        default=10 * 1024 * 1024,  # 10 MB
        alias="GATEWAY_MAX_REQUEST_BODY_BYTES",
        description="Maximum allowed request body size in bytes. 0 = unlimited.",
    )
```

### Step 3 — Add body size middleware to `app.py`

In `app.py`, after the `GZipMiddleware` line and before the `request_id_middleware`, add:

```python
    # ── Middleware: body size limit ─────────────────────────────────────
    if settings.max_request_body_bytes > 0:
        @app.middleware("http")
        async def body_size_limit(request: Request, call_next):
            content_length = request.headers.get("content-length")
            if content_length is not None:
                try:
                    if int(content_length) > settings.max_request_body_bytes:
                        from handlers import RequestValidationError
                        body = RequestValidationError(
                            f"Request body too large: {content_length} bytes "
                            f"(limit {settings.max_request_body_bytes} bytes)"
                        )
                        is_anthropic = _is_anthropic(request)
                        return JSONResponse(
                            status_code=413,
                            content=body.to_anthropic() if is_anthropic else body.to_openai(),
                        )
                except (ValueError, TypeError):
                    pass
            return await call_next(request)
```

Note: This checks `Content-Length` header only (fast path). Chunked/streaming uploads without `Content-Length` are not blocked by this check — that is acceptable for this proxy since all LLM API clients send `Content-Length`.

### Step 4 — Write tests

Create `tests/test_app.py` (or append if it exists):

```python
from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient
from app import create_app


@pytest.fixture
def small_body_client(monkeypatch):
    """App client with a tiny 100-byte body limit."""
    from config import settings as real_settings
    monkeypatch.setattr(
        "app.settings",
        SimpleNamespace(
            **{k: getattr(real_settings, k) for k in vars(real_settings)},
            max_request_body_bytes=100,
        ),
    )
    return TestClient(create_app())


def test_body_size_limit_413(small_body_client):
    big_payload = "x" * 200
    r = small_body_client.post(
        "/v1/chat/completions",
        headers={
            "Authorization": "Bearer test-key",
            "Content-Length": str(len(big_payload)),
        },
        content=big_payload,
    )
    assert r.status_code == 413
```

Note: testing body size via `Content-Length` header injection is the reliable approach since TestClient sets it automatically when `content=` is used.

### Step 5 — Run tests

```bash
python -m pytest tests/test_app.py -x -q
```

### Step 6 — Run full suite

```bash
python -m pytest tests/ -x -q --ignore=tests/integration
```

### Step 7 — Commit

```bash
git add app.py config.py tests/test_app.py
git commit -m "feat: add configurable request body size limit middleware (default 10MB)"
```

---

## Task 3: Content-Type guard — 400 not 422 (HIGH)

**Files:**
- Modify: `app.py` — intercept Starlette JSON decode errors before they become 422
- Test: `tests/test_app.py`

Context: When FastAPI receives a non-JSON body on a JSON endpoint (wrong Content-Type or malformed body), Starlette raises `json.JSONDecodeError` which FastAPI wraps as `RequestValidationError` → 422. We want 400 with our error shape.

The `FastAPIValidationError` handler in `app.py` already converts these to 400 (line 104–120). The issue is the message format and that body parse errors specifically should be clearly identified.

### Step 1 — Write failing test

Append to `tests/test_app.py`:

```python
from fastapi.testclient import TestClient
from app import create_app


@pytest.fixture
def plain_client():
    return TestClient(create_app(), raise_server_exceptions=False)


def test_non_json_body_returns_400_not_422(plain_client):
    r = plain_client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer test-key", "Content-Type": "text/plain"},
        content="not json at all",
    )
    assert r.status_code == 400
    body = r.json()
    assert "error" in body
    assert body["error"]["type"] == "invalid_request_error"


def test_malformed_json_returns_400(plain_client):
    r = plain_client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer test-key", "Content-Type": "application/json"},
        content="{not valid json",
    )
    assert r.status_code == 400
    body = r.json()
    assert "error" in body
```

### Step 2 — Run tests

```bash
python -m pytest tests/test_app.py -k 'non_json or malformed_json' -x -q
```

Expected: check if they already pass (the existing FastAPIValidationError handler may already handle this). If they pass — the gap is already covered; skip to commit. If they fail — proceed.

### Step 3 — Fix if needed: update `validation_error_handler` in `app.py`

If the existing handler returns 422 for body parse errors, update it to also handle `json.JSONDecodeError`. In `app.py`:

Add import at top:
```python
import json as _json
```

After the `FastAPIValidationError` handler, add:
```python
    @app.exception_handler(_json.JSONDecodeError)
    async def json_decode_error_handler(
        request: Request, exc: _json.JSONDecodeError
    ) -> JSONResponse:
        log.warning("json_decode_error", path=str(request.url.path), error=str(exc)[:100])
        body = {
            "error": {
                "message": "Request body is not valid JSON",
                "type": "invalid_request_error",
                "code": "400",
            }
        }
        return JSONResponse(status_code=400, content=body)
```

### Step 4 — Run tests again

```bash
python -m pytest tests/test_app.py -k 'non_json or malformed_json' -x -q
```
Expected: PASS

### Step 5 — Run full suite

```bash
python -m pytest tests/ -x -q --ignore=tests/integration
```

### Step 6 — Commit

```bash
git add app.py tests/test_app.py
git commit -m "fix: ensure malformed/non-JSON body returns 400 not 422"
```

---

## Task 4: `stream_options.include_usage` support (MEDIUM)

**Files:**
- Modify: `pipeline.py` — emit usage chunk when `include_usage=True` on Anthropic streams (OpenAI stream already emits usage chunk)
- Modify: `routers/unified.py` — extract `stream_options` and pass `include_usage` flag
- Modify: `pipeline.py` `PipelineParams` — add `include_usage` field

Context: OpenAI's `stream_options: {include_usage: true}` tells the proxy to append a final `data:` chunk with `usage` in the stream. The OpenAI stream path in `pipeline.py` already emits `openai_usage_chunk` unconditionally — so this gap is already handled for OpenAI. The only real work is: (1) extract `stream_options` in the router and log it, (2) add `include_usage` to `PipelineParams` for future use.

### Step 1 — Add `include_usage` to `PipelineParams`

In `pipeline.py`, in `PipelineParams`, add after `max_tokens`:

```python
    include_usage: bool = True  # stream_options.include_usage — default True (we always emit usage)
```

### Step 2 — Extract `stream_options` in `chat_completions`

In `routers/unified.py`, in `chat_completions`, after `json_mode = (...)`, add:

```python
    _stream_opts = payload.get("stream_options") or {}
    include_usage = bool(_stream_opts.get("include_usage", True))
```

Add to the `PipelineParams(...)` call:
```python
        include_usage=include_usage,
```

Add to `log.info("openai_request", ...)` block:
```python
        include_usage=include_usage,
```

### Step 3 — Run full suite

```bash
python -m pytest tests/ -x -q --ignore=tests/integration
```

### Step 4 — Commit

```bash
git add pipeline.py routers/unified.py
git commit -m "feat: wire stream_options.include_usage into PipelineParams"
```

---

## Task 5: `response_format: json_schema` — return 400 instead of silently ignoring (MEDIUM)

**Files:**
- Modify: `validators/request.py` — validate `response_format` type field
- Test: `tests/test_request_validators.py`

Context: OpenAI's newer structured-output format sends `response_format: {type: "json_schema", json_schema: {...}}`. We cannot support true structured outputs (the upstream does not), but we should not silently ignore it — we should return a clear 400 or fall back to `json_mode=True` with a warning.

Decision: fall back to `json_mode=True` and log a warning. This is better than 400-ing since many clients send `json_schema` when they just want JSON.

### Step 1 — Update `chat_completions` json_mode extraction

In `routers/unified.py`, replace:

```python
    json_mode = (
        isinstance(payload.get("response_format"), dict)
        and payload["response_format"].get("type") == "json_object"
    )
```

With:

```python
    _rf = payload.get("response_format")
    _rf_type = _rf.get("type") if isinstance(_rf, dict) else None
    json_mode = _rf_type in ("json_object", "json_schema")
    if _rf_type == "json_schema":
        log.info(
            "json_schema_fallback",
            model=model,
            schema_name=(_rf.get("json_schema") or {}).get("name"),
        )
```

### Step 2 — Write test

Append to `tests/test_request_validators.py`:

```python
def test_openai_json_schema_response_format_accepted(app_client, bypass, monkeypatch):
    """json_schema response_format must not be rejected — falls back to json_mode."""
    async def fake_handler(client, params, anthropic_tools):
        return {'id': 'x', 'choices': [{'message': {'content': '{}'}, 'finish_reason': 'stop'}], 'usage': {}}
    monkeypatch.setattr('routers.unified.handle_openai_non_streaming', fake_handler)

    r = app_client.post(
        '/v1/chat/completions',
        headers={'Authorization': 'Bearer test-key'},
        json={
            'model': 'cursor-small',
            'messages': [{'role': 'user', 'content': 'hi'}],
            'response_format': {'type': 'json_schema', 'json_schema': {'name': 'MySchema', 'schema': {}}},
            'stream': False,
        },
    )
    assert r.status_code == 200
```

### Step 3 — Run test

```bash
python -m pytest tests/test_request_validators.py -k 'json_schema' -x -q
```

### Step 4 — Run full suite

```bash
python -m pytest tests/ -x -q --ignore=tests/integration
```

### Step 5 — Commit

```bash
git add routers/unified.py tests/test_request_validators.py
git commit -m "feat: fall back json_schema response_format to json_mode with log warning"
```

---

## Task 6: `thinking.budget_tokens` passthrough (MEDIUM)

**Files:**
- Modify: `pipeline.py` — add `thinking_budget_tokens` to `PipelineParams`
- Modify: `routers/unified.py` — extract and pass it
- Modify: `converters/to_cursor.py` `anthropic_to_cursor` — accept and inject budget hint

Context: Anthropic's extended thinking API sends `thinking: {type: "enabled", budget_tokens: 10000}`. Currently `budget_tokens` is discarded. We should pass it into the system prompt so the model can respect it.

### Step 1 — Add `thinking_budget_tokens` to `PipelineParams`

In `pipeline.py` `PipelineParams`, add:

```python
    thinking_budget_tokens: int | None = None  # Anthropic extended thinking budget
```

### Step 2 — Extract in `anthropic_messages`

In `routers/unified.py`, in `anthropic_messages`, the `thinking` dict is already extracted. Add:

```python
    thinking_budget = int(thinking["budget_tokens"]) if thinking and "budget_tokens" in thinking else None
```

Add to `PipelineParams(...)` call:
```python
        thinking_budget_tokens=thinking_budget,
```

Add to `log.info("anthropic_request", ...)` block:
```python
        thinking_budget_tokens=thinking_budget,
```

### Step 3 — Inject budget hint in `anthropic_to_cursor` in `converters/to_cursor.py`

In `converters/to_cursor.py`, in `anthropic_to_cursor`, after the `if thinking:` block that sets `show_reasoning`, add a system message with the budget:

Find the section in `anthropic_to_cursor` where `show_reasoning` is set and add:

```python
    if thinking and thinking.get("budget_tokens"):
        budget = thinking["budget_tokens"]
        cursor_messages.append(_msg(
            "system",
            f"Extended thinking budget: {budget} tokens. "
            "Think deeply and use your full reasoning budget before responding."
        ))
```

### Step 4 — Run full suite

```bash
python -m pytest tests/ -x -q --ignore=tests/integration
```

### Step 5 — Commit

```bash
git add pipeline.py routers/unified.py converters/to_cursor.py
git commit -m "feat: pass thinking.budget_tokens through to pipeline and cursor converter"
```

---

## Task 7: Rate limit `count_tokens` and `validate_tools` endpoints (MEDIUM)

**Files:**
- Modify: `routers/unified.py` — add `enforce_rate_limit` call to both utility endpoints

Context: `/v1/messages/count_tokens` and `/v1/tools/validate` currently only call `verify_bearer`. A valid key can spam them cheaply. Add rate limiting.

### Step 1 — Add `enforce_rate_limit` to `count_tokens`

In `routers/unified.py`, in `count_tokens`, after `verify_bearer(authorization)`, add:

```python
    enforce_rate_limit(api_key)
```

But first capture the return value: change `verify_bearer(authorization)` to:

```python
    api_key = verify_bearer(authorization)
    enforce_rate_limit(api_key)
```

### Step 2 — Add `enforce_rate_limit` to `validate_tools`

Same pattern in `validate_tools`:

```python
    api_key = verify_bearer(authorization)
    enforce_rate_limit(api_key)
```

### Step 3 — Write integration tests

Append to `tests/test_request_validators.py`:

```python
def test_count_tokens_rate_limited(app_client, monkeypatch):
    """count_tokens should call enforce_rate_limit."""
    called = {}
    monkeypatch.setattr('routers.unified.verify_bearer', lambda a: 'test-key')
    monkeypatch.setattr('routers.unified.enforce_rate_limit', lambda k: called.update({'key': k}))
    monkeypatch.setattr('routers.unified.resolve_model', lambda m: m or 'cursor-small')
    app_client.post(
        '/v1/messages/count_tokens',
        headers={'Authorization': 'Bearer test-key'},
        json={'messages': [{'role': 'user', 'content': 'hi'}], 'model': 'x'},
    )
    assert called.get('key') == 'test-key'


def test_validate_tools_rate_limited(app_client, monkeypatch):
    """validate_tools should call enforce_rate_limit."""
    called = {}
    monkeypatch.setattr('routers.unified.verify_bearer', lambda a: 'test-key')
    monkeypatch.setattr('routers.unified.enforce_rate_limit', lambda k: called.update({'key': k}))
    monkeypatch.setattr('routers.unified.resolve_model', lambda m: m or 'cursor-small')
    app_client.post(
        '/v1/tools/validate',
        headers={'Authorization': 'Bearer test-key'},
        json={'tools': [], 'model': 'x'},
    )
    assert called.get('key') == 'test-key'
```

### Step 4 — Run tests

```bash
python -m pytest tests/test_request_validators.py -k 'rate_limited' -x -q
```
Expected: 2 FAILED (rate limit not called yet)

### Step 5 — Apply the fix, then run again

```bash
python -m pytest tests/test_request_validators.py -k 'rate_limited' -x -q
```
Expected: 2 PASSED

### Step 6 — Run full suite

```bash
python -m pytest tests/ -x -q --ignore=tests/integration
```

### Step 7 — Commit

```bash
git add routers/unified.py tests/test_request_validators.py
git commit -m "fix: add rate limiting to count_tokens and validate_tools endpoints"
```

---

## Task 8: `stop` / `stop_sequences` — log and pass through (MEDIUM)

**Files:**
- Modify: `pipeline.py` `PipelineParams` — add `stop` field
- Modify: `routers/unified.py` — extract from both endpoints

Context: We cannot enforce stop sequences at the proxy level (the upstream the-editor API does not expose this). But we should extract them, store in `PipelineParams`, and log them so the operator knows the client requested them. This prevents silent confusion when sequences are not honoured.

### Step 1 — Add `stop` to `PipelineParams`

In `pipeline.py`, add to `PipelineParams`:

```python
    stop: list[str] | None = None  # stop sequences requested by client (informational — not enforced upstream)
```

### Step 2 — Extract in `chat_completions`

In `routers/unified.py`, in `chat_completions`, after `json_mode`, add:

```python
    stop_raw = payload.get("stop")
    stop: list[str] | None = (
        [stop_raw] if isinstance(stop_raw, str)
        else stop_raw if isinstance(stop_raw, list)
        else None
    )
    if stop:
        log.info("stop_sequences_requested", count=len(stop), model=model)
```

Add to `PipelineParams(...)` call:
```python
        stop=stop,
```

### Step 3 — Extract in `anthropic_messages`

In `routers/unified.py`, in `anthropic_messages`, after `messages_raw`, add:

```python
    stop_sequences = payload.get("stop_sequences") or []
    if stop_sequences:
        log.info("stop_sequences_requested", count=len(stop_sequences), model=model)
```

Add to `PipelineParams(...)` call:
```python
        stop=stop_sequences or None,
```

### Step 4 — Run full suite

```bash
python -m pytest tests/ -x -q --ignore=tests/integration
```

### Step 5 — Commit

```bash
git add pipeline.py routers/unified.py
git commit -m "feat: extract stop/stop_sequences into PipelineParams and log when present"
```

---

## Task 9: LOW items — logging + legacy prompt validation (LOW)

**Files:**
- Modify: `routers/unified.py`

### Changes

**9a — Log `parallel_tool_calls` in `openai_request`:**

Add `parallel_tool_calls=parallel_tool_calls` to the `log.info("openai_request", ...)` block in `chat_completions`.

**9b — Move `request_complete` log after `complete()`:**

In `_handle_non_streaming`, move the `log.info("request_complete", ...)` block to after `if idem_key: await complete(idem_key, resp)` so it only fires after the response is durably stored.

**9c — Validate `prompt` in `text_completions`:**

In `routers/unified.py`, in `text_completions`, after `prompt = payload.get("prompt", "")`, add:

```python
    if not isinstance(prompt, str):
        from handlers import RequestValidationError
        raise RequestValidationError("prompt must be a string")
```

### Step 1 — Apply all three changes

### Step 2 — Run full suite

```bash
python -m pytest tests/ -x -q --ignore=tests/integration
```

### Step 3 — Commit

```bash
git add routers/unified.py
git commit -m "fix: log parallel_tool_calls, fix request_complete log order, validate legacy prompt"
```

---

## Task 10: Final verification

### Step 1 — Run full suite

```bash
python -m pytest tests/ -q --ignore=tests/integration
```
Expected: all pass.

### Step 2 — Import check

```bash
python -c "from routers.unified import router; from pipeline import PipelineParams; print('OK')"
```

### Step 3 — Push

```bash
git push
```
