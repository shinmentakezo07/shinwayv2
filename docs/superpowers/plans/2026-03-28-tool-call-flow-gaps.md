# Tool Call Flow — Gap Fixes Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close 8 identified gaps in the tool-call extraction, validation, and emission pipeline: payload size cap, streaming array-root support, `tool_choice=required` enforcement, `ToolRegistry` wiring into non-streaming path, multi-tool ordering stability, partial-JSON abandonment guard, schema-default injection in repair, and a structured tool-call audit ring-buffer with `/internal/tool-calls/recent` endpoint.

**Architecture:** All changes are additive to the existing `tools/` and `pipeline/` module tree. No public API changes. Each fix is a targeted edit to one or two focused modules with corresponding tests. The audit buffer follows the same pattern as `analytics.py`.

**Tech Stack:** Python 3.12, FastAPI, pydantic-settings, structlog, msgspec, pytest, aiosqlite (none needed — in-memory ring buffer only).

---

## Chunk 1: Configuration, Size Cap, and Registry Wiring

### Task 1: Add `max_tool_args_bytes` and `max_tool_payload_bytes` to `config.py`

**Files:**
- Modify: `config.py`
- Test: `tests/test_config.py` (new file if absent)

- [ ] **Step 1.1: Write the failing test**

```python
# tests/test_config.py
from config import settings

def test_max_tool_args_bytes_default():
    assert settings.max_tool_args_bytes == 524288  # 512 KB

def test_max_tool_payload_bytes_default():
    assert settings.max_tool_payload_bytes == 2097152  # 2 MB
```

- [ ] **Step 1.2: Run test to verify it fails**

```bash
pytest tests/test_config.py::test_max_tool_args_bytes_default tests/test_config.py::test_max_tool_payload_bytes_default -v
```
Expected: `AttributeError: 'Settings' object has no attribute 'max_tool_args_bytes'`

- [ ] **Step 1.3: Add the two fields to `config.py`**

In `config.py`, inside the `Settings` class, after `max_tools`:

```python
    max_tool_args_bytes: int = Field(
        default=524288,   # 512 KB — per-call argument blob cap
        alias="SHINWAY_MAX_TOOL_ARGS_BYTES",
    )
    max_tool_payload_bytes: int = Field(
        default=2097152,  # 2 MB — streaming parser abandonment threshold
        alias="SHINWAY_MAX_TOOL_PAYLOAD_BYTES",
    )
```

- [ ] **Step 1.4: Run tests to verify they pass**

```bash
pytest tests/test_config.py::test_max_tool_args_bytes_default tests/test_config.py::test_max_tool_payload_bytes_default -v
```
Expected: PASS

- [ ] **Step 1.5: Commit**

```bash
git add config.py tests/test_config.py
git commit -m "feat(config): add max_tool_args_bytes and max_tool_payload_bytes settings"
```

---

### Task 2: Enforce per-call argument size cap in `tools/results.py`

**Files:**
- Modify: `tools/results.py`
- Test: `tests/test_results.py` (new)

- [ ] **Step 2.1: Write the failing test**

```python
# tests/test_results.py
import json
import pytest
from tools.results import _build_tool_call_results

_TOOL = [{"function": {"name": "Bash", "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}}}]

def _allowed():
    return {"bash": "Bash"}

def _schema():
    return {"Bash": {"command"}}

def test_oversized_args_dropped(monkeypatch):
    """Arguments exceeding max_tool_args_bytes must be dropped with a warning."""
    from config import settings
    monkeypatch.setattr(settings, "max_tool_args_bytes", 10)  # tiny cap
    big_args = json.dumps({"command": "x" * 100})
    merged = [{"name": "Bash", "arguments": big_args}]
    result = _build_tool_call_results(
        merged=merged,
        allowed_exact=_allowed(),
        schema_map=_schema(),
        streaming=False,
    )
    assert result == []  # dropped

def test_normal_args_pass():
    merged = [{"name": "Bash", "arguments": json.dumps({"command": "ls"})}]
    result = _build_tool_call_results(
        merged=merged,
        allowed_exact=_allowed(),
        schema_map=_schema(),
        streaming=False,
    )
    assert len(result) == 1
    assert result[0]["function"]["name"] == "Bash"
```

- [ ] **Step 2.2: Run test to verify it fails**

```bash
pytest tests/test_results.py::test_oversized_args_dropped -v
```
Expected: FAIL — no size check exists yet.

- [ ] **Step 2.3: Add size cap to `tools/results.py`**

In `_build_tool_call_results`, after `arg_str = msgjson.encode(args_dict).decode("utf-8")` and before the `out.append(...)` call:

```python
        from config import settings  # lazy import — avoids circular at module level
        if len(arg_str) > settings.max_tool_args_bytes:
            log.warning(
                "tool_args_oversized_dropped",
                tool=name,
                size=len(arg_str),
                limit=settings.max_tool_args_bytes,
            )
            continue
```

- [ ] **Step 2.4: Run all results tests**

```bash
pytest tests/test_results.py -v
```
Expected: all PASS

- [ ] **Step 2.5: Commit**

