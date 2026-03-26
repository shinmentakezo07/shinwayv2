# tools/ Phase 3 — Reliability & Observability Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close observability gaps, fix silent failures, and add deduplication + sanitize utilities — all with zero breaking changes.

**Architecture:** Six independent improvements in six chunks. Each chunk is self-contained. No chunk depends on another. The order below is priority-ordered but any chunk can be implemented in isolation.

**Tech Stack:** Python 3.12, structlog, pytest. No new pip dependencies.

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `tools/metrics.py` | CREATE | Stable metrics wrapper — `inc_parse_outcome`, `inc_tool_repair`, `inc_schema_validation` |
| `tools/registry.py` | MODIFY | Add collision warning in `__init__` (match no-registry path behavior) |
| `tools/emitter.py` | MODIFY | Add `log.warning` on `parse_tool_arguments` failure (line 47) |
| `tools/budget.py` | MODIFY | Add `deduplicate_tool_calls(calls)` function |
| `tools/sanitize.py` | CREATE | Move `_sanitize_user_content` + `_CURSOR_WORD_RE` from `converters/cursor_helpers.py` |
| `tools/results.py` | CREATE | Extract `_build_tool_call_results` from `tools/parse.py` |
| `tools/parse.py` | MODIFY | Replace try/except ImportError with `from tools.metrics import inc_parse_outcome`; import `_build_tool_call_results` from `tools/results.py` |
| `converters/cursor_helpers.py` | MODIFY | Import `_sanitize_user_content` + `_CURSOR_WORD_RE` from `tools/sanitize.py`; keep backward-compat re-export |
| `tests/test_metrics.py` | CREATE | Tests for `tools/metrics.py` |
| `tests/test_registry.py` | MODIFY | Add test for collision warning |
| `tests/test_emitter.py` | MODIFY | Add test that parse failure is logged |
| `tests/test_budget.py` | MODIFY | Add tests for `deduplicate_tool_calls` |
| `tests/test_sanitize.py` | CREATE | Tests for `_sanitize_user_content` |
| `tests/test_results.py` | CREATE | Tests for `_build_tool_call_results` |

---

## Chunk 1: `tools/metrics.py` — stable metrics wrapper

### Task 1: Write failing tests

**Files:**
- Create: `tests/test_metrics.py`

- [ ] **Step 1: Write tests**

```python
# tests/test_metrics.py
from __future__ import annotations
from tools.metrics import inc_parse_outcome, inc_tool_repair, inc_schema_validation


def test_inc_parse_outcome_no_error():
    """Calling inc_parse_outcome never raises, even with no metrics backend."""
    inc_parse_outcome("success", 1)
    inc_parse_outcome("regex_fallback", 2)
    inc_parse_outcome("low_confidence_dropped")

def test_inc_tool_repair_no_error():
    inc_tool_repair("repaired")
    inc_tool_repair("dropped")
    inc_tool_repair("passed_through")

def test_inc_schema_validation_no_error():
    inc_schema_validation("passed")
    inc_schema_validation("failed")

def test_all_functions_callable():
    assert callable(inc_parse_outcome)
    assert callable(inc_tool_repair)
    assert callable(inc_schema_validation)
```

- [ ] **Step 2: Run — expect ImportError**

```bash
cd /teamspace/studios/this_studio/dikders
pytest tests/test_metrics.py -v 2>&1 | tail -5
```

### Task 2: Create `tools/metrics.py`

- [ ] **Step 1: Write the file**

```python
"""
Shin Proxy — Tool call metrics instrumentation.

Provides a stable import surface for metrics counters. The underlying
metrics backend (metrics.parse_metrics) is optional. When absent, all
functions are no-ops. This eliminates the try/except ImportError scattered
across other modules.
"""
from __future__ import annotations

try:
    from metrics.parse_metrics import inc_parse_outcome as _inc_parse_outcome
except ImportError:
    def _inc_parse_outcome(outcome: str, count: int = 1) -> None:  # type: ignore[misc]
        pass


def inc_parse_outcome(outcome: str, count: int = 1) -> None:
    """Increment a parse outcome counter.

    Outcomes: 'success', 'regex_fallback', 'truncated_recovery',
    'low_confidence_dropped'.
    """
    _inc_parse_outcome(outcome, count)


def inc_tool_repair(outcome: str, count: int = 1) -> None:
    """Increment a tool repair outcome counter.

    Outcomes: 'repaired', 'dropped', 'passed_through'.
    No-op if metrics backend not installed.
    """
    # Repair metrics not yet in the external backend — no-op stub
    # that gives callers a stable import point for future wiring.
    pass


def inc_schema_validation(result: str, count: int = 1) -> None:
    """Increment a schema validation result counter.

    Results: 'passed', 'failed'.
    No-op if metrics backend not installed.
    """
    pass
```

- [ ] **Step 2: Update `tools/parse.py`** — replace the try/except block

Find in `tools/parse.py` (lines 20-24):
```python
try:
    from metrics.parse_metrics import inc_parse_outcome
except ImportError:
    def inc_parse_outcome(outcome: str, count: int = 1) -> None:  # type: ignore[misc]
        pass
```
Replace with:
```python
from tools.metrics import inc_parse_outcome
```

- [ ] **Step 3: Run tests — all pass**

```bash
pytest tests/test_metrics.py tests/test_parse.py tests/test_parse_extended.py -v 2>&1 | tail -10
```

- [ ] **Step 4: Full suite**

```bash
pytest tests/ --ignore=tests/integration -q 2>&1 | tail -5
```

- [ ] **Step 5: Commit**

```bash
git add tools/metrics.py tests/test_metrics.py tools/parse.py
git commit -m "feat(tools): add metrics.py — stable instrumentation wrapper; inc_tool_repair, inc_schema_validation"
```

---

## Chunk 2: `tools/registry.py` — add collision warning

### Task 3: Add collision warning test

**Files:**
- Modify: `tests/test_registry.py`

- [ ] **Step 1: Add test to existing `tests/test_registry.py`**

Read `tests/test_registry.py` first. Confirm `_tool()` helper exists — if not, add it:

```python
def _tool(name: str, **props) -> dict:
    properties = {k: {"type": t} for k, t in props.items()}
    return {
        "type": "function",
        "function": {
            "name": name,
            "parameters": {"type": "object", "properties": properties},
        },
    }
```

Then append the collision test. Note: `ToolRegistry` uses `structlog` which is NOT routed to stdlib `logging` in this project. Use `structlog.testing.capture_logs()` instead of `caplog`:

```python
def test_collision_warning_emitted():
    """ToolRegistry warns when two tool names normalize to the same string."""
    import structlog.testing
    with structlog.testing.capture_logs() as cap:
        # "write_file" and "write-file" both normalize to "writefile"
        tools = [
            _tool("write_file", content="string"),
            _tool("write-file", content="string"),
        ]
        ToolRegistry(tools)
    assert any(
        "collision" in str(entry).lower() or "normalization" in str(entry).lower()
        for entry in cap
    )
```

- [ ] **Step 2: Run — expect FAIL** (warning not yet emitted)

```bash
pytest tests/test_registry.py::test_collision_warning_emitted -v 2>&1 | tail -5
```

### Task 4: Update `tools/registry.py`

**Files:**
- Modify: `tools/registry.py`

- [ ] **Step 1: Read the full `tools/registry.py`**

- [ ] **Step 2: Add structlog import + warning in `__init__`**

Add import at the top:
```python
import structlog
log = structlog.get_logger()
```

In the `for t in _tools:` loop, find the line:
```python
            _ae[norm] = name
```

Replace with:
```python
            if norm in _ae and _ae[norm] != name:
                log.warning(
                    "tool_name_normalization_collision",
                    name_a=_ae[norm],
                    name_b=name,
                    normalized=norm,
                )
            _ae[norm] = name
```

- [ ] **Step 3: Run test — expect PASS**

```bash
pytest tests/test_registry.py -v 2>&1 | tail -10
```

- [ ] **Step 4: Full suite**

```bash
pytest tests/ --ignore=tests/integration -q 2>&1 | tail -5
```

- [ ] **Step 5: Commit**

```bash
git add tools/registry.py tests/test_registry.py
git commit -m "fix(tools): registry.py emits tool_name_normalization_collision warning matching parse.py behavior"
```

---

## Chunk 3: `tools/emitter.py` — log parse_tool_arguments failures

### Task 5: Add failure logging test

**Files:**
- Modify: `tests/test_emitter.py`

- [ ] **Step 1: Add test to existing `tests/test_emitter.py`**

Read the current file first, then append:

Note: structlog is NOT routed to stdlib `logging` in this project — use `structlog.testing.capture_logs()` instead of `caplog`:

```python
def test_parse_tool_arguments_logs_on_failure():
    """parse_tool_arguments warns when JSON is invalid instead of silently returning {}."""
    import structlog.testing
    with structlog.testing.capture_logs() as cap:
        result = parse_tool_arguments("not{json")
    assert result == {}
    assert any(
        "parse" in str(entry).lower() or "arguments" in str(entry).lower()
        for entry in cap
    )
```

- [ ] **Step 2: Run — expect FAIL**

```bash
pytest tests/test_emitter.py::test_parse_tool_arguments_logs_on_failure -v 2>&1 | tail -5
```

### Task 6: Update `tools/emitter.py`

**Files:**
- Modify: `tools/emitter.py`

- [ ] **Step 1: Read `tools/emitter.py`**

- [ ] **Step 2: Add structlog import + warning**

Add after the existing imports:
```python
import structlog
log = structlog.get_logger()
```

In `parse_tool_arguments`, find the `except Exception:` block:
```python
    except Exception:
        return {}
```
Replace with:
```python
    except Exception as exc:
        log.warning(
            "emitter_args_parse_failed",
            error=str(exc),
            raw_len=len(raw_args) if isinstance(raw_args, str) else 0,
        )
        return {}
```

- [ ] **Step 3: Run test — expect PASS**

```bash
pytest tests/test_emitter.py -v 2>&1 | tail -10
```

- [ ] **Step 4: Full suite**

```bash
pytest tests/ --ignore=tests/integration -q 2>&1 | tail -5
```

- [ ] **Step 5: Commit**

```bash
git add tools/emitter.py tests/test_emitter.py
git commit -m "fix(tools): emitter.py logs parse_tool_arguments failures instead of silently returning {}"
```

---

## Chunk 4: `tools/budget.py` — add `deduplicate_tool_calls`

### Task 7: Add deduplication tests to `tests/test_budget.py`

**Files:**
- Modify: `tests/test_budget.py`

- [ ] **Step 1: Read `tests/test_budget.py`, then append these tests and add `deduplicate_tool_calls` to the import line**

```python
def test_dedup_no_duplicates_unchanged():
    c1 = {"id": "call_1", "type": "function", "function": {"name": "Bash", "arguments": '{"command": "ls"}'}}
    c2 = {"id": "call_2", "type": "function", "function": {"name": "Write", "arguments": '{"file_path": "/f"}'}}
    assert len(deduplicate_tool_calls([c1, c2])) == 2

def test_dedup_removes_identical_signature():
    c1 = {"id": "call_1", "type": "function", "function": {"name": "Bash", "arguments": '{"command": "ls"}'}}
    c2 = {"id": "call_2", "type": "function", "function": {"name": "Bash", "arguments": '{"command": "ls"}'}}
    result = deduplicate_tool_calls([c1, c2])
    assert len(result) == 1
    assert result[0]["id"] == "call_1"

def test_dedup_different_args_not_deduped():
    c1 = {"id": "call_1", "type": "function", "function": {"name": "Bash", "arguments": '{"command": "ls"}'}}
    c2 = {"id": "call_2", "type": "function", "function": {"name": "Bash", "arguments": '{"command": "pwd"}'}}
    assert len(deduplicate_tool_calls([c1, c2])) == 2

def test_dedup_empty_list():
    assert deduplicate_tool_calls([]) == []

def test_dedup_single_call_unchanged():
    c = {"id": "call_1", "type": "function", "function": {"name": "Bash", "arguments": '{"command": "ls"}'}}
    assert deduplicate_tool_calls([c]) == [c]
```

- [ ] **Step 2: Run — expect ImportError on deduplicate_tool_calls**

```bash
pytest tests/test_budget.py::test_dedup_no_duplicates_unchanged -v 2>&1 | tail -5
```

### Task 8: Add `deduplicate_tool_calls` to `tools/budget.py`

**Files:**
- Modify: `tools/budget.py`

- [ ] **Step 1: Read `tools/budget.py`, then append at the end:**

```python
def deduplicate_tool_calls(calls: list[dict]) -> list[dict]:
    """Remove duplicate tool calls by (name, arguments) signature.

    Preserves the first occurrence. Does not mutate the input list.
    """
    seen: set[str] = set()
    out: list[dict] = []
    for call in calls:
        fn = call.get("function", {})
        sig = fn.get("name", "") + fn.get("arguments", "{}")
        if sig not in seen:
            seen.add(sig)
            out.append(call)
    return out
```

- [ ] **Step 2: Run tests — all pass**

```bash
pytest tests/test_budget.py -v 2>&1 | tail -15
```

- [ ] **Step 3: Full suite**

```bash
pytest tests/ --ignore=tests/integration -q 2>&1 | tail -5
```

- [ ] **Step 4: Commit**

```bash
git add tools/budget.py tests/test_budget.py
git commit -m "feat(tools): add deduplicate_tool_calls to budget.py"
```

---

## Chunk 5: `tools/sanitize.py` — move `_sanitize_user_content`

### Task 9: Write failing tests

**Files:**
- Create: `tests/test_sanitize.py`

- [ ] **Step 1: Write tests**

```python
# tests/test_sanitize.py
from __future__ import annotations
from tools.sanitize import _sanitize_user_content, _CURSOR_WORD_RE


def test_replaces_standalone_cursor_word():
    assert _sanitize_user_content("I use Cursor every day") == "I use the-editor every day"

def test_replaces_lowercase_cursor():
    assert _sanitize_user_content("open cursor please") == "open the-editor please"

def test_does_not_replace_path_component():
    assert "cursor/client.py" in _sanitize_user_content("see cursor/client.py")

def test_does_not_replace_windows_path():
    result = _sanitize_user_content(r"path: C:\cursor\file.py")
    assert r"cursor\file.py" in result

def test_does_not_replace_cursor_with_extension():
    assert ".cursor" in _sanitize_user_content("file.cursor")

def test_empty_string_returns_empty():
    assert _sanitize_user_content("") == ""

def test_backward_compat_cursor_helpers():
    from converters.cursor_helpers import _sanitize_user_content as f
    assert callable(f)
    assert f("use Cursor") == "use the-editor"

def test_cursor_word_re_is_compiled_regex():
    import re
    assert isinstance(_CURSOR_WORD_RE, type(re.compile("")))
```

- [ ] **Step 2: Run — expect ImportError**

```bash
pytest tests/test_sanitize.py -v 2>&1 | tail -5
```

### Task 10: Create `tools/sanitize.py` (COPY — do not remove from cursor_helpers yet)

**Files:**
- Create: `tools/sanitize.py`

- [ ] **Step 1: Read `converters/cursor_helpers.py`** — find `_CURSOR_REPLACEMENT`, `_CURSOR_WORD_RE`, `_sanitize_user_content` (approximately lines 22-54). Copy exactly.

- [ ] **Step 2: Write `tools/sanitize.py`**

First read lines 30-46 of `converters/cursor_helpers.py` to get the exact regex. Then write:

```python
"""
Shin Proxy — User content sanitization.

Replaces the standalone word 'cursor' (any case) in user-supplied content
with a neutral placeholder to prevent the upstream model from activating
its Support Assistant identity.

Extracted from converters/cursor_helpers.py. converters/ keeps a backward-
compat re-export. tools/ has zero dependency on converters/.
"""
from __future__ import annotations

import re

_CURSOR_REPLACEMENT = "the-editor"

# Copy this regex EXACTLY from converters/cursor_helpers.py lines 42-46.
# The correct regex is:
_CURSOR_WORD_RE = re.compile(
    r"(?<![/\\a-zA-Z0-9])"      # not preceded by path sep or word char
    r"[Cc][Uu][Rr][Ss][Oo][Rr]" # the word itself
    r"(?![/\\.](\w))"           # not followed by path sep, dot+word (WRONG — see below)
)
```

**IMPORTANT: Do NOT copy the regex from this plan document.** The source of truth is `converters/cursor_helpers.py` lines 42-46. Read those lines first, then copy them verbatim. The correct regex ends with `r"(?![/\\.](\w))"` — no capture group in the lookahead. Any template in this document may have encoding artifacts. Always read the source file.

**Do NOT remove originals from `cursor_helpers.py` yet — that is Task 11.**

- [ ] **Step 3: Run tests — all pass**

```bash
pytest tests/test_sanitize.py -v 2>&1 | tail -12
```

- [ ] **Step 4: Full suite**

```bash
pytest tests/ --ignore=tests/integration -q 2>&1 | tail -5
```

- [ ] **Step 5: Commit**

```bash
git add tools/sanitize.py tests/test_sanitize.py
git commit -m "feat(tools): add sanitize.py — _sanitize_user_content, _CURSOR_WORD_RE (copy; cursor_helpers intact)"
```

### Task 11: Update `converters/cursor_helpers.py`

**Files:**
- Modify: `converters/cursor_helpers.py`

- [ ] **Step 1: Read `converters/cursor_helpers.py`** — confirm lines for `_CURSOR_REPLACEMENT`, `_CURSOR_WORD_RE`, `_sanitize_user_content`

- [ ] **Step 2: Remove originals, add re-exports**

Delete the `_CURSOR_REPLACEMENT` constant, `_CURSOR_WORD_RE` regex, and `_sanitize_user_content` function body.

Add at top (after existing imports):
```python
# Sanitization moved to tools/sanitize.py — re-exported here for backward compat
from tools.sanitize import _CURSOR_WORD_RE  # noqa: F401
from tools.sanitize import _sanitize_user_content  # noqa: F401
```

- [ ] **Step 3: Verify**

```bash
python -c "from converters.cursor_helpers import _sanitize_user_content; print(_sanitize_user_content('use Cursor here'))"
```

Expected: `use the-editor here`

- [ ] **Step 4: Full suite**

```bash
pytest tests/ --ignore=tests/integration -q 2>&1 | tail -5
```

- [ ] **Step 5: Commit**

```bash
git add converters/cursor_helpers.py
git commit -m "refactor(converters): cursor_helpers re-exports _sanitize_user_content from tools/sanitize"
```

---

## Chunk 6: `tools/results.py` — extract `_build_tool_call_results`

### Task 12: Write failing tests

**Files:**
- Create: `tests/test_results.py`

- [ ] **Step 1: Write tests**

```python
# tests/test_results.py
from __future__ import annotations
from tools.results import _build_tool_call_results


def _tool(name: str, **props) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "parameters": {
                "type": "object",
                "properties": {k: {"type": v} for k, v in props.items()},
                "required": list(props.keys()),
            },
        },
    }


def _allowed(tools):
    import re
    return {re.sub(r"[-_\s]", "", t["function"]["name"].lower()): t["function"]["name"] for t in tools}

def _schema_map(tools):
    return {t["function"]["name"]: set(t["function"]["parameters"]["properties"].keys()) for t in tools}


def test_valid_call_normalised():
    tools = [_tool("Bash", command="string")]
    merged = [{"name": "Bash", "arguments": {"command": "ls"}}]
    result = _build_tool_call_results(
        merged=merged,
        allowed_exact=_allowed(tools),
        schema_map=_schema_map(tools),
        streaming=False,
    )
    assert len(result) == 1
    assert result[0]["function"]["name"] == "Bash"
    assert result[0]["type"] == "function"
    assert "id" in result[0]

def test_unknown_tool_dropped():
    tools = [_tool("Bash", command="string")]
    merged = [{"name": "Unknown", "arguments": {}}]
    result = _build_tool_call_results(
        merged=merged,
        allowed_exact=_allowed(tools),
        schema_map=_schema_map(tools),
        streaming=False,
    )
    assert result == []  # unknown tool dropped

def test_arguments_always_json_string():
    """INVARIANT: arguments in output is always a JSON string."""
    import json
    tools = [_tool("Bash", command="string")]
    merged = [{"name": "Bash", "arguments": {"command": "ls"}}]  # dict input
    result = _build_tool_call_results(
        merged=merged,
        allowed_exact=_allowed(tools),
        schema_map=_schema_map(tools),
        streaming=False,
    )
    assert isinstance(result[0]["function"]["arguments"], str)
    assert json.loads(result[0]["function"]["arguments"]) == {"command": "ls"}

def test_fuzzy_name_corrected():
    tools = [_tool("Bash", command="string")]
    merged = [{"name": "bash", "arguments": {"command": "ls"}}]  # lowercase
    result = _build_tool_call_results(
        merged=merged,
        allowed_exact=_allowed(tools),
        schema_map=_schema_map(tools),
        streaming=False,
    )
    assert len(result) == 1
    assert result[0]["function"]["name"] == "Bash"

def test_id_assigned():
    tools = [_tool("Bash", command="string")]
    merged = [{"name": "Bash", "arguments": {}}]
    result = _build_tool_call_results(
        merged=merged,
        allowed_exact=_allowed(tools),
        schema_map=_schema_map(tools),
        streaming=False,
    )
    assert result[0]["id"].startswith("call_")
```

- [ ] **Step 2: Run — expect ImportError**

```bash
pytest tests/test_results.py -v 2>&1 | tail -5
```

### Task 13: Create `tools/results.py` (COPY step)

**Files:**
- Create: `tools/results.py`

- [ ] **Step 1: Read `tools/parse.py`** — find `_build_tool_call_results` (approximately line 827). Read the full function.

- [ ] **Step 2: Write `tools/results.py`**

`_normalize_name` is defined in `tools/parse.py` (line 47) and `tools/registry.py` (line 15) — it is NOT in `tools/coerce.py`. Copy it directly into `tools/results.py` rather than importing from a private location.

```python
"""
Shin Proxy — Tool call result builder.

Extracts _build_tool_call_results from tools/parse.py.
Builds normalized tool call dicts from merged parsed candidates.
"""
from __future__ import annotations

import re
import uuid

import msgspec.json as msgjson
import structlog

from tools.coerce import _fuzzy_match_param

log = structlog.get_logger()


def _normalize_name(name: str) -> str:
    """Normalize tool name for fuzzy matching — lowercase, strip separators."""
    return re.sub(r"[-_\s]", "", (name or "").lower())
```

Then copy `_build_tool_call_results` verbatim from `tools/parse.py` (approximately lines 827-916). The function calls `_normalize_name` and `_fuzzy_match_param` — both are now available in `tools/results.py`.

**Do NOT remove from `tools/parse.py` yet — that is Task 14.**

- [ ] **Step 3: Run tests — all pass**

```bash
pytest tests/test_results.py -v 2>&1 | tail -15
```

- [ ] **Step 4: Full suite**

```bash
pytest tests/ --ignore=tests/integration -q 2>&1 | tail -5
```

- [ ] **Step 5: Commit**

```bash
git add tools/results.py tests/test_results.py
git commit -m "feat(tools): add results.py — _build_tool_call_results extracted from parse.py (copy step)"
```

### Task 14: Update `tools/parse.py` to import from `tools/results.py`

**Files:**
- Modify: `tools/parse.py`

- [ ] **Step 1: Add import to `tools/parse.py`**

At the top of `tools/parse.py` (after the existing re-export block), add:
```python
from tools.results import _build_tool_call_results  # noqa: F401
```

- [ ] **Step 2: Delete the `_build_tool_call_results` function body from `tools/parse.py`**

Find the `def _build_tool_call_results(` definition and delete it (approximately lines 827-916).

- [ ] **Step 3: Verify the re-export works**

```bash
python -c "from tools.parse import _build_tool_call_results; print('OK')"
```

- [ ] **Step 4: Run parse tests**

```bash
pytest tests/test_parse.py tests/test_parse_extended.py -v 2>&1 | tail -15
```

- [ ] **Step 5: Check parse.py line count**

```bash
wc -l /teamspace/studios/this_studio/dikders/tools/parse.py
```

Expected: ~100 lines fewer than before this chunk.

- [ ] **Step 6: Full suite**

```bash
pytest tests/ --ignore=tests/integration -q 2>&1 | tail -5
```

- [ ] **Step 7: Commit**

```bash
git add tools/parse.py
git commit -m "refactor(tools): parse.py imports _build_tool_call_results from tools/results"
```

---

## Chunk 7: Final validation + UPDATES.md

### Task 15: Full verification

- [ ] **Step 1: Import smoke test**

```bash
cd /teamspace/studios/this_studio/dikders
python -c "
import tools.metrics
import tools.sanitize
import tools.results
from tools.metrics import inc_parse_outcome, inc_tool_repair, inc_schema_validation
from tools.sanitize import _sanitize_user_content
from tools.results import _build_tool_call_results
from tools.budget import deduplicate_tool_calls
from converters.cursor_helpers import _sanitize_user_content as f
from tools.parse import _build_tool_call_results as r
assert f('use Cursor') == 'use the-editor'
print('ALL IMPORTS OK')
"
```

- [ ] **Step 2: Coverage on new modules**

```bash
pytest tests/test_metrics.py tests/test_sanitize.py tests/test_results.py \
    tests/test_budget.py tests/test_registry.py tests/test_emitter.py \
    --cov=tools.metrics --cov=tools.sanitize --cov=tools.results \
    --cov=tools.budget --cov=tools.registry --cov=tools.emitter \
    --cov-report=term-missing -q 2>&1 | tail -15
```

Expected: >= 80% on each new module.

- [ ] **Step 3: Full non-integration suite**

```bash
pytest tests/ --ignore=tests/integration -q 2>&1 | tail -5
```

### Task 16: UPDATES.md + push

- [ ] **Step 1: Add session entry to UPDATES.md**

`## Session 144 — tools/ Phase 3: reliability and observability (2026-03-26)`

Include: files created/modified, functions affected, why, commit SHAs (`git log --oneline -10`).

- [ ] **Step 2: Commit and push**

```bash
git add UPDATES.md
git commit -m "docs: update UPDATES.md for Session 144 — tools/ Phase 3"
git push
```

---

## Summary

| Chunk | Files | Tests | Key outcome |
|---|---|---|---|
| 1 | `tools/metrics.py` | `test_metrics.py` (4 tests) | Stable metrics import; `inc_tool_repair`, `inc_schema_validation` added |
| 2 | `tools/registry.py` | `test_registry.py` (+1 test) | Collision warning matches `parse.py` no-registry behavior |
| 3 | `tools/emitter.py` | `test_emitter.py` (+1 test) | `parse_tool_arguments` logs failures instead of silently returning `{}` |
| 4 | `tools/budget.py` | `test_budget.py` (+5 tests) | `deduplicate_tool_calls` added |
| 5 | `tools/sanitize.py` + converters | `test_sanitize.py` (8 tests) | `_sanitize_user_content` moved to `tools/` with dedicated tests |
| 6 | `tools/results.py` | `test_results.py` (4 tests) | `_build_tool_call_results` extracted; `parse.py` shrinks further |
| 7 | UPDATES.md | full suite >= 80% | Final validation and push |

**Zero new external dependencies. Zero breaking changes. All existing tests pass.**

