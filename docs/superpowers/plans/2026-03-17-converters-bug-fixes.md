# Converters Bug Fixes Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 9 bugs in the `converters/` package covering silent data loss, dead code paths, fake streaming, missing SSE events, and logic inconsistencies.

**Architecture:** Surgical edits only — no new files, no refactors beyond what each bug demands. Each task is independently testable. Ordered by severity: data-loss first, structural second, streaming last.

**Tech Stack:** Python 3.11+, FastAPI, pytest, structlog, litellm (optional), msgspec

---

## Chunk 1: Data-Loss and Dead-Path Bugs (BUG 1, 2, 3)

### Task 1: BUG 2 — Log warning instead of silent discard for malformed tool arguments

**Files:**
- Modify: `converters/from_cursor.py` — `_parse_tool_call_arguments`
- Test: `tests/test_from_cursor.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_from_cursor.py`:

```python
def test_parse_tool_call_arguments_warns_on_malformed_json(caplog):
    """Malformed JSON arguments must emit a warning, not silently discard."""
    import logging
    tool_calls = [{"id": "call_x", "function": {"name": "run", "arguments": "{bad json here}"}}]
    with caplog.at_level(logging.WARNING):
        result = convert_tool_calls_to_anthropic(tool_calls)
    assert result[0]["input"] == {}  # fallback still returns empty dict
    assert any("tool_call_arguments_parse_failed" in r.message for r in caplog.records)
```

- [ ] **Step 2: Run to confirm FAIL**

```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/test_from_cursor.py::test_parse_tool_call_arguments_warns_on_malformed_json -v
```

Expected: FAIL — no warning emitted currently.

- [ ] **Step 3: Fix `_parse_tool_call_arguments` in `converters/from_cursor.py`**

Replace the function body (lines 254-260):

```python
def _parse_tool_call_arguments(arguments: object) -> object:
    if isinstance(arguments, str):
        try:
            return json.loads(arguments)
        except json.JSONDecodeError:
            log.warning(
                "tool_call_arguments_parse_failed",
                raw=arguments[:200],
            )
            return {}
    return arguments if arguments is not None else {}
```

- [ ] **Step 4: Run to confirm PASS**

```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/test_from_cursor.py -v
```

- [ ] **Step 5: Commit**

```bash
git add converters/from_cursor.py tests/test_from_cursor.py
git commit -m "fix(converters): log warning on malformed tool call arguments instead of silent discard"
```

---

### Task 2: BUG 3 — litellm converter receives dict instead of JSON string for arguments

**Files:**
- Modify: `converters/from_cursor.py` — `convert_tool_calls_to_anthropic`
- Test: `tests/test_from_cursor.py`

Root cause: arguments are pre-parsed to dict before litellm sees them. litellm expects a JSON string per the OpenAI spec. The litellm path is effectively dead — it always fails and falls back to the manual path. Also removes the redundant second `copy.deepcopy`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_from_cursor.py`:

```python
def test_convert_tool_calls_litellm_receives_string_arguments():
    """litellm converter must receive arguments as a JSON string, not a parsed dict."""
    from unittest.mock import patch
    import converters.from_cursor as fc_mod

    received = {}

    def capturing_converter(tcs):
        for tc in tcs:
            received["type"] = type(tc.get("function", {}).get("arguments")).__name__
        return []  # trigger manual fallback for result

    fake_utils = type("U", (), {"convert_to_anthropic_tool_use": staticmethod(capturing_converter)})()
    fake_litellm = type("L", (), {"utils": fake_utils})()

    with patch.object(fc_mod, "litellm", fake_litellm):
        fc_mod.convert_tool_calls_to_anthropic(
            [{"id": "c1", "function": {"name": "f", "arguments": '{"k": 1}'}}]
        )

    assert received.get("type") == "str", (
        f"Expected str, got {received.get('type')!r} — litellm received a dict"
    )