```bash
git add tools/results.py tests/test_results.py
git commit -m "feat(tools/results): drop tool calls whose serialised args exceed max_tool_args_bytes"
```

---

### Task 3: Wire `ToolRegistry` into the non-streaming pipeline

**Context:** `pipeline/nonstream.py:_parse_score_repair` calls `parse_tool_calls_from_text(text, params.tools)` without a `registry=` argument, so `allowed_exact` / `schema_map` are rebuilt on every call. The streaming paths already pass `registry=`.

**Files:**
- Modify: `pipeline/params.py`
- Modify: `pipeline/tools.py`
- Modify: `pipeline/nonstream.py`
- Modify: `pipeline/stream_openai.py` (registry construction — ensure same pattern)
- Modify: `pipeline/stream_anthropic.py` (same)
- Test: `tests/test_registry_nonstream.py` (new)

- [ ] **Step 3.1: Add `registry` field to `PipelineParams`**

In `pipeline/params.py`:

```python
# Add at top of file
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from tools.registry import ToolRegistry

@dataclass
class PipelineParams:
    # ... existing fields unchanged ...
    registry: "ToolRegistry | None" = field(default=None, repr=False)
```

- [ ] **Step 3.2: Write failing test**

```python
# tests/test_registry_nonstream.py
import json
from unittest.mock import patch, AsyncMock
from pipeline.params import PipelineParams
from tools.registry import ToolRegistry

_TOOL = [{"type": "function", "function": {"name": "Bash", "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}}}]

def test_registry_field_on_params():
    reg = ToolRegistry(_TOOL)
    p = PipelineParams(
        api_style="openai",
        model="gpt-4",
        messages=[],
        cursor_messages=[],
        tools=_TOOL,
        registry=reg,
    )
    assert p.registry is reg

def test_registry_none_by_default():
    p = PipelineParams(
        api_style="openai",
        model="gpt-4",
        messages=[],
        cursor_messages=[],
    )
    assert p.registry is None
```

- [ ] **Step 3.3: Run failing test**

```bash
pytest tests/test_registry_nonstream.py -v
```
Expected: FAIL — `registry` field doesn't exist yet.

- [ ] **Step 3.4: Add `registry` field to `PipelineParams`** (apply step 3.1 edit)

- [ ] **Step 3.5: Run test to verify it passes**

```bash
pytest tests/test_registry_nonstream.py -v
```
Expected: PASS

- [ ] **Step 3.6: Thread `registry` through `_parse_score_repair` in `pipeline/tools.py`**

Update `_parse_score_repair` signature and body:

```python
def _parse_score_repair(
    text: str,
    params: PipelineParams,
    context: str,
) -> list[dict]:
    calls = _limit_tool_calls(
        parse_tool_calls_from_text(
            text,
            params.tools,
            registry=params.registry,   # <-- was missing
        ) or [],
        params.parallel_tool_calls,
    )
    if not calls:
        return []
    confidence = score_tool_call_confidence(text, calls)
    log.debug("tool_call_confidence", score=confidence, calls=len(calls))
    if confidence < CONFIDENCE_THRESHOLD:
        log.debug("low_confidence_tool_call_dropped", score=confidence)
        return []
    log_tool_calls(calls, context=context)
    return _repair_invalid_calls(calls, params.tools)
```

- [ ] **Step 3.7: Build `ToolRegistry` once in routers/callers and assign to `params.registry`**

In `routers/unified.py` (or wherever `PipelineParams` is constructed before calling `handle_openai_non_streaming` / `handle_anthropic_non_streaming`), add:

```python
from tools.registry import ToolRegistry

# When building PipelineParams:
registry = ToolRegistry(validated_tools) if validated_tools else None
params = PipelineParams(
    ...,
    registry=registry,
)
```

The streaming paths (`stream_openai.py`, `stream_anthropic.py`) already build `ToolRegistry` locally — keep those as-is; they now read from `params.registry` as a fallback if present.

- [ ] **Step 3.8: Run existing registry wiring tests**

```bash
pytest tests/test_registry_wiring.py tests/test_registry_nonstream.py -v
```
Expected: all PASS

- [ ] **Step 3.9: Commit**

```bash
git add pipeline/params.py pipeline/tools.py pipeline/nonstream.py routers/unified.py tests/test_registry_nonstream.py
git commit -m "feat(pipeline): thread ToolRegistry into non-streaming path via PipelineParams.registry"
```

---

## Chunk 2: Streaming Array-Root and Partial-JSON Abandonment

### Task 4: Fix `StreamingToolCallParser` to handle array-root payloads

**Context:** The JSON-complete detector in `StreamingToolCallParser.feed()` looks for the opening `{` after the marker. If the upstream emits a bare array `[{...}]` (Shape 1), `_json_start` is never set and the call falls through to `finalize()`.

**Files:**
- Modify: `tools/streaming.py`
- Test: `tests/test_streaming.py`

- [ ] **Step 4.1: Write the failing test**

```python
# In tests/test_streaming.py — add this test
from tools.streaming import StreamingToolCallParser

_TOOL = [{"type": "function", "function": {"name": "Bash", "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}}}]

def test_array_root_detected_during_streaming():
    """Shape 1: bare array [{}] after marker — parser must detect JSON-complete during streaming."""
    parser = StreamingToolCallParser(_TOOL)
    payload = '[assistant_tool_calls]\n[{"name":"Bash","arguments":{"command":"ls"}}]'
    # Feed in two chunks
    r1 = parser.feed(payload[:30])
    r2 = parser.feed(payload[30:])
    # At least one feed call must return non-None (detected during streaming, not just finalize)
    assert r1 is not None or r2 is not None
```

- [ ] **Step 4.2: Run to verify it fails**

```bash
pytest tests/test_streaming.py::test_array_root_detected_during_streaming -v
```
Expected: FAIL — both `r1` and `r2` are `None`; detection only happens in `finalize()`.

- [ ] **Step 4.3: Update `StreamingToolCallParser` to track both `{`/`}` and `[`/`]` as outermost containers**

In `tools/streaming.py`, modify `__init__` and `feed`:

```python
class StreamingToolCallParser:
    _LOOKBACK = len("[assistant_tool_calls]")

    def __init__(self, tools: list[dict], registry=None) -> None:
        from tools.parse import parse_tool_calls_from_text as _ptcft
        self._parse = _ptcft
        self._tools = tools
        self._registry = registry
        self.buf = ""
        self._scan_pos = 0
        self._marker_confirmed = False
        self._marker_pos: int = -1
        self._json_start: int = -1
        self._depth: int = 0
        self._in_str: bool = False
        self._esc: bool = False
        self._json_complete: bool = False
        self._last_result = None
        self._root_char: str = "{"   # NEW: '{' or '['
        self._close_char: str = "}"  # NEW: '}' or ']'

    def feed(self, chunk: str):
        self.buf += chunk
        if not self._marker_confirmed:
            rescan_start = max(0, self._scan_pos - self._LOOKBACK)
            from tools.score import _find_marker_pos
            relative_pos = _find_marker_pos(self.buf[rescan_start:])
            if relative_pos >= 0:
                self._marker_pos = rescan_start + relative_pos
                self._marker_confirmed = True
                # Detect whether payload is object or array
                post = self.buf[self._marker_pos:]
                brace = post.find("{")
                bracket = post.find("[")
                if bracket >= 0 and (brace < 0 or bracket < brace):
                    self._root_char = "["
                    self._close_char = "]"
                    self._json_start = self._marker_pos + bracket
                elif brace >= 0:
                    self._root_char = "{"
                    self._close_char = "}"
                    self._json_start = self._marker_pos + brace
                self._scan_pos = self._json_start if self._json_start >= 0 else self._marker_pos
            else:
                self._scan_pos = max(0, len(self.buf) - self._LOOKBACK)
            if not self._marker_confirmed:
                return None

        if self._json_complete:
            return self._last_result

        buf = self.buf
        buf_len = len(buf)
        i = self._scan_pos
        open_ch = self._root_char
        close_ch = self._close_char
        while i < buf_len:
            ch = buf[i]
            if self._esc:
                self._esc = False
            elif self._in_str:
                if ch == "\\":
                    self._esc = True
                elif ch == '"':
                    self._in_str = False
            else:
                if ch == '"':
                    self._in_str = True
                elif ch == open_ch:
                    self._depth += 1
                elif ch == close_ch:
                    self._depth -= 1
                    if self._depth == 0:
                        self._json_complete = True
                        self._scan_pos = i + 1
                        self._last_result = self._parse(
                            buf[self._marker_pos:], self._tools,
                            streaming=True, registry=self._registry,
                        )
                        return self._last_result
            i += 1
        self._scan_pos = buf_len
        return None
```

- [ ] **Step 4.4: Run all streaming tests**

```bash
pytest tests/test_streaming.py -v
```
Expected: all PASS including `test_array_root_detected_during_streaming`

- [ ] **Step 4.5: Commit**

```bash
git add tools/streaming.py tests/test_streaming.py
git commit -m "fix(tools/streaming): support bare-array root payloads in StreamingToolCallParser"
```

---

### Task 5: Partial-JSON abandonment guard in `StreamingToolCallParser`

**Context:** If the upstream closes before the closing bracket/brace, `finalize()` attempts a non-streaming re-parse. There is no byte cap — a 10 MB truncated payload will wait. Add `max_tool_payload_bytes` guard.

**Files:**
- Modify: `tools/streaming.py`
- Test: `tests/test_streaming.py`

- [ ] **Step 5.1: Write the failing test**

```python
# tests/test_streaming.py — add:
from config import settings

def test_oversized_payload_abandoned(monkeypatch):
    """Parser must return None and not hang when payload exceeds max_tool_payload_bytes."""
    monkeypatch.setattr(settings, "max_tool_payload_bytes", 50)
    parser = StreamingToolCallParser(_TOOL)
    marker = "[assistant_tool_calls]\n"
    result = parser.feed(marker + "{" + "x" * 100)  # never closes
    assert result is None  # abandoned, not hung
    assert parser._json_abandoned  # flag set
```

- [ ] **Step 5.2: Run to verify it fails**

```bash
pytest tests/test_streaming.py::test_oversized_payload_abandoned -v
```
Expected: FAIL — no `_json_abandoned` attribute and no cap.

- [ ] **Step 5.3: Add `_json_abandoned` flag and byte-cap check in `feed()`**

In `StreamingToolCallParser.__init__` add:
```python
        self._json_abandoned: bool = False
```

In `feed()`, at the top of the scanning loop (before `while i < buf_len`), add:
```python
        if self._json_start >= 0:
            payload_len = len(buf) - self._json_start
            from config import settings
            if payload_len > settings.max_tool_payload_bytes:
                log.warning(
                    "tool_streaming_payload_too_large",
                    size=payload_len,
                    limit=settings.max_tool_payload_bytes,
                )
                self._json_abandoned = True
                return None
```

Also guard `finalize()` against abandoned state:
```python
    def finalize(self):
        if self._json_abandoned or not self.buf:
            return None
        parse_slice = self.buf[self._marker_pos:] if self._marker_pos >= 0 else self.buf
        return self._parse(parse_slice, self._tools, streaming=False, registry=self._registry)
```

- [ ] **Step 5.4: Run all streaming tests**

```bash
pytest tests/test_streaming.py -v
```
Expected: all PASS

- [ ] **Step 5.5: Commit**

```bash
git add tools/streaming.py tests/test_streaming.py
git commit -m "feat(tools/streaming): abandon oversized partial-JSON payloads via max_tool_payload_bytes"
```

---

## Chunk 3: tool_choice Enforcement, Ordering, and Schema-Default Repair

### Task 6: Enforce `tool_choice=required` post-stream in streaming path

**Context:** Non-streaming already retries when `tool_choice=required` and no calls parsed (`pipeline/nonstream.py:99-117`). Streaming path (`stream_openai.py`) has no equivalent check — it silently emits a text response.

**Files:**
- Modify: `pipeline/stream_openai.py`
- Modify: `pipeline/stream_anthropic.py`
- Test: `tests/test_stream_openai.py`

- [ ] **Step 6.1: Write failing test**

```python
# tests/test_stream_openai.py — add:
import pytest
from unittest.mock import AsyncMock, patch

async def _fake_stream_text(chunks):
    for c in chunks:
        yield c

@pytest.mark.asyncio
async def test_tool_choice_required_triggers_retry(monkeypatch):
    """When tool_choice=required and stream yields no tool calls, a retry must occur."""
    call_count = {"n": 0}

    async def fake_stream(*a, **kw):
        call_count["n"] += 1
        # First call: pure text. Second call: also text (max retries).
        for chunk in ["Hello world"]:
            yield chunk

    import pipeline
    monkeypatch.setattr(pipeline, "parse_tool_calls_from_text", lambda *a, **kw: [])
    monkeypatch.setattr(pipeline, "score_tool_call_confidence", lambda *a, **kw: 1.0)
    # verify retry_count > 1 after exhaustion
    from config import settings
    monkeypatch.setattr(settings, "retry_attempts", 2)
    # ... (full async test wiring; see existing test_stream_openai.py patterns)
    assert call_count["n"] >= 2
```

- [ ] **Step 6.2: Run to verify it fails**

```bash
pytest tests/test_stream_openai.py::test_tool_choice_required_triggers_retry -v
```
Expected: FAIL

- [ ] **Step 6.3: Add `_tool_choice_requires_call()` helper and retry block to `stream_openai.py`**

Add helper near top of `pipeline/stream_openai.py`:
```python
def _tool_choice_requires_call(tool_choice) -> bool:
    """Return True when the client mandates at least one tool call."""
    if tool_choice in ("required", "any"):
        return True
    if isinstance(tool_choice, dict):
        return tool_choice.get("type") in ("any", "function", "tool")
    return False
```

In `_openai_stream`, after the final `parsed_calls` is determined and before emitting:
```python
    if (
        params.tools
        and _tool_choice_requires_call(params.tool_choice)
        and not parsed_calls
        and _retry_count < settings.retry_attempts
    ):
        # Retry with an appended reminder — mirrors nonstream.py:104-116
        retry_params = _with_appended_cursor_message(
            params,
            _msg("user", "This request needs a tool call. Please respond using the "
                          "[assistant_tool_calls] JSON format with one of the session tools."),
        )
        async for chunk in _openai_stream(client, retry_params, anthropic_tools,
                                           _retry_count=_retry_count + 1):
            yield chunk
        return
```

Add `_retry_count: int = 0` to `_openai_stream` signature.
Apply equivalent change to `_anthropic_stream` in `stream_anthropic.py`.

- [ ] **Step 6.4: Run full streaming test suite**

```bash
pytest tests/test_stream_openai.py tests/test_stream_anthropic.py -v
```
Expected: all PASS

- [ ] **Step 6.5: Commit**

```bash
git add pipeline/stream_openai.py pipeline/stream_anthropic.py tests/test_stream_openai.py
git commit -m "feat(pipeline): enforce tool_choice=required retry in streaming path"
```

---

### Task 7: Schema-default injection in `repair_tool_call`

**Context:** `repair_tool_call` in `tools/repair.py` marks missing required string params as `UNFILLABLE` (line 129). But when the schema declares a `default`, the value is safe to inject automatically — promoting case 3 (drop) → case 2 (repaired) in `repair_invalid_calls`.

**Files:**
- Modify: `tools/repair.py`
- Test: `tests/test_repair.py`

- [ ] **Step 7.1: Write failing test**

```python
# tests/test_repair.py — add:
from tools.repair import repair_tool_call
import json

def test_default_injected_for_missing_required():
    """Missing required param with schema default must be auto-filled, not marked UNFILLABLE."""
    tool = {"type": "function", "function": {
        "name": "Search",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string"},
            "limit": {"type": "integer", "default": 10},
        }, "required": ["query", "limit"]},
    }}
    call = {"id": "c1", "type": "function",
            "function": {"name": "Search", "arguments": json.dumps({"query": "hello"})}}
    repaired, repairs = repair_tool_call(call, [tool])
    args = json.loads(repaired["function"]["arguments"])
    assert args["limit"] == 10
    assert any("limit" in r for r in repairs)
    assert not any("UNFILLABLE" in r for r in repairs)

def test_string_with_default_injected():
    """String param with explicit default must be filled, not skipped."""
    tool = {"type": "function", "function": {
        "name": "Greet",
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string", "default": "World"},
        }, "required": ["name"]},
    }}
    call = {"id": "c2", "type": "function",
            "function": {"name": "Greet", "arguments": "{}"}}
    repaired, repairs = repair_tool_call(call, [tool])
    args = json.loads(repaired["function"]["arguments"])
    assert args["name"] == "World"
```

- [ ] **Step 7.2: Run to verify it fails**

```bash
pytest tests/test_repair.py::test_default_injected_for_missing_required tests/test_repair.py::test_string_with_default_injected -v
```
Expected: FAIL — defaults are not injected.

- [ ] **Step 7.3: Modify `repair_tool_call` in `tools/repair.py`**

In the required-param filling block (around line 110-131), replace the string-skip logic:

Replace the required-param block in `tools/repair.py` Pass 3 (lines ~103-131) with:

```python
    # Pass 3 — fill missing required params.
    # Priority: (1) explicit schema default, (2) type-appropriate safe fallback.
    # String params with NO default and NO enum are left UNFILLABLE to prevent
    # fabricating empty destructive values (e.g. empty 'command', empty 'path').
    for req in required:
        if req not in repaired_args:
            prop_schema = known_props.get(req, {})
            prop_type = prop_schema.get("type", "string")
            explicit_default = prop_schema.get("default", _SENTINEL)

            if explicit_default is not _SENTINEL:
                # Schema declared a default — always safe to inject
                repaired_args[req] = explicit_default
                repairs.append(f"filled missing required '{req}' with schema default {explicit_default!r}")
            elif prop_schema.get("enum"):
                fallback = prop_schema["enum"][0]
                repaired_args[req] = fallback
                repairs.append(f"filled missing required '{req}' with first enum value {fallback!r}")
            elif prop_type == "array":
                repaired_args[req] = []
                repairs.append(f"filled missing required '{req}' with []")
            elif prop_type == "object":
                repaired_args[req] = {}
                repairs.append(f"filled missing required '{req}' with {{}}")
            elif prop_type == "boolean":
                repaired_args[req] = False
                repairs.append(f"filled missing required '{req}' with false")
            elif prop_type in ("number", "integer"):
                repaired_args[req] = 0
                repairs.append(f"filled missing required '{req}' with 0")
            else:
                repairs.append(f"UNFILLABLE: missing required string '{req}' has no safe default")
```

Add sentinel at module top:
```python
_SENTINEL = object()  # distinguishes "no default" from default=None
```

- [ ] **Step 7.4: Run repair tests**

```bash
pytest tests/test_repair.py -v
```
Expected: all PASS

- [ ] **Step 7.5: Commit**

```bash
git add tools/repair.py tests/test_repair.py
git commit -m "feat(tools/repair): inject schema default for missing required params before UNFILLABLE"
```

---

## Chunk 4: Multi-Tool Ordering and Audit Ring Buffer

### Task 8: Stable multi-tool ordering by schema declaration order

**Context:** When the model emits multiple tool calls in one payload, `OpenAIToolEmitter.emit()` assigns `index` by first-seen order. This can differ from the client's declared tool list order. Add index-stabilisation by sorting the parsed call list to match schema order before emitting.

**Files:**
- Modify: `tools/budget.py` (add `sort_calls_by_schema_order`)
- Modify: `pipeline/stream_openai.py` (call sort before emit)
- Modify: `pipeline/nonstream.py` (call sort before building response)
- Test: `tests/test_budget.py` (new)

- [ ] **Step 8.1: Write the failing test**

```python
# tests/test_budget.py
import json
from tools.budget import sort_calls_by_schema_order

_TOOLS = [
    {"type": "function", "function": {"name": "Read", "parameters": {}}},
    {"type": "function", "function": {"name": "Write", "parameters": {}}},
    {"type": "function", "function": {"name": "Bash", "parameters": {}}},
]

def _call(name):
    return {"id": f"c_{name}", "type": "function",
            "function": {"name": name, "arguments": "{}"}}

def test_sort_respects_schema_order():
    calls = [_call("Bash"), _call("Read"), _call("Write")]
    sorted_calls = sort_calls_by_schema_order(calls, _TOOLS)
    names = [c["function"]["name"] for c in sorted_calls]
    assert names == ["Read", "Write", "Bash"]

def test_sort_unknown_tool_goes_last():
    calls = [_call("Unknown"), _call("Read")]
    sorted_calls = sort_calls_by_schema_order(calls, _TOOLS)
    names = [c["function"]["name"] for c in sorted_calls]
    assert names[0] == "Read"
    assert names[-1] == "Unknown"

def test_sort_empty_calls():
    assert sort_calls_by_schema_order([], _TOOLS) == []

def test_sort_empty_tools():
    calls = [_call("Bash")]
    result = sort_calls_by_schema_order(calls, [])
    assert result == calls  # unchanged when no schema
```

- [ ] **Step 8.2: Run to verify it fails**

```bash
pytest tests/test_budget.py -v
```
Expected: `ImportError` — `sort_calls_by_schema_order` does not exist.

- [ ] **Step 8.3: Add `sort_calls_by_schema_order` to `tools/budget.py`**

```python
def sort_calls_by_schema_order(
    calls: list[dict],
    tools: list[dict],
) -> list[dict]:
    """Re-order parsed tool calls to match the client's declared tool list order.

    Calls whose name is not in the schema are appended at the end, preserving
    their relative order. Calls within the schema are sorted by schema position.
    Does not mutate the input list.
    """
    if not tools or not calls:
        return calls
    order: dict[str, int] = {
        t.get("function", {}).get("name", ""): i
        for i, t in enumerate(tools)
        if isinstance(t, dict)
    }
    sentinel = len(tools)  # unknown tools sort after all known ones
    return sorted(calls, key=lambda c: order.get(c.get("function", {}).get("name", ""), sentinel))
```

- [ ] **Step 8.4: Wire into streaming path**

In `pipeline/stream_openai.py`, after `parsed_calls` is finalised and before `_emitter.emit(parsed_calls)`:

```python
    from tools.budget import sort_calls_by_schema_order as _sort_calls
    parsed_calls = _sort_calls(parsed_calls, params.tools)
```

Apply equivalent in `pipeline/nonstream.py` before building the response message.

- [ ] **Step 8.5: Run tests**

```bash
pytest tests/test_budget.py tests/test_stream_openai.py tests/test_pipeline.py -v
```
Expected: all PASS

- [ ] **Step 8.6: Commit**

```bash
git add tools/budget.py pipeline/stream_openai.py pipeline/nonstream.py tests/test_budget.py
git commit -m "feat(tools/budget): sort parallel tool calls by schema declaration order"
```

---

### Task 9: Tool call audit ring buffer + `/internal/tool-calls/recent` endpoint

**Context:** `log_tool_calls` emits structlog entries but there is no in-process queryable buffer. Add `tools/audit.py` (ring buffer, same pattern as `analytics.py`) and expose it at `/internal/tool-calls/recent`.

**Files:**
- Create: `tools/audit.py`
- Modify: `tools/parse.py` (call `audit.record()` from `log_tool_calls`)
- Modify: `routers/internal.py` (add endpoint)
- Test: `tests/test_audit.py` (new)

- [ ] **Step 9.1: Write the failing tests**

```python
# tests/test_audit.py
import json
from tools.audit import ToolCallAudit

def _call(name, args=None):
    return {
        "id": f"c_{name}",
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args or {})},
    }

def test_record_and_recent():
    buf = ToolCallAudit(maxsize=10)
    buf.record([_call("Bash", {"command": "ls"})], raw="[assistant_tool_calls]\n{}", outcome="success")
    entries = buf.recent()
    assert len(entries) == 1
    assert entries[0]["calls"][0]["function"]["name"] == "Bash"
    assert entries[0]["outcome"] == "success"

def test_ring_evicts_oldest():
    buf = ToolCallAudit(maxsize=3)
    for i in range(5):
        buf.record([_call(f"Tool{i}")], raw="x", outcome="success")
    entries = buf.recent()
    assert len(entries) == 3
    names = [e["calls"][0]["function"]["name"] for e in entries]
    assert "Tool0" not in names
    assert "Tool4" in names

def test_recent_limit():
    buf = ToolCallAudit(maxsize=20)
    for i in range(15):
        buf.record([_call(f"T{i}")], raw="x", outcome="success")
    assert len(buf.recent(limit=5)) == 5

def test_empty_buffer():
    buf = ToolCallAudit(maxsize=10)
    assert buf.recent() == []
```

- [ ] **Step 9.2: Run to verify it fails**

```bash
pytest tests/test_audit.py -v
```
Expected: `ModuleNotFoundError: No module named 'tools.audit'`

- [ ] **Step 9.3: Create `tools/audit.py`**

```python
"""Shin Proxy — Tool call audit ring buffer.

Stores the last N raw tool call payloads with their parse outcome.
Thread-safe for asyncio (single-threaded event loop). No external deps.
Follows the same in-memory ring-buffer pattern as analytics.py.
"""
from __future__ import annotations

import collections
import time
from copy import deepcopy
from typing import Any


class ToolCallAudit:
    """Fixed-size ring buffer of recent tool call parse events.

    Args:
        maxsize: Maximum number of events to retain. Oldest entries are
                 evicted when the buffer is full.
    """

    def __init__(self, maxsize: int = 50) -> None:
        self._buf: collections.deque[dict] = collections.deque(maxlen=maxsize)

    def record(
        self,
        calls: list[dict],
        raw: str,
        outcome: str,
        request_id: str = "",
    ) -> None:
        """Append a parse event to the buffer.

        Args:
            calls:      Parsed tool call list (will be deep-copied).
            raw:        Raw marker+JSON text slice from the upstream stream.
            outcome:    Parse outcome label — 'success', 'low_confidence_dropped',
                        'oversized_dropped', 'streaming_abandoned'.
            request_id: Optional request identifier for correlation.
        """
        self._buf.append({
            "ts": time.time(),
            "request_id": request_id,
            "outcome": outcome,
            "call_count": len(calls),
            "calls": deepcopy(calls),
            "raw_snippet": raw[:500],  # cap to prevent huge audit entries
        })

    def recent(self, limit: int | None = None) -> list[dict]:
        """Return the most recent entries, newest-last.

        Args:
            limit: If provided, return at most this many entries.

        Returns:
            List of audit entry dicts. Does not mutate the buffer.
        """
        entries = list(self._buf)
        if limit is not None:
            entries = entries[-limit:]
        return entries


# Module-level singleton — built once, shared across all requests.
tool_call_audit = ToolCallAudit(maxsize=50)
```

- [ ] **Step 9.4: Run audit tests**

```bash
pytest tests/test_audit.py -v
```
Expected: all PASS

- [ ] **Step 9.5: Wire `tool_call_audit.record()` into `log_tool_calls` in `tools/parse.py`**

In `tools/parse.py`, update `log_tool_calls`:

```python
def log_tool_calls(
    calls: list[dict],
    context: str = "parsed",
    request_id: str | None = None,
    raw: str = "",
    outcome: str = "success",
) -> None:
    """Emit structured log entry per call and record to audit buffer."""
    from tools.audit import tool_call_audit  # lazy — avoids import cycle
    tool_call_audit.record(calls, raw=raw, outcome=outcome, request_id=request_id or "")
    for call in calls or []:
        fn = call.get("function", {})
        name = fn.get("name", "unknown")
        args_raw = fn.get("arguments", "{}")
        try:
            args_dict = msgjson.decode(args_raw.encode()) if isinstance(args_raw, str) else args_raw
        except Exception:
            args_dict = {}
        log.info(
            "tool_call",
            context=context,
            tool=name,
            call_id=call.get("id", ""),
            arg_keys=sorted(args_dict.keys()) if isinstance(args_dict, dict) else [],
            arg_count=len(args_dict) if isinstance(args_dict, dict) else 0,
            **({
                "request_id": request_id} if request_id else {}),
        )
```

Update call sites that call `log_tool_calls` to pass `raw=text` where the raw text is available (e.g. in `_parse_score_repair` and `parse_tool_calls_from_text`).

- [ ] **Step 9.6: Add `/internal/tool-calls/recent` endpoint to `routers/internal.py`**

```python
@router.get("/internal/tool-calls/recent", summary="Recent tool call parse events")
async def get_recent_tool_calls(
    limit: int = 50,
    _: str = Depends(verify_admin),
) -> dict:
    """Return the last N tool call parse events from the in-process audit buffer.

    Requires admin auth (same as /internal/logs).
    """
    from tools.audit import tool_call_audit
    entries = tool_call_audit.recent(limit=min(limit, 200))
    return {"count": len(entries), "entries": entries}
```

- [ ] **Step 9.7: Run full internal router tests**

```bash
pytest tests/test_internal.py tests/test_audit.py -v
```
Expected: all PASS

- [ ] **Step 9.8: Commit**

```bash
git add tools/audit.py tools/parse.py routers/internal.py tests/test_audit.py
git commit -m "feat(tools/audit): tool call audit ring buffer + /internal/tool-calls/recent endpoint"
```

---

## Chunk 5: Full Test Run, UPDATES.md, and Push

### Task 10: Run full test suite and fix any regressions

**Files:** All test files.

- [ ] **Step 10.1: Run all non-integration tests**

```bash
pytest tests/ -m 'not integration' -v --tb=short 2>&1 | tail -40
```
Expected: all PASS. If failures appear, fix the root cause in the affected module before continuing.

- [ ] **Step 10.2: Verify no import cycles**

```bash
python -c "import tools.audit; import tools.parse; import pipeline.tools; import routers.internal; print('ok')"
```
Expected: `ok` — no import errors.

- [ ] **Step 10.3: Commit any fixes from the regression run**

```bash
git add -A
git commit -m "fix: resolve any regressions from tool-call gap fixes"
```

---

### Task 11: Update UPDATES.md and push

**Files:**
- Modify: `UPDATES.md`

- [ ] **Step 11.1: Add a new session entry to `UPDATES.md`**

Append a new section at the bottom of `UPDATES.md`:

```markdown
## Session 155 — Tool Call Flow Gap Fixes (2026-03-28)

### What changed

| File | Change |
|---|---|
| `config.py` | Added `SHINWAY_MAX_TOOL_ARGS_BYTES` (512 KB) and `SHINWAY_MAX_TOOL_PAYLOAD_BYTES` (2 MB) settings |
| `tools/results.py` | Drop calls whose serialised args exceed `max_tool_args_bytes` |
| `tools/streaming.py` | Array-root payload support (`[{...}]` shape), `_json_abandoned` size-cap guard, `max_tool_payload_bytes` enforcement in `finalize()` |
| `tools/repair.py` | Schema `default` injection for missing required params (before UNFILLABLE); `_SENTINEL` constant |
| `tools/budget.py` | `sort_calls_by_schema_order()` — stable multi-tool index assignment |
| `tools/audit.py` | New: `ToolCallAudit` ring buffer + `tool_call_audit` singleton |
| `tools/parse.py` | `log_tool_calls` extended with `raw=` / `outcome=` args; audit recording wired in |
| `pipeline/params.py` | Added `registry: ToolRegistry | None` field |
| `pipeline/tools.py` | `_parse_score_repair` passes `registry=params.registry` to parser |
| `pipeline/nonstream.py` | `sort_calls_by_schema_order` applied before response build; registry wired |
| `pipeline/stream_openai.py` | `_tool_choice_requires_call()` helper; `tool_choice=required` retry loop; sort applied before emit |
| `pipeline/stream_anthropic.py` | Same `tool_choice=required` retry as OpenAI path |
| `routers/unified.py` | `ToolRegistry` built once per request and stored on `PipelineParams.registry` |
| `routers/internal.py` | `GET /internal/tool-calls/recent` endpoint |
| `tests/test_config.py` | Config field coverage |
| `tests/test_results.py` | Size-cap enforcement |
| `tests/test_streaming.py` | Array-root + abandonment guard |
| `tests/test_repair.py` | Schema default injection |
| `tests/test_budget.py` | Sort ordering |
| `tests/test_audit.py` | Ring buffer |
| `tests/test_registry_nonstream.py` | Registry field on PipelineParams |

### Why

Gap audit of the tool-call extraction pipeline identified 8 missing behaviours:
1. No argument size cap — unbounded args could pass through.
2. `StreamingToolCallParser` only tracked `{}`-root payloads; bare-array shape fell through to `finalize()`.
3. No partial-JSON abandonment threshold — truncated streams waited for HTTP timeout.
4. `tool_choice=required` was advisory-only in the streaming path.
5. `ToolRegistry` was not threaded into non-streaming parse, causing per-call rebuilds.
6. Multi-tool index assignment was first-seen, not schema-declared order.
7. Schema `default` values were ignored during repair — valid safe fills were marked UNFILLABLE.
8. No queryable in-process tool call audit trail for production debugging.

### Commit SHAs

| SHA | Description |
|---|---|
| TBD | feat(config): add max_tool_args_bytes and max_tool_payload_bytes settings |
| TBD | feat(tools/results): drop tool calls whose serialised args exceed max_tool_args_bytes |
| TBD | feat(pipeline): thread ToolRegistry into non-streaming path via PipelineParams.registry |
| TBD | fix(tools/streaming): support bare-array root payloads in StreamingToolCallParser |
| TBD | feat(tools/streaming): abandon oversized partial-JSON payloads via max_tool_payload_bytes |
| TBD | feat(pipeline): enforce tool_choice=required retry in streaming path |
| TBD | feat(tools/repair): inject schema default for missing required params before UNFILLABLE |
| TBD | feat(tools/budget): sort parallel tool calls by schema declaration order |
| TBD | feat(tools/audit): tool call audit ring buffer + /internal/tool-calls/recent endpoint |
| TBD | fix: resolve any regressions from tool-call gap fixes |
```

- [ ] **Step 11.2: Commit and push**

```bash
git add UPDATES.md
git commit -m "docs: update UPDATES.md for Session 155 — tool call flow gap fixes"
git push
```

---

## Summary

| Chunk | Tasks | Gaps closed |
|---|---|---|
| 1 | 1-3 | Config settings, arg size cap, ToolRegistry non-streaming wiring |
| 2 | 4-5 | Streaming array-root, partial-JSON abandonment |
| 3 | 6-7 | tool_choice=required enforcement, schema-default repair |
| 4 | 8-9 | Multi-tool ordering, audit ring buffer + endpoint |
| 5 | 10-11 | Regression test run, UPDATES.md, push |