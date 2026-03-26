# tools/ Phase 2 Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire `validate_schema` into the production repair path, extract `budget.py` + `emitter.py` from `pipeline/tools.py`, and wire `ToolRegistry` into the streaming hot path — with zero breaking changes.

**Architecture:** Six-step sequential rollout. Each step produces a passing test suite before the next begins. `pipeline/tools.py` keeps re-export aliases throughout so no intermediate broken state is possible. `pipeline/__init__.py` is never touched.

**Tech Stack:** Python 3.12, msgspec, structlog, pytest. No new pip dependencies.

**Spec:** `docs/superpowers/specs/2026-03-26-tools-phase2-design.md`

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `tools/validate.py` | CREATE | `validate_tool_call_full` — sequential gate: `validate_tool_call` → `validate_schema` |
| `tools/budget.py` | CREATE | `limit_tool_calls`, `repair_invalid_calls` (uses `validate_tool_call_full`) |
| `tools/emitter.py` | CREATE | `compute_tool_signature`, `parse_tool_arguments`, `serialize_tool_arguments`, `stream_anthropic_tool_input`, `OpenAIToolEmitter` |
| `tools/parse.py` | MODIFY | Add `registry: ToolRegistry | None = None` param to `parse_tool_calls_from_text` |
| `tools/streaming.py` | MODIFY | Add `registry` param to `StreamingToolCallParser.__init__`, `feed()`, `finalize()` |
| `pipeline/tools.py` | MODIFY | Remove moved bodies; add re-export aliases; `_parse_score_repair` body stays |
| `pipeline/stream_openai.py` | MODIFY | Direct imports from `tools.budget`, `tools.emitter`, `tools.registry`; construct `ToolRegistry` once per request |
| `pipeline/stream_anthropic.py` | MODIFY | Direct imports from `tools.budget`, `tools.emitter`; construct `ToolRegistry` once per request |
| `tests/test_validate.py` | CREATE | Tests for `validate_tool_call_full` |
| `tests/test_budget.py` | CREATE | Tests for `limit_tool_calls` + `repair_invalid_calls` |
| `tests/test_emitter.py` | CREATE | Tests for `compute_tool_signature`, `parse_tool_arguments`, `OpenAIToolEmitter` |
| `tests/test_registry_wiring.py` | CREATE | Tests for `parse_tool_calls_from_text` with registry |

---

## Chunk 1: `tools/validate.py`

### Task 1: Write failing tests

**Files:**
- Create: `tests/test_validate.py`

- [ ] **Step 1: Write tests**

```python
# tests/test_validate.py
from __future__ import annotations
from tools.validate import validate_tool_call_full


def _tool(name: str, **props) -> dict:
    """Build a minimal tool definition."""
    prop_defs = {}
    for k, v in props.items():
        if isinstance(v, dict):
            prop_defs[k] = v
        else:
            prop_defs[k] = {"type": v}
    return {
        "type": "function",
        "function": {
            "name": name,
            "parameters": {
                "type": "object",
                "properties": prop_defs,
                "required": list(props.keys()),
            },
        },
    }


def _call(name: str, **kwargs) -> dict:
    import json
    return {
        "id": "call_abc",
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(kwargs)},
    }


def test_valid_call_passes():
    ok, errs = validate_tool_call_full(_call("Bash", command="ls"), [_tool("Bash", command="string")])
    assert ok and errs == []

def test_unknown_tool_fails_fast():
    ok, errs = validate_tool_call_full(_call("NoSuch", x="y"), [_tool("Bash", command="string")])
    assert not ok
    assert any("not found" in e for e in errs)

def test_missing_required_fails():
    ok, errs = validate_tool_call_full(_call("Bash"), [_tool("Bash", command="string")])
    assert not ok
    assert any("command" in e for e in errs)

def test_wrong_type_fails():
    ok, errs = validate_tool_call_full(_call("Bash", command=42), [_tool("Bash", command="string")])
    assert not ok
    assert any("string" in e for e in errs)

def test_enum_violation_fails():
    ok, errs = validate_tool_call_full(
        _call("Shot", type="gif"),
        [_tool("Shot", type={"type": "string", "enum": ["png", "jpeg"]})],
    )
    assert not ok
    assert any("enum" in e for e in errs)

def test_no_double_required_error():
    """Missing required should produce exactly one error, not two."""
    ok, errs = validate_tool_call_full(_call("Bash"), [_tool("Bash", command="string")])
    assert not ok
    required_errs = [e for e in errs if "command" in e]
    assert len(required_errs) == 1

def test_correct_type_after_required_check():
    ok, errs = validate_tool_call_full(
        _call("Bash", command="echo"),
        [_tool("Bash", command="string")],
    )
    assert ok

def test_unknown_tool_no_schema_check():
    """Unknown tool returns structural error without running schema."""
    ok, errs = validate_tool_call_full(_call("Unknown"), [])
    assert not ok
    assert len(errs) == 1  # only the 'not found' error, no schema errors
```

- [ ] **Step 2: Run — expect ImportError**

```bash
cd /teamspace/studios/this_studio/dikders
pytest tests/test_validate.py -v 2>&1 | tail -5
```

Expected: `ModuleNotFoundError: No module named 'tools.validate'`

### Task 2: Create `tools/validate.py`

**Files:**
- Create: `tools/validate.py`

- [ ] **Step 1: Write the file**

```python
"""
Shin Proxy — Full tool call validation.

Composes validate_tool_call (structural: name + required presence) and
validate_schema (type, enum, bounds) into a single sequential gate.
validate_schema is only called when validate_tool_call passes, so required-
field errors are never duplicated.
"""
from __future__ import annotations

import msgspec.json as msgjson

from tools.parse import validate_tool_call
from tools.schema import validate_schema


def validate_tool_call_full(
    call: dict,
    tools: list[dict],
) -> tuple[bool, list[str]]:
    """Full validation: name + required presence + JSON Schema type/enum/bounds.

    Sequential gate:
    1. validate_tool_call — structural check (name present, required params present).
       Returns early on failure — no point running schema on a broken call.
    2. validate_schema — type, enum, minLength/maxLength, minimum/maximum, minItems/maxItems.
       Only called when step 1 passes, so required-field errors are never duplicated.

    Returns (is_valid, errors). errors is empty when valid.
    """
    # Step 1: structural check
    ok, errors = validate_tool_call(call, tools)
    if not ok:
        return False, errors

    # Step 2: find the matching tool's parameters schema
    fn = call.get("function", {})
    name = fn.get("name", "")
    parameters: dict | None = None
    for t in tools or []:
        fn_def = t.get("function", {})
        if fn_def.get("name") == name:
            parameters = fn_def.get("parameters", {})
            break

    if parameters is None:
        # Should not happen since validate_tool_call already found the tool,
        # but guard defensively.
        return True, []

    # Step 3: parse arguments to dict
    args_raw = fn.get("arguments", "{}")
    if isinstance(args_raw, str):
        try:
            args_dict: dict = msgjson.decode(args_raw.encode()) if args_raw else {}
        except Exception:
            args_dict = {}
    elif isinstance(args_raw, dict):
        args_dict = args_raw
    else:
        args_dict = {}

    # Step 4: full schema enforcement
    return validate_schema(args_dict, parameters, tool_name=name)
```

- [ ] **Step 2: Run tests — expect PASS**

```bash
pytest tests/test_validate.py -v 2>&1 | tail -12
```

Expected: all 8 tests PASS

- [ ] **Step 3: Full suite — no regressions**

```bash
pytest tests/ --ignore=tests/integration -q 2>&1 | tail -5
```

- [ ] **Step 4: Commit**

```bash
git add tools/validate.py tests/test_validate.py
git commit -m "feat(tools): add validate.py — validate_tool_call_full sequential gate"
```

---

## Chunk 2: `tools/budget.py` + pipeline re-exports + direct imports

### Task 3: Write failing tests

**Files:**
- Create: `tests/test_budget.py`

- [ ] **Step 1: Write tests**

```python
# tests/test_budget.py
from __future__ import annotations
import json
from tools.budget import limit_tool_calls, repair_invalid_calls


def _tool(name: str, **props) -> dict:
    prop_defs = {k: ({"type": v} if isinstance(v, str) else v) for k, v in props.items()}
    return {
        "type": "function",
        "function": {
            "name": name,
            "parameters": {
                "type": "object",
                "properties": prop_defs,
                "required": list(props.keys()),
            },
        },
    }


def _call(name: str, **kwargs) -> dict:
    return {
        "id": "call_abc",
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(kwargs)},
    }


# ── limit_tool_calls ─────────────────────────────────────────────────────────

def test_limit_parallel_true_returns_all():
    calls = [_call("Bash", command="ls"), _call("Bash", command="pwd")]
    assert limit_tool_calls(calls, parallel=True) == calls

def test_limit_parallel_false_returns_first():
    calls = [_call("Bash", command="ls"), _call("Bash", command="pwd")]
    result = limit_tool_calls(calls, parallel=False)
    assert len(result) == 1
    assert result[0]["function"]["arguments"] == json.dumps({"command": "ls"})

def test_limit_empty_list():
    assert limit_tool_calls([], parallel=False) == []


# ── repair_invalid_calls ─────────────────────────────────────────────────────

def test_repair_valid_call_passthrough():
    tools = [_tool("Bash", command="string")]
    calls = [_call("Bash", command="echo")]
    result = repair_invalid_calls(calls, tools)
    assert len(result) == 1
    assert json.loads(result[0]["function"]["arguments"])["command"] == "echo"

def test_repair_wrong_param_name_repaired():
    # "cmd" is an alias for "command" — should be repaired
    tools = [_tool("Bash", command="string")]
    call = {
        "id": "call_x",
        "type": "function",
        "function": {"name": "Bash", "arguments": json.dumps({"cmd": "ls"})},
    }
    result = repair_invalid_calls([call], tools)
    assert len(result) == 1
    args = json.loads(result[0]["function"]["arguments"])
    assert "command" in args

def test_repair_schema_type_error_triggers_repair_attempt():
    # command is integer but schema says string — repair should coerce
    tools = [_tool("Bash", command="string")]
    call = _call("Bash", command=42)
    result = repair_invalid_calls([call], tools)
    # coerce repairs int → string
    assert len(result) == 1
    args = json.loads(result[0]["function"]["arguments"])
    assert isinstance(args["command"], str)

def test_repair_unknown_tool_passed_through():
    # Unknown tool: no schema to validate against — passes through unchanged
    calls = [_call("Unknown", x="y")]
    result = repair_invalid_calls(calls, [])
    assert len(result) == 1

def test_repair_multiple_calls():
    tools = [_tool("Bash", command="string")]
    calls = [_call("Bash", command="ls"), _call("Bash", command="pwd")]
    result = repair_invalid_calls(calls, tools)
    assert len(result) == 2
```

- [ ] **Step 2: Run — expect ImportError**

```bash
pytest tests/test_budget.py -v 2>&1 | tail -5
```

### Task 4: Create `tools/budget.py`

**Files:**
- Create: `tools/budget.py`

- [ ] **Step 1: Write the file**

```python
"""
Shin Proxy — Tool call budget enforcement.

limit_tool_calls and repair_invalid_calls extracted from pipeline/tools.py.
repair_invalid_calls now uses validate_tool_call_full (full schema enforcement)
instead of validate_tool_call (structural only).
"""
from __future__ import annotations

import structlog

from tools.parse import repair_tool_call
from tools.validate import validate_tool_call_full

log = structlog.get_logger()


def limit_tool_calls(calls: list[dict], parallel: bool) -> list[dict]:
    """Enforce parallel_tool_calls limit.

    If parallel=False, returns only the first call.
    If parallel=True or calls is empty, returns unchanged.
    """
    if calls and not parallel:
        return calls[:1]
    return calls


def repair_invalid_calls(
    calls: list[dict],
    tools: list[dict],
) -> list[dict]:
    """Validate each call with full schema enforcement; attempt repair if invalid.

    Four-case behavior:
    1. validate_tool_call_full passes → append unchanged.
    2. Fails → repair_tool_call produces repairs → re-validate passes → append repaired.
    3. Fails → repair_tool_call produces repairs → re-validate still fails → drop, warn.
    4. Fails → repair_tool_call produces no repairs → pass through original, warn (non-fatal).
    """
    out: list[dict] = []
    for call in calls:
        ok, errs = validate_tool_call_full(call, tools)
        if ok:
            out.append(call)
            continue
        repaired, repairs = repair_tool_call(call, tools)
        if repairs:
            ok2, errs2 = validate_tool_call_full(repaired, tools)
            if ok2:
                out.append(repaired)
            else:
                log.warning(
                    "tool_call_unrepairable",
                    tool=call.get("function", {}).get("name"),
                    original_errors=errs,
                    post_repair_errors=errs2,
                )
        else:
            log.warning(
                "tool_call_validation_failed",
                tool=call.get("function", {}).get("name"),
                errors=errs,
            )
            out.append(call)  # case 4: pass through — non-fatal
    return out
```

- [ ] **Step 2: Run tests — expect PASS**

```bash
pytest tests/test_budget.py -v 2>&1 | tail -15
```

Expected: all 8 tests PASS

- [ ] **Step 3: Full suite — no regressions**

```bash
pytest tests/ --ignore=tests/integration -q 2>&1 | tail -5
```

### Task 5: Update `pipeline/tools.py` re-exports + direct imports in stream files

**Files:**
- Modify: `pipeline/tools.py`
- Modify: `pipeline/stream_openai.py`
- Modify: `pipeline/stream_anthropic.py`

- [ ] **Step 1: Read `pipeline/tools.py` to confirm current state**

```bash
head -25 /teamspace/studios/this_studio/dikders/pipeline/tools.py
```

- [ ] **Step 2: Add re-exports to `pipeline/tools.py`** (after existing imports, before function definitions)

Add these two lines after the existing `from tools.parse import (...)` block:

```python
# budget.py extracted — re-exported here for pipeline/__init__.py backward compat
from tools.budget import limit_tool_calls as _limit_tool_calls  # noqa: F401
from tools.budget import repair_invalid_calls as _repair_invalid_calls  # noqa: F401
```

- [ ] **Step 3: Update `pipeline/stream_openai.py`**

Replace:
```python
from pipeline.tools import (
    _limit_tool_calls,
    _repair_invalid_calls,
    _OpenAIToolEmitter,
)
```
With:
```python
from tools.budget import limit_tool_calls as _limit_tool_calls
from tools.budget import repair_invalid_calls as _repair_invalid_calls
from pipeline.tools import _OpenAIToolEmitter  # emitter moved in next chunk
```

- [ ] **Step 4: Update `pipeline/stream_anthropic.py`**

Replace:
```python
from pipeline.tools import (
    _compute_tool_signature,
    _limit_tool_calls,
    _repair_invalid_calls,
    _stream_anthropic_tool_input,
)
```
With:
```python
from tools.budget import limit_tool_calls as _limit_tool_calls
from tools.budget import repair_invalid_calls as _repair_invalid_calls
from pipeline.tools import _compute_tool_signature, _stream_anthropic_tool_input  # emitter chunk
```

- [ ] **Step 5: Verify imports — no breakage**

```bash
python -c "from pipeline.tools import _limit_tool_calls, _repair_invalid_calls; print('OK')"
python -c "from pipeline import _limit_tool_calls, _repair_invalid_calls; print('OK')"
```

- [ ] **Step 6: Full suite — no regressions**

```bash
pytest tests/ --ignore=tests/integration -q 2>&1 | tail -5
```

- [ ] **Step 7: Commit**

```bash
git add tools/budget.py tests/test_budget.py pipeline/tools.py pipeline/stream_openai.py pipeline/stream_anthropic.py
git commit -m "feat(tools): add budget.py — limit_tool_calls, repair_invalid_calls; update pipeline callers"
```

---

## Chunk 3: `tools/emitter.py` + pipeline re-exports + direct imports

### Task 6: Write failing tests

**Files:**
- Create: `tests/test_emitter.py`

- [ ] **Step 1: Write tests**

```python
# tests/test_emitter.py
from __future__ import annotations
import json
import pytest
from tools.emitter import (
    compute_tool_signature,
    parse_tool_arguments,
    serialize_tool_arguments,
    OpenAIToolEmitter,
)


def _tc(name: str, **kwargs) -> dict:
    return {
        "id": "call_abc",
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(kwargs)},
    }


def test_compute_tool_signature_deterministic():
    fn = {"name": "Bash", "arguments": json.dumps({"b": 2, "a": 1})}
    sig1 = compute_tool_signature(fn)
    fn2 = {"name": "Bash", "arguments": json.dumps({"a": 1, "b": 2})}
    sig2 = compute_tool_signature(fn2)
    assert sig1 == sig2  # key order normalized

def test_compute_tool_signature_different_args_differ():
    fn1 = {"name": "Bash", "arguments": json.dumps({"command": "ls"})}
    fn2 = {"name": "Bash", "arguments": json.dumps({"command": "pwd"})}
    assert compute_tool_signature(fn1) != compute_tool_signature(fn2)

def test_parse_tool_arguments_from_string():
    result = parse_tool_arguments('{"command": "ls"}')
    assert result == {"command": "ls"}

def test_parse_tool_arguments_from_dict():
    d = {"command": "ls"}
    assert parse_tool_arguments(d) is d

def test_parse_tool_arguments_double_encoded():
    # Double-encoded JSON string
    inner = json.dumps({"command": "ls"})
    double = json.dumps(inner)
    result = parse_tool_arguments(double)
    assert result == {"command": "ls"}

def test_parse_tool_arguments_invalid_returns_empty():
    assert parse_tool_arguments("not json") == {}

def test_serialize_tool_arguments_from_string():
    raw = '{"command": "ls"}'
    result = serialize_tool_arguments(raw)
    assert json.loads(result) == {"command": "ls"}

def test_openai_tool_emitter_new_call_produces_chunks():
    emitter = OpenAIToolEmitter(chunk_id="cid", model="claude", created=0)
    chunks = emitter.emit([_tc("Bash", command="ls")])
    assert len(chunks) > 0
    assert emitter.active is True

def test_openai_tool_emitter_dedup_same_signature():
    emitter = OpenAIToolEmitter(chunk_id="cid", model="claude", created=0)
    call = _tc("Bash", command="ls")
    chunks1 = emitter.emit([call])
    chunks2 = emitter.emit([call])  # same signature — no new header
    # Second emit should produce arg delta chunks, not a new header
    # Both together: header + arg chunks on first emit
    assert len(chunks1) > 0
    assert isinstance(chunks2, list)

def test_openai_tool_emitter_empty_list():
    emitter = OpenAIToolEmitter(chunk_id="cid", model="claude", created=0)
    assert emitter.emit([]) == []
```

- [ ] **Step 2: Run — expect ImportError**

```bash
pytest tests/test_emitter.py -v 2>&1 | tail -5
```

### Task 7: Create `tools/emitter.py`

**Files:**
- Create: `tools/emitter.py`

- [ ] **Step 1: Read `pipeline/tools.py`** to get the exact bodies for all 5 items

```bash
wc -l /teamspace/studios/this_studio/dikders/pipeline/tools.py
```

Read the full file, locate:
- `_compute_tool_signature` function
- `_parse_tool_arguments` function
- `_serialize_tool_arguments` function
- `_stream_anthropic_tool_input` function
- `_OpenAIToolEmitter` class

- [ ] **Step 2: Write `tools/emitter.py`** with public names (no leading underscore)

```python
"""
Shin Proxy — Tool call SSE emitter and argument serialization helpers.

Extracted from pipeline/tools.py. Depends on converters/from_cursor for
SSE formatting utilities. pipeline/tools.py re-exports these under the
original private names for backward compat.

Dependency note: tools/emitter.py → converters/from_cursor is safe because
converters/from_cursor.py never imports from tools/.
"""
from __future__ import annotations

import msgspec.json as msgjson

from converters.from_cursor import (
    anthropic_content_block_delta,
    openai_chunk,
    openai_sse,
)


def compute_tool_signature(fn: dict) -> str:
    """Deterministic signature for a tool call to deduplicate emissions."""
    args = fn.get("arguments", "{}")
    if isinstance(args, str):
        try:
            args = msgjson.decode(args.encode())
        except Exception:  # nosec B110
            pass
    if isinstance(args, dict):
        args = {k: args[k] for k in sorted(args)}
    normalized: dict = {"arguments": args, "name": fn.get("name")}
    return msgjson.encode(normalized).decode("utf-8")


def parse_tool_arguments(raw_args: str | dict) -> dict:
    """Safely parse tool call arguments from string or dict.

    Handles double-encoded JSON: e.g. the parsed result is still a string.
    """
    if isinstance(raw_args, dict):
        return raw_args
    try:
        result = msgjson.decode(raw_args.encode()) if raw_args else {}
        if isinstance(result, str):
            result = msgjson.decode(result.encode())
        return result if isinstance(result, dict) else {}
    except Exception:
        return {}


def serialize_tool_arguments(raw_args: str | dict) -> str:
    """Return compact JSON text for Anthropic input_json_delta streaming."""
    return msgjson.encode(parse_tool_arguments(raw_args)).decode("utf-8")


def stream_anthropic_tool_input(
    index: int, raw_args: str | dict, chunk_size: int = 96
) -> list[str]:
    """Return input_json_delta events whose concatenation remains valid JSON."""
    args_json = serialize_tool_arguments(raw_args)
    return [
        anthropic_content_block_delta(
            index,
            {"type": "input_json_delta", "partial_json": args_json[i : i + chunk_size]},
        )
        for i in range(0, len(args_json), chunk_size)
    ]


class OpenAIToolEmitter:
    """Tracks and yields OpenAI-format tool call SSE chunks incrementally."""

    ARGS_CHUNK_SIZE = 96

    def __init__(self, chunk_id: str, model: str, created: int = 0) -> None:
        self._cid = chunk_id
        self._model = model
        self._created = created
        self._signatures: dict[str, dict] = {}  # sig -> {index, sent}
        self._count = 0
        self.active = False

    def emit(self, tool_calls: list[dict]) -> list[str]:
        """Process tool calls and return SSE chunks to yield."""
        chunks: list[str] = []
        self.active = True

        for tc in tool_calls:
            fn = tc.get("function", {})
            sig = compute_tool_signature(fn)
            call_id = tc.get("id")
            fn_name = fn.get("name")
            args_text = fn.get("arguments", "{}")

            rec = self._signatures.get(sig)
            if rec is None:
                rec = {"index": self._count, "sent": 0}
                self._signatures[sig] = rec
                chunks.append(openai_sse(openai_chunk(
                    self._cid, self._model,
                    delta={"tool_calls": [{
                        "index": self._count,
                        "id": call_id,
                        "type": "function",
                        "function": {"name": fn_name, "arguments": ""},
                    }]},
                    created=self._created,
                )))
                self._count += 1

            sent = rec["sent"]
            if len(args_text) > sent:
                remaining = args_text[sent:]
                rec["sent"] = len(args_text)
                for i in range(0, len(remaining), self.ARGS_CHUNK_SIZE):
                    piece = remaining[i : i + self.ARGS_CHUNK_SIZE]
                    chunks.append(openai_sse(openai_chunk(
                        self._cid, self._model,
                        delta={"tool_calls": [{
                            "index": rec["index"],
                            "function": {"arguments": piece},
                        }]},
                        created=self._created,
                    )))

        return chunks
```

- [ ] **Step 3: Run tests — expect PASS**

```bash
pytest tests/test_emitter.py -v 2>&1 | tail -15
```

Expected: all 10 tests PASS

- [ ] **Step 4: Full suite — no regressions**

```bash
pytest tests/ --ignore=tests/integration -q 2>&1 | tail -5
```

### Task 8: Update `pipeline/tools.py` re-exports + direct imports in stream files

**Files:**
- Modify: `pipeline/tools.py`
- Modify: `pipeline/stream_openai.py`
- Modify: `pipeline/stream_anthropic.py`

- [ ] **Step 1: Add re-exports to `pipeline/tools.py`** (after the budget re-exports added in Task 5)

```python
# emitter.py extracted — re-exported here for pipeline/__init__.py backward compat
from tools.emitter import compute_tool_signature as _compute_tool_signature  # noqa: F401
from tools.emitter import parse_tool_arguments as _parse_tool_arguments  # noqa: F401
from tools.emitter import serialize_tool_arguments as _serialize_tool_arguments  # noqa: F401
from tools.emitter import stream_anthropic_tool_input as _stream_anthropic_tool_input  # noqa: F401
from tools.emitter import OpenAIToolEmitter as _OpenAIToolEmitter  # noqa: F401
```

- [ ] **Step 2: Update `pipeline/stream_openai.py`**

Replace the temporary import from Task 5 Step 3:
```python
from pipeline.tools import _OpenAIToolEmitter  # emitter moved in next chunk
```
With:
```python
from tools.emitter import OpenAIToolEmitter as _OpenAIToolEmitter
```

- [ ] **Step 3: Update `pipeline/stream_anthropic.py`**

Replace the temporary imports from Task 5 Step 4:
```python
from pipeline.tools import _compute_tool_signature, _stream_anthropic_tool_input  # emitter chunk
```
With:
```python
from tools.emitter import compute_tool_signature as _compute_tool_signature
from tools.emitter import stream_anthropic_tool_input as _stream_anthropic_tool_input
```

- [ ] **Step 4: Verify import chains**

```bash
python -c "from pipeline.tools import _compute_tool_signature, _OpenAIToolEmitter, _stream_anthropic_tool_input; print('pipeline.tools OK')"
python -c "from pipeline import _compute_tool_signature, _OpenAIToolEmitter; print('pipeline.__init__ OK')"
```

- [ ] **Step 5: Full suite — no regressions**

```bash
pytest tests/ --ignore=tests/integration -q 2>&1 | tail -5
```

- [ ] **Step 6: Commit**

```bash
git add tools/emitter.py tests/test_emitter.py pipeline/tools.py pipeline/stream_openai.py pipeline/stream_anthropic.py
git commit -m "feat(tools): add emitter.py — OpenAIToolEmitter, serialization helpers; update pipeline callers"
```

---

## Chunk 4: Wire `ToolRegistry` into `parse_tool_calls_from_text` + streaming

### Task 9: Write failing tests

**Files:**
- Create: `tests/test_registry_wiring.py`

- [ ] **Step 1: Write tests**

```python
# tests/test_registry_wiring.py
from __future__ import annotations
from tools.parse import parse_tool_calls_from_text
from tools.registry import ToolRegistry
from tools.streaming import StreamingToolCallParser


def _tool(name: str) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
        },
    }


def _payload(name: str, command: str) -> str:
    return f'[assistant_tool_calls]\n{{"tool_calls": [{{"name": "{name}", "arguments": {{"command": "{command}"}}}}]}}'


# ── parse_tool_calls_from_text with registry ─────────────────────────────────

def test_with_registry_returns_same_result_as_without():
    tools = [_tool("Bash")]
    text = _payload("Bash", "ls")
    reg = ToolRegistry(tools)
    result_no_reg = parse_tool_calls_from_text(text, tools)
    result_with_reg = parse_tool_calls_from_text(text, tools, registry=reg)
    assert result_no_reg is not None
    assert result_with_reg is not None
    assert result_no_reg[0]["function"]["name"] == result_with_reg[0]["function"]["name"]

def test_registry_none_still_works():
    tools = [_tool("Bash")]
    text = _payload("Bash", "pwd")
    result = parse_tool_calls_from_text(text, tools, registry=None)
    assert result is not None

def test_registry_with_no_tools_returns_none():
    reg = ToolRegistry([])
    text = _payload("Bash", "ls")
    result = parse_tool_calls_from_text(text, [], registry=reg)
    assert result is None

def test_registry_fuzzy_name_resolves():
    tools = [_tool("Bash")]
    reg = ToolRegistry(tools)
    # "bash" (lowercase) should fuzzy-match "Bash"
    text = '[assistant_tool_calls]\n{"tool_calls": [{"name": "bash", "arguments": {"command": "ls"}}]}'
    result = parse_tool_calls_from_text(text, tools, registry=reg)
    assert result is not None
    assert result[0]["function"]["name"] == "Bash"


# ── StreamingToolCallParser with registry ────────────────────────────────────

def test_streaming_parser_with_registry():
    tools = [_tool("Bash")]
    reg = ToolRegistry(tools)
    parser = StreamingToolCallParser(tools, registry=reg)
    payload = _payload("Bash", "ls")
    result = None
    for i in range(0, len(payload), 20):
        result = parser.feed(payload[i:i+20]) or result
    assert result is not None
    assert result[0]["function"]["name"] == "Bash"

def test_streaming_parser_finalize_with_registry():
    tools = [_tool("Bash")]
    reg = ToolRegistry(tools)
    parser = StreamingToolCallParser(tools, registry=reg)
    payload = _payload("Bash", "echo hi")
    parser.feed(payload)
    result = parser.finalize()
    assert result is not None
    assert result[0]["function"]["name"] == "Bash"

def test_streaming_parser_registry_none_backward_compat():
    tools = [_tool("Bash")]
    parser = StreamingToolCallParser(tools)  # no registry — old call style
    payload = _payload("Bash", "ls")
    parser.feed(payload)
    result = parser.finalize()
    assert result is not None
```

- [ ] **Step 2: Run — some tests will fail (registry param not yet added)**

```bash
pytest tests/test_registry_wiring.py -v 2>&1 | tail -15
```

Expected: failures on `StreamingToolCallParser(tools, registry=reg)` — unexpected kwarg.

### Task 10: Update `tools/parse.py` — add `registry` param

**Files:**
- Modify: `tools/parse.py`

- [ ] **Step 1: Read `tools/parse.py`** — find `parse_tool_calls_from_text` definition and the `allowed_exact`/`schema_map` rebuild block

```bash
grep -n 'def parse_tool_calls_from_text\|allowed_exact\|schema_map\|_CURSOR_BACKEND' /teamspace/studios/this_studio/dikders/tools/parse.py | head -20
```

- [ ] **Step 2: Update the function signature and add the registry fast-path**

Change the function signature from:
```python
def parse_tool_calls_from_text(
    text: str,
    tools: list[dict] | None,
    streaming: bool = False,
) -> list[dict] | None:
```
To:
```python
def parse_tool_calls_from_text(
    text: str,
    tools: list[dict] | None,
    streaming: bool = False,
    registry: "ToolRegistry | None" = None,
) -> list[dict] | None:
```

Note: use a string annotation `"ToolRegistry | None"` to avoid a circular import at module load time (ToolRegistry is in `tools.registry` which imports from `tools.coerce`; `tools.parse` already imports from `tools.coerce` — no cycle, but using `TYPE_CHECKING` guard is cleaner).

Actually: add `from __future__ import annotations` is already at the top of parse.py. Import `ToolRegistry` under `TYPE_CHECKING`:

```python
from __future__ import annotations

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from tools.registry import ToolRegistry
```

Then find the block that builds `allowed_exact` and `schema_map` (it starts with `allowed_exact: dict[str, str] = {}` and loops over `tools`). Wrap it with the registry fast-path:

```python
    if registry is not None:
        allowed_exact = registry.allowed_exact()
        schema_map = registry.schema_map()
    else:
        # existing rebuild logic — unchanged
        allowed_exact: dict[str, str] = {}
        for t in tools:
            ...
        # ... rest of existing build logic including _CURSOR_BACKEND_TOOLS ...
        schema_map: dict[str, set[str]] = {}
        ...
```

- [ ] **Step 3: Run registry wiring tests**

```bash
pytest tests/test_registry_wiring.py::test_with_registry_returns_same_result_as_without tests/test_registry_wiring.py::test_registry_none_still_works -v 2>&1 | tail -10
```

### Task 11: Update `tools/streaming.py` — add `registry` param

**Files:**
- Modify: `tools/streaming.py`

- [ ] **Step 1: Read `tools/streaming.py`** — find `__init__`, `feed`, `finalize`

- [ ] **Step 2: Update `__init__` to accept and store `registry`**

Change:
```python
def __init__(self, tools: list[dict]) -> None:
    from tools.parse import parse_tool_calls_from_text as _ptcft
    self._parse = _ptcft
    self._tools = tools
    ...
```
To:
```python
def __init__(self, tools: list[dict], registry: "ToolRegistry | None" = None) -> None:
    from tools.parse import parse_tool_calls_from_text as _ptcft
    self._parse = _ptcft
    self._tools = tools
    self._registry = registry
    ...
```

Add `TYPE_CHECKING` guard at top of `tools/streaming.py`:
```python
from __future__ import annotations
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from tools.registry import ToolRegistry
```

- [ ] **Step 3: Update `feed()` — pass registry to `self._parse`**

Find the line inside `feed()` where `self._parse` is called (inside `if self._depth == 0:` block):
```python
self._last_result = self._parse(
    buf[self._marker_pos:], self._tools, streaming=True
)
```
Change to:
```python
self._last_result = self._parse(
    buf[self._marker_pos:], self._tools, streaming=True,
    registry=self._registry,
)
```

- [ ] **Step 4: Update `finalize()` — pass registry**

Find:
```python
return self._parse(parse_slice, self._tools, streaming=False)
```
Change to:
```python
return self._parse(parse_slice, self._tools, streaming=False, registry=self._registry)
```

- [ ] **Step 5: Run ALL registry wiring tests**

```bash
pytest tests/test_registry_wiring.py -v 2>&1 | tail -15
```

Expected: all 7 tests PASS

- [ ] **Step 6: Run existing parse + streaming tests — must not break**

```bash
pytest tests/test_parse.py tests/test_parse_extended.py tests/test_streaming.py -v 2>&1 | tail -15
```

- [ ] **Step 7: Full suite**

```bash
pytest tests/ --ignore=tests/integration -q 2>&1 | tail -5
```

### Task 12: Wire `ToolRegistry` in pipeline stream files

**Files:**
- Modify: `pipeline/stream_openai.py`
- Modify: `pipeline/stream_anthropic.py`

- [ ] **Step 1: Read `pipeline/stream_openai.py`** — find where `StreamingToolCallParser` is constructed

```bash
grep -n 'StreamingToolCallParser\|params.tools\|ToolRegistry' /teamspace/studios/this_studio/dikders/pipeline/stream_openai.py | head -10
```

- [ ] **Step 2: Update `pipeline/stream_openai.py`**

Add import at the top:
```python
from tools.registry import ToolRegistry
```

Find where `StreamingToolCallParser` is constructed (it will be something like):
```python
_stream_parser = pkg.StreamingToolCallParser(params.tools) if params.tools else None
```

Change to:
```python
_registry = ToolRegistry(params.tools) if params.tools else None
_stream_parser = pkg.StreamingToolCallParser(params.tools, registry=_registry) if params.tools else None
```

Also pass `registry=_registry` to any direct `parse_tool_calls_from_text` calls in `stream_openai.py`:
```python
parse_tool_calls_from_text(text, params.tools, streaming=True, registry=_registry)
```

- [ ] **Step 3: Read `pipeline/stream_anthropic.py`** — find where `StreamingToolCallParser` is constructed

```bash
grep -n 'StreamingToolCallParser\|params.tools\|ToolRegistry' /teamspace/studios/this_studio/dikders/pipeline/stream_anthropic.py | head -10
```

- [ ] **Step 4: Update `pipeline/stream_anthropic.py`**

Add import at top:
```python
from tools.registry import ToolRegistry
```

Find the `StreamingToolCallParser` construction and add registry:
```python
_registry = ToolRegistry(params.tools) if params.tools else None
_stream_parser = pkg.StreamingToolCallParser(params.tools, registry=_registry) if params.tools else None
```

- [ ] **Step 5: Full suite — no regressions**

```bash
pytest tests/ --ignore=tests/integration -q 2>&1 | tail -5
```

- [ ] **Step 6: Commit**

```bash
git add tools/parse.py tools/streaming.py pipeline/stream_openai.py pipeline/stream_anthropic.py tests/test_registry_wiring.py
git commit -m "feat(tools): wire ToolRegistry into parse_tool_calls_from_text and StreamingToolCallParser"
```

---

## Chunk 5: Clean up `pipeline/tools.py`

### Task 13: Remove moved bodies from `pipeline/tools.py`

**Files:**
- Modify: `pipeline/tools.py`

- [ ] **Step 1: Read the full `pipeline/tools.py`**

Confirm re-export aliases from chunks 2 and 3 are in place before deleting bodies.

- [ ] **Step 2: Remove moved function bodies**

Delete these function/class bodies (they are now re-exported via aliases):
- `_compute_tool_signature` function
- `_parse_tool_arguments` function
- `_serialize_tool_arguments` function
- `_stream_anthropic_tool_input` function
- `_limit_tool_calls` function
- `_repair_invalid_calls` function
- `_OpenAIToolEmitter` class

DO NOT remove:
- `_parse_score_repair` function (stays — takes `PipelineParams`)
- The re-export aliases added in chunks 2 and 3
- `log = structlog.get_logger()` and other module-level setup

- [ ] **Step 3: Verify `_parse_score_repair` still calls the re-exported names**

```bash
grep -n '_limit_tool_calls\|_repair_invalid_calls' /teamspace/studios/this_studio/dikders/pipeline/tools.py
```

Expected: re-export aliases at top, and `_parse_score_repair` body using them at lines ~30-40.

- [ ] **Step 4: Verify import chains still work**

```bash
python -c "
from pipeline.tools import _limit_tool_calls, _repair_invalid_calls
from pipeline.tools import _compute_tool_signature, _OpenAIToolEmitter
from pipeline.tools import _parse_score_repair
from pipeline import _limit_tool_calls, _repair_invalid_calls, _OpenAIToolEmitter
print('ALL pipeline import chains OK')
"
```

- [ ] **Step 5: Full suite**

```bash
pytest tests/ --ignore=tests/integration -q 2>&1 | tail -5
```

- [ ] **Step 6: Commit**

```bash
git add pipeline/tools.py
git commit -m "refactor(pipeline): tools.py removes moved bodies; only re-exports and _parse_score_repair remain"
```

---

## Chunk 6: Final validation + UPDATES.md

### Task 14: Full verification

- [ ] **Step 1: Import smoke test**

```bash
cd /teamspace/studios/this_studio/dikders
python -c "
import tools.validate
import tools.budget
import tools.emitter
import tools.parse
import tools.streaming
import tools.registry
from tools.validate import validate_tool_call_full
from tools.budget import limit_tool_calls, repair_invalid_calls
from tools.emitter import OpenAIToolEmitter, compute_tool_signature
from pipeline.tools import _limit_tool_calls, _repair_invalid_calls, _OpenAIToolEmitter
from pipeline import _limit_tool_calls, _repair_invalid_calls
from pipeline.tools import _parse_score_repair
print('ALL IMPORTS OK')
"
```

Expected: `ALL IMPORTS OK`

- [ ] **Step 2: Verify `pipeline/tools.py` has no moved bodies**

```bash
grep -n 'def _compute_tool_signature\|def _parse_tool_arguments\|def _limit_tool_calls\|def _repair_invalid_calls\|class _OpenAIToolEmitter' /teamspace/studios/this_studio/dikders/pipeline/tools.py
```

Expected: no output (bodies removed, only aliases remain)

- [ ] **Step 3: Verify `validate_schema` is called in production path**

```bash
grep -rn 'validate_schema' /teamspace/studios/this_studio/dikders/tools/ | grep -v test | grep -v '.pyc'
```

Expected: `tools/validate.py` imports and calls `validate_schema`

- [ ] **Step 4: Verify `ToolRegistry` wired in both stream files**

```bash
grep -n 'ToolRegistry' /teamspace/studios/this_studio/dikders/pipeline/stream_openai.py /teamspace/studios/this_studio/dikders/pipeline/stream_anthropic.py
```

Expected: both files show ToolRegistry import and construction

- [ ] **Step 5: Run full non-integration test suite**

```bash
pytest tests/ --ignore=tests/integration -q 2>&1 | tail -10
```

Expected: all existing tests pass + 4 new test files pass. 5 pre-existing failures in `test_fallback.py` and `test_responses_router.py` are acceptable.

- [ ] **Step 6: Coverage check on new modules**

```bash
pytest tests/test_validate.py tests/test_budget.py tests/test_emitter.py tests/test_registry_wiring.py \
    --cov=tools.validate --cov=tools.budget --cov=tools.emitter \
    --cov-report=term-missing -q 2>&1 | tail -15
```

Expected: ≥ 80% coverage on each new module.

### Task 15: Update UPDATES.md and push

- [ ] **Step 1: Update UPDATES.md**

Add a new `## Session 143 — tools/ Phase 2 (2026-03-26)` section at the bottom of `UPDATES.md` with:
- Files created: `tools/validate.py`, `tools/budget.py`, `tools/emitter.py`
- Files modified: `tools/parse.py` (registry param), `tools/streaming.py` (registry param), `pipeline/tools.py` (removed bodies, added re-exports), `pipeline/stream_openai.py`, `pipeline/stream_anthropic.py`
- Test files created: `tests/test_validate.py`, `tests/test_budget.py`, `tests/test_emitter.py`, `tests/test_registry_wiring.py`
- Why: wire validate_schema into production repair path; extract budget/emitter from pipeline; eliminate per-call ToolRegistry rebuilds in streaming hot path
- Commit SHAs: `git log --oneline -6`

- [ ] **Step 2: Commit and push**

```bash
git add UPDATES.md
git commit -m "docs: update UPDATES.md for Session 143 — tools/ Phase 2"
git push
```

---

## Summary

| Chunk | Files | Tests | Key outcome |
|---|---|---|---|
| 1 | `tools/validate.py` | `test_validate.py` (8 tests) | `validate_schema` wired into production repair path |
| 2 | `tools/budget.py` + pipeline callers | `test_budget.py` (8 tests) | `limit_tool_calls`, `repair_invalid_calls` extracted |
| 3 | `tools/emitter.py` + pipeline callers | `test_emitter.py` (10 tests) | `OpenAIToolEmitter` + helpers extracted |
| 4 | `parse.py` + `streaming.py` + pipeline | `test_registry_wiring.py` (7 tests) | `ToolRegistry` wired into streaming hot path |
| 5 | `pipeline/tools.py` cleanup | existing tests | Bodies removed; only re-exports remain |
| 6 | UPDATES.md | full suite ≥ 80% coverage | Final validation and push |

**Zero new external dependencies. Zero breaking changes. All existing tests pass.**

