# Converters Gap Fixes Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close 4 gaps in the `converters/` package: deduplicate the `_safe_pct` utility defined identically in 3 files, add a `converters/message_normalizer.py` for pre-conversion message edge cases, build a proper `converters/__init__.py` public API surface, and add unit tests for `converters/to_responses.py` and `converters/from_responses.py`.

**Architecture:** All changes are additive or pure deduplication. No public API breaks. `_safe_pct` is extracted to `converters/shared.py` and imported by the 3 existing files. The message normalizer is a new standalone module. `converters/__init__.py` grows re-exports. Tests are added alongside the existing converter test files.

**Tech Stack:** Python 3.12, msgspec, structlog, pytest.

---

## Chunk 1: Extract `_safe_pct` + `converters/__init__.py` public API

### Task 1: Extract `_safe_pct` to `converters/shared.py`

**Files:**
- Create: `converters/shared.py`
- Modify: `converters/from_cursor_openai.py`
- Modify: `converters/from_cursor_anthropic.py`
- Modify: `converters/from_cursor.py`
- Test: `tests/test_converters_shared.py`

`_safe_pct` is defined identically in all three files. Extract it once to `converters/shared.py` and import from there.

- [ ] **Step 1.1: Write the failing test**

```python
# tests/test_converters_shared.py
from converters.shared import _safe_pct

def test_safe_pct_normal():
    assert _safe_pct(1000, 10000) == 10.0

def test_safe_pct_zero_context():
    # Must not divide by zero
    assert _safe_pct(100, 0) == 0.0

def test_safe_pct_full():
    assert _safe_pct(10000, 10000) == 100.0

def test_safe_pct_rounds_to_2dp():
    assert _safe_pct(1, 3) == 33.33

def test_safe_pct_zero_used():
    assert _safe_pct(0, 10000) == 0.0
```

- [ ] **Step 1.2: Run to verify it fails**

```bash
cd /teamspace/studios/this_studio/dikders && pytest tests/test_converters_shared.py -v 2>&1 | tail -5
```
Expected: `ModuleNotFoundError: No module named 'converters.shared'`

- [ ] **Step 1.3: Create `converters/shared.py`**

```python
"""Converters — shared utilities used by multiple format-specific modules.

Keep this module dependency-free: no imports from other converters submodules,
no imports from pipeline or router modules.
"""
from __future__ import annotations


def _safe_pct(used: int, ctx: int) -> float:
    """Return usage percentage rounded to 2 decimal places.

    Guards against zero context window to prevent ZeroDivisionError.

    Args:
        used: Tokens consumed.
        ctx:  Total context window size.

    Returns:
        Percentage as a float rounded to 2dp, or 0.0 when ctx is zero.
    """
    return round(used / ctx * 100, 2) if ctx else 0.0
```

- [ ] **Step 1.4: Run tests to verify they pass**

```bash
cd /teamspace/studios/this_studio/dikders && pytest tests/test_converters_shared.py -v 2>&1 | tail -8
```
Expected: 5/5 PASS

- [ ] **Step 1.5: Replace `_safe_pct` in `converters/from_cursor_openai.py`**

Read `converters/from_cursor_openai.py`. Remove the local `_safe_pct` definition and add at the top with other imports:
```python
from converters.shared import _safe_pct
```

- [ ] **Step 1.6: Replace `_safe_pct` in `converters/from_cursor_anthropic.py`**

Read `converters/from_cursor_anthropic.py`. Remove the local `_safe_pct` definition and add:
```python
from converters.shared import _safe_pct
```

- [ ] **Step 1.7: Replace `_safe_pct` in `converters/from_cursor.py`**

Read `converters/from_cursor.py`. Remove the local `_safe_pct` definition and add:
```python
from converters.shared import _safe_pct
```

- [ ] **Step 1.8: Verify no local `_safe_pct` definitions remain**

```bash
cd /teamspace/studios/this_studio/dikders && grep -rn 'def _safe_pct' converters/ --include='*.py'
```
Expected: only `converters/shared.py:` appears. Zero other results.

- [ ] **Step 1.9: Run full suite to verify no regressions**

```bash
cd /teamspace/studios/this_studio/dikders && pytest tests/ -m 'not integration' -q --tb=short 2>&1 | tail -8
```
Expected: all PASS

- [ ] **Step 1.10: Commit**

