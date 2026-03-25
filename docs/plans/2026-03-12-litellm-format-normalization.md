# LiteLLM Format Normalization Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Integrate LiteLLM as an internal normalization and token-counting layer while preserving current external OpenAI- and Anthropic-compatible behavior.

**Architecture:** Keep Cursor as the backend and preserve the current internal OpenAI-style representation for tools. Introduce LiteLLM as the primary translation and token-counting layer only at the normalization/conversion boundaries, with the current manual logic retained as explicit fallback behavior. Router changes stay minimal and local, while public function signatures and response shapes remain unchanged.

**Tech Stack:** FastAPI, Python, structlog, orjson, LiteLLM, pytest

---

### Task 1: Lock current normalization behavior with regression tests

**Files:**
- Create: `tests/test_normalize.py`
- Modify: `tools/normalize.py`

**Step 1: Write the failing tests**

```python
from tools.normalize import (
    normalize_anthropic_tools,
    normalize_openai_tools,
    to_anthropic_tool_format,
)


def test_normalize_openai_tools_drops_malformed_entries():
    tools = [
        {"type": "function", "function": {"name": "ok"}},
        {"type": "other"},
        {"type": "function", "function": {}},
        "bad",
    ]

    assert normalize_openai_tools(tools) == [
        {
            "type": "function",
            "function": {
                "name": "ok",
                "description": "",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]


def test_normalize_anthropic_tools_defaults_missing_schema():
    tools = [{"name": "lookup"}]

    assert normalize_anthropic_tools(tools) == [
        {
            "type": "function",
            "function": {
                "name": "lookup",
                "description": "",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]


def test_to_anthropic_tool_format_preserves_current_shape():
    tools = [
        {
            "type": "function",
            "function": {
                "name": "search",
                "description": "Find data",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]

    assert to_anthropic_tool_format(tools) == [
        {
            "name": "search",
            "description": "Find data",
            "input_schema": {"type": "object", "properties": {}},
        }
    ]
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_normalize.py -v`
Expected: FAIL because the new test file does not exist yet.

**Step 3: Write minimal test file implementation**

Create `tests/test_normalize.py` with the tests above.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_normalize.py -v`
Expected: PASS against current code.

**Step 5: Commit**

```bash
git add tests/test_normalize.py
git commit -m "test: lock tool normalization behavior"
```

### Task 2: Lock current tool-call conversion behavior

**Files:**
- Create: `tests/test_from_cursor.py`
- Modify: `converters/from_cursor.py`

**Step 1: Write the failing tests**

```python
from converters.from_cursor import convert_tool_calls_to_anthropic


def test_convert_tool_calls_to_anthropic_parses_json_arguments():
    tool_calls = [
        {
            "id": "call_1",
            "function": {
                "name": "weather",
                "arguments": '{"city":"Tokyo"}',
            },
        }
    ]

    assert convert_tool_calls_to_anthropic(tool_calls) == [
        {
            "type": "tool_use",
            "id": "call_1",
            "name": "weather",
            "input": {"city": "Tokyo"},
        }
    ]


def test_convert_tool_calls_to_anthropic_invalid_json_defaults_to_empty_object():
    tool_calls = [
        {
            "function": {
                "name": "weather",
                "arguments": '{bad json}',
            },
        }
    ]

    result = convert_tool_calls_to_anthropic(tool_calls)

    assert result[0]["type"] == "tool_use"
    assert result[0]["name"] == "weather"
    assert result[0]["input"] == {}
    assert result[0]["id"].startswith("toolu_")
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_from_cursor.py -v`
Expected: FAIL because the new test file does not exist yet.

**Step 3: Write minimal test file implementation**

Create `tests/test_from_cursor.py` with the tests above.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_from_cursor.py -v`
Expected: PASS against current code.

**Step 5: Commit**

```bash
git add tests/test_from_cursor.py
git commit -m "test: lock tool call conversion behavior"
```

### Task 3: Lock token API behavior at the public boundary

**Files:**
- Create: `tests/test_tokens.py`
- Modify: `tokens.py`

**Step 1: Write the failing tests**

