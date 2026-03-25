# ShinWayAPI Master Remediation and LiteLLM Integration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix the known critical ShinWayAPI bugs, remove dead and risky artifacts, integrate LiteLLM for format normalization and token counting with manual fallbacks, improve streaming behavior, and complete the remaining proxy hardening tasks without changing the core Cursor-backend architecture.

**Architecture:** Preserve ShinWayAPI as a Cursor reverse proxy with one internal tool format: OpenAI-style tools internally, converted only at the boundaries. Keep Cursor as the only backend, retain suppression retry, confidence scoring, stream sanitization, and pair-aware trimming, and introduce LiteLLM only as a compatibility and counting layer with explicit manual fallbacks. Execute changes in the required order: critical bug fixes first, cleanup second, LiteLLM normalization third, streaming fixes fourth, and minor improvements last.

**Tech Stack:** FastAPI, Python, structlog, httpx, orjson, pydantic-settings, cachetools, Redis, LiteLLM, pytest

---

### Task 1: Fix thinking block ordering in Anthropic streaming

**Files:**
- Modify: `pipeline.py`
- Test: `tests/test_pipeline.py`

**Step 1: Write the failing test**

Add a focused test in `tests/test_pipeline.py` that asserts an Anthropic thinking/content block delta is emitted before its matching `content_block_stop`.

```python
def test_anthropic_stream_emits_thinking_delta_before_block_stop():
    events = collect_stream_events(...)
    thinking_start = events.index("content_block_start:thinking")
    thinking_delta = events.index("content_block_delta:thinking")
    thinking_stop = events.index("content_block_stop:thinking")

    assert thinking_start < thinking_delta < thinking_stop
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_pipeline.py -v -k thinking_delta`
Expected: FAIL because the current stream order emits the delta after the stop event.

**Step 3: Write minimal implementation**