```

- [ ] **Step 2: Run to confirm FAIL**

```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/test_from_cursor.py::test_convert_tool_calls_litellm_receives_string_arguments -v
```

Expected: FAIL — type will be `dict`.

- [ ] **Step 3: Fix `convert_tool_calls_to_anthropic` in `converters/from_cursor.py`**

Replace lines 288-305:

```python
def convert_tool_calls_to_anthropic(tool_calls: list[dict]) -> list[dict]:
    """Convert OpenAI-style tool_calls to Anthropic tool_use blocks.

    litellm's converter expects arguments as a JSON string (OpenAI wire format).
    Argument parsing to dict is deferred to the manual fallback path only.
    """
    tool_calls = copy.deepcopy(tool_calls or [])

    converter = getattr(getattr(litellm, "utils", None), "convert_to_anthropic_tool_use", None)
    if converter is None:
        # No litellm — parse arguments inline for manual converter
        for tc in tool_calls:
            fn = tc.get("function")
            if isinstance(fn, dict):
                fn["arguments"] = _parse_tool_call_arguments(fn.get("arguments", {}))
        return _manual_convert_tool_calls_to_anthropic(tool_calls)

    try:
        # Pass raw tool_calls with arguments as JSON string — what litellm expects
        return converter(tool_calls)
    except Exception as exc:
        log.warning("litellm_anthropic_tool_use_conversion_failed", error=str(exc))
        # Fall back: now parse arguments to dict for manual path
        for tc in tool_calls:
            fn = tc.get("function")
            if isinstance(fn, dict):
                fn["arguments"] = _parse_tool_call_arguments(fn.get("arguments", {}))
        return _manual_convert_tool_calls_to_anthropic(tool_calls)
```

- [ ] **Step 4: Run all from_cursor tests**

```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/test_from_cursor.py -v
```

- [ ] **Step 5: Commit**

```bash
git add converters/from_cursor.py tests/test_from_cursor.py
git commit -m "fix(converters): pass arguments as JSON string to litellm converter, remove double deepcopy"
```

---

### Task 3: BUG 1 — Remove duplicate `context_window_for` in `from_cursor.py`, import from `tokens`

**Files:**
- Modify: `converters/from_cursor.py` — remove lines 24-42, add import
- Test: `tests/test_from_cursor.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_from_cursor.py`:

```python
def test_from_cursor_context_window_for_is_from_tokens():
    """from_cursor must not define context_window_for locally — must import from tokens."""
    import tokens as tokens_mod
    import converters.from_cursor as fc_mod
    assert fc_mod.context_window_for is tokens_mod.context_window_for, (
        "context_window_for should be imported from tokens, not defined locally in from_cursor"
    )
```

- [ ] **Step 2: Run to confirm FAIL**

```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/test_from_cursor.py::test_from_cursor_context_window_for_is_from_tokens -v
```

Expected: FAIL — local definition exists.

- [ ] **Step 3: Remove local registry from `converters/from_cursor.py`**

Delete lines 24-42 in `converters/from_cursor.py` (the `MODEL_CONTEXT_WINDOWS` dict, `DEFAULT_CONTEXT_WINDOW` constant, and `context_window_for` function).

Add this import after the existing imports block:

```python
from tokens import context_window_for
```

Verify no stale references remain:

```bash
grep -n 'MODEL_CONTEXT_WINDOWS\|DEFAULT_CONTEXT_WINDOW' /teamspace/studios/this_studio/wiwi/converters/from_cursor.py
```

Expected: no output.

- [ ] **Step 4: Run tests**

```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/test_from_cursor.py tests/test_tokens.py -v
```

- [ ] **Step 5: Commit**

```bash
git add converters/from_cursor.py tests/test_from_cursor.py
git commit -m "fix(converters): remove duplicate context_window_for, import canonical from tokens"
```

---

## Chunk 2: Logic Correctness Bugs (BUG 4, 5, 6, 9)

### Task 4: BUG 4 — Reasoning instruction injected after identity pair in Anthropic path, before it in OpenAI path

**Files:**
- Modify: `converters/to_cursor.py` — `anthropic_to_cursor` function (~lines 553-567)
- Test: `tests/test_to_cursor.py` (create if absent)

In `openai_to_cursor`, reasoning is injected before the fake assistant/user pair. In `anthropic_to_cursor`, it is injected after. Both paths should be consistent: reasoning instruction must appear before the identity re-declaration so the model's fake agreement acknowledges it.

- [ ] **Step 1: Write the failing test**

Create or append to `tests/test_to_cursor.py`:

```python
"""Tests for converters/to_cursor.py"""
from converters.to_cursor import openai_to_cursor, anthropic_to_cursor


