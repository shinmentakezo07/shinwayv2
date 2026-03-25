# Converter Split Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split `converters/to_cursor.py` (798 lines) and `converters/from_cursor.py` (426 lines) into four focused modules, with shared helpers in a dedicated file, while keeping all existing imports working via thin shim re-exports.

**Architecture:** Create `converters/cursor_helpers.py` for shared internals used by both directions, then `converters/to_cursor_openai.py`, `converters/to_cursor_anthropic.py`, `converters/from_cursor_openai.py`, `converters/from_cursor_anthropic.py` for direction-specific logic. Reduce `to_cursor.py` and `from_cursor.py` to shim files that re-export everything, preserving all existing import paths across the codebase.

**Tech Stack:** Python 3.12, FastAPI, no new dependencies.

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `converters/cursor_helpers.py` | CREATE | Shared helpers: `_msg`, `_extract_text`, `_build_system_prompt`, `_build_role_override`, `_build_identity_declaration`, `_sanitize_user_content`, `_CURSOR_WORD_RE`, `_tool_result_text`, `_assistant_tool_call_text`, `_example_value`, `_PARAM_EXAMPLES`, `build_tool_instruction`, `_tool_instruction_cache` |
| `converters/to_cursor_openai.py` | CREATE | `openai_to_cursor()` only — imports helpers from `cursor_helpers` |
| `converters/to_cursor_anthropic.py` | CREATE | `anthropic_to_cursor()`, `anthropic_messages_to_openai()`, `parse_system()` — imports helpers from `cursor_helpers` |
| `converters/from_cursor_openai.py` | CREATE | `openai_chunk()`, `openai_sse()`, `openai_done()`, `openai_non_streaming_response()`, `openai_usage_chunk()`, `now_ts()` |
| `converters/from_cursor_anthropic.py` | CREATE | `anthropic_sse_event()`, `anthropic_message_start/delta/stop()`, `anthropic_content_block_*()`, `anthropic_non_streaming_response()`, `convert_tool_calls_to_anthropic()`, `_parse_tool_call_arguments()`, `_manual_convert_tool_calls_to_anthropic()` |
| `converters/to_cursor.py` | REPLACE | Thin shim: re-exports all public names from `cursor_helpers`, `to_cursor_openai`, `to_cursor_anthropic` |
| `converters/from_cursor.py` | REPLACE | Thin shim: re-exports all public names from `from_cursor_openai`, `from_cursor_anthropic`; hosts `sanitize_visible_text`, `split_visible_reasoning`, `scrub_support_preamble`, `_safe_pct`, `_scrub_the_editor`, `_has_real_tool_marker`, `_looks_like_raw_tool_payload`, `_JSON_FENCE_RE`, `_THE_EDITOR_RE` directly (cross-cutting, not direction-specific) |
| `tests/test_to_cursor_openai.py` | CREATE | Unit tests for `openai_to_cursor` in isolation |
| `tests/test_to_cursor_anthropic.py` | CREATE | Unit tests for `anthropic_to_cursor`, `anthropic_messages_to_openai`, `parse_system` in isolation |
| `tests/test_from_cursor_openai.py` | CREATE | Unit tests for OpenAI formatter functions |
| `tests/test_from_cursor_anthropic.py` | CREATE | Unit tests for Anthropic formatter functions |
| `tests/test_cursor_helpers.py` | CREATE | Unit tests for shared helpers |

---

## Chunk 1: `cursor_helpers.py` — shared internals

### Task 1: Write failing tests for shared helpers

**Files:**
- Create: `tests/test_cursor_helpers.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_cursor_helpers.py
from __future__ import annotations
import pytest


def test_msg_shape():
    from converters.cursor_helpers import _msg
    m = _msg("user", "hello")
    assert m["role"] == "user"
    assert m["parts"] == [{"type": "text", "text": "hello"}]
    assert len(m["id"]) == 16


def test_extract_text_string():
    from converters.cursor_helpers import _extract_text
    assert _extract_text("hello") == "hello"


def test_extract_text_list():
    from converters.cursor_helpers import _extract_text
    assert _extract_text([{"type": "text", "text": "hello"}]) == "hello"


def test_sanitize_user_content_replaces_cursor():
    from converters.cursor_helpers import _sanitize_user_content
    assert _sanitize_user_content("use cursor here") == "use the-editor here"


def test_sanitize_user_content_preserves_path():
    from converters.cursor_helpers import _sanitize_user_content
    # path component must not be replaced
    assert _sanitize_user_content("cursor/client.py") == "cursor/client.py"


def test_build_system_prompt_contains_model():
    from converters.cursor_helpers import _build_system_prompt
    result = _build_system_prompt("test-model")
    assert "test-model" in result


def test_tool_result_text_format():
    from converters.cursor_helpers import _tool_result_text
    result = _tool_result_text("Read", "abc123", "content here")
    assert result == "[tool_result name=Read id=abc123]\ncontent here"


def test_build_tool_instruction_empty():
    from converters.cursor_helpers import build_tool_instruction
    assert build_tool_instruction([], "auto") == ""


def test_build_tool_instruction_with_tool():
    from converters.cursor_helpers import build_tool_instruction
    tools = [{"function": {"name": "Read", "description": "read a file",
              "parameters": {"type": "object", "properties": {
                  "file_path": {"type": "string"}},
              "required": ["file_path"]}}}]
    result = build_tool_instruction(tools, "auto")
    assert "Read" in result
    assert "[assistant_tool_calls]" in result
```

- [ ] **Step 2: Run tests — expect ImportError (module does not exist yet)**

```bash
cd /teamspace/studios/this_studio/dikders
pytest tests/test_cursor_helpers.py -v 2>&1 | tail -20
```

Expected: `ModuleNotFoundError: No module named 'converters.cursor_helpers'`

---

### Task 2: Create `converters/cursor_helpers.py`

**Files:**
- Create: `converters/cursor_helpers.py`

- [ ] **Step 1: Extract shared helpers from `to_cursor.py` into new file**

Copy the following sections verbatim from `converters/to_cursor.py` into `converters/cursor_helpers.py`:
- Module docstring (new, see below)
- All imports needed by the helpers
- `_CURSOR_REPLACEMENT`, `_CURSOR_WORD_RE` (lines ~28-40)
- `_sanitize_user_content()` (lines ~43-56)
- `_msg()` (lines ~61-67)
- `_extract_text()` (lines ~70-95)
- `_build_system_prompt()` (lines ~98-112)
- `_build_role_override()` (lines ~115-167)
- `_build_identity_declaration()` (lines ~170-190)
- `_tool_result_text()` (lines ~193-195)
- `_assistant_tool_call_text()` (lines ~198-209)
- `_PARAM_EXAMPLES` dict (lines ~212-242)
- `_example_value()` (lines ~245-273)
- `_tool_instruction_cache` (line ~279)
- `build_tool_instruction()` (lines ~282-398)

File header:
```python
"""
Shin Proxy — Shared converter helpers.

Used by both to_cursor_openai and to_cursor_anthropic.
Do not import pipeline or router modules from here — this module
has no direction-specific logic.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import re
import uuid

import msgspec.json as _msgjson
from cachetools import LRUCache

from config import settings
```

- [ ] **Step 2: Run the helper tests — expect PASS**

```bash
pytest tests/test_cursor_helpers.py -v 2>&1 | tail -20
```

Expected: all 9 tests PASS

- [ ] **Step 3: Run full test suite to confirm nothing broken**

```bash
pytest tests/ --ignore=tests/integration -x -q 2>&1 | tail -10
```

Expected: same pass count as before (684 passed)

- [ ] **Step 4: Commit**

```bash
git add converters/cursor_helpers.py tests/test_cursor_helpers.py
git commit -m "feat(converters): add cursor_helpers.py with shared converter internals"
```

---

## Chunk 2: `to_cursor_openai.py` and `to_cursor_anthropic.py`

### Task 3: Write failing tests for `to_cursor_openai`

**Files:**
- Create: `tests/test_to_cursor_openai.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_to_cursor_openai.py
from __future__ import annotations
import pytest


def test_openai_to_cursor_basic():
    from converters.to_cursor_openai import openai_to_cursor
    messages = [{"role": "user", "content": "hello"}]
    result = openai_to_cursor(messages)
    # Must return a list of cursor-format messages
    assert isinstance(result, list)
    assert len(result) > 0
    # Last message must be the user turn
    last = result[-1]
    assert last["role"] == "user"
    assert last["parts"][0]["text"] == "hello"


def test_openai_to_cursor_tool_result_uses_name_map():
    """tool role message must resolve name from prior assistant tool_calls."""
    from converters.to_cursor_openai import openai_to_cursor
    messages = [
        {"role": "assistant", "content": None, "tool_calls": [{
            "id": "call_abc",
            "type": "function",
            "function": {"name": "Read", "arguments": "{}"},
        }]},
        {"role": "tool", "tool_call_id": "call_abc", "content": "file content"},
    ]
    result = openai_to_cursor(messages)
    tool_result_msg = next(
        m for m in result
        if "tool_result" in (m["parts"][0].get("text") or "")
    )
    assert "name=Read" in tool_result_msg["parts"][0]["text"]


def test_openai_to_cursor_sanitizes_cursor_word():
    from converters.to_cursor_openai import openai_to_cursor
    messages = [{"role": "user", "content": "I use cursor daily"}]
    result = openai_to_cursor(messages)
    user_msg = result[-1]
    assert "the-editor" in user_msg["parts"][0]["text"]
    assert "cursor" not in user_msg["parts"][0]["text"].lower().replace("the-editor", "")


def test_openai_to_cursor_no_tool_sanitize_path():
    """File paths containing 'cursor' must not be replaced in tool results."""
    from converters.to_cursor_openai import openai_to_cursor
    messages = [
        {"role": "assistant", "content": None, "tool_calls": [{
            "id": "call_xyz",
            "type": "function",
            "function": {"name": "Read", "arguments": "{}"},
        }]},
        {"role": "tool", "tool_call_id": "call_xyz",
         "content": "/workspace/cursor/client.py"},
    ]
    result = openai_to_cursor(messages)
    tool_msg = next(m for m in result if "tool_result" in (m["parts"][0].get("text") or ""))
    assert "cursor/client.py" in tool_msg["parts"][0]["text"]
```

- [ ] **Step 2: Run tests — expect ImportError**

```bash
pytest tests/test_to_cursor_openai.py -v 2>&1 | tail -10
```

Expected: `ModuleNotFoundError: No module named 'converters.to_cursor_openai'`

---

### Task 4: Create `converters/to_cursor_openai.py`

**Files:**
- Create: `converters/to_cursor_openai.py`

- [ ] **Step 1: Write the file**

```python
"""
Shin Proxy — Convert OpenAI messages to the editor (Cursor) format.

Public API:
    openai_to_cursor(messages, tools, tool_choice, reasoning_effort,
                     show_reasoning, model, json_mode, parallel_tool_calls)
        → list[dict]  (cursor parts-format messages)
"""
from __future__ import annotations

import json
import uuid

from config import settings
from converters.cursor_helpers import (
    _msg,
    _extract_text,
    _sanitize_user_content,
    _build_system_prompt,
    _build_role_override,
    _build_identity_declaration,
    _tool_result_text,
    _assistant_tool_call_text,
    build_tool_instruction,
)
```

Then copy `openai_to_cursor()` verbatim from `converters/to_cursor.py` (lines ~403-513), updating the imports it uses to come from `cursor_helpers`.

- [ ] **Step 2: Run to_cursor_openai tests — expect PASS**

```bash
pytest tests/test_to_cursor_openai.py -v 2>&1 | tail -10
```

Expected: 4 tests PASS

-
- [ ] **Step 3: Run full suite**

```bash
pytest tests/ --ignore=tests/integration -x -q 2>&1 | tail -5
```
Expected: 684+ passed

---

### Task 5: Write failing tests for `to_cursor_anthropic`

**Files:**
- Create: `tests/test_to_cursor_anthropic.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_to_cursor_anthropic.py
from __future__ import annotations
import pytest


def test_parse_system_string():
    from converters.to_cursor_anthropic import parse_system
    assert parse_system("hello") == "hello"


def test_parse_system_list():
    from converters.to_cursor_anthropic import parse_system
    blocks = [{"type": "text", "text": "hello"}, {"type": "text", "text": " world"}]
    assert parse_system(blocks) == "hello world"


def test_parse_system_none():
    from converters.to_cursor_anthropic import parse_system
    assert parse_system(None) == ""


def test_anthropic_messages_to_openai_basic():
    from converters.to_cursor_anthropic import anthropic_messages_to_openai
    msgs = [{"role": "user", "content": "hi"}]
    result = anthropic_messages_to_openai(msgs, "")
    assert result == [{"role": "user", "content": "hi"}]


def test_anthropic_messages_to_openai_with_system():
    from converters.to_cursor_anthropic import anthropic_messages_to_openai
    msgs = [{"role": "user", "content": "hi"}]
    result = anthropic_messages_to_openai(msgs, "You are helpful")
    assert result[0] == {"role": "system", "content": "You are helpful"}
    assert result[1]["role"] == "user"


def test_anthropic_messages_to_openai_tool_result():
    from converters.to_cursor_anthropic import anthropic_messages_to_openai
    msgs = [{
        "role": "user",
        "content": [{
            "type": "tool_result",
            "tool_use_id": "toolu_abc",
            "content": "file data",
        }]
    }]
    result = anthropic_messages_to_openai(msgs, "")
    assert result[0]["role"] == "tool"
    assert result[0]["tool_call_id"] == "toolu_abc"
    assert result[0]["content"] == "file data"


def test_anthropic_to_cursor_returns_tuple():
    from converters.to_cursor_anthropic import anthropic_to_cursor
    msgs = [{"role": "user", "content": "hello"}]
    cursor_msgs, show_reasoning = anthropic_to_cursor(msgs)
    assert isinstance(cursor_msgs, list)
    assert isinstance(show_reasoning, bool)
    assert show_reasoning is False


def test_anthropic_to_cursor_thinking_enables_reasoning():
    from converters.to_cursor_anthropic import anthropic_to_cursor
    msgs = [{"role": "user", "content": "hello"}]
    _, show_reasoning = anthropic_to_cursor(msgs, thinking={"type": "enabled", "budget_tokens": 1000})
    assert show_reasoning is True
```

- [ ] **Step 2: Run tests — expect ImportError**

```bash
pytest tests/test_to_cursor_anthropic.py -v 2>&1 | tail -10
```

Expected: `ModuleNotFoundError: No module named 'converters.to_cursor_anthropic'`

---

### Task 6: Create `converters/to_cursor_anthropic.py`

**Files:**
- Create: `converters/to_cursor_anthropic.py`

- [ ] **Step 1: Write the file**

File header:
```python
"""
Shin Proxy — Convert Anthropic messages to the editor (Cursor) format.

Public API:
    anthropic_to_cursor(messages, system_text, tools, tool_choice,
                        thinking, model, parallel_tool_calls)
        → tuple[list[dict], bool]  (cursor_messages, show_reasoning)

    anthropic_messages_to_openai(messages, system_text) → list[dict]
    parse_system(system) → str
"""
from __future__ import annotations

import json
import uuid

import msgspec.json as _msgjson

from config import settings
from converters.cursor_helpers import (
    _msg,
    _extract_text,
    _sanitize_user_content,
    _build_system_prompt,
    _build_role_override,
    _build_identity_declaration,
    _tool_result_text,
    build_tool_instruction,
)
```

Then copy verbatim from `converters/to_cursor.py`:
- `parse_system()` (lines ~679-684)
- `anthropic_messages_to_openai()` (lines ~690-795)
- `anthropic_to_cursor()` (lines ~516-667)

- [ ] **Step 2: Run to_cursor_anthropic tests — expect PASS**

```bash
pytest tests/test_to_cursor_anthropic.py -v 2>&1 | tail -15
```

Expected: 8 tests PASS

- [ ] **Step 3: Run full suite**

```bash
pytest tests/ --ignore=tests/integration -x -q 2>&1 | tail -5
```

Expected: 684+ passed

- [ ] **Step 4: Commit**

```bash
git add converters/to_cursor_openai.py converters/to_cursor_anthropic.py \
        tests/test_to_cursor_openai.py tests/test_to_cursor_anthropic.py
git commit -m "feat(converters): add to_cursor_openai and to_cursor_anthropic modules"
```

---

## Chunk 3: `from_cursor_openai.py` and `from_cursor_anthropic.py`

### Task 7: Write failing tests for `from_cursor_openai`

**Files:**
- Create: `tests/test_from_cursor_openai.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_from_cursor_openai.py
from __future__ import annotations
import json


def test_now_ts_is_int():
    from converters.from_cursor_openai import now_ts
    assert isinstance(now_ts(), int)


def test_openai_sse_format():
    from converters.from_cursor_openai import openai_sse
    result = openai_sse({"foo": "bar"})
    assert result.startswith("data: ")
    assert result.endswith("\n\n")
    assert json.loads(result[6:]) == {"foo": "bar"}


def test_openai_done():
    from converters.from_cursor_openai import openai_done
    assert openai_done() == "data: [DONE]\n\n"


def test_openai_chunk_shape():
    from converters.from_cursor_openai import openai_chunk
    chunk = openai_chunk("cid", "model", delta={"content": "hi"})
    assert chunk["object"] == "chat.completion.chunk"
    assert chunk["choices"][0]["delta"] == {"content": "hi"}


def test_openai_non_streaming_response_shape():
    from converters.from_cursor_openai import openai_non_streaming_response
    msg = {"role": "assistant", "content": "hello"}
    resp = openai_non_streaming_response("cid", "cursor-small", msg)
    assert resp["object"] == "chat.completion"
    assert resp["choices"][0]["message"] == msg
    assert "usage" in resp


def test_openai_usage_chunk_shape():
    from converters.from_cursor_openai import openai_usage_chunk
    result = openai_usage_chunk("cid", "cursor-small", 100, 50)
    data = json.loads(result[6:])
    assert data["usage"]["prompt_tokens"] == 100
    assert data["usage"]["completion_tokens"] == 50
```

- [ ] **Step 2: Run tests — expect ImportError**

```bash
pytest tests/test_from_cursor_openai.py -v 2>&1 | tail -10
```

---

### Task 8: Create `converters/from_cursor_openai.py`

**Files:**
- Create: `converters/from_cursor_openai.py`

- [ ] **Step 1: Write the file**

```python
"""
Shin Proxy — Convert the editor (Cursor) SSE output to OpenAI response format.

Public API:
    now_ts() → int
    openai_chunk(chunk_id, model, delta, finish_reason, created) → dict
    openai_sse(payload) → str
    openai_done() → str
    openai_non_streaming_response(...) → dict
    openai_usage_chunk(chunk_id, model, input_tokens, output_tokens) → str
"""
from __future__ import annotations

import json
import time

from tokens import context_window_for
```

Then copy verbatim from `converters/from_cursor.py`:
- `_safe_pct()` helper (needed by the formatters — keep private, not re-exported)
- `now_ts()` (line ~58)
- `openai_chunk()` (lines ~64-84)
- `openai_sse()` (lines ~87-89)
- `openai_done()` (lines ~92-93)
- `openai_non_streaming_response()` (lines ~96-129)
- `openai_usage_chunk()` (lines ~139-156)

Note: `_safe_pct` is also needed by `from_cursor_anthropic.py`. Copy it into both files as a private helper — it is 2 lines and has no state.

- [ ] **Step 2: Run from_cursor_openai tests — expect PASS**

```bash
pytest tests/test_from_cursor_openai.py -v 2>&1 | tail -10
```

Expected: 6 tests PASS

---

### Task 9: Write failing tests for `from_cursor_anthropic`

**Files:**
- Create: `tests/test_from_cursor_anthropic.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_from_cursor_anthropic.py
from __future__ import annotations
import json


def test_anthropic_sse_event_format():
    from converters.from_cursor_anthropic import anthropic_sse_event
    result = anthropic_sse_event("message_start", {"type": "message_start"})
    assert result.startswith("event: message_start\n")
    assert "data: " in result
    assert result.endswith("\n\n")


def test_anthropic_message_start_shape():
    from converters.from_cursor_anthropic import anthropic_message_start
    result = anthropic_message_start("msg_abc", "cursor-small", input_tokens=10)
    data = json.loads(result.split("data: ", 1)[1])
    assert data["type"] == "message_start"
    assert data["message"]["id"] == "msg_abc"
    assert data["message"]["usage"]["input_tokens"] == 10


def test_anthropic_message_stop_shape():
    from converters.from_cursor_anthropic import anthropic_message_stop
    result = anthropic_message_stop()
    assert "message_stop" in result


def test_anthropic_non_streaming_response_shape():
    from converters.from_cursor_anthropic import anthropic_non_streaming_response
    blocks = [{"type": "text", "text": "hello"}]
    resp = anthropic_non_streaming_response("msg_abc", "cursor-small", blocks)
    assert resp["type"] == "message"
    assert resp["role"] == "assistant"
    assert resp["content"] == blocks
    assert resp["stop_reason"] == "end_turn"


def test_convert_tool_calls_to_anthropic_basic():
    from converters.from_cursor_anthropic import convert_tool_calls_to_anthropic
    tool_calls = [{
        "id": "call_abc",
        "type": "function",
        "function": {"name": "Read", "arguments": '{"file_path": "/foo.py"}'},
    }]
    result = convert_tool_calls_to_anthropic(tool_calls)
    assert len(result) == 1
    assert result[0]["type"] == "tool_use"
    assert result[0]["name"] == "Read"
    assert result[0]["id"] == "call_abc"
    assert result[0]["input"] == {"file_path": "/foo.py"}


def test_convert_tool_calls_synthesises_missing_id():
    from converters.from_cursor_anthropic import convert_tool_calls_to_anthropic
    tool_calls = [{
        "type": "function",
        "function": {"name": "Read", "arguments": "{}"},
    }]
    result = convert_tool_calls_to_anthropic(tool_calls)
    assert result[0]["id"].startswith("call_")
```

- [ ] **Step 2: Run tests — expect ImportError**

```bash
pytest tests/test_from_cursor_anthropic.py -v 2>&1 | tail -10
```

---

### Task 10: Create `converters/from_cursor_anthropic.py`

**Files:**
- Create: `converters/from_cursor_anthropic.py`

- [ ] **Step 1: Write the file**

```python
"""
Shin Proxy — Convert the editor (Cursor) SSE output to Anthropic response format.

Public API:
    anthropic_sse_event(event_type, data) → str
    anthropic_message_start(msg_id, model, input_tokens) → str
    anthropic_content_block_start(index, block) → str
    anthropic_content_block_delta(index, delta) → str
    anthropic_content_block_stop(index) → str
    anthropic_message_delta(stop_reason, output_tokens) → str
    anthropic_message_stop() → str
    anthropic_non_streaming_response(...) → dict
    convert_tool_calls_to_anthropic(tool_calls) → list[dict]
"""
from __future__ import annotations

import copy
import json
import uuid

import structlog

try:
    import litellm
except ImportError:
    litellm = None

from tokens import context_window_for
```

Then copy verbatim from `converters/from_cursor.py`:
- `_safe_pct()` (private copy)
- `anthropic_sse_event()` (line ~134)
- `anthropic_message_start()` (lines ~159-179)
- `anthropic_content_block_start()` (lines ~182-187)
- `anthropic_content_block_delta()` (lines ~189-194)
- `anthropic_content_block_stop()` (lines ~196-200)
- `anthropic_message_delta()` (lines ~203-211)
- `anthropic_message_stop()` (lines ~214-217)
- `anthropic_non_streaming_response()` (lines ~220-243)
- `_parse_tool_call_arguments()` (lines ~246-256)
- `_manual_convert_tool_calls_to_anthropic()` (lines ~259-281)
- `convert_tool_calls_to_anthropic()` (lines ~284-318)

- [ ] **Step 2: Run from_cursor_anthropic tests — expect PASS**

```bash
pytest tests/test_from_cursor_anthropic.py -v 2>&1 | tail -15
```

Expected: 6 tests PASS

- [ ] **Step 3: Run full suite**

```bash
pytest tests/ --ignore=tests/integration -x -q 2>&1 | tail -5
```

Expected: 684+ passed

- [ ] **Step 4: Commit**

```bash
git add converters/from_cursor_openai.py converters/from_cursor_anthropic.py \
        tests/test_from_cursor_openai.py tests/test_from_cursor_anthropic.py
git commit -m "feat(converters): add from_cursor_openai and from_cursor_anthropic modules"
```

---

## Chunk 4: Shim `to_cursor.py` and `from_cursor.py` + final validation

### Task 11: Rewrite `to_cursor.py` as a thin shim

**Files:**
- Modify: `converters/to_cursor.py`

- [ ] **Step 1: Replace `to_cursor.py` content with shim**

The shim must re-export every name that external code imports. Known importers:
- `routers/unified.py`: `anthropic_messages_to_openai`, `anthropic_to_cursor`, `openai_to_cursor`, `parse_system`
- `routers/responses.py`: `openai_to_cursor`
- `pipeline/nonstream.py`: `_build_role_override`, `_msg`
- `utils/context.py`: `build_tool_instruction`, `_build_role_override`
- `tokens.py`: `build_tool_instruction`

```python
"""
Shin Proxy — to_cursor shim.

This file exists solely to preserve existing import paths.
All logic lives in the focused modules below.
"""
from __future__ import annotations

# Shared helpers (used by pipeline and utils directly)
from converters.cursor_helpers import (  # noqa: F401
    _msg,
    _extract_text,
    _sanitize_user_content,
    _build_system_prompt,
    _build_role_override,
    _build_identity_declaration,
    _tool_result_text,
    _assistant_tool_call_text,
    _example_value,
    _PARAM_EXAMPLES,
    _tool_instruction_cache,
    build_tool_instruction,
)

# OpenAI → the editor
from converters.to_cursor_openai import openai_to_cursor  # noqa: F401

# Anthropic → the editor
from converters.to_cursor_anthropic import (  # noqa: F401
    anthropic_to_cursor,
    anthropic_messages_to_openai,
    parse_system,
)
```

- [ ] **Step 2: Run full suite — must still pass with zero changes to importers**

```bash
pytest tests/ --ignore=tests/integration -x -q 2>&1 | tail -5
```

Expected: 684+ passed

---

### Task 12: Rewrite `from_cursor.py` as a thin shim

**Files:**
- Modify: `converters/from_cursor.py`

- [ ] **Step 1: Replace `from_cursor.py` with shim**

Known importers:
- `routers/unified.py`: `now_ts`
- `pipeline/stream_openai.py`: `openai_chunk`, `openai_done`, `openai_sse`, `openai_usage_chunk`
- `pipeline/stream_anthropic.py`: `anthropic_content_block_delta`, `anthropic_content_block_start`, `anthropic_content_block_stop`, `anthropic_message_delta`, `anthropic_message_start`, `anthropic_message_stop`, `anthropic_sse_event`
- `pipeline/nonstream.py`: `convert_tool_calls_to_anthropic`, `anthropic_non_streaming_response`, `openai_non_streaming_response`, `sanitize_visible_text`, `scrub_support_preamble`, `split_visible_reasoning`
- `converters/from_cursor.py` tests: `convert_tool_calls_to_anthropic`
- `routers/internal.py`: `now_ts`
- `tokens.py`: `context_window_for` (via tokens module, not from_cursor directly)

The cross-cutting text processing functions (`sanitize_visible_text`, `split_visible_reasoning`, `scrub_support_preamble`, `_scrub_the_editor`, `_THE_EDITOR_RE`, `_JSON_FENCE_RE`, `_has_real_tool_marker`, `_looks_like_raw_tool_payload`, `_safe_pct`) stay in `from_cursor.py` directly — they are consumed by both pipeline paths and do not belong to either direction.

```python
"""
Shin Proxy — from_cursor shim + cross-cutting text processors.

This file re-exports all direction-specific formatters from the focused
modules below. It also hosts the cross-cutting text processing utilities
that are consumed by both OpenAI and Anthropic pipeline paths.
"""
from __future__ import annotations

import re

import structlog

from tools.parse import _find_marker_pos

# ── Cross-cutting text processors (stay here — used by both pipeline paths) ──

_JSON_FENCE_RE = re.compile(
    r"```(?:json)?\s*([\s\S]*?)\s*```", flags=re.IGNORECASE
)
_THE_EDITOR_RE = re.compile(r"\bthe-editor\b", re.IGNORECASE)


def _scrub_the_editor(text: str) -> str:
    return _THE_EDITOR_RE.sub("the editor", text)


def _has_real_tool_marker(text: str) -> bool:
    return _find_marker_pos(text) >= 0


def _looks_like_raw_tool_payload(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    return _has_real_tool_marker(t)


def split_visible_reasoning(text: str) -> tuple[str | None, str]:
    # (full implementation copied verbatim from current from_cursor.py)
    ...


def scrub_support_preamble(text: str) -> tuple[str, bool]:
    # (full implementation copied verbatim from current from_cursor.py)
    ...


def sanitize_visible_text(
    text: str, parsed_tool_calls: list[dict] | None = None
) -> tuple[str, bool]:
    # (full implementation copied verbatim from current from_cursor.py)
    ...


# ── OpenAI formatters ────────────────────────────────────────────────────────
from converters.from_cursor_openai import (  # noqa: F401
    now_ts,
    openai_chunk,
    openai_sse,
    openai_done,
    openai_non_streaming_response,
    openai_usage_chunk,
)

# ── Anthropic formatters ─────────────────────────────────────────────────────
from converters.from_cursor_anthropic import (  # noqa: F401
    anthropic_sse_event,
    anthropic_message_start,
    anthropic_content_block_start,
    anthropic_content_block_delta,
    anthropic_content_block_stop,
    anthropic_message_delta,
    anthropic_message_stop,
    anthropic_non_streaming_response,
    convert_tool_calls_to_anthropic,
)
```

**IMPORTANT:** Replace the `...` placeholders with the full function bodies copied verbatim from the current `from_cursor.py`. The `_SUPPORT_PREAMBLE_RE` pattern must also be copied here.

- [ ] **Step 2: Run full suite**

```bash
pytest tests/ --ignore=tests/integration -x -q 2>&1 | tail -5
```

Expected: 684+ passed

- [ ] **Step 3: Commit**

```bash
git add converters/to_cursor.py converters/from_cursor.py
git commit -m "refactor(converters): replace to_cursor and from_cursor with thin shims"
```

---

### Task 13: Final validation — full suite + import smoke test

**Files:** none new

- [ ] **Step 1: Verify all new modules are independently importable**

```bash
cd /teamspace/studios/this_studio/dikders
python -c "
from converters.cursor_helpers import _msg, build_tool_instruction
from converters.to_cursor_openai import openai_to_cursor
from converters.to_cursor_anthropic import anthropic_to_cursor, anthropic_messages_to_openai, parse_system
from converters.from_cursor_openai import now_ts, openai_chunk, openai_sse, openai_done
from converters.from_cursor_anthropic import anthropic_message_start, convert_tool_calls_to_anthropic
# Shim re-exports still work
from converters.to_cursor import openai_to_cursor, anthropic_to_cursor, _msg, build_tool_instruction
from converters.from_cursor import now_ts, openai_chunk, anthropic_message_start, sanitize_visible_text
print('All imports OK')
"
```

Expected: `All imports OK`

- [ ] **Step 2: Run full test suite including new tests**

```bash
pytest tests/ --ignore=tests/integration -q 2>&1 | tail -10
```

Expected: 719+ passed (684 existing + 35 new tests across 5 new test files)

- [ ] **Step 3: Verify no direct references to old monolith functions remain outside converters/**

```bash
grep -r 'from converters.to_cursor import' /teamspace/studios/this_studio/dikders \
  --include='*.py' | grep -v 'converters/'
```

All results must still work because shim re-exports everything. No output = no direct-to-module imports outside converters. Both outcomes are acceptable.

- [ ] **Step 4: Final commit**

```bash
git add tests/test_cursor_helpers.py
git commit -m "docs: add converter split implementation plan"
```

---

## Summary

| Task | Deliverable | Tests |
|---|---|---|
| 1-2 | `converters/cursor_helpers.py` | `tests/test_cursor_helpers.py` (9 tests) |
| 3-4 | `converters/to_cursor_openai.py` | `tests/test_to_cursor_openai.py` (4 tests) |
| 5-6 | `converters/to_cursor_anthropic.py` | `tests/test_to_cursor_anthropic.py` (8 tests) |
| 7-8 | `converters/from_cursor_openai.py` | `tests/test_from_cursor_openai.py` (6 tests) |
| 9-10 | `converters/from_cursor_anthropic.py` | `tests/test_from_cursor_anthropic.py` (6 tests) |
| 11 | `converters/to_cursor.py` → shim | existing tests |
| 12 | `converters/from_cursor.py` → shim | existing tests |
| 13 | final validation | all 719+ tests pass |

**Zero changes** to any file outside `converters/` and `tests/`.
