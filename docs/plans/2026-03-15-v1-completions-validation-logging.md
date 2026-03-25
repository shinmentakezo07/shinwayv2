# v1/chat/completions — Validation + Structured Logging Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add explicit request validation with typed 400 errors and structured per-request logging to `/v1/chat/completions` (OpenAI) and `/v1/messages` (Anthropic).

**Architecture:** A `validators/` module holds pure validation functions that raise `RequestValidationError` (existing handler). Logging is injected into both endpoint handlers: one structlog call at entry (model, tools, stream, reasoning_effort) and one at completion (finish_reason, token counts). Both changes are additive — zero behaviour change on valid requests.

**Tech Stack:** Python 3.12, FastAPI, structlog, existing `handlers.RequestValidationError`

---

## Task 1: Create `validators/` module

**Files:**
- Create: `validators/__init__.py` (empty)
- Create: `validators/request.py`
- Test: `tests/test_request_validators.py`

### Step 1 — Write the failing tests

Create `tests/test_request_validators.py`:

```python
import pytest
from handlers import RequestValidationError
from validators.request import (
    validate_messages,
    validate_model,
    validate_max_tokens,
    validate_temperature,
    validate_n,
    validate_openai_payload,
    validate_anthropic_payload,
)


def test_messages_empty_raises():
    with pytest.raises(RequestValidationError, match="messages"):
        validate_messages([])

def test_messages_none_raises():
    with pytest.raises(RequestValidationError, match="messages"):
        validate_messages(None)

def test_messages_not_list_raises():
    with pytest.raises(RequestValidationError, match="messages"):
        validate_messages("hi")

def test_messages_missing_role_raises():
    with pytest.raises(RequestValidationError, match="role"):
        validate_messages([{"content": "hi"}])

def test_messages_invalid_role_raises():
    with pytest.raises(RequestValidationError, match="role"):
        validate_messages([{"role": "robot", "content": "hi"}])

def test_messages_valid_passes():
    for role in ("user", "assistant", "system", "tool"):
        validate_messages([{"role": role, "content": "x"}])

def test_model_none_ok():
    validate_model(None)

def test_model_empty_ok():
    validate_model("")

def test_model_non_string_raises():
    with pytest.raises(RequestValidationError, match="model"):
        validate_model(42)

def test_max_tokens_none_ok():
    validate_max_tokens(None)

def test_max_tokens_positive_ok():
    validate_max_tokens(1024)

def test_max_tokens_zero_raises():
    with pytest.raises(RequestValidationError, match="max_tokens"):
        validate_max_tokens(0)

def test_max_tokens_negative_raises():
    with pytest.raises(RequestValidationError, match="max_tokens"):
        validate_max_tokens(-1)

def test_max_tokens_string_raises():
    with pytest.raises(RequestValidationError, match="max_tokens"):
        validate_max_tokens("big")

def test_temperature_none_ok():
    validate_temperature(None)

def test_temperature_in_range_ok():
    validate_temperature(0.7)

def test_temperature_out_of_range_raises():
    with pytest.raises(RequestValidationError, match="temperature"):
        validate_temperature(3.0)

def test_n_none_ok():
    validate_n(None)

def test_n_one_ok():
    validate_n(1)

def test_n_zero_raises():
    with pytest.raises(RequestValidationError, match="n"):
        validate_n(0)

def test_n_gt_one_raises():
    with pytest.raises(RequestValidationError, match="n"):
        validate_n(3)

def test_openai_minimal_valid():
    validate_openai_payload({"messages": [{"role": "user", "content": "hi"}]})

def test_openai_empty_messages_raises():
    with pytest.raises(RequestValidationError, match="messages"):
        validate_openai_payload({"messages": []})

def test_openai_bad_max_tokens_raises():
    with pytest.raises(RequestValidationError, match="max_tokens"):
        validate_openai_payload({
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": -5,
        })

def test_openai_bad_temperature_raises():
    with pytest.raises(RequestValidationError, match="temperature"):
        validate_openai_payload({
            "messages": [{"role": "user", "content": "hi"}],
            "temperature": 3.0,
        })

def test_openai_bad_n_raises():
    with pytest.raises(RequestValidationError, match="n"):
        validate_openai_payload({
            "messages": [{"role": "user", "content": "hi"}],
            "n": 0,
        })

def test_anthropic_minimal_valid():
    validate_anthropic_payload({
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 1024,
    })

def test_anthropic_missing_max_tokens_raises():
    with pytest.raises(RequestValidationError, match="max_tokens"):
        validate_anthropic_payload({"messages": [{"role": "user", "content": "hi"}]})

def test_anthropic_empty_messages_raises():
    with pytest.raises(RequestValidationError, match="messages"):
        validate_anthropic_payload({"max_tokens": 1024})
```

### Step 2 — Run tests to confirm they fail

```bash
cd /teamspace/studios/this_studio/wiwi
python -m pytest tests/test_request_validators.py -x -q
```
Expected: `ModuleNotFoundError: No module named 'validators'`

### Step 3 — Create `validators/__init__.py`

Empty file — just marks the package.

### Step 4 — Create `validators/request.py`

```python
"""
Shin Proxy — Request payload validators.

All functions raise RequestValidationError on invalid input.
Pure functions — no side effects, no I/O.
"""

from __future__ import annotations

from handlers import RequestValidationError

_VALID_OPENAI_ROLES = frozenset({"user", "assistant", "system", "tool", "function"})
_VALID_ANTHROPIC_ROLES = frozenset({"user", "assistant"})


def validate_messages(
    messages: object,
    valid_roles: frozenset[str] = _VALID_OPENAI_ROLES,
) -> None:
    """Validate messages array — non-empty list of dicts with valid roles."""
    if not isinstance(messages, list) or not messages:
        raise RequestValidationError("messages must be a non-empty array")
    for i, msg in enumerate(messages):
        if not isinstance(msg, dict):
            raise RequestValidationError(f"messages[{i}] must be an object")
        role = msg.get("role")
        if not role:
            raise RequestValidationError(f"messages[{i}] missing required field 'role'")
        if role not in valid_roles:
            raise RequestValidationError(
                f"messages[{i}].role '{role}' is not valid — "
                f"must be one of: {', '.join(sorted(valid_roles))}"
            )


def validate_model(model: object) -> None:
    """Validate model field — string or absent."""
    if model is not None and model != "" and not isinstance(model, str):
        raise RequestValidationError("model must be a string")


def validate_max_tokens(max_tokens: object) -> None:
    """Validate max_tokens — positive integer when present."""
    if max_tokens is None:
        return
    if not isinstance(max_tokens, int) or isinstance(max_tokens, bool):
        raise RequestValidationError("max_tokens must be an integer")
    if max_tokens <= 0:
        raise RequestValidationError(f"max_tokens must be positive, got {max_tokens}")


def validate_temperature(temperature: object) -> None:
    """Validate temperature — float in [0.0, 2.0] when present."""
    if temperature is None:
        return
    if not isinstance(temperature, (int, float)) or isinstance(temperature, bool):
        raise RequestValidationError("temperature must be a number")
    if not (0.0 <= float(temperature) <= 2.0):
        raise RequestValidationError(
            f"temperature must be between 0.0 and 2.0, got {temperature}"
        )


def validate_n(n: object) -> None:
    """Validate n — only 1 supported."""
    if n is None:
        return
    if not isinstance(n, int) or isinstance(n, bool) or n <= 0:
        raise RequestValidationError("n must be a positive integer")
    if n > 1:
        raise RequestValidationError(
            "n > 1 is not supported — this proxy returns a single completion"
        )


def validate_openai_payload(payload: dict) -> None:
    """Full validation of an OpenAI /v1/chat/completions payload."""
    validate_model(payload.get("model"))
    validate_messages(payload.get("messages"))
    validate_max_tokens(payload.get("max_tokens"))
    validate_temperature(payload.get("temperature"))
    validate_n(payload.get("n"))


def validate_anthropic_payload(payload: dict) -> None:
    """Full validation of an Anthropic /v1/messages payload.

    Anthropic requires max_tokens to be explicitly provided.
    """
    validate_model(payload.get("model"))
    validate_messages(payload.get("messages"), valid_roles=_VALID_ANTHROPIC_ROLES)
    if payload.get("max_tokens") is None:
        raise RequestValidationError("max_tokens is required for Anthropic messages requests")
    validate_max_tokens(payload.get("max_tokens"))
```

### Step 5 — Run tests again

```bash
python -m pytest tests/test_request_validators.py -x -q
```
Expected: all 27 tests pass.

### Step 6 — Commit

```bash
git add validators/__init__.py validators/request.py tests/test_request_validators.py
git commit -m "feat: add request validators for OpenAI and Anthropic payloads"
```

---

## Task 2: Wire validators into `routers/unified.py`

**Files:**
- Modify: `routers/unified.py`
- Test: extend `tests/test_request_validators.py` with router integration tests

### Step 1 — Append integration tests to `tests/test_request_validators.py`

```python
# ── Router integration ───────────────────────────────────────────────────────

from types import SimpleNamespace
from fastapi.testclient import TestClient
from app import create_app


@pytest.fixture
def app_client():
    return TestClient(create_app())


@pytest.fixture
def bypass(monkeypatch):
    monkeypatch.setattr("routers.unified.verify_bearer", lambda a: "test-key")
    monkeypatch.setattr("routers.unified.enforce_rate_limit", lambda k: None)
    monkeypatch.setattr("routers.unified.check_budget", lambda k: None)
    monkeypatch.setattr("routers.unified.resolve_model", lambda m: m or "cursor-small")
    monkeypatch.setattr("routers.unified.get_http_client", lambda: object())
    monkeypatch.setattr("routers.unified.CursorClient", lambda c: object())
    monkeypatch.setattr("routers.unified.settings", SimpleNamespace(trim_context=False))
    monkeypatch.setattr(
        "routers.unified.context_engine",
        SimpleNamespace(
            trim_to_budget=lambda m, model, tools: (m, 0),
            check_preflight=lambda m, t, model, cm: SimpleNamespace(
                token_count=0, within_budget=True
            ),
        ),
    )


def test_openai_empty_messages_400(app_client, bypass):
    r = app_client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer test-key"},
        json={"model": "cursor-small", "messages": [], "stream": False},
    )
    assert r.status_code == 400
    assert "messages" in r.json()["error"]["message"]


def test_openai_invalid_max_tokens_400(app_client, bypass):
    r = app_client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer test-key"},
        json={
            "model": "cursor-small",
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": -1,
            "stream": False,
        },
    )
    assert r.status_code == 400
    assert "max_tokens" in r.json()["error"]["message"]


def test_openai_invalid_n_400(app_client, bypass):
    r = app_client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer test-key"},
        json={
            "model": "cursor-small",
            "messages": [{"role": "user", "content": "hi"}],
            "n": 3,
            "stream": False,
        },
    )
    assert r.status_code == 400
    assert "n" in r.json()["error"]["message"]


def test_anthropic_missing_max_tokens_400(app_client, bypass):
    r = app_client.post(
        "/v1/messages",
        headers={"Authorization": "Bearer test-key"},
        json={
            "model": "anthropic/claude-sonnet-4.6",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": False,
        },
    )
    assert r.status_code == 400
    assert "max_tokens" in r.json()["error"]["message"]


def test_anthropic_invalid_role_400(app_client, bypass):
    r = app_client.post(
        "/v1/messages",
        headers={"Authorization": "Bearer test-key"},
        json={
            "model": "anthropic/claude-sonnet-4.6",
            "messages": [{"role": "tool", "content": "result"}],
            "max_tokens": 1024,
            "stream": False,
        },
    )
    assert r.status_code == 400
    assert "role" in r.json()["error"]["message"]
```

### Step 2 — Run integration tests to confirm they fail

```bash
python -m pytest tests/test_request_validators.py -k "_400" -x -q
```
Expected: 5 failures (400 not returned yet).

### Step 3 — Wire validators into `routers/unified.py`

Add import at the top of `routers/unified.py` (with the other imports):

```python
from validators.request import validate_anthropic_payload, validate_openai_payload
```

In `chat_completions`, immediately after `payload = await request.json()`, add:

```python
    validate_openai_payload(payload)
```

In `anthropic_messages`, immediately after `payload = await request.json()`, add:

```python
    validate_anthropic_payload(payload)
```

### Step 4 — Run integration tests again

```bash
python -m pytest tests/test_request_validators.py -x -q
```
Expected: all 32 tests pass.

### Step 5 — Run full suite

```bash
python -m pytest tests/ -x -q --ignore=tests/integration
```
Expected: all tests pass.

### Step 6 — Commit

```bash
git add routers/unified.py tests/test_request_validators.py
git commit -m "feat: wire request validators into OpenAI and Anthropic endpoints"
```

---

## Task 3: Structured per-request logging

**Files:**
- Modify: `routers/unified.py`
- No new tests needed — structlog output is validated in integration tests by confirming no 500s on valid requests

### Step 1 — Enrich the OpenAI entry log

In `chat_completions`, after `tools_raw`, `reasoning_effort`, `show_reasoning`, and `json_mode` are extracted, replace the current:

```python
    log.info("openai_request", model=model, stream=stream)
```

with:

```python
    log.info(
        "openai_request",
        model=model,
        stream=stream,
        tool_count=len(tools_raw),
        reasoning_effort=reasoning_effort,
        json_mode=json_mode,
        message_count=len(messages),
    )
```

**Where to place it:** after `json_mode = (...)` and before the context trimming block.

### Step 2 — Enrich the Anthropic entry log

In `anthropic_messages`, replace:

```python
    log.info("anthropic_request", model=model, stream=stream)
```

with:

```python
    log.info(
        "anthropic_request",
        model=model,
        stream=stream,
        tool_count=len(tools_raw),
        has_thinking=thinking is not None,
        message_count=len(messages_raw),
    )
```

**Where to place it:** after `thinking`, `tools_raw`, and `messages_raw` are extracted.

### Step 3 — Add completion log to `_handle_non_streaming`

In `_handle_non_streaming`, after `resp = await handler(client, params, anthropic_tools)`, add:

```python
    _choices = resp.get("choices") or []
    _content = resp.get("content") or []  # Anthropic non-streaming
    _usage = resp.get("usage") or {}
    log.info(
        "request_complete",
        api_style=params.api_style,
        model=params.model,
        finish_reason=(_choices[0].get("finish_reason") if _choices else None),
        stop_reason=(resp.get("stop_reason") if not _choices else None),  # Anthropic
        tool_calls_returned=(
            bool(_choices and (_choices[0].get("message") or {}).get("tool_calls"))
            or any(b.get("type") == "tool_use" for b in _content)
        ),
        input_tokens=_usage.get("prompt_tokens") or _usage.get("input_tokens"),
        output_tokens=_usage.get("completion_tokens") or _usage.get("output_tokens"),
    )
```

**Where to place it:** between `resp = await handler(...)` and the `if idem_key: await complete(...)` line.

### Step 4 — Run full suite to confirm no regressions

```bash
python -m pytest tests/ -x -q --ignore=tests/integration
```
Expected: all tests pass.

### Step 5 — Commit

```bash
git add routers/unified.py
git commit -m "feat: add structured entry and completion logs to both endpoints"
```

---

## Task 4: Final verification + push

### Step 1 — Run full test suite one last time

```bash
python -m pytest tests/ -q --ignore=tests/integration
```
Expected: all pass, 0 failures.

### Step 2 — Push

```bash
git push
```