```bash
git add converters/shared.py tests/test_converters_shared.py converters/from_cursor_openai.py converters/from_cursor_anthropic.py converters/from_cursor.py
git commit -m "refactor(converters): extract _safe_pct to converters/shared.py — eliminate 3x duplication"
```

---

### Task 2: Build `converters/__init__.py` public API

**Files:**
- Modify: `converters/__init__.py`
- Test: `tests/test_converters_init.py`

`converters/__init__.py` is currently empty (1 line). Add re-exports of the key public names so `from converters import openai_to_cursor` works.

- [ ] **Step 2.1: Write failing tests**

```python
# tests/test_converters_init.py
def test_openai_to_cursor_importable_from_package():
    from converters import openai_to_cursor
    assert callable(openai_to_cursor)

def test_anthropic_to_cursor_importable_from_package():
    from converters import anthropic_to_cursor
    assert callable(anthropic_to_cursor)

def test_openai_chunk_importable_from_package():
    from converters import openai_chunk
    assert callable(openai_chunk)

def test_openai_sse_importable_from_package():
    from converters import openai_sse
    assert callable(openai_sse)

def test_anthropic_sse_event_importable_from_package():
    from converters import anthropic_sse_event
    assert callable(anthropic_sse_event)

def test_sanitize_visible_text_importable_from_package():
    from converters import sanitize_visible_text
    assert callable(sanitize_visible_text)

def test_split_visible_reasoning_importable_from_package():
    from converters import split_visible_reasoning
    assert callable(split_visible_reasoning)

def test_convert_tool_calls_to_anthropic_importable_from_package():
    from converters import convert_tool_calls_to_anthropic
    assert callable(convert_tool_calls_to_anthropic)
```

- [ ] **Step 2.2: Run to verify they fail**

```bash
cd /teamspace/studios/this_studio/dikders && pytest tests/test_converters_init.py -v 2>&1 | tail -8
```
Expected: `ImportError` for all 8 tests.

- [ ] **Step 2.3: Populate `converters/__init__.py`**

Replace the single-line empty file with:

```python
"""Converters — public API surface for the converters package.

Consumers can import directly from `converters` instead of knowing
the exact submodule name. Submodule structure is an implementation detail.
"""
from converters.to_cursor import (  # noqa: F401
    openai_to_cursor,
    anthropic_to_cursor,
    build_tool_instruction,
    _msg,
)
from converters.from_cursor_openai import (  # noqa: F401
    openai_chunk,
    openai_sse,
    openai_done,
    openai_non_streaming_response,
    openai_usage_chunk,
)
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
from converters.from_cursor import (  # noqa: F401
    sanitize_visible_text,
    split_visible_reasoning,
    scrub_support_preamble,
)
from converters.shared import _safe_pct  # noqa: F401
```

- [ ] **Step 2.4: Run tests to verify they pass**

```bash
cd /teamspace/studios/this_studio/dikders && pytest tests/test_converters_init.py -v 2>&1 | tail -12
```
Expected: 8/8 PASS

- [ ] **Step 2.5: Run full suite**

```bash
cd /teamspace/studios/this_studio/dikders && pytest tests/ -m 'not integration' -q --tb=short 2>&1 | tail -8
```
Expected: all PASS

- [ ] **Step 2.6: Commit**

```bash
git add converters/__init__.py tests/test_converters_init.py
git commit -m "feat(converters): public API surface in __init__.py — stable package imports"
```

---

## Chunk 2: `converters/message_normalizer.py`

### Task 3: Create `converters/message_normalizer.py`

**Files:**
- Create: `converters/message_normalizer.py`
- Modify: `converters/__init__.py`
- Test: `tests/test_message_normalizer.py`

Edge cases in OpenAI and Anthropic message lists that currently reach the converters unhandled: `content: null`, `content: []`, messages with no role, and duplicate adjacent same-role messages. A pre-conversion normalizer makes these invariants explicit and testable.

- [ ] **Step 3.1: Write failing tests**