def _msg_texts(msgs):
    return [m["parts"][0]["text"] for m in msgs]


def test_anthropic_to_cursor_reasoning_before_identity_declaration():
    """Reasoning instruction must appear before the identity re-declaration in Anthropic path."""
    msgs, _ = anthropic_to_cursor(
        messages=[{"role": "user", "content": "hello"}],
        thinking={"type": "enabled", "budget_tokens": 1024},
        model="cursor-small",
    )
    texts = _msg_texts(msgs)
    # Find positions
    reasoning_idx = next((i for i, t in enumerate(texts) if "Reasoning effort" in t), None)
    identity_idx = next((i for i, t in enumerate(texts) if "I'm ready to work" in t), None)
    assert reasoning_idx is not None, "Reasoning instruction not found"
    assert identity_idx is not None, "Identity declaration not found"
    assert reasoning_idx < identity_idx, (
        f"Reasoning (pos {reasoning_idx}) must precede identity declaration (pos {identity_idx})"
    )


def test_openai_to_cursor_reasoning_before_identity_declaration():
    """Reasoning instruction must appear before the identity re-declaration in OpenAI path."""
    msgs = openai_to_cursor(
        messages=[{"role": "user", "content": "hello"}],
        reasoning_effort="high",
        model="cursor-small",
    )
    texts = _msg_texts(msgs)
    reasoning_idx = next((i for i, t in enumerate(texts) if "Reasoning effort" in t), None)
    identity_idx = next((i for i, t in enumerate(texts) if "I'm ready to work" in t), None)
    assert reasoning_idx is not None
    assert identity_idx is not None
    assert reasoning_idx < identity_idx
```

- [ ] **Step 2: Run to see which path fails**

```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/test_to_cursor.py -v
```

Expected: `test_anthropic_to_cursor_reasoning_before_identity_declaration` FAILS.

- [ ] **Step 3: Fix `anthropic_to_cursor` in `converters/to_cursor.py`**

In `anthropic_to_cursor`, the reasoning block (lines ~553-567) currently appears **after** the identity re-declaration pair. Move it to appear **before** the identity re-declaration block, matching `openai_to_cursor`.

The current order in `anthropic_to_cursor` is:
1. system prompt, client system text, role override, tool instruction
2. identity re-declaration (`_msg("assistant", ...)` + `_msg("user", ...)`)
3. last-word tool reinforcer
4. **reasoning** ← wrong position
5. thinking budget

The correct order (matching `openai_to_cursor`) is:
1. system prompt, client system text, role override, tool instruction
2. **reasoning** ← move here
3. **thinking budget** ← move here
4. identity re-declaration
5. last-word tool reinforcer

Edit `converters/to_cursor.py`. Locate the reasoning block (~line 553):
```python
    # Reasoning
    if reasoning_effort:
        txt = f"Reasoning effort preference: {reasoning_effort}."
        txt += (
            " Include a visible short 'thinking' section before the final answer"
            " using: <thinking>...</thinking> then <final>...</final>."
        )
        cursor_messages.append(_msg("system", txt))

    if thinking and thinking.get("budget_tokens"):
        cursor_messages.append(_msg(
            "system",
            f"Extended thinking budget: {thinking['budget_tokens']} tokens. "
            "Think deeply and use your full reasoning budget before responding.",
        ))