```python
from tokens import (
    context_window_for,
    count_cursor_messages,
    count_message_tokens,
    count_tokens,
    count_tool_instruction_tokens,
    count_tool_tokens,
    estimate_from_messages,
    estimate_from_text,
)


def test_count_tokens_returns_positive_int():
    result = count_tokens("hello world", "anthropic/claude-sonnet-4.6")
    assert isinstance(result, int)
    assert result > 0


def test_count_message_tokens_handles_empty_messages():
    result = count_message_tokens([], "anthropic/claude-sonnet-4.6")
    assert isinstance(result, int)
    assert result > 0


def test_estimate_aliases_match_primary_functions():
    messages = [{"role": "user", "content": "hi"}]
    assert estimate_from_text("hi", "cursor-small") == count_tokens("hi", "cursor-small")
    assert estimate_from_messages(messages, "cursor-small") == count_message_tokens(messages, "cursor-small")


def test_context_window_for_known_model_is_unchanged():
    assert context_window_for("anthropic/claude-sonnet-4.6") == 200_000


def test_count_tool_instruction_tokens_returns_int_for_tools():
    tools = [
        {
            "type": "function",
            "function": {
                "name": "lookup",
                "description": "",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]

    result = count_tool_tokens(tools, "cursor-small")
    assert isinstance(result, int)
    assert result > 0

    result2 = count_tool_instruction_tokens(tools, "auto", "cursor-small")
    assert isinstance(result2, int)
    assert result2 > 0
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_tokens.py -v`
Expected: FAIL because the new test file does not exist yet.

**Step 3: Write minimal test file implementation**

Create `tests/test_tokens.py` with the tests above.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_tokens.py -v`
Expected: PASS against current code.

**Step 5: Commit**

```bash
git add tests/test_tokens.py
git commit -m "test: lock token api behavior"
```

### Task 4: Add router-level regression coverage for tool normalization hooks

**Files:**
- Modify: `tests/test_routing.py`
- Modify: `routers/openai.py`
- Modify: `routers/anthropic.py`

**Step 1: Write the failing tests**

Add focused tests to `tests/test_routing.py` covering:

```python
def test_openai_router_normalizes_tool_result_messages(...):
    ...


def test_openai_router_invalid_tool_choice_defaults_to_auto(...):
    ...


def test_anthropic_router_normalizes_tool_result_messages(...):
    ...


def test_anthropic_router_invalid_tool_choice_defaults_to_auto(...):
    ...
```

Assertions should verify:
- no-tools requests still succeed,
- invalid `tool_choice` becomes `"auto"` when tools exist,
- missing tools still fall back to `"none"` or existing default behavior,
- normalized messages are what gets passed downstream.

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_routing.py -v`
Expected: FAIL because the new assertions target behavior not implemented yet.

**Step 3: Write minimal test updates**

Use the existing testing style in `tests/test_routing.py`. Patch downstream functions at the router boundary and assert on the arguments received.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_routing.py -v`
Expected: PASS once router changes are implemented later in the plan.

**Step 5: Commit**

```bash
git add tests/test_routing.py
git commit -m "test: cover router tool normalization hooks"
```

### Task 5: Add LiteLLM dependency

**Files:**
- Modify: `requirements.txt`

**Step 1: Write the failing test**

There is no meaningful unit test for dependency declaration alone. Instead, use import verification in the next task.

**Step 2: Run check to verify dependency is absent**

Run: `python -c "import litellm"`
Expected: FAIL with `ModuleNotFoundError` before installation.

**Step 3: Write minimal implementation**

Add this line to `requirements.txt`:

```text
litellm>=1.40.0
```

**Step 4: Run check to verify dependency is available**

Run: `pip install -r requirements.txt && python -c "import litellm; print(litellm.__version__)"`
Expected: PASS and print a LiteLLM version.

**Step 5: Commit**

```bash
git add requirements.txt
git commit -m "chore: add litellm dependency"
```

### Task 6: Rewrite tool normalization to LiteLLM-first with manual fallback

**Files:**
- Modify: `tools/normalize.py`
- Test: `tests/test_normalize.py`

**Step 1: Write the failing tests**

Extend `tests/test_normalize.py` with fallback-focused tests:

```python
from unittest.mock import patch
from tools.normalize import (
    normalize_anthropic_tools,
    normalize_tool_result_messages,
    to_anthropic_tool_format,
    validate_tool_choice,
)


def test_normalize_anthropic_tools_falls_back_when_litellm_raises():
    with patch("tools.normalize.litellm.utils.convert_to_openai_tool_format", side_effect=Exception("boom")):
        assert normalize_anthropic_tools([{"name": "lookup"}])[0]["function"]["name"] == "lookup"


def test_to_anthropic_tool_format_falls_back_when_litellm_raises():
    tools = [{"type": "function", "function": {"name": "lookup"}}]
    with patch("tools.normalize.litellm.utils.convert_to_anthropic_tool_format", side_effect=Exception("boom")):
        assert to_anthropic_tool_format(tools)[0]["name"] == "lookup"


def test_validate_tool_choice_invalid_string_defaults_to_auto_when_tools_exist():
    assert validate_tool_choice("weird", [{"type": "function", "function": {"name": "x"}}]) == "auto"


def test_validate_tool_choice_defaults_to_none_without_tools():
    assert validate_tool_choice(None, []) == "none"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_normalize.py -v`
Expected: FAIL because the new functions and LiteLLM-backed paths do not exist yet.

**Step 3: Write minimal implementation**

Update `tools/normalize.py` to:
- import `litellm` and `structlog`,
- keep `normalize_openai_tools()` behavior unchanged,
- make `normalize_anthropic_tools()` LiteLLM-first via `convert_to_openai_tool_format()` with manual fallback,
- make `to_anthropic_tool_format()` LiteLLM-first via `convert_to_anthropic_tool_format()` with manual fallback,
- add `normalize_tool_result_messages(messages, target)`,
- add `validate_tool_choice(tool_choice, tools)`.

The fallback behavior must preserve the exact current output shapes.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_normalize.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add tools/normalize.py tests/test_normalize.py
git commit -m "refactor: use litellm for tool normalization"
```

### Task 7: Apply message normalization and tool-choice validation in the OpenAI router

**Files:**
- Modify: `routers/openai.py`
- Test: `tests/test_routing.py`

**Step 1: Write the failing test**

Add/complete a test like:

```python
def test_openai_router_normalizes_messages_and_tool_choice(client, monkeypatch):
    captured = {}
    ...
    assert captured["messages"] == expected_messages
    assert captured["tool_choice"] == "auto"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_routing.py -v -k openai`
Expected: FAIL because the router does not yet normalize message history or validate `tool_choice`.

**Step 3: Write minimal implementation**

In `routers/openai.py`:
- import `normalize_tool_result_messages` and `validate_tool_choice`,
- after `tools = normalize_openai_tools(...)`, add:

```python
messages = normalize_tool_result_messages(messages, target="openai")
tool_choice = validate_tool_choice(payload.get("tool_choice", "auto"), tools)
```

Preserve all other existing behavior.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_routing.py -v -k openai`
Expected: PASS.

**Step 5: Commit**

```bash
git add routers/openai.py tests/test_routing.py
git commit -m "refactor: normalize openai tool message inputs"
```

### Task 8: Apply message normalization and tool-choice validation in the Anthropic router

**Files:**
- Modify: `routers/anthropic.py`
- Test: `tests/test_routing.py`

**Step 1: Write the failing test**

Add/complete a test like:

```python
def test_anthropic_router_normalizes_messages_and_tool_choice(client, monkeypatch):
    captured = {}
    ...
    assert captured["messages"] == expected_messages
    assert captured["tool_choice"] == "auto"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_routing.py -v -k anthropic`
Expected: FAIL because the router does not yet normalize message history or validate `tool_choice`.

**Step 3: Write minimal implementation**

In `routers/anthropic.py`:
- import `normalize_tool_result_messages` and `validate_tool_choice`,
- after `tools = normalize_anthropic_tools(...)`, add:

```python
messages = normalize_tool_result_messages(messages, target="anthropic")
tool_choice = validate_tool_choice(payload.get("tool_choice", "auto"), tools)
```

Preserve all other existing behavior.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_routing.py -v -k anthropic`
Expected: PASS.

**Step 5: Commit**

```bash
git add routers/anthropic.py tests/test_routing.py
git commit -m "refactor: normalize anthropic tool message inputs"
```

### Task 9: Switch tool-call conversion to LiteLLM-first with fallback

**Files:**
- Modify: `converters/from_cursor.py`
- Test: `tests/test_from_cursor.py`

**Step 1: Write the failing test**

Extend `tests/test_from_cursor.py`:

```python
from unittest.mock import patch


def test_convert_tool_calls_to_anthropic_uses_fallback_when_litellm_fails():
    tool_calls = [{"id": "call_1", "function": {"name": "weather", "arguments": '{"city":"Tokyo"}'}}]

    with patch("litellm.utils.convert_to_anthropic_tool_use", side_effect=Exception("boom")):
        result = convert_tool_calls_to_anthropic(tool_calls)

    assert result == [{
        "type": "tool_use",
        "id": "call_1",
        "name": "weather",
        "input": {"city": "Tokyo"},
    }]
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_from_cursor.py -v`
Expected: FAIL because the LiteLLM-first path does not exist yet.

**Step 3: Write minimal implementation**

Update `convert_tool_calls_to_anthropic()` in `converters/from_cursor.py` to:
- try `litellm.utils.convert_to_anthropic_tool_use(tool_calls)` first,
- log warning on exception,
- fall back to the existing manual conversion logic,
- preserve existing synthetic-id and invalid-JSON behavior.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_from_cursor.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add converters/from_cursor.py tests/test_from_cursor.py
git commit -m "refactor: use litellm for tool call conversion"
```

### Task 10: Replace primary token counting with LiteLLM while preserving public API

**Files:**
- Modify: `tokens.py`
- Test: `tests/test_tokens.py`

**Step 1: Write the failing tests**

Extend `tests/test_tokens.py` with fallback-focused tests:

```python
from unittest.mock import patch
from tokens import count_message_tokens, count_tokens


def test_count_tokens_falls_back_when_litellm_raises():
    with patch("tokens.litellm.token_counter", side_effect=Exception("boom")):
        result = count_tokens("hello", "cursor-small")
    assert isinstance(result, int)
    assert result > 0


def test_count_message_tokens_falls_back_when_litellm_raises():
    messages = [{"role": "user", "content": "hi"}]
    with patch("tokens.litellm.token_counter", side_effect=Exception("boom")):
        result = count_message_tokens(messages, "cursor-small")
    assert isinstance(result, int)
    assert result > 0
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_tokens.py -v`
Expected: FAIL because `tokens.py` does not yet use LiteLLM.

**Step 3: Write minimal implementation**

Update `tokens.py` to:
- import `litellm`,
- make `count_tokens()` call `litellm.token_counter(model=model, text=text)` first,
- make `count_message_tokens()` call `litellm.token_counter(model=model, messages=messages)` first,
- keep public function names and signatures unchanged,
- retain conservative fallback behavior for failures,
- keep `context_window_for()` compatible with the current model registry fallback,
- make `count_tool_tokens()` and `count_tool_instruction_tokens()` LiteLLM-first over serialized text.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_tokens.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add tokens.py tests/test_tokens.py
git commit -m "refactor: use litellm for token counting"
```

### Task 11: Run targeted verification for each changed area

**Files:**
- Test: `tests/test_normalize.py`
- Test: `tests/test_from_cursor.py`
- Test: `tests/test_tokens.py`
- Test: `tests/test_routing.py`

**Step 1: Run normalization tests**

Run: `pytest tests/test_normalize.py -v`
Expected: PASS.

**Step 2: Run converter tests**

Run: `pytest tests/test_from_cursor.py -v`
Expected: PASS.

**Step 3: Run token tests**

Run: `pytest tests/test_tokens.py -v`
Expected: PASS.

**Step 4: Run routing tests**

Run: `pytest tests/test_routing.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add tests/test_normalize.py tests/test_from_cursor.py tests/test_tokens.py tests/test_routing.py
git commit -m "test: verify litellm normalization integration"
```

### Task 12: Run broader regression verification before completion

**Files:**
- Modify: `requirements.txt`
- Modify: `tools/normalize.py`
- Modify: `routers/openai.py`
- Modify: `routers/anthropic.py`
- Modify: `converters/from_cursor.py`
- Modify: `tokens.py`

**Step 1: Run focused existing regression tests**

Run: `pytest tests/test_e2e.py tests/test_trim.py tests/test_parse.py -v`
Expected: PASS.

**Step 2: Run the full changed-area suite together**

Run: `pytest tests/test_normalize.py tests/test_from_cursor.py tests/test_tokens.py tests/test_routing.py -v`
Expected: PASS.

**Step 3: Review diff for unintended API changes**

Run: `git diff -- requirements.txt tools/normalize.py routers/openai.py routers/anthropic.py converters/from_cursor.py tokens.py tests/test_normalize.py tests/test_from_cursor.py tests/test_tokens.py tests/test_routing.py`
Expected: Only the planned internal integration changes.

**Step 4: Verify no public behavior contract was altered**

Confirm manually:
- Cursor backend code is untouched,
- response shapes are unchanged,
- public function names/signatures in `tokens.py` are unchanged,
- tool normalization remains permissive and fallback-safe.

**Step 5: Commit**

```bash
git add requirements.txt tools/normalize.py routers/openai.py routers/anthropic.py converters/from_cursor.py tokens.py tests/test_normalize.py tests/test_from_cursor.py tests/test_tokens.py tests/test_routing.py
git commit -m "refactor: integrate litellm for format normalization"
```