```python
# tests/test_message_normalizer.py
from converters.message_normalizer import (
    normalize_openai_messages,
    normalize_anthropic_messages,
)


class TestNormalizeOpenAIMessages:
    def test_empty_list_returns_empty(self):
        assert normalize_openai_messages([]) == []

    def test_none_content_coerced_to_empty_string(self):
        msgs = [{"role": "user", "content": None}]
        result = normalize_openai_messages(msgs)
        assert result[0]["content"] == ""

    def test_missing_content_key_coerced_to_empty_string(self):
        msgs = [{"role": "user"}]
        result = normalize_openai_messages(msgs)
        assert result[0]["content"] == ""

    def test_empty_list_content_coerced_to_empty_string(self):
        msgs = [{"role": "user", "content": []}]
        result = normalize_openai_messages(msgs)
        assert result[0]["content"] == ""

    def test_missing_role_defaults_to_user(self):
        msgs = [{"content": "hello"}]
        result = normalize_openai_messages(msgs)
        assert result[0]["role"] == "user"

    def test_valid_message_passes_through_unchanged(self):
        msgs = [{"role": "user", "content": "hello"}]
        result = normalize_openai_messages(msgs)
        assert result == [{"role": "user", "content": "hello"}]

    def test_tool_messages_content_not_coerced_to_empty(self):
        """Tool result content must not be stripped even if empty string."""
        msgs = [
            {"role": "tool", "tool_call_id": "c1", "content": ""},
        ]
        result = normalize_openai_messages(msgs)
        assert result[0]["content"] == ""
        assert result[0]["tool_call_id"] == "c1"

    def test_non_dict_entries_dropped(self):
        msgs = [{"role": "user", "content": "hi"}, "not a dict", None]
        result = normalize_openai_messages(msgs)
        assert len(result) == 1
        assert result[0]["content"] == "hi"

    def test_does_not_mutate_input(self):
        msgs = [{"role": "user", "content": None}]
        normalize_openai_messages(msgs)
        assert msgs[0]["content"] is None


class TestNormalizeAnthropicMessages:
    def test_empty_list_returns_empty(self):
        assert normalize_anthropic_messages([]) == []

    def test_none_content_coerced_to_empty_list(self):
        msgs = [{"role": "user", "content": None}]
        result = normalize_anthropic_messages(msgs)
        assert result[0]["content"] == []

    def test_missing_content_key_coerced_to_empty_list(self):
        msgs = [{"role": "user"}]
        result = normalize_anthropic_messages(msgs)
        assert result[0]["content"] == []

    def test_string_content_preserved_as_string(self):
        """Anthropic allows content as a plain string — preserve it."""
        msgs = [{"role": "user", "content": "hello"}]
        result = normalize_anthropic_messages(msgs)
        assert result[0]["content"] == "hello"

    def test_missing_role_defaults_to_user(self):
        msgs = [{"content": "hello"}]
        result = normalize_anthropic_messages(msgs)
        assert result[0]["role"] == "user"

    def test_non_dict_entries_dropped(self):
        msgs = [{"role": "user", "content": "hi"}, None, 42]
        result = normalize_anthropic_messages(msgs)
        assert len(result) == 1

    def test_does_not_mutate_input(self):
        msgs = [{"role": "user", "content": None}]
        normalize_anthropic_messages(msgs)
        assert msgs[0]["content"] is None

    def test_valid_message_passes_through_unchanged(self):
        msgs = [{"role": "user", "content": [{"type": "text", "text": "hi"}]}]
        result = normalize_anthropic_messages(msgs)
        assert result[0]["content"] == [{"type": "text", "text": "hi"}]
```

- [ ] **Step 3.2: Run to verify they fail**

```bash
cd /teamspace/studios/this_studio/dikders && pytest tests/test_message_normalizer.py -v 2>&1 | tail -5
```
Expected: `ModuleNotFoundError: No module named 'converters.message_normalizer'`

- [ ] **Step 3.3: Create `converters/message_normalizer.py`**