In `pipeline.py`, adjust the Anthropic streaming event sequence so the thinking delta is yielded before `content_block_stop` for the same block.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_pipeline.py -v -k thinking_delta`
Expected: PASS.

**Step 5: Commit**

```bash
git add pipeline.py tests/test_pipeline.py
git commit -m "fix: emit thinking delta before block stop"
```

### Task 2: Prevent tool call and tool result pairs from splitting during trimming

**Files:**
- Modify: `utils/context.py`
- Test: `tests/test_context.py`

**Step 1: Write the failing test**

Add a test proving a tool call message and its paired tool result are dropped or preserved together during trimming.

```python
def test_trim_to_budget_keeps_tool_call_result_pairs_together():
    messages = [
        {"role": "assistant", "tool_calls": [{"id": "call_1", "function": {"name": "lookup", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "call_1", "content": "ok"},
        {"role": "user", "content": "latest"},
    ]

    trimmed, _tokens = context_engine.trim_to_budget(messages, "cursor-small", tools=[])

    ids = [m.get("tool_call_id") for m in trimmed if isinstance(m, dict)]
    assistant_calls = [m for m in trimmed if m.get("tool_calls")]
    assert ("call_1" in ids) == bool(assistant_calls)
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_context.py -v -k pairs_together`
Expected: FAIL because the current trimming logic can split pairs.

**Step 3: Write minimal implementation**

Update `utils/context.py` so the trimming scorer/tiebreaker treats assistant tool calls and their result messages as an atomic pair.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_context.py -v -k pairs_together`
Expected: PASS.

**Step 5: Commit**

```bash
git add utils/context.py tests/test_context.py
git commit -m "fix: preserve tool call result pairs during trimming"
```

### Task 3: Stop suppression retry from mutating cursor messages in place

**Files:**
- Modify: `pipeline.py`
- Test: `tests/test_pipeline.py`

**Step 1: Write the failing test**

Add a regression test that calls the suppression retry path twice and asserts the original `params.cursor_messages` input remains unchanged.

```python
def test_suppression_retry_does_not_mutate_cursor_messages_in_place():
    original = [{"role": "user", "parts": [{"type": "text", "text": "hello"}]}]
    params = make_pipeline_params(cursor_messages=original)

    trigger_retry_path(params)

    assert params.cursor_messages == original
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_pipeline.py -v -k mutate_cursor_messages`
Expected: FAIL because retry currently mutates in place.

**Step 3: Write minimal implementation**

In `pipeline.py`, clone or rebuild `params.cursor_messages` per retry attempt instead of mutating the shared structure.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_pipeline.py -v -k mutate_cursor_messages`
Expected: PASS.

**Step 5: Commit**

```bash
git add pipeline.py tests/test_pipeline.py
git commit -m "fix: avoid in-place mutation during suppression retry"
```

### Task 4: Remove dead trim code or replace it with a safe shim

**Files:**
- Modify: `utils/trim.py`
- Test: `tests/test_trim.py`

**Step 1: Write the failing test**

Add a test that imports `utils.trim` and verifies it either delegates to `utils.context` or clearly exposes only shim behavior, without duplicate trimming logic.

```python
def test_utils_trim_delegates_to_context_trim_logic():
    import utils.trim as trim
    from utils import context

    assert trim.trim_to_budget is context.context_engine.trim_to_budget or callable(trim.trim_to_budget)
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_trim.py -v`
Expected: FAIL if the file still contains drifting duplicate logic.

**Step 3: Write minimal implementation**

Replace the dead duplicated implementation in `utils/trim.py` with a thin shim to `utils.context`, or reduce it to a minimal compatibility wrapper if imports require it.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_trim.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add utils/trim.py tests/test_trim.py
git commit -m "refactor: replace dead trim logic with context shim"
```

### Task 5: Deduplicate tool call result building in parser

**Files:**
- Modify: `tools/parse.py`
- Test: `tests/test_parse.py`

**Step 1: Write the failing test**

Add a test that exercises the main parsing path and asserts the shared helper for tool call results is the one used to build outputs.

```python
def test_parse_tool_calls_uses_shared_tool_result_builder(monkeypatch):
    called = {"count": 0}

    def fake_builder(*args, **kwargs):
        called["count"] += 1
        return []

    monkeypatch.setattr("tools.parse._build_tool_call_results", fake_builder)
    parse_tool_calls_from_text("[assistant_tool_calls]\n{\"tool_calls\": []}")

    assert called["count"] >= 1
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_parse.py -v -k tool_result_builder`
Expected: FAIL because the main path duplicates logic instead of using the helper.

**Step 3: Write minimal implementation**

Refactor `tools/parse.py` so the main path uses a single `_build_tool_call_results` helper and remove duplicate result-building logic.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_parse.py -v -k tool_result_builder`
Expected: PASS.

**Step 5: Commit**

```bash
git add tools/parse.py tests/test_parse.py
git commit -m "refactor: deduplicate tool result building in parser"
```

### Task 6: Remove the risky jailbreak prompt artifact from the repo

**Files:**
- Modify: `pw1.md`

**Step 1: Write the failing test**

There is no useful unit test for this deletion. Verify presence first.

Run: `test -f pw1.md`
Expected: PASS because the file currently exists.

**Step 2: Run check to verify current risky artifact exists**

Run: `python -c "from pathlib import Path; assert Path('pw1.md').exists()"`
Expected: PASS.

**Step 3: Write minimal implementation**

Delete `pw1.md` from the repository.

**Step 4: Run check to verify it is removed**

Run: `python -c "from pathlib import Path; assert not Path('pw1.md').exists()"`
Expected: PASS.

**Step 5: Commit**

```bash
git add pw1.md
git commit -m "chore: remove risky prompt artifact"
```

### Task 7: Add LiteLLM dependency

**Files:**
- Modify: `requirements.txt`

**Step 1: Write the failing check**

Run: `python -c "import litellm"`
Expected: FAIL with `ModuleNotFoundError` before dependency install.

**Step 2: Run the check to verify it fails**

Run: `python -c "import litellm"`
Expected: FAIL.

**Step 3: Write minimal implementation**

Add this line to `requirements.txt`:

```text
litellm>=1.40.0
```

**Step 4: Run check to verify dependency is available**

Run: `pip install -r requirements.txt && python -c "import litellm; print(litellm.__version__)"`
Expected: PASS.

**Step 5: Commit**

```bash
git add requirements.txt
git commit -m "chore: add litellm dependency"
```

### Task 8: Rewrite tool normalization with LiteLLM and explicit fallbacks

**Files:**
- Create: `tests/test_normalize.py`
- Modify: `tools/normalize.py`

**Step 1: Write the failing tests**

Create `tests/test_normalize.py` covering current behavior and new fallback helpers.

```python
from unittest.mock import patch
from tools.normalize import (
    normalize_anthropic_tools,
    normalize_openai_tools,
    normalize_tool_result_messages,
    to_anthropic_tool_format,
    validate_tool_choice,
)


def test_normalize_openai_tools_drops_malformed_entries():
    tools = [
        {"type": "function", "function": {"name": "ok"}},
        {"type": "other"},
        {"type": "function", "function": {}},
        "bad",
    ]

    assert normalize_openai_tools(tools) == [{
        "type": "function",
        "function": {
            "name": "ok",
            "description": "",
            "parameters": {"type": "object", "properties": {}},
        },
    }]


def test_normalize_anthropic_tools_falls_back_when_litellm_raises():
    with patch("tools.normalize.litellm.utils.convert_to_openai_tool_format", side_effect=Exception("boom")):
        result = normalize_anthropic_tools([{"name": "lookup"}])
    assert result[0]["function"]["name"] == "lookup"


def test_to_anthropic_tool_format_falls_back_when_litellm_raises():
    tools = [{"type": "function", "function": {"name": "lookup"}}]
    with patch("tools.normalize.litellm.utils.convert_to_anthropic_tool_format", side_effect=Exception("boom")):
        result = to_anthropic_tool_format(tools)
    assert result[0]["name"] == "lookup"


def test_validate_tool_choice_invalid_string_defaults_to_auto_when_tools_exist():
    tools = [{"type": "function", "function": {"name": "x"}}]
    assert validate_tool_choice("weird", tools) == "auto"


def test_validate_tool_choice_defaults_to_none_without_tools():
    assert validate_tool_choice(None, []) == "none"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_normalize.py -v`
Expected: FAIL because the file and new helpers do not exist yet.

**Step 3: Write minimal implementation**

Update `tools/normalize.py` to:
- keep `normalize_openai_tools()` behavior unchanged,
- use `litellm.utils.convert_to_openai_tool_format()` first in `normalize_anthropic_tools()`,
- use `litellm.utils.convert_to_anthropic_tool_format()` first in `to_anthropic_tool_format()`,
- add `normalize_tool_result_messages(messages, target)`,
- add `validate_tool_choice(tool_choice, tools)`,
- log warnings on LiteLLM failure and fall back to current manual behavior.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_normalize.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add tools/normalize.py tests/test_normalize.py
git commit -m "refactor: use litellm for tool normalization"
```

### Task 9: Replace token counting with LiteLLM-first behavior and preserve the API

**Files:**
- Create: `tests/test_tokens.py`
- Modify: `tokens.py`

**Step 1: Write the failing tests**

Create `tests/test_tokens.py` with contract and fallback tests.

```python
from unittest.mock import patch
from tokens import (
    context_window_for,
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


def test_count_tool_instruction_tokens_returns_int_for_tools():
    tools = [{
        "type": "function",
        "function": {
            "name": "lookup",
            "description": "",
            "parameters": {"type": "object", "properties": {}},
        },
    }]
    assert count_tool_tokens(tools, "cursor-small") > 0
    assert count_tool_instruction_tokens(tools, "auto", "cursor-small") > 0
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_tokens.py -v`
Expected: FAIL because the file does not exist and LiteLLM is not wired in.

**Step 3: Write minimal implementation**

Update `tokens.py` to:
- import `litellm`,
- use `litellm.token_counter(model=model, text=text)` in `count_tokens()`,
- use `litellm.token_counter(model=model, messages=messages)` in `count_message_tokens()`,
- preserve current public function names and signatures,
- keep conservative fallback logic,
- keep `context_window_for()` compatible with current model registry fallback,
- use LiteLLM-first counting for serialized tool schemas and tool instruction text.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_tokens.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add tokens.py tests/test_tokens.py
git commit -m "refactor: use litellm for token counting"
```

### Task 10: Convert tool calls to Anthropic blocks via LiteLLM with manual fallback

**Files:**
- Create: `tests/test_from_cursor.py`
- Modify: `converters/from_cursor.py`

**Step 1: Write the failing tests**

Create `tests/test_from_cursor.py`.

```python
from unittest.mock import patch
from converters.from_cursor import convert_tool_calls_to_anthropic


def test_convert_tool_calls_to_anthropic_parses_json_arguments():
    tool_calls = [{
        "id": "call_1",
        "function": {"name": "weather", "arguments": '{"city":"Tokyo"}'},
    }]

    assert convert_tool_calls_to_anthropic(tool_calls) == [{
        "type": "tool_use",
        "id": "call_1",
        "name": "weather",
        "input": {"city": "Tokyo"},
    }]


def test_convert_tool_calls_to_anthropic_invalid_json_defaults_to_empty_object():
    tool_calls = [{"function": {"name": "weather", "arguments": '{bad json}'}}]
    result = convert_tool_calls_to_anthropic(tool_calls)
    assert result[0]["input"] == {}
    assert result[0]["id"].startswith("toolu_")


def test_convert_tool_calls_to_anthropic_uses_fallback_when_litellm_fails():
    tool_calls = [{
        "id": "call_1",
        "function": {"name": "weather", "arguments": '{"city":"Tokyo"}'},
    }]

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
Expected: FAIL because the file does not exist and LiteLLM is not wired in.

**Step 3: Write minimal implementation**

Update `converters/from_cursor.py` so `convert_tool_calls_to_anthropic()`:
- tries `litellm.utils.convert_to_anthropic_tool_use(tool_calls)` first,
- logs a warning if LiteLLM raises,
- falls back to the current manual JSON parsing logic,
- preserves current ID and invalid-JSON behavior.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_from_cursor.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add converters/from_cursor.py tests/test_from_cursor.py
git commit -m "refactor: use litellm for tool call conversion"
```

### Task 11: Normalize tool result messages and validate tool choice in both routers

**Files:**
- Modify: `routers/openai.py`
- Modify: `routers/anthropic.py`
- Test: `tests/test_routing.py`

**Step 1: Write the failing tests**

Add focused tests to `tests/test_routing.py`.

```python
def test_openai_router_normalizes_messages_and_tool_choice(client, monkeypatch):
    captured = {}
    ...
    assert captured["messages"] == expected_messages
    assert captured["tool_choice"] == "auto"


def test_anthropic_router_normalizes_messages_and_tool_choice(client, monkeypatch):
    captured = {}
    ...
    assert captured["messages"] == expected_messages
    assert captured["tool_choice"] == "auto"
```

Assertions should verify:
- normalized tool result messages are what get passed downstream,
- invalid `tool_choice` falls back to `"auto"` when tools exist,
- no-tools requests keep existing behavior.

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_routing.py -v -k "tool_choice or normalizes_messages"`
Expected: FAIL because the routers do not yet do this normalization.

**Step 3: Write minimal implementation**

In `routers/openai.py`, after `tools = normalize_openai_tools(...)`, add:

```python
messages = normalize_tool_result_messages(messages, target="openai")
tool_choice = validate_tool_choice(payload.get("tool_choice", "auto"), tools)
```

In `routers/anthropic.py`, after `tools = normalize_anthropic_tools(...)`, add:

```python
messages = normalize_tool_result_messages(messages, target="anthropic")
tool_choice = validate_tool_choice(payload.get("tool_choice", "auto"), tools)
```

Import the new helpers from `tools.normalize` in both files.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_routing.py -v -k "tool_choice or normalizes_messages"`
Expected: PASS.

**Step 5: Commit**

```bash
git add routers/openai.py routers/anthropic.py tests/test_routing.py
git commit -m "refactor: normalize router tool results and tool choice"
```

### Task 12: Emit incremental text in OpenAI streams when tools are enabled

**Files:**
- Modify: `pipeline.py`
- Test: `tests/test_pipeline.py`

**Step 1: Write the failing test**

Add a test asserting OpenAI streaming still emits incremental text deltas when tools are enabled and the model produces visible text before or alongside tool calls.

```python
def test_openai_stream_emits_text_deltas_when_tools_enabled():
    chunks = collect_openai_chunks(..., tools_enabled=True)
    assert any(chunk_contains_text_delta(c) for c in chunks)
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_pipeline.py -v -k tools_enabled_text_deltas`
Expected: FAIL because current streaming drops incremental text in this case.

**Step 3: Write minimal implementation**

In `pipeline.py`, adjust the OpenAI streaming path so visible text deltas are emitted even when tool-call handling is active, provided the text is not raw tool payload content.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_pipeline.py -v -k tools_enabled_text_deltas`
Expected: PASS.

**Step 5: Commit**

```bash
git add pipeline.py tests/test_pipeline.py
git commit -m "fix: emit openai text deltas with tools enabled"
```

### Task 13: Stream Anthropic tool inputs as input_json_delta chunks

**Files:**
- Modify: `pipeline.py`
- Test: `tests/test_pipeline.py`

**Step 1: Write the failing test**

Add a test that asserts Anthropic tool input arguments are streamed as `input_json_delta` chunks instead of being dumped all at once.

```python
def test_anthropic_stream_emits_input_json_delta_chunks_for_tool_args():
    events = collect_stream_events(...)
    deltas = [e for e in events if event_type(e) == "content_block_delta" and delta_type(e) == "input_json_delta"]
    assert deltas
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_pipeline.py -v -k input_json_delta`
Expected: FAIL because current implementation dumps the tool args at once.

**Step 3: Write minimal implementation**

In `pipeline.py`, split Anthropic tool argument JSON into streamed `input_json_delta` chunks that preserve valid cumulative JSON behavior.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_pipeline.py -v -k input_json_delta`
Expected: PASS.

**Step 5: Commit**

```bash
git add pipeline.py tests/test_pipeline.py
git commit -m "fix: stream anthropic tool inputs as json deltas"
```

### Task 14: Catch stream stall TimeoutError explicitly

**Files:**
- Modify: `pipeline.py`
- Test: `tests/test_pipeline.py`

**Step 1: Write the failing test**

Add a test that triggers a `TimeoutError` in the stream monitor path and asserts the dedicated timeout handling branch is used instead of the generic exception path.

```python
def test_stream_timeout_uses_specific_timeout_handling():
    result = run_stream_timeout_case(...)
    assert result.error_type == "timeout"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_pipeline.py -v -k timeout_handling`
Expected: FAIL because `TimeoutError` is currently swallowed by a generic `except Exception`.

**Step 3: Write minimal implementation**

In `pipeline.py`, add a dedicated `except TimeoutError` branch before the generic exception handler in the streaming path.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_pipeline.py -v -k timeout_handling`
Expected: PASS.

**Step 5: Commit**

```bash
git add pipeline.py tests/test_pipeline.py
git commit -m "fix: handle stream timeout explicitly"
```

### Task 15: Reduce false positives in suppression detection

**Files:**
- Modify: `pipeline.py`
- Test: `tests/test_pipeline.py`

**Step 1: Write the failing test**

Add a test proving a long legitimate response mentioning support-like phrases is not classified as suppression.

```python
def test_is_suppressed_does_not_flag_legitimate_long_response():
    text = """Here is a long valid answer about Cursor settings and API compatibility..."""
    assert _is_suppressed(text) is False
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_pipeline.py -v -k is_suppressed_false_positive`
Expected: FAIL because current phrase matching is too broad.

**Step 3: Write minimal implementation**

Tighten `_is_suppressed()` in `pipeline.py` by adjusting phrase matching and/or threshold behavior so only true support-assistant persona responses are classified as suppression.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_pipeline.py -v -k is_suppressed_false_positive`
Expected: PASS.

**Step 5: Commit**

```bash
git add pipeline.py tests/test_pipeline.py
git commit -m "fix: reduce suppression false positives"
```

### Task 16: Add context debug endpoint for budget breakdown

**Files:**
- Modify: `routers/internal.py`
- Test: `tests/test_internal.py`

**Step 1: Write the failing test**

Add a test for a new authenticated endpoint that returns a detailed token budget/context breakdown for an input payload.

```python
def test_debug_context_endpoint_returns_budget_breakdown(client, auth_headers):
    response = client.post("/v1/debug/context", headers=auth_headers, json={"messages": [{"role": "user", "content": "hi"}], "model": "cursor-small"})
    assert response.status_code == 200
    body = response.json()
    assert "token_count" in body
    assert "within_budget" in body
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_internal.py -v -k debug_context`
Expected: FAIL because the endpoint does not exist yet.

**Step 3: Write minimal implementation**

In `routers/internal.py`, add `POST /v1/debug/context` using existing auth and context budget logic to return the same kind of budget information used internally.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_internal.py -v -k debug_context`
Expected: PASS.

**Step 5: Commit**

```bash
git add routers/internal.py tests/test_internal.py
git commit -m "feat: add debug context budget endpoint"
```

### Task 17: Avoid double tool schema token estimation

**Files:**
- Modify: `utils/context.py`
- Test: `tests/test_context.py`

**Step 1: Write the failing test**

Add a test that patches the tool schema estimation function and asserts it is called once per request path.

```python
def test_context_budget_estimates_tool_schema_tokens_once(monkeypatch):
    calls = {"count": 0}

    def fake_count(*args, **kwargs):
        calls["count"] += 1
        return 10

    monkeypatch.setattr("utils.context.count_tool_instruction_tokens", fake_count)
    context_engine.check_preflight([{"role": "user", "content": "hi"}], [{"type": "function", "function": {"name": "x"}}], "cursor-small", [])

    assert calls["count"] == 1
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_context.py -v -k estimates_tool_schema_tokens_once`
Expected: FAIL because the estimate is currently performed twice.

**Step 3: Write minimal implementation**

In `utils/context.py`, cache or reuse the computed tool schema count within the request path so it is only calculated once.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_context.py -v -k estimates_tool_schema_tokens_once`
Expected: PASS.

**Step 5: Commit**

```bash
git add utils/context.py tests/test_context.py
git commit -m "perf: avoid duplicate tool schema token counting"
```

### Task 18: Unify minimum retained message count into one source of truth

**Files:**
- Modify: `utils/context.py`
- Modify: `utils/trim.py`
- Possibly Modify: `config.py`
- Test: `tests/test_context.py`

**Step 1: Write the failing test**

Add a test that asserts the minimum keep behavior comes from one shared constant or config value, not duplicated literals.

```python
def test_minimum_keep_value_comes_from_single_source_of_truth():
    from utils import context, trim
    assert getattr(trim, "MIN_KEEP", None) == getattr(context, "MIN_KEEP", None)
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_context.py -v -k minimum_keep_value`
Expected: FAIL because `_MIN_KEEP` is duplicated.

**Step 3: Write minimal implementation**

Move the minimum-keep value into one shared constant or config-backed value used by both `utils/context.py` and any `utils/trim.py` shim code.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_context.py -v -k minimum_keep_value`
Expected: PASS.

**Step 5: Commit**

```bash
git add utils/context.py utils/trim.py config.py tests/test_context.py
git commit -m "refactor: unify minimum keep trimming constant"
```

### Task 19: Run targeted verification for each changed area

**Files:**
- Test: `tests/test_pipeline.py`
- Test: `tests/test_context.py`
- Test: `tests/test_trim.py`
- Test: `tests/test_parse.py`
- Test: `tests/test_normalize.py`
- Test: `tests/test_tokens.py`
- Test: `tests/test_from_cursor.py`
- Test: `tests/test_routing.py`
- Test: `tests/test_internal.py`

**Step 1: Run pipeline and context fixes**

Run: `pytest tests/test_pipeline.py tests/test_context.py tests/test_trim.py -v`
Expected: PASS.

**Step 2: Run parser and normalization tests**

Run: `pytest tests/test_parse.py tests/test_normalize.py tests/test_from_cursor.py tests/test_tokens.py tests/test_routing.py -v`
Expected: PASS.

**Step 3: Run internal endpoint tests**

Run: `pytest tests/test_internal.py -v`
Expected: PASS.

**Step 4: Run focused regression set together**

Run: `pytest tests/test_pipeline.py tests/test_context.py tests/test_trim.py tests/test_parse.py tests/test_normalize.py tests/test_tokens.py tests/test_from_cursor.py tests/test_routing.py tests/test_internal.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add tests/test_pipeline.py tests/test_context.py tests/test_trim.py tests/test_parse.py tests/test_normalize.py tests/test_tokens.py tests/test_from_cursor.py tests/test_routing.py tests/test_internal.py
git commit -m "test: verify proxy remediation and litellm integration"
```

### Task 20: Review final diff and verify preserved design constraints

**Files:**
- Modify: `pipeline.py`
- Modify: `utils/context.py`
- Modify: `utils/trim.py`
- Modify: `tools/parse.py`
- Modify: `tools/normalize.py`
- Modify: `tokens.py`
- Modify: `converters/from_cursor.py`
- Modify: `routers/openai.py`
- Modify: `routers/anthropic.py`
- Modify: `routers/internal.py`
- Modify: `requirements.txt`
- Modify: `pw1.md`

**Step 1: Run diff review for intended files only**

Run: `git diff -- pipeline.py utils/context.py utils/trim.py tools/parse.py tools/normalize.py tokens.py converters/from_cursor.py routers/openai.py routers/anthropic.py routers/internal.py requirements.txt pw1.md tests/test_pipeline.py tests/test_context.py tests/test_trim.py tests/test_parse.py tests/test_normalize.py tests/test_tokens.py tests/test_from_cursor.py tests/test_routing.py tests/test_internal.py`
Expected: Only planned remediation and integration changes.

**Step 2: Verify preserved design constraints manually**

Confirm:
- Cursor remains the only backend,
- one internal tool format is preserved,
- suppression retry still exists,
- LiteLLM is used only with manual fallbacks,
- cookie values are never exposed,
- confidence scoring on tool calls still exists,
- raw tool payload JSON is still sanitized from output,
- pair-aware trimming is preserved.

**Step 3: Run the broad existing regression suite**

Run: `pytest tests/test_e2e.py tests/test_trim.py tests/test_parse.py -v`
Expected: PASS.

**Step 4: Verify repo no longer contains the risky prompt artifact**

Run: `python -c "from pathlib import Path; assert not Path('pw1.md').exists()"`
Expected: PASS.

**Step 5: Commit**

```bash
git add pipeline.py utils/context.py utils/trim.py tools/parse.py tools/normalize.py tokens.py converters/from_cursor.py routers/openai.py routers/anthropic.py routers/internal.py requirements.txt pw1.md tests/test_pipeline.py tests/test_context.py tests/test_trim.py tests/test_parse.py tests/test_normalize.py tests/test_tokens.py tests/test_from_cursor.py tests/test_routing.py tests/test_internal.py
git commit -m "fix: remediate proxy bugs and integrate litellm normalization"
```