```

Cut both blocks and paste them immediately after the tool instruction block (after `if tool_inst: cursor_messages.append(...)`) and before the identity re-declaration block (`if settings.role_override_enabled: cursor_messages.append(_msg("assistant", ...))`).

- [ ] **Step 4: Run tests**

```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/test_to_cursor.py -v
```

- [ ] **Step 5: Commit**

```bash
git add converters/to_cursor.py tests/test_to_cursor.py
git commit -m "fix(converters): inject reasoning instruction before identity declaration in anthropic_to_cursor"
```

---

### Task 5: BUG 5 — Anthropic tool_use blocks in history missing `id` field in Cursor wire format

**Files:**
- Modify: `converters/to_cursor.py` — `anthropic_to_cursor` inline `tool_use` block serialization (~lines 626-635)
- Test: `tests/test_to_cursor.py`

When replaying Anthropic `tool_use` history to Cursor, the emitted `[assistant_tool_calls]` JSON uses `{"tool_calls": [{"name": ..., "arguments": ...}]}` — the tool call has no `id` field. The upstream model cannot correlate these with `tool_result` blocks. The `id` must be included.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_to_cursor.py`:

```python
import json


def test_anthropic_tool_use_history_includes_id_in_cursor_wire():
    """tool_use blocks replayed to Cursor must include id for result correlation."""
    msgs, _ = anthropic_to_cursor(
        messages=[
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_abc123",
                        "name": "calc",
                        "input": {"x": 1},
                    }
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_abc123",
                        "content": "42",
                    }
                ],
            },
        ],
        model="cursor-small",
    )
    # Find the assistant message with [assistant_tool_calls]
    tool_call_msg = next(
        (m for m in msgs if "[assistant_tool_calls]" in m["parts"][0]["text"]),
        None,
    )
    assert tool_call_msg is not None, "No [assistant_tool_calls] message found"
    raw = tool_call_msg["parts"][0]["text"]
    payload_str = raw[raw.index("\n") + 1 :]
    payload = json.loads(payload_str)
    tc = payload["tool_calls"][0]
    assert "id" in tc, f"tool_call must include 'id' field, got: {tc}"
    assert tc["id"] == "toolu_abc123"
```

- [ ] **Step 2: Run to confirm FAIL**

```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/test_to_cursor.py::test_anthropic_tool_use_history_includes_id_in_cursor_wire -v
```

- [ ] **Step 3: Fix the `tool_use` block serialization in `anthropic_to_cursor`**

Locate the `elif btype == "tool_use":` block (~line 623). The current serialization:

```python
                elif btype == "tool_use":
                    # F5: don't sanitize tool_use block — name/input should be verbatim
                    _flush_text()
                    one = {
                        "tool_calls": [
                            {
                                "name": block.get("name"),
                                "arguments": json.dumps(block.get("input", {}), ensure_ascii=False),
                            }
                        ]
                    }
                    cursor_messages.append(
                        _msg("assistant", f"[assistant_tool_calls]\n{json.dumps(one, ensure_ascii=False)}")
                    )
```

Replace with (add `id` field):

```python
                elif btype == "tool_use":
                    # F5: don't sanitize tool_use block — name/input should be verbatim
                    _flush_text()
                    one = {
                        "tool_calls": [
                            {
                                "id": block.get("id", f"call_{uuid.uuid4().hex[:24]}"),
                                "name": block.get("name"),
                                "arguments": json.dumps(block.get("input", {}), ensure_ascii=False),
                            }
                        ]
                    }
                    cursor_messages.append(
                        _msg("assistant", f"[assistant_tool_calls]\n{json.dumps(one, ensure_ascii=False)}")
                    )
```

- [ ] **Step 4: Run tests**

```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/test_to_cursor.py -v
```

- [ ] **Step 5: Commit**

```bash
git add converters/to_cursor.py tests/test_to_cursor.py
git commit -m "fix(converters): include id in tool_use history blocks in Cursor wire format"
```

---

### Task 6: BUG 6 — `to_responses.py` silently drops `reasoning` and other output types from prior history

**Files:**
- Modify: `converters/to_responses.py` — `_prior_output_to_messages`
- Test: `tests/test_responses_converter.py`

`reasoning` output items from prior responses are silently dropped. They should be passed through as assistant messages so multi-turn conversations preserve reasoning context.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_responses_converter.py`:

```python
def test_prior_reasoning_item_preserved_as_assistant_message():
    """reasoning output items must be preserved as assistant messages in prior history."""
    prior_output = [
        {
            "type": "reasoning",
            "id": "rs_001",
            "summary": [{"type": "summary_text", "text": "I think step by step..."}],
        },
        {"type": "message", "role": "assistant",
         "content": [{"type": "output_text", "text": "Done."}]},
    ]
    msgs = input_to_messages("continue", prior_output=prior_output)
    roles = [m["role"] for m in msgs]
    # reasoning should produce an assistant message before the actual assistant message
    assert roles.count("assistant") >= 1
    # The reasoning text must appear somewhere in the messages
    all_content = " ".join(m.get("content", "") for m in msgs if isinstance(m.get("content"), str))
    assert "I think step by step" in all_content, (
        f"Reasoning summary text not found in messages: {msgs}"
    )
```

- [ ] **Step 2: Run to confirm FAIL**

```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/test_responses_converter.py::test_prior_reasoning_item_preserved_as_assistant_message -v
```

- [ ] **Step 3: Fix `_prior_output_to_messages` in `converters/to_responses.py`**

Add a `reasoning` handler after the `function_call_output` branch, inside `_prior_output_to_messages`:

```python
        elif t == "reasoning":
            # Preserve reasoning summaries as assistant messages for multi-turn continuity.
            # The 'summary' field is a list of summary_text blocks.
            summary_parts = [
                s.get("text", "")
                for s in item.get("summary") or []
                if isinstance(s, dict) and s.get("type") == "summary_text"
            ]
            text = "\n".join(p for p in summary_parts if p)
            if text:
                msgs.append({"role": "assistant", "content": text})
            else:
                log.debug("to_responses_skip_prior_item", item_type=t)
```

- [ ] **Step 4: Run tests**

```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/test_responses_converter.py -v
```

- [ ] **Step 5: Commit**

```bash
git add converters/to_responses.py tests/test_responses_converter.py
git commit -m "fix(converters): preserve reasoning output items from prior history in to_responses"
```

---

### Task 7: BUG 9 — `input_to_messages` drops `function_call` items in input array

**Files:**
- Modify: `converters/to_responses.py` — `input_to_messages`
- Test: `tests/test_responses_converter.py`

`function_call` items in `input_data` (not prior_output) fall through to `log.debug(skip)`. `_prior_output_to_messages` handles them correctly; `input_to_messages` must too.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_responses_converter.py`:

```python
def test_input_function_call_item_becomes_tool_message():
    """function_call items in input array must produce assistant tool_call messages."""
    items = [
        {"role": "user", "content": "Run calc"},
        {
            "type": "function_call",
            "call_id": "call_input_1",
            "name": "calc",
            "arguments": '{"x": 5}',
        },
        {
            "type": "function_call_output",
            "call_id": "call_input_1",
            "output": "25",
        },
    ]
    msgs = input_to_messages(items)
    assistant_msg = next((m for m in msgs if m.get("role") == "assistant" and m.get("tool_calls")), None)
    assert assistant_msg is not None, "function_call in input must produce assistant tool_calls message"
    assert assistant_msg["tool_calls"][0]["function"]["name"] == "calc"
    assert assistant_msg["tool_calls"][0]["id"] == "call_input_1"
```

- [ ] **Step 2: Run to confirm FAIL**

```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/test_responses_converter.py::test_input_function_call_item_becomes_tool_message -v
```

- [ ] **Step 3: Fix `input_to_messages` in `converters/to_responses.py`**

In `input_to_messages`, inside the `for item in input_data:` loop, add a `function_call` handler before the `role in (...)` branch:

```python
        if t == "function_call_output":
            msgs.append({
                "role": "tool",
                "tool_call_id": item.get("call_id", ""),
                "content": item.get("output", ""),
            })
        elif t == "function_call":
            msgs.append({
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": item.get("call_id", f"call_{uuid.uuid4().hex[:8]}"),
                    "type": "function",
                    "function": {
                        "name": item.get("name", ""),
                        "arguments": item.get("arguments", "{}"),
                    },
                }],
            })
        elif role in ("user", "assistant", "system", "developer"):
            ...
```

- [ ] **Step 4: Run tests**

```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/test_responses_converter.py -v
```

- [ ] **Step 5: Commit**

```bash
git add converters/to_responses.py tests/test_responses_converter.py
git commit -m "fix(converters): handle function_call items in input_to_messages input array"
```

---

## Chunk 3: Streaming Correctness Bugs (BUG 7, BUG 8)

### Task 8: BUG 8 — `generate_streaming_events` missing `response.done` terminal event

**Files:**
- Modify: `converters/from_responses.py` — `generate_streaming_events`
- Test: `tests/test_responses_converter.py`

The OpenAI Responses API SSE stream must end with a `response.done` event. Currently only `response.completed` is emitted. Clients that listen for `response.done` hang indefinitely.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_responses_converter.py`:

```python
from converters.from_responses import generate_streaming_events


def test_generate_streaming_events_ends_with_response_done():
    """Streaming events must terminate with a response.done event."""
    import json
    events = generate_streaming_events(
        response_id="resp_test",
        model="cursor-small",
        text="Hello!",
        tool_calls=None,
        input_tokens=5,
        output_tokens=3,
        params={"tool_choice": "auto", "tools": [], "temperature": 1.0,
                "instructions": None, "previous_response_id": None,
                "metadata": {}, "store": True, "parallel_tool_calls": True},
    )
    event_types = []
    for ev in events:
        # Each event line starts with "event: <type>"
        for line in ev.split("\n"):
            if line.startswith("event: "):
                event_types.append(line[len("event: "):])
    assert "response.done" in event_types, (
        f"response.done not found in event stream. Got: {event_types}"
    )
    assert event_types[-1] == "response.done", (
        f"response.done must be the last event. Got last: {event_types[-1]!r}"
    )
```

- [ ] **Step 2: Run to confirm FAIL**

```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/test_responses_converter.py::test_generate_streaming_events_ends_with_response_done -v
```

Expected: FAIL — `response.done` is not emitted.

- [ ] **Step 3: Fix `generate_streaming_events` in `converters/from_responses.py`**

At the end of `generate_streaming_events`, after the `response.completed` event is appended, add:

```python
    events.append(responses_sse_event("response.done", {
        "type": "response.done",
        "sequence_number": seq,
        "response": completed,
    }))
```

- [ ] **Step 4: Run tests**

```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/test_responses_converter.py -v
```

- [ ] **Step 5: Commit**

```bash
git add converters/from_responses.py tests/test_responses_converter.py
git commit -m "fix(converters): emit response.done terminal event in generate_streaming_events"
```

---

### Task 9: BUG 7 — Streaming Responses API waits for full response before sending first byte (fake streaming)

**Files:**
- Modify: `routers/responses.py` — `create_response` streaming branch
- Test: `tests/test_responses_router.py`

When `stream=True`, the router calls `handle_openai_non_streaming()` (blocking until full response), then passes the complete text to `generate_streaming_events()` which fake-chunks it. Real streaming requires calling `_openai_stream()` and forwarding live SSE chunks.

Note: `generate_streaming_events` can still be used for non-streaming responses that need to be played back as events (e.g. from cache or prior stored responses). For the live path, use `_openai_stream`.

- [ ] **Step 1: Write a test that verifies the streaming path calls `_openai_stream`**

Append to `tests/test_responses_router.py` (read file first to determine existing structure and imports):

The test should:
1. POST `/v1/responses` with `stream=true`
2. Mock `pipeline._openai_stream` and verify it is called
3. Verify `handle_openai_non_streaming` is NOT called for the streaming path

```python
# Read tests/test_responses_router.py first to find the existing test client fixture,
# then add this test using the same fixture pattern.

async def test_streaming_responses_uses_openai_stream_not_non_streaming(client, monkeypatch):
    """stream=True must call _openai_stream, not handle_openai_non_streaming."""
    from pipeline import _openai_stream
    non_stream_called = []
    stream_called = []

    async def fake_non_streaming(cursor_client, params, anthropic_tools):
        non_stream_called.append(True)
        return {
            "choices": [{"message": {"content": "Hi", "tool_calls": None}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 3},
        }

    async def fake_stream(cursor_client, params, anthropic_tools):
        stream_called.append(True)
        yield 'data: {"id":"c1","object":"chat.completion.chunk","choices":[{"delta":{"content":"Hi"},"finish_reason":null}]}\n\n'
        yield "data: [DONE]\n\n"

    monkeypatch.setattr("pipeline.handle_openai_non_streaming", fake_non_streaming)
    monkeypatch.setattr("pipeline._openai_stream", fake_stream)

    resp = await client.post(
        "/v1/responses",
        json={"model": "cursor-small", "input": "hello", "stream": True},
        headers={"Authorization": "Bearer sk-test"},
    )
    assert resp.status_code == 200
    assert not non_stream_called, "handle_openai_non_streaming must not be called when stream=True"
    assert stream_called, "_openai_stream must be called when stream=True"
```

- [ ] **Step 2: Read `tests/test_responses_router.py` before writing**

```bash
cd /teamspace/studios/this_studio/wiwi && head -60 tests/test_responses_router.py
```

Adapt the test to match the existing fixture pattern in that file.

- [ ] **Step 3: Run to confirm FAIL**

```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/test_responses_router.py -k streaming_uses_openai_stream -v
```

- [ ] **Step 4: Fix `create_response` in `routers/responses.py`**

Split the streaming and non-streaming branches:

```python
    if stream:
        # Real streaming — call _openai_stream and forward live chunks
        from pipeline import _openai_stream

        async def _stream_gen():
            async for chunk in _openai_stream(cursor_client, params, anthropic_tools):
                yield chunk

        return StreamingResponse(
            _stream_gen(),
            media_type="text/event-stream",
            headers=_SSE_HEADERS,
        )

    # Non-streaming — call blocking handler, build Responses API object
    openai_resp = await handle_openai_non_streaming(cursor_client, params, anthropic_tools)

    choice = (openai_resp.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    text: str = message.get("content") or ""
    tool_calls: list[dict] | None = message.get("tool_calls")
    usage = openai_resp.get("usage") or {}
    input_tokens = usage.get("prompt_tokens", count_message_tokens(messages, model))
    output_tokens = usage.get("completion_tokens", 0)

    responses_resp = build_response_object(
        response_id=response_id,
        model=model,
        text=text if not tool_calls else None,
        tool_calls=tool_calls,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        params=resp_params,
    )

    if store:
        await response_store.save(response_id, responses_resp, api_key=api_key)

    log.info("responses_api_request", model=model, stream=False, response_id=response_id)
    return JSONResponse(responses_resp)
```

Remove the old block that called `handle_openai_non_streaming` unconditionally and then conditionally called `generate_streaming_events`.

Note: The `store` call on the streaming path is intentionally omitted — you cannot save a response that hasn't been fully received yet. If persistence is needed for streamed responses, a future session can add it with a collect-then-store approach.

- [ ] **Step 5: Run all Responses API tests**

```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/test_responses_router.py tests/test_responses_converter.py tests/test_responses_storage.py -v
```

- [ ] **Step 6: Commit**

```bash
git add routers/responses.py tests/test_responses_router.py
git commit -m "fix(responses): stream=True uses real _openai_stream, not fake-chunked non-streaming"
```

---

## Final Step: Full test suite + UPDATES.md

- [ ] **Run the full unit test suite**

```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/ -m 'not integration' -v
```

Expected: all pass.

- [ ] **Update UPDATES.md**

Add a new session entry at the bottom of `UPDATES.md` documenting:
- All 9 bugs fixed
- Files modified: `converters/from_cursor.py`, `converters/to_cursor.py`, `converters/to_responses.py`, `converters/from_responses.py`, `routers/responses.py`
- New/modified test files: `tests/test_from_cursor.py`, `tests/test_to_cursor.py`, `tests/test_responses_converter.py`, `tests/test_responses_router.py`
- Commit SHAs (fill in after commits)

- [ ] **Final commit**

```bash
git add UPDATES.md
git commit -m "docs: update UPDATES.md for converters bug fix session"
git push
```