```python
"""Converters — pre-conversion message normalization.

Normalizes OpenAI and Anthropic message lists before they reach the
format-specific converters. Handles: None/missing content, empty content
arrays, missing role. Never mutates input — always returns new list.

Does NOT collapse adjacent same-role messages — that is the converter's
responsibility. These normalizers only enforce structural invariants.
"""
from __future__ import annotations

from copy import deepcopy


def normalize_openai_messages(messages: list[dict]) -> list[dict]:
    """Normalise a list of OpenAI-format messages before conversion.

    Invariants enforced:
    - Non-dict entries are dropped.
    - Missing `role` defaults to 'user'.
    - `content: None` or `content: []` is coerced to empty string ''
      for non-tool messages. Tool messages keep content as-is because
      empty string is a valid (and meaningful) tool result.

    Args:
        messages: Raw OpenAI message list from the client request.

    Returns:
        New list with all invariants satisfied. Input is not mutated.
    """
    out: list[dict] = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        m = deepcopy(msg)
        if "role" not in m:
            m["role"] = "user"
        # Only coerce content for non-tool messages
        if m["role"] != "tool":
            content = m.get("content")
            if content is None or content == []:
                m["content"] = ""
        out.append(m)
    return out


def normalize_anthropic_messages(messages: list[dict]) -> list[dict]:
    """Normalise a list of Anthropic-format messages before conversion.

    Invariants enforced:
    - Non-dict entries are dropped.
    - Missing `role` defaults to 'user'.
    - `content: None` is coerced to empty list `[]`.
    - String content and list content are both preserved as-is.

    Args:
        messages: Raw Anthropic message list from the client request.

    Returns:
        New list with all invariants satisfied. Input is not mutated.
    """
    out: list[dict] = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        m = deepcopy(msg)
        if "role" not in m:
            m["role"] = "user"
        content = m.get("content")
        if content is None:
            m["content"] = []
        out.append(m)
    return out
```

- [ ] **Step 3.4: Run tests to verify they pass**

```bash
cd /teamspace/studios/this_studio/dikders && pytest tests/test_message_normalizer.py -v 2>&1 | tail -15
```
Expected: 17/17 PASS

- [ ] **Step 3.5: Export from `converters/__init__.py`**

Add to `converters/__init__.py`:
```python
from converters.message_normalizer import (  # noqa: F401
    normalize_openai_messages,
    normalize_anthropic_messages,
)
```

- [ ] **Step 3.6: Run full suite**

```bash
cd /teamspace/studios/this_studio/dikders && pytest tests/ -m 'not integration' -q --tb=short 2>&1 | tail -8
```
Expected: all PASS

- [ ] **Step 3.7: Commit**

```bash
git add converters/message_normalizer.py tests/test_message_normalizer.py converters/__init__.py
git commit -m "feat(converters/message_normalizer): normalize_openai_messages + normalize_anthropic_messages"
```

---

## Chunk 3: Responses API converter tests + final cleanup

### Task 4: Unit tests for `converters/to_responses.py` and `converters/from_responses.py`

**Files:**
- Test: `tests/test_converters_responses.py`

The Responses API converters have no standalone unit tests. They are only tested via the responses router integration path.

- [ ] **Step 4.1: Confirm public API of both files**

```bash
cd /teamspace/studios/this_studio/dikders && grep -n '^def ' converters/to_responses.py converters/from_responses.py
```

Expected output (key names):
- `converters/to_responses.py` — `_output_text_from_content`, `input_to_messages`, `extract_function_tools`, `has_builtin_tools`
- `converters/from_responses.py` — `responses_sse_event`, `build_response_object`, `_build_message_output_item`, `_build_function_call_output_item`

- [ ] **Step 4.2: Write tests**

Create `tests/test_converters_responses.py`:

```python
# tests/test_converters_responses.py
"""Unit tests for converters/to_responses.py and converters/from_responses.py."""
# to_responses.py: input conversion (Responses API request -> OpenAI messages)
# from_responses.py: output conversion (pipeline result -> Responses API response shape)
from converters.from_responses import (
    build_response_object,
    responses_sse_event,
    _build_message_output_item,
    _build_function_call_output_item,
)
from converters.to_responses import (
    input_to_messages,
    _output_text_from_content,
    BUILTIN_TOOL_TYPES,
)


class TestResponsesSseEvent:
    def test_format(self):
        result = responses_sse_event("response.created", {"type": "response.created"})
        assert result.startswith("event: response.created\n")
        assert "data: " in result
        assert result.endswith("\n\n")


class TestBuildMessageOutputItem:
    def test_structure(self):
        item = _build_message_output_item("hello world", "msg_abc")
        assert item["type"] == "message"
        assert item["id"] == "msg_abc"
        assert item["role"] == "assistant"
        assert item["status"] == "completed"
        assert item["content"][0]["text"] == "hello world"
        assert item["content"][0]["type"] == "output_text"


class TestBuildFunctionCallOutputItem:
    def test_structure(self):
        tc = {
            "id": "call_abc",
            "type": "function",
            "function": {"name": "Bash", "arguments": '{"command": "ls"}'},
        }
        item = _build_function_call_output_item(tc, 0, item_id="fc_1")
        assert item["type"] == "function_call"
        assert item["id"] == "fc_1"
        assert item["call_id"] == "call_abc"
        assert item["name"] == "Bash"
        assert item["arguments"] == '{"command": "ls"}'
        assert item["status"] == "completed"

    def test_missing_item_id_synthesized(self):
        tc = {"id": "c1", "type": "function", "function": {"name": "T", "arguments": "{}"}}
        item = _build_function_call_output_item(tc, 0)
        assert item["id"].startswith("fc_")


class TestBuildResponseObject:
    def _params(self):
        return {"model": "claude-3-5-sonnet", "temperature": None}

    def test_text_only(self):
        resp = build_response_object(
            response_id="resp_1", model="m", text="hello",
            tool_calls=None, input_tokens=10, output_tokens=5, params=self._params(),
        )
        assert resp["id"] == "resp_1"
        assert resp["object"] == "realtime.response"
        assert len(resp["output"]) == 1
        assert resp["output"][0]["type"] == "message"
        assert resp["usage"]["input_tokens"] == 10
        assert resp["usage"]["output_tokens"] == 5

    def test_tool_calls_only(self):
        tool_calls = [{
            "id": "c1", "type": "function",
            "function": {"name": "Bash", "arguments": '{"command": "ls"}'}
        }]
        resp = build_response_object(
            response_id="resp_2", model="m", text=None,
            tool_calls=tool_calls, input_tokens=5, output_tokens=3, params=self._params(),
        )
        assert len(resp["output"]) == 1
        assert resp["output"][0]["type"] == "function_call"

    def test_empty_text_not_included(self):
        resp = build_response_object(
            response_id="resp_3", model="m", text="",
            tool_calls=None, input_tokens=0, output_tokens=0, params=self._params(),
        )
        assert resp["output"] == []

    def test_text_and_tool_calls(self):
        tool_calls = [{"id": "c1", "type": "function",
                       "function": {"name": "T", "arguments": "{}"}}]
        resp = build_response_object(
            response_id="resp_4", model="m", text="thinking...",
            tool_calls=tool_calls, input_tokens=1, output_tokens=1, params=self._params(),
        )
        assert len(resp["output"]) == 2
        types = {o["type"] for o in resp["output"]}
        assert "message" in types
        assert "function_call" in types


class TestOutputTextFromContent:
    def test_string_passthrough(self):
        assert _output_text_from_content("hello") == "hello"

    def test_list_of_text_blocks(self):
        content = [
            {"type": "output_text", "text": "hello"},
            {"type": "output_text", "text": " world"},
        ]
        assert _output_text_from_content(content) == "hello\n world"

    def test_non_text_blocks_ignored(self):
        content = [
            {"type": "image", "url": "http://example.com/img.png"},
            {"type": "output_text", "text": "visible"},
        ]
        assert _output_text_from_content(content) == "visible"

    def test_empty_list_returns_empty_string(self):
        assert _output_text_from_content([]) == ""


class TestBuiltinToolTypes:
    def test_web_search_present(self):
        assert "web_search_preview" in BUILTIN_TOOL_TYPES

    def test_code_interpreter_present(self):
        assert "code_interpreter" in BUILTIN_TOOL_TYPES

    def test_is_frozenset(self):
        assert isinstance(BUILTIN_TOOL_TYPES, frozenset)


class TestInputToMessages:
    def test_simple_text_input(self):
        """A plain string input with no prior output produces one user message."""
        result = input_to_messages(
            input_data="hello",
            instructions=None,
            prior_output=[],
        )
        assert any(m["role"] == "user" for m in result)

    def test_instructions_become_system_message(self):
        result = input_to_messages(
            input_data="hi",
            instructions="You are helpful.",
            prior_output=[],
        )
        assert result[0]["role"] == "system"
        assert result[0]["content"] == "You are helpful."

    def test_empty_prior_output(self):
        result = input_to_messages(
            input_data="hello",
            instructions=None,
            prior_output=[],
        )
        assert len(result) >= 1

    def test_builtin_tool_items_filtered_out(self):
        """Items whose type is in BUILTIN_TOOL_TYPES must not produce messages."""
        input_items = [
            {"type": "web_search_preview", "query": "test"},
            {"type": "message", "role": "user",
             "content": [{"type": "input_text", "text": "hello"}]},
        ]
        result = input_to_messages(
            input_data=input_items,
            instructions=None,
            prior_output=[],
        )
        # Only the user message should appear (no web_search_preview message)
        user_msgs = [m for m in result if m.get("role") == "user"]
        assert len(user_msgs) == 1
        assert "hello" in user_msgs[0]["content"]
```

- [ ] **Step 4.3: Run to verify tests fail or reveal missing functions**

```bash
cd /teamspace/studios/this_studio/dikders && pytest tests/test_converters_responses.py -v 2>&1 | tail -15
```

If `convert_responses_input_to_messages` does not exist in `from_responses.py`, check whether a differently-named public function exists:
```bash
cd /teamspace/studios/this_studio/dikders && grep -n '^def ' converters/from_responses.py
```
Adjust the import and test accordingly — do NOT create a new function, use whatever exists.

- [ ] **Step 4.4: Fix any import errors by reading the actual public API of the files**

```bash
cd /teamspace/studios/this_studio/dikders && grep -n '^def ' converters/to_responses.py converters/from_responses.py
```

Update `tests/test_converters_responses.py` imports to match exactly.

- [ ] **Step 4.5: Run tests until they pass**

```bash
cd /teamspace/studios/this_studio/dikders && pytest tests/test_converters_responses.py -v 2>&1 | tail -20
```
Expected: all PASS

- [ ] **Step 4.6: Commit**

```bash
git add tests/test_converters_responses.py
git commit -m "test(converters): unit tests for to_responses.py and from_responses.py"
```

---

### Task 5: Final verification and push

- [ ] **Step 5.1: Run full non-integration suite**

```bash
cd /teamspace/studios/this_studio/dikders && pytest tests/ -m 'not integration' -q --tb=short 2>&1 | tail -15
```
Expected: all PASS

- [ ] **Step 5.2: Run ruff on all modified/created files**

```bash
cd /teamspace/studios/this_studio/dikders && ruff check converters/shared.py converters/__init__.py converters/message_normalizer.py --select F401,F811 2>&1
```
Expected: no issues

- [ ] **Step 5.3: Verify no remaining duplicate `_safe_pct` definitions**

```bash
cd /teamspace/studios/this_studio/dikders && grep -rn 'def _safe_pct' converters/ --include='*.py'
```
Expected: exactly one result — `converters/shared.py`

- [ ] **Step 5.4: Update UPDATES.md**

Read UPDATES.md to find the last session number, then append:

```markdown
## Session 165 — Converters Gap Fixes (2026-03-28)

### What changed

| File | Change |
|---|---|
| `converters/shared.py` | New: `_safe_pct` — single canonical definition, eliminates 3x duplication |
| `converters/__init__.py` | New: public API surface — stable package imports |
| `converters/message_normalizer.py` | New: `normalize_openai_messages` + `normalize_anthropic_messages` |
| `converters/from_cursor_openai.py` | Removed local `_safe_pct` definition — imports from shared |
| `converters/from_cursor_anthropic.py` | Removed local `_safe_pct` definition — imports from shared |
| `converters/from_cursor.py` | Removed local `_safe_pct` definition — imports from shared |
| `tests/test_converters_shared.py` | New test file |
| `tests/test_converters_init.py` | New test file |
| `tests/test_message_normalizer.py` | New test file |
| `tests/test_converters_responses.py` | New test file |

### Why

`_safe_pct` was defined identically in 3 files — a silent divergence risk. `converters/__init__.py` was empty, requiring consumers to know submodule paths. `normalize_openai_messages`/`normalize_anthropic_messages` fill a gap where malformed client messages (null content, missing role) reached the converters unhandled. Responses API converters had zero unit tests.

### Commit SHAs

Run `git log --oneline main | head -10` after all commits.
```

- [ ] **Step 5.5: Commit UPDATES.md and push**

```bash
git add UPDATES.md
git commit -m "docs: update UPDATES.md for Session 165 — converters gap fixes"
git push
```

---

## Summary

| Chunk | Tasks | What it delivers |
|---|---|---|
| 1 | 1-2 | `_safe_pct` deduplication + `converters/__init__.py` public API |
| 2 | 3 | `converters/message_normalizer.py` — pre-conversion edge case handling |
| 3 | 4-5 | Responses API converter tests + full suite + push |