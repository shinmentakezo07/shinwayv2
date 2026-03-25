# `/v1/responses` Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a fully-compatible OpenAI Responses API (`POST /v1/responses`) with stateful multi-turn via SQLite, streaming SSE events, function tool support, and 501 stubs for built-in tools.

**Architecture:** New `routers/responses.py` handles the endpoint, delegates to `converters/to_responses.py` (builds `messages[]` from `input[]` + resolves `previous_response_id`), routes through existing `pipeline.py` with `api_style="openai"`, and `converters/from_responses.py` reshapes the result into Responses API `output[]` shape + SSE events. Completed responses are stored in SQLite.

**Tech Stack:** FastAPI, aiosqlite, existing pipeline.py (unchanged), msgspec, structlog

---

## Background: Responses API vs Chat Completions

| Aspect | Chat Completions | Responses API |
|---|---|---|
| Input field | `messages` | `input` (string or array) |
| Output field | `choices[].message` | `output[]` (typed items) |
| Multi-turn state | Client manages | `previous_response_id` (server stores) |
| Response object | `chat.completion` | `response` |
| Streaming events | `chat.completion.chunk` | `response.*` event types |
| Built-in tools | No | stubbed 501 |

### Minimal Request
```json
{"model": "gpt-4o", "input": "Hello"}
```

### Full Request
```json
{
  "model": "gpt-4o",
  "input": [
    {"role": "user", "content": "What is 2+2?"},
    {"type": "function_call_output", "call_id": "call_abc", "output": "4"}
  ],
  "instructions": "You are a math tutor.",
  "previous_response_id": "resp_abc123",
  "tools": [{"type": "function", "name": "calc", "description": "...", "parameters": {}}],
  "tool_choice": "auto",
  "stream": true,
  "temperature": 1.0,
  "max_output_tokens": 2048,
  "store": true,
  "truncation": "auto",
  "reasoning": {"effort": "medium"},
  "metadata": {}
}
```

### Non-Streaming Response
```json
{
  "id": "resp_abc123",
  "object": "response",
  "created_at": 1714000000,
  "model": "gpt-4o",
  "status": "completed",
  "output": [
    {
      "type": "message",
      "id": "msg_001",
      "role": "assistant",
      "status": "completed",
      "content": [{"type": "output_text", "text": "2+2 = 4", "annotations": []}]
    }
  ],
  "usage": {
    "input_tokens": 10, "input_tokens_details": {"cached_tokens": 0},
    "output_tokens": 8, "output_tokens_details": {"reasoning_tokens": 0},
    "total_tokens": 18
  },
  "tool_choice": "auto", "tools": [], "parallel_tool_calls": true,
  "truncation": "disabled", "temperature": 1.0, "store": true,
  "instructions": null, "previous_response_id": null,
  "metadata": {}, "error": null, "incomplete_details": null
}
```

### Tool Call in output[]
```json
{
  "type": "function_call", "id": "fc_001", "call_id": "call_abc",
  "name": "calc", "arguments": "{\"x\": 2}", "status": "completed"
}
```

### Streaming SSE Sequence
```
event: response.created
data: {"type": "response.created", "sequence_number": 0, "response": {<resp, status: in_progress>}}

event: response.output_item.added
data: {"type": "response.output_item.added", "sequence_number": 1, "output_index": 0, "item": {"type": "message", "id": "msg_001", "role": "assistant", "status": "in_progress", "content": []}}

event: response.content_part.added
data: {"type": "response.content_part.added", "sequence_number": 2, "item_id": "msg_001", "output_index": 0, "content_index": 0, "part": {"type": "output_text", "text": "", "annotations": []}}

event: response.output_text.delta
data: {"type": "response.output_text.delta", "sequence_number": 3, "item_id": "msg_001", "output_index": 0, "content_index": 0, "delta": "Hello"}

event: response.output_text.done
data: {"type": "response.output_text.done", "sequence_number": 4, "item_id": "msg_001", "output_index": 0, "content_index": 0, "text": "Hello world"}

event: response.content_part.done
data: {"type": "response.content_part.done", "sequence_number": 5, "item_id": "msg_001", "output_index": 0, "content_index": 0, "part": {"type": "output_text", "text": "Hello world", "annotations": []}}

event: response.output_item.done
data: {"type": "response.output_item.done", "sequence_number": 6, "output_index": 0, "item": {<completed message item>}}

event: response.completed
data: {"type": "response.completed", "sequence_number": 7, "response": {<resp, status: completed>}}
```

### Built-in Tool 501
```json
{"error": {"type": "not_implemented_error", "message": "Built-in tool is not supported. Use function tools instead.", "code": "501"}}
```

---

## Files to Touch

| Action | Path |
|---|---|
| Create | `storage/__init__.py` |
| Create | `storage/responses.py` |
| Create | `converters/to_responses.py` |
| Create | `converters/from_responses.py` |
| Create | `routers/responses.py` |
| Create | `tests/test_responses_storage.py` |
| Create | `tests/test_responses_converter.py` |
| Create | `tests/test_responses_router.py` |
| Modify | `app.py` |
| Modify | `requirements.txt` |


---

## Task 1: SQLite Response Storage

**Files:**
- Create: `storage/__init__.py`
- Create: `storage/responses.py`
- Test: `tests/test_responses_storage.py`

**Step 1: Add aiosqlite to requirements.txt**

```bash
grep aiosqlite requirements.txt || echo "aiosqlite>=0.20" >> requirements.txt
pip install aiosqlite
```

**Step 2: Create `storage/__init__.py`**

```python
"""Shin Proxy — persistent storage modules."""
```

**Step 3: Write failing tests — `tests/test_responses_storage.py`**

```python
"""Tests for responses SQLite storage."""
from __future__ import annotations
import pytest
import pytest_asyncio
from storage.responses import ResponseStore


@pytest_asyncio.fixture
async def store(tmp_path):
    s = ResponseStore(db_path=str(tmp_path / "responses.db"))
    await s.init()
    yield s
    await s.close()


@pytest.mark.asyncio
async def test_save_and_get(store):
    payload = {"id": "resp_001", "output": [], "model": "gpt-4o"}
    await store.save("resp_001", payload, api_key="sk-test")
    result = await store.get("resp_001")
    assert result is not None
    assert result["id"] == "resp_001"
    assert result["model"] == "gpt-4o"


@pytest.mark.asyncio
async def test_get_missing_returns_none(store):
    assert await store.get("resp_nope") is None


@pytest.mark.asyncio
async def test_save_idempotent(store):
    payload = {"id": "resp_002", "output": [], "model": "gpt-4o"}
    await store.save("resp_002", payload, api_key="sk-test")
    await store.save("resp_002", payload, api_key="sk-test")
    result = await store.get("resp_002")
    assert result is not None
```

**Step 4: Run — expect FAIL**

```bash
python -m pytest tests/test_responses_storage.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'storage.responses'`

**Step 5: Implement `storage/responses.py`**

```python
"""
Shin Proxy — SQLite store for completed Responses API objects.
Used by POST /v1/responses to resolve previous_response_id.
"""
from __future__ import annotations
import json
import time
import aiosqlite
import structlog

log = structlog.get_logger()

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS responses (
    id          TEXT PRIMARY KEY,
    api_key     TEXT NOT NULL,
    payload     TEXT NOT NULL,
    created_at  INTEGER NOT NULL
)
"""


class ResponseStore:
    """Async SQLite store for Responses API objects."""

    def __init__(self, db_path: str = "responses.db") -> None:
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def init(self) -> None:
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute(_CREATE_TABLE)
        await self._db.commit()
        log.info("responses_store_ready", path=self._db_path)

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    async def save(self, response_id: str, payload: dict, api_key: str) -> None:
        """Persist a completed response. Idempotent (INSERT OR REPLACE)."""
        assert self._db is not None, "Call init() first"
        await self._db.execute(
            "INSERT OR REPLACE INTO responses (id, api_key, payload, created_at) VALUES (?, ?, ?, ?)",
            (response_id, api_key, json.dumps(payload), int(time.time())),
        )
        await self._db.commit()

    async def get(self, response_id: str) -> dict | None:
        """Fetch a stored response by id. Returns None if not found."""
        assert self._db is not None, "Call init() first"
        async with self._db.execute(
            "SELECT payload FROM responses WHERE id = ?", (response_id,)
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        return json.loads(row[0])


response_store: ResponseStore = ResponseStore()
```

**Step 6: Run — expect PASS**

```bash
python -m pytest tests/test_responses_storage.py -v
```

Expected: 3 passed.

**Step 7: Commit**

```bash
git add storage/__init__.py storage/responses.py tests/test_responses_storage.py requirements.txt
git commit -m "feat: add SQLite response store for /v1/responses stateful turns"
```


---

## Task 2: Input Converter (`converters/to_responses.py`)

**Files:**
- Create: `converters/to_responses.py`
- Test: `tests/test_responses_converter.py`

Converts Responses API `input` (string or array) + `instructions` + prior history from `previous_response_id` into OpenAI `messages[]` for `pipeline.py`. Also classifies tools.

**Step 1: Write failing tests — `tests/test_responses_converter.py`**

```python
"""Tests for Responses API input converter."""
from __future__ import annotations
import pytest
from converters.to_responses import (
    input_to_messages,
    extract_function_tools,
    has_builtin_tools,
    BUILTIN_TOOL_TYPES,
)


def test_string_input_becomes_user_message():
    msgs = input_to_messages("Hello")
    assert msgs == [{"role": "user", "content": "Hello"}]


def test_instructions_prepended_as_system():
    msgs = input_to_messages("Hi", instructions="Be concise.")
    assert msgs[0] == {"role": "system", "content": "Be concise."}
    assert msgs[1] == {"role": "user", "content": "Hi"}


def test_array_easy_message_passthrough():
    items = [{"role": "user", "content": "Hello"}]
    assert input_to_messages(items) == [{"role": "user", "content": "Hello"}]


def test_function_call_output_becomes_tool_message():
    items = [
        {"role": "user", "content": "Calc"},
        {"type": "function_call_output", "call_id": "call_abc", "output": "4"},
    ]
    msgs = input_to_messages(items)
    tool_msg = next(m for m in msgs if m["role"] == "tool")
    assert tool_msg["tool_call_id"] == "call_abc"
    assert tool_msg["content"] == "4"


def test_prior_output_prepended_as_assistant():
    prior_output = [
        {"type": "message", "role": "assistant",
         "content": [{"type": "output_text", "text": "Hi!"}]},
    ]
    msgs = input_to_messages("How are you?", prior_output=prior_output)
    assert msgs[0]["role"] == "assistant"
    assert msgs[0]["content"] == "Hi!"
    assert msgs[1]["role"] == "user"


def test_prior_function_call_creates_tool_messages():
    prior_output = [
        {"type": "function_call", "call_id": "call_xyz", "name": "calc", "arguments": "{}"},
        {"type": "function_call_output", "call_id": "call_xyz", "output": "42"},
    ]
    msgs = input_to_messages("next", prior_output=prior_output)
    assert any(m.get("role") == "assistant" and m.get("tool_calls") for m in msgs)
    assert any(m.get("role") == "tool" for m in msgs)


def test_extract_function_tools_filters_builtins():
    tools = [
        {"type": "function", "name": "calc", "description": "...", "parameters": {}},
        {"type": "web_search_preview"},
    ]
    result = extract_function_tools(tools)
    assert len(result) == 1
    assert result[0]["function"]["name"] == "calc"


def test_has_builtin_tools_detects_them():
    assert has_builtin_tools([{"type": "web_search_preview"}])
    assert has_builtin_tools([{"type": "code_interpreter"}])
    assert not has_builtin_tools([{"type": "function", "name": "x"}])


def test_builtin_tool_types_set():
    assert "web_search_preview" in BUILTIN_TOOL_TYPES
    assert "code_interpreter" in BUILTIN_TOOL_TYPES
    assert "file_search" in BUILTIN_TOOL_TYPES
```

**Step 2: Run — expect FAIL**

```bash
python -m pytest tests/test_responses_converter.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'converters.to_responses'`

**Step 3: Implement `converters/to_responses.py`**

```python
"""
Shin Proxy — Responses API input converter.

Converts OpenAI Responses API input[] + instructions + prior history
into OpenAI messages[] for pipeline.py.
"""
from __future__ import annotations

import uuid
import structlog

log = structlog.get_logger()

BUILTIN_TOOL_TYPES: frozenset[str] = frozenset({
    "web_search_preview",
    "web_search_preview_2025_03_11",
    "web_search",
    "code_interpreter",
    "file_search",
    "computer",
    "computer_use_preview",
    "image_generation",
})


def _output_text_from_content(content: list[dict] | str) -> str:
    if isinstance(content, str):
        return content
    return "\n".join(
        b.get("text", "") for b in content
        if isinstance(b, dict) and b.get("type") == "output_text"
    )


def _prior_output_to_messages(prior_output: list[dict]) -> list[dict]:
    msgs: list[dict] = []
    pending_calls: list[dict] = []

    for item in prior_output:
        t = item.get("type")

        if t == "message":
            role = item.get("role", "assistant")
            content = item.get("content", [])
            text = _output_text_from_content(content)
            msgs.append({"role": role, "content": text})

        elif t == "function_call":
            pending_calls.append(item)
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

        elif t == "function_call_output":
            msgs.append({
                "role": "tool",
                "tool_call_id": item.get("call_id", ""),
                "content": item.get("output", ""),
            })

    return msgs


def input_to_messages(
    input_data: str | list,
    instructions: str | None = None,
    prior_output: list[dict] | None = None,
) -> list[dict]:
    msgs: list[dict] = []

    if instructions:
        msgs.append({"role": "system", "content": instructions})

    if prior_output:
        msgs.extend(_prior_output_to_messages(prior_output))

    if isinstance(input_data, str):
        msgs.append({"role": "user", "content": input_data})
        return msgs

    for item in input_data:
        if not isinstance(item, dict):
            continue
        t = item.get("type")
        role = item.get("role")

        if t == "function_call_output":
            msgs.append({
                "role": "tool",
                "tool_call_id": item.get("call_id", ""),
                "content": item.get("output", ""),
            })
        elif role in ("user", "assistant", "system", "developer"):
            actual_role = "system" if role == "developer" else role
            content = item.get("content", "")
            if isinstance(content, list):
                content = "\n".join(
                    p.get("text", "") for p in content
                    if isinstance(p, dict) and p.get("type") in ("input_text", "text", "output_text")
                )
            msgs.append({"role": actual_role, "content": content})
        else:
            log.debug("to_responses_skip_item", item_type=t)

    return msgs


def extract_function_tools(tools: list[dict]) -> list[dict]:
    out: list[dict] = []
    for t in tools or []:
        if t.get("type") in BUILTIN_TOOL_TYPES:
            continue
        fn = {
            "type": "function",
            "function": {
                "name": t.get("name", ""),
                "description": t.get("description", ""),
                "parameters": t.get("parameters", {"type": "object", "properties": {}}),
            },
        }
        out.append(fn)
    return out


def has_builtin_tools(tools: list[dict]) -> bool:
    return any(t.get("type") in BUILTIN_TOOL_TYPES for t in tools or [])
```

**Step 4: Run — expect PASS**

```bash
python -m pytest tests/test_responses_converter.py -v
```

Expected: all 8 passed.

**Step 5: Commit**

```bash
git add converters/to_responses.py tests/test_responses_converter.py
git commit -m "feat: add input converter for /v1/responses"
```


---

## Task 3: Output Converter (`converters/from_responses.py`)

**Files:**
- Create: `converters/from_responses.py`
- Append tests to: `tests/test_responses_converter.py`

Translates the pipeline's OpenAI non-streaming response into Responses API shape, and generates SSE events for streaming.

**Step 1: Add tests to `tests/test_responses_converter.py`**

Append these tests:

```python
from converters.from_responses import (
    build_response_object,
    openai_message_to_output_items,
    responses_sse_event,
)


def test_build_response_object_text():
    resp = build_response_object(
        response_id="resp_001",
        model="gpt-4o",
        text="Hello!",
        tool_calls=None,
        input_tokens=5,
        output_tokens=3,
        params={"tool_choice": "auto", "tools": [], "temperature": 1.0,
                "instructions": None, "previous_response_id": None,
                "metadata": {}, "store": True, "parallel_tool_calls": True},
    )
    assert resp["object"] == "response"
    assert resp["status"] == "completed"
    assert len(resp["output"]) == 1
    assert resp["output"][0]["type"] == "message"
    assert resp["output"][0]["content"][0]["text"] == "Hello!"
    assert resp["usage"]["input_tokens"] == 5
    assert resp["usage"]["total_tokens"] == 8


def test_build_response_object_tool_calls():
    tool_calls = [{
        "id": "call_abc",
        "type": "function",
        "function": {"name": "calc", "arguments": "{}"},
    }]
    resp = build_response_object(
        response_id="resp_002",
        model="gpt-4o",
        text=None,
        tool_calls=tool_calls,
        input_tokens=5,
        output_tokens=3,
        params={"tool_choice": "auto", "tools": [], "temperature": 1.0,
                "instructions": None, "previous_response_id": None,
                "metadata": {}, "store": True, "parallel_tool_calls": True},
    )
    fc = resp["output"][0]
    assert fc["type"] == "function_call"
    assert fc["name"] == "calc"
    assert fc["call_id"] == "call_abc"


def test_responses_sse_event_format():
    event = responses_sse_event("response.completed", {"type": "response.completed", "sequence_number": 1, "response": {}})
    assert event.startswith("event: response.completed\ndata: ")
    assert event.endswith("\n\n")
```

**Step 2: Run — expect FAIL**

```bash
python -m pytest tests/test_responses_converter.py::test_build_response_object_text -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'converters.from_responses'`

**Step 3: Implement `converters/from_responses.py`**

```python
"""
Shin Proxy — Responses API output converter.

Translates pipeline output (OpenAI format) into Responses API
response object shape and SSE event sequence.
"""
from __future__ import annotations

import json
import time
import uuid
from typing import Any

import structlog

log = structlog.get_logger()


def responses_sse_event(event_type: str, data: dict) -> str:
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


def _build_message_output_item(text: str, msg_id: str) -> dict:
    return {
        "type": "message",
        "id": msg_id,
        "role": "assistant",
        "status": "completed",
        "content": [{"type": "output_text", "text": text, "annotations": []}],
    }


def _build_function_call_output_item(tc: dict, idx: int) -> dict:
    fn = tc.get("function", {})
    return {
        "type": "function_call",
        "id": f"fc_{uuid.uuid4().hex[:8]}",
        "call_id": tc.get("id", f"call_{uuid.uuid4().hex[:8]}"),
        "name": fn.get("name", ""),
        "arguments": fn.get("arguments", "{}"),
        "status": "completed",
    }


def build_response_object(
    response_id: str,
    model: str,
    text: str | None,
    tool_calls: list[dict] | None,
    input_tokens: int,
    output_tokens: int,
    params: dict,
) -> dict:
    output: list[dict] = []

    if tool_calls:
        for i, tc in enumerate(tool_calls):
            output.append(_build_function_call_output_item(tc, i))
    elif text:
        msg_id = f"msg_{uuid.uuid4().hex[:24]}"
        output.append(_build_message_output_item(text, msg_id))

    return {
        "id": response_id,
        "object": "response",
        "created_at": int(time.time()),
        "model": model,
        "status": "completed",
        "output": output,
        "usage": {
            "input_tokens": input_tokens,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens": output_tokens,
            "output_tokens_details": {"reasoning_tokens": 0},
            "total_tokens": input_tokens + output_tokens,
        },
        "tool_choice": params.get("tool_choice", "auto"),
        "tools": params.get("tools", []),
        "parallel_tool_calls": params.get("parallel_tool_calls", True),
        "truncation": "disabled",
        "temperature": params.get("temperature", 1.0),
        "store": params.get("store", True),
        "instructions": params.get("instructions"),
        "previous_response_id": params.get("previous_response_id"),
        "metadata": params.get("metadata") or {},
        "error": None,
        "incomplete_details": None,
    }


def build_in_progress_response(response_id: str, model: str, params: dict) -> dict:
    resp = build_response_object(
        response_id=response_id,
        model=model,
        text=None,
        tool_calls=None,
        input_tokens=0,
        output_tokens=0,
        params=params,
    )
    resp["status"] = "in_progress"
    return resp


def generate_streaming_events(
    response_id: str,
    model: str,
    text: str,
    tool_calls: list[dict] | None,
    input_tokens: int,
    output_tokens: int,
    params: dict,
) -> list[str]:
    seq = 0
    events: list[str] = []

    in_progress = build_in_progress_response(response_id, model, params)
    events.append(responses_sse_event("response.created", {
        "type": "response.created", "sequence_number": seq, "response": in_progress
    }))
    seq += 1

    if tool_calls:
        for i, tc in enumerate(tool_calls):
            fn = tc.get("function", {})
            item = _build_function_call_output_item(tc, i)
            item_in_progress = {**item, "status": "in_progress"}
            events.append(responses_sse_event("response.output_item.added", {
                "type": "response.output_item.added",
                "sequence_number": seq, "output_index": i, "item": item_in_progress,
            }))
            seq += 1
            events.append(responses_sse_event("response.output_item.done", {
                "type": "response.output_item.done",
                "sequence_number": seq, "output_index": i, "item": item,
            }))
            seq += 1
    else:
        msg_id = f"msg_{uuid.uuid4().hex[:24]}"
        events.append(responses_sse_event("response.output_item.added", {
            "type": "response.output_item.added",
            "sequence_number": seq, "output_index": 0,
            "item": {"type": "message", "id": msg_id, "role": "assistant",
                     "status": "in_progress", "content": []},
        }))
        seq += 1
        events.append(responses_sse_event("response.content_part.added", {
            "type": "response.content_part.added",
            "sequence_number": seq, "item_id": msg_id,
            "output_index": 0, "content_index": 0,
            "part": {"type": "output_text", "text": "", "annotations": []},
        }))
        seq += 1
        # Stream text in 40-char chunks
        for i in range(0, max(1, len(text)), 40):
            chunk = text[i:i + 40]
            events.append(responses_sse_event("response.output_text.delta", {
                "type": "response.output_text.delta",
                "sequence_number": seq, "item_id": msg_id,
                "output_index": 0, "content_index": 0, "delta": chunk,
            }))
            seq += 1
        events.append(responses_sse_event("response.output_text.done", {
            "type": "response.output_text.done",
            "sequence_number": seq, "item_id": msg_id,
            "output_index": 0, "content_index": 0, "text": text,
        }))
        seq += 1
        events.append(responses_sse_event("response.content_part.done", {
            "type": "response.content_part.done",
            "sequence_number": seq, "item_id": msg_id,
            "output_index": 0, "content_index": 0,
            "part": {"type": "output_text", "text": text, "annotations": []},
        }))
        seq += 1
        completed_item = _build_message_output_item(text, msg_id)
        events.append(responses_sse_event("response.output_item.done", {
            "type": "response.output_item.done",
            "sequence_number": seq, "output_index": 0, "item": completed_item,
        }))
        seq += 1

    completed = build_response_object(
        response_id=response_id, model=model, text=text,
        tool_calls=tool_calls, input_tokens=input_tokens,
        output_tokens=output_tokens, params=params,
    )
    events.append(responses_sse_event("response.completed", {
        "type": "response.completed", "sequence_number": seq, "response": completed,
    }))

    return events
```

**Step 4: Run — expect PASS**

```bash
python -m pytest tests/test_responses_converter.py -v
```

Expected: all tests pass.

**Step 5: Commit**

```bash
git add converters/from_responses.py tests/test_responses_converter.py
git commit -m "feat: add output converter for /v1/responses — response object + SSE events"
```


---

## Task 4: Router (`routers/responses.py`)

**Files:**
- Create: `routers/responses.py`
- Test: `tests/test_responses_router.py`

The FastAPI endpoint. Handles auth, built-in tool 501 early exit, `previous_response_id` lookup, input conversion, pipeline call, response formatting, and SQLite storage.

**Step 1: Write failing tests — `tests/test_responses_router.py`**

```python
"""Tests for POST /v1/responses router."""
from __future__ import annotations
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient


def _make_app():
    from app import create_app
    return create_app()


@pytest.fixture
def client():
    app = _make_app()
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


def test_missing_auth_returns_401(client):
    resp = client.post("/v1/responses", json={"model": "gpt-4o", "input": "hi"})
    assert resp.status_code == 401


def test_builtin_tool_returns_501(client):
    resp = client.post(
        "/v1/responses",
        headers={"Authorization": "Bearer sk-local-dev"},
        json={
            "model": "gpt-4o",
            "input": "search for stuff",
            "tools": [{"type": "web_search_preview"}],
        },
    )
    assert resp.status_code == 501
    body = resp.json()
    assert "not_implemented_error" in body.get("error", {}).get("type", "")


def test_missing_input_returns_400(client):
    resp = client.post(
        "/v1/responses",
        headers={"Authorization": "Bearer sk-local-dev"},
        json={"model": "gpt-4o"},
    )
    assert resp.status_code == 400
```

**Step 2: Run — expect FAIL**

```bash
python -m pytest tests/test_responses_router.py::test_missing_auth_returns_401 -v 2>&1 | head -20
```

Expected: `404 Not Found` (endpoint doesn't exist yet).

**Step 3: Implement `routers/responses.py`**

```python
"""
Shin Proxy — OpenAI Responses API endpoint.

POST /v1/responses
  - Full Responses API compatibility
  - Stateful multi-turn via previous_response_id + SQLite
  - Built-in tools return 501
  - Function tools fully supported
  - Streaming and non-streaming
"""
from __future__ import annotations

import uuid
import time

import structlog
from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app import get_http_client
from converters.to_responses import (
    input_to_messages,
    extract_function_tools,
    has_builtin_tools,
    BUILTIN_TOOL_TYPES,
)
from converters.from_responses import (
    build_response_object,
    generate_streaming_events,
)
from cursor.client import CursorClient
from middleware.auth import check_budget, verify_bearer
from middleware.rate_limit import enforce_rate_limit
from pipeline import (
    PipelineParams,
    handle_openai_non_streaming,
)
from routers.model_router import resolve_model
from storage.responses import response_store
from tokens import count_message_tokens
from tools.normalize import normalize_openai_tools, validate_tool_choice

router = APIRouter()
log = structlog.get_logger()

_SSE_HEADERS = {
    "X-Accel-Buffering": "no",
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
}


@router.post("/v1/responses")
async def create_response(
    request: Request,
    authorization: str | None = Header(default=None),
):
    api_key = verify_bearer(authorization)
    enforce_rate_limit(api_key)
    check_budget(api_key)

    payload = await request.json()

    # Validate required field
    if "input" not in payload:
        return JSONResponse(status_code=400, content={
            "error": {
                "type": "invalid_request_error",
                "message": "'input' is required",
                "code": "400",
            }
        })

    # Reject built-in tools early
    tools_raw = payload.get("tools") or []
    if has_builtin_tools(tools_raw):
        builtin_names = [t["type"] for t in tools_raw if t.get("type") in BUILTIN_TOOL_TYPES]
        return JSONResponse(status_code=501, content={
            "error": {
                "type": "not_implemented_error",
                "message": (
                    f"Built-in tools {builtin_names} are not supported by this proxy. "
                    "Use function tools instead."
                ),
                "code": "501",
            }
        })

    model = resolve_model(payload.get("model"))
    stream = bool(payload.get("stream", False))
    instructions = payload.get("instructions")
    previous_response_id = payload.get("previous_response_id")
    store = bool(payload.get("store", True))
    temperature = payload.get("temperature", 1.0)
    metadata = payload.get("metadata") or {}
    reasoning = payload.get("reasoning")
    reasoning_effort = (reasoning or {}).get("effort") if reasoning else None

    # Resolve previous_response_id -> prior output
    prior_output: list[dict] | None = None
    if previous_response_id:
        prior_resp = await response_store.get(previous_response_id)
        if prior_resp is not None:
            prior_output = prior_resp.get("output", [])
        else:
            log.warning("previous_response_id_not_found", id=previous_response_id)

    # Build OpenAI messages
    messages = input_to_messages(
        payload["input"],
        instructions=instructions,
        prior_output=prior_output,
    )

    # Normalize function tools
    tools = normalize_openai_tools(extract_function_tools(tools_raw))
    tool_choice = validate_tool_choice(payload.get("tool_choice", "auto"), tools)
    parallel_tool_calls = bool(payload.get("parallel_tool_calls", True))

    from converters.to_cursor import openai_to_cursor
    cursor_messages = openai_to_cursor(
        messages,
        tools=tools,
        tool_choice=tool_choice,
        reasoning_effort=reasoning_effort,
        model=model,
    )

    from tools.normalize import to_anthropic_tool_format
    anthropic_tools = to_anthropic_tool_format(tools) if tools else None

    params = PipelineParams(
        api_style="openai",
        model=model,
        messages=messages,
        cursor_messages=cursor_messages,
        tools=tools,
        tool_choice=tool_choice,
        stream=False,  # We always collect full response then re-stream Responses-style
        show_reasoning=False,
        reasoning_effort=reasoning_effort,
        parallel_tool_calls=parallel_tool_calls,
        api_key=api_key,
    )

    response_id = f"resp_{uuid.uuid4().hex[:24]}"
    resp_params = {
        "tool_choice": tool_choice,
        "tools": tools_raw,
        "temperature": temperature,
        "instructions": instructions,
        "previous_response_id": previous_response_id,
        "metadata": metadata,
        "store": store,
        "parallel_tool_calls": parallel_tool_calls,
    }

    client = CursorClient(get_http_client())
    openai_resp = await handle_openai_non_streaming(client, params, anthropic_tools)

    choice = (openai_resp.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    text = message.get("content") or ""
    tool_calls = message.get("tool_calls")
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

    # Persist for future previous_response_id lookups
    if store:
        await response_store.save(response_id, responses_resp, api_key=api_key)

    log.info("responses_api_request", model=model, stream=stream, response_id=response_id)

    if stream:
        events = generate_streaming_events(
            response_id=response_id,
            model=model,
            text=text,
            tool_calls=tool_calls,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            params=resp_params,
        )

        async def _stream():
            for event in events:
                yield event

        return StreamingResponse(
            _stream(),
            media_type="text/event-stream",
            headers=_SSE_HEADERS,
        )

    return JSONResponse(responses_resp)
```

**Step 4: Run tests — expect PASS**

```bash
python -m pytest tests/test_responses_router.py -v
```

Expected: all 3 pass.

**Step 5: Commit**

```bash
git add routers/responses.py tests/test_responses_router.py
git commit -m "feat: add /v1/responses router with tool support, stateful turns, streaming"
```


---

## Task 5: Wire Up — `app.py` + Lifespan

**Files:**
- Modify: `app.py`

Register the responses router and init/teardown the SQLite store in the app lifespan.

**Step 1: Read `app.py` before editing**

```bash
head -70 app.py
```

**Step 2: Add router import and lifespan changes**

In `app.py`, modify `_lifespan` to init/close the response store:

```python
# In _lifespan, after httpx client init:
from storage.responses import response_store
await response_store.init()
log.info("response_store_started")

# In the finally block, before httpx close:
await response_store.close()
log.info("response_store_closed")
```

In `create_app()`, register the new router alongside the existing ones:

```python
from routers.responses import router as responses_router
app.include_router(responses_router)
```

Full diff context — edit the lifespan function:

```python
@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    global _http_client
    _http_client = httpx.AsyncClient(
        http2=True,
        timeout=httpx.Timeout(connect=15.0, read=None, write=None, pool=15.0),
        limits=httpx.Limits(
            max_connections=1500,
            max_keepalive_connections=300,
            keepalive_expiry=60.0,
        ),
        follow_redirects=True,
    )
    log.info("httpx_client_started")
    # Pre-warm
    try:
        await _http_client.head(settings.cursor_base_url, timeout=5.0)
        log.info("upstream_connection_prewarmed", url=settings.cursor_base_url)
    except Exception as exc:
        log.warning("upstream_prewarm_failed", error=str(exc)[:100])

    # Init response store
    from storage.responses import response_store
    await response_store.init()
    log.info("response_store_started")

    try:
        yield
    finally:
        await response_store.close()
        log.info("response_store_closed")
        await _http_client.aclose()
        log.info("httpx_client_closed")
```

And in `create_app()` near the other router registrations:

```python
from routers.internal import router as internal_router
from routers.unified import router as unified_router
from routers.responses import router as responses_router

app.include_router(internal_router)
app.include_router(unified_router)
app.include_router(responses_router)
```

**Step 3: Verify app starts**

```bash
python -c "from app import create_app; app = create_app(); print('OK')"
```

Expected: `OK` (no import errors)

**Step 4: Run all responses tests**

```bash
python -m pytest tests/test_responses_storage.py tests/test_responses_converter.py tests/test_responses_router.py -v
```

Expected: all pass.

**Step 5: Commit**

```bash
git add app.py
git commit -m "feat: wire /v1/responses router and response_store into app lifespan"
```

---

## Task 6: Integration Smoke Test

**Files:**
- No new files — manual curl test against running server

**Step 1: Start the server**

```bash
cd /teamspace/studios/this_studio/wiwi
LITELLM_MASTER_KEY=sk-local-dev python -m uvicorn app:app --port 4001 &
sleep 3
```

**Step 2: Test non-streaming text response**

```bash
curl -s -X POST http://localhost:4001/v1/responses \
  -H "Authorization: Bearer sk-local-dev" \
  -H "Content-Type: application/json" \
  -d '{"model": "cursor-small", "input": "Say hello in one word."}' | python -m json.tool
```

Expected: JSON with `object: "response"`, `status: "completed"`, `output[0].type: "message"`, `output[0].content[0].text` containing a word.

**Step 3: Test streaming**

```bash
curl -s -X POST http://localhost:4001/v1/responses \
  -H "Authorization: Bearer sk-local-dev" \
  -H "Content-Type: application/json" \
  -d '{"model": "cursor-small", "input": "Say hi.", "stream": true}'
```

Expected: SSE events starting with `event: response.created`, ending with `event: response.completed`.

**Step 4: Test built-in tool rejection**

```bash
curl -s -X POST http://localhost:4001/v1/responses \
  -H "Authorization: Bearer sk-local-dev" \
  -H "Content-Type: application/json" \
  -d '{"model": "cursor-small", "input": "search", "tools": [{"type": "web_search_preview"}]}'
```

Expected: HTTP 501, `error.type: "not_implemented_error"`.

**Step 5: Test previous_response_id**

Save the `id` from step 2, then:

```bash
curl -s -X POST http://localhost:4001/v1/responses \
  -H "Authorization: Bearer sk-local-dev" \
  -H "Content-Type: application/json" \
  -d "{\"model\": \"cursor-small\", \"input\": \"What did I just ask?\", \"previous_response_id\": \"<id from step 2>\"}" | python -m json.tool
```

Expected: assistant references the prior turn content.

**Step 6: Stop server**

```bash
kill %1 2>/dev/null || true
```

**Step 7: Run full test suite**

```bash
python -m pytest tests/ -v --ignore=tests/integration -x 2>&1 | tail -30
```

Expected: all existing + new tests pass, no regressions.

**Step 8: Commit**

```bash
git add -A
git commit -m "feat: /v1/responses — full implementation complete (storage, converters, router, wiring)"
```

---

## Done Criteria

- [ ] `POST /v1/responses` returns Responses API `response` object (non-streaming)
- [ ] `POST /v1/responses` with `stream: true` returns correct SSE event sequence
- [ ] `previous_response_id` resolves prior turn from SQLite
- [ ] Built-in tools (`web_search_preview`, `code_interpreter`, etc.) return HTTP 501
- [ ] Function tools work end-to-end
- [ ] No existing tests broken
- [ ] All new tests pass
