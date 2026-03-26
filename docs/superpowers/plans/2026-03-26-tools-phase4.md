# tools/ Phase 4 — JSON Repair, Repair, Confidence Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract `tools/json_repair.py`, `tools/repair.py`, and `tools/confidence.py` from `parse.py` and `score.py` — reducing `parse.py` from 1002 lines to ~395 lines with zero breaking changes.

**Architecture:** Three atomic extractions in sequence. Each step: copy verbatim → test → update source to import from new module → re-export for backward compat → verify all tests pass → commit.

**Tech Stack:** Python 3.12, msgspec, structlog, pytest. No new pip dependencies.

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `tools/json_repair.py` | CREATE | `_repair_json_control_chars`, `_escape_unescaped_quotes`, `_extract_after_marker`, `_lenient_json_loads`, `_decode_json_escapes`, `_extract_truncated_args`, `extract_json_candidates` |
| `tools/repair.py` | CREATE | `repair_tool_call` |
| `tools/confidence.py` | CREATE | `CONFIDENCE_THRESHOLD`, `score_tool_call_confidence`, `_find_marker_pos` (from score.py) |
| `tools/parse.py` | MODIFY | Remove extracted bodies; import from new modules; re-export all names used by existing tests |
| `tools/score.py` | UNCHANGED | `confidence.py` imports FROM `score.py` — no change needed; modifying score.py would create a circular import |
| `tests/test_json_repair.py` | CREATE | Tests for all 7 functions in json_repair.py |
| `tests/test_repair.py` | CREATE | Tests for repair_tool_call |
| `tests/test_confidence.py` | CREATE | Tests for CONFIDENCE_THRESHOLD and is_confident helper |

---

## Chunk 1: `tools/json_repair.py`

### Task 1: Write failing tests

**Files:**
- Create: `tests/test_json_repair.py`

- [ ] **Step 1: Write tests**

```python
# tests/test_json_repair.py
from __future__ import annotations
from tools.json_repair import (
    _repair_json_control_chars,
    _escape_unescaped_quotes,
    _extract_after_marker,
    _lenient_json_loads,
    _decode_json_escapes,
    _extract_truncated_args,
    extract_json_candidates,
)


# ── _repair_json_control_chars ───────────────────────────────────────────────

def test_repair_control_chars_newline_in_string():
    raw = '{"key": "line1\nline2"}'
    result = _repair_json_control_chars(raw)
    assert '\\n' in result
    assert '\n' not in result.split('"key"')[1]

def test_repair_control_chars_tab_in_string():
    raw = '{"key": "col1\tcol2"}'
    result = _repair_json_control_chars(raw)
    assert '\\t' in result

def test_repair_control_chars_no_change_outside_string():
    # newline outside a string value should not be touched
    raw = '{\n"key": "value"\n}'
    result = _repair_json_control_chars(raw)
    assert '\n' in result  # structural newline preserved


# ── _escape_unescaped_quotes ─────────────────────────────────────────────────

def test_escape_unescaped_quotes_in_value():
    # bare quotes inside a string value
    raw = '{"key": "say \"hello\""}'
    # already has escaped quotes — should remain valid
    import msgspec.json as msgjson
    result = _escape_unescaped_quotes(raw)
    parsed = msgjson.decode(result.encode())
    assert parsed["key"] == 'say "hello"'

def test_escape_unescaped_quotes_passthrough_valid():
    raw = '{"key": "value"}'
    result = _escape_unescaped_quotes(raw)
    assert result == raw


# ── _lenient_json_loads ──────────────────────────────────────────────────────

def test_lenient_json_loads_strict():
    raw = '{"key": "value"}'
    assert _lenient_json_loads(raw) == {"key": "value"}

def test_lenient_json_loads_control_chars():
    raw = '{"key": "line1\nline2"}'
    result = _lenient_json_loads(raw)
    assert result is not None
    assert result["key"] == "line1\nline2"

def test_lenient_json_loads_returns_none_on_garbage():
    assert _lenient_json_loads("not json at all") is None

def test_lenient_json_loads_list():
    assert _lenient_json_loads('[1, 2, 3]') == [1, 2, 3]


# ── _decode_json_escapes ─────────────────────────────────────────────────────

def test_decode_json_escapes_newline():
    assert _decode_json_escapes("line1\\nline2") == "line1\nline2"

def test_decode_json_escapes_tab():
    assert _decode_json_escapes("col1\\tcol2") == "col1\tcol2"

def test_decode_json_escapes_backslash():
    assert _decode_json_escapes("\\\\") == "\\"

def test_decode_json_escapes_unicode():
    assert _decode_json_escapes("\\u0041") == "A"


# ── _extract_truncated_args ──────────────────────────────────────────────────

def test_extract_truncated_args_single_field():
    raw = '{"result": "partial output that was cut off'
    result = _extract_truncated_args(raw)
    assert result is not None
    assert "result" in result
    assert "partial output" in result["result"]

def test_extract_truncated_args_returns_none_no_keys():
    assert _extract_truncated_args("not valid") is None


# ── extract_json_candidates ──────────────────────────────────────────────────

def test_extract_json_candidates_bare_object():
    text = 'prefix {"key": "value"} suffix'
    result = extract_json_candidates(text)
    assert len(result) >= 1
    assert any('{"key": "value"}' in c for c in result)

def test_extract_json_candidates_fenced():
    text = '```json\n{"key": "value"}\n```'
    result = extract_json_candidates(text)
    assert len(result) >= 1

def test_extract_json_candidates_empty():
    assert extract_json_candidates('') == []
    assert extract_json_candidates(None) == []

def test_extract_json_candidates_no_duplicates():
    text = '{"a": 1}'
    result = extract_json_candidates(text)
    assert len(result) == len(set(result))


# ── _extract_after_marker ────────────────────────────────────────────────────

def test_extract_after_marker_returns_json():
    text = '[assistant_tool_calls]\n{"tool_calls": []}'
    result = _extract_after_marker(text)
    assert result is not None
    assert result.startswith('{')

def test_extract_after_marker_no_marker_returns_none():
    assert _extract_after_marker('no marker here {"a": 1}') is None
```

- [ ] **Step 2: Run — expect ImportError**

```bash
cd /teamspace/studios/this_studio/dikders
pytest tests/test_json_repair.py -v 2>&1 | tail -5
```

Expected: `ModuleNotFoundError: No module named 'tools.json_repair'`

### Task 2: Create `tools/json_repair.py`

**Files:**
- Create: `tools/json_repair.py`

- [ ] **Step 1: Read `tools/parse.py`** lines 47–582 to get exact function bodies

```bash
sed -n '47,582p' /teamspace/studios/this_studio/dikders/tools/parse.py
```

- [ ] **Step 2: Write `tools/json_repair.py`** with exact copies of all 7 items

Module header:
```python
"""
Shin Proxy — Resilient JSON parsing and repair.

Extracts JSON repair strategies from tools/parse.py:
- _repair_json_control_chars  — escape literal control chars inside strings
- _escape_unescaped_quotes    — fix bare quotes inside string values
- _extract_after_marker       — grab first complete JSON object after [assistant_tool_calls]
- _lenient_json_loads         — 4-strategy parser (strict → control repair → quote repair → regex)
- _decode_json_escapes        — decode \\n \\t etc from raw extracted strings
- _extract_truncated_args     — recover args from cut-off streams
- extract_json_candidates     — bracket-match JSON from arbitrary text

No imports from other tools/ modules.
"""
from __future__ import annotations

import re

import msgspec.json as msgjson
import structlog

log = structlog.get_logger()
```

Then copy the 7 functions verbatim from `tools/parse.py`.

**DO NOT remove them from parse.py yet — that is Task 3.**

- [ ] **Step 3: Run tests — all pass**

```bash
pytest tests/test_json_repair.py -v 2>&1 | tail -15
```

Expected: all 21 tests PASS

- [ ] **Step 4: Full suite — no regressions**

```bash
pytest tests/ --ignore=tests/integration -q 2>&1 | tail -5
```

- [ ] **Step 5: Commit copy step**

```bash
git add tools/json_repair.py tests/test_json_repair.py
git commit -m "feat(tools): add json_repair.py — resilient JSON parsing extracted from parse.py (copy step)"
```

### Task 3: Update `tools/parse.py` — import from `tools/json_repair.py` and remove bodies

- [ ] **Step 1: Add to the re-export block in parse.py:**

```python
from tools.json_repair import (  # noqa: F401
    _repair_json_control_chars,
    _escape_unescaped_quotes,
    _extract_after_marker,
    _lenient_json_loads,
    _decode_json_escapes,
    _extract_truncated_args,
    extract_json_candidates,
)
```

- [ ] **Step 2: Delete the 7 function bodies + their private constants** (`_JSON_FENCE_RE`, `_JSON_AFTER_CLOSE_QUOTE`, `_TOOL_CALL_RE`, `_KV_OPEN_RE`, `_FIELD_RE`). Verify each constant is not used outside the deleted functions before removing.

- [ ] **Step 3: Verify backward compat imports**

```bash
python -c "from tools.parse import _lenient_json_loads, _repair_json_control_chars, _escape_unescaped_quotes, _extract_truncated_args, extract_json_candidates; print('OK')"
python -c "import tools; print('tools __init__ OK')"
```

- [ ] **Step 4: Run existing parse tests**

```bash
pytest tests/test_parse.py tests/test_parse_extended.py tests/test_json_repair.py -v 2>&1 | tail -15
```

- [ ] **Step 5: Check parse.py line count — expect ~530**

```bash
wc -l /teamspace/studios/this_studio/dikders/tools/parse.py
```

- [ ] **Step 6: Full suite**

```bash
pytest tests/ --ignore=tests/integration -q 2>&1 | tail -5
```

- [ ] **Step 7: Commit**

```bash
git add tools/parse.py
git commit -m "refactor(tools): parse.py imports JSON repair functions from tools/json_repair"
```

---

## Chunk 2: `tools/repair.py`

### Task 4: Write failing tests

- [ ] **Step 1: Create `tests/test_repair.py`**

```python
# tests/test_repair.py
from __future__ import annotations
import json
from tools.repair import repair_tool_call


def _tool(name: str, **props) -> dict:
    prop_defs = {k: ({"type": v} if isinstance(v, str) else v) for k, v in props.items()}
    return {"type": "function", "function": {"name": name, "parameters": {"type": "object", "properties": prop_defs, "required": list(props.keys())}}}

def _call(name: str, **kwargs) -> dict:
    return {"id": "call_abc", "type": "function", "function": {"name": name, "arguments": json.dumps(kwargs)}}


def test_no_repair_needed():
    tools = [_tool("Bash", command="string")]
    call = _call("Bash", command="ls")
    repaired, repairs = repair_tool_call(call, tools)
    assert repairs == []

def test_alias_param_repaired():
    tools = [_tool("Bash", command="string")]
    call = {"id": "c", "type": "function", "function": {"name": "Bash", "arguments": json.dumps({"cmd": "ls"})}}
    repaired, repairs = repair_tool_call(call, tools)
    assert any("cmd" in r and "command" in r for r in repairs)
    assert "command" in json.loads(repaired["function"]["arguments"])

def test_type_coercion_int_to_string():
    tools = [_tool("Bash", command="string")]
    repaired, repairs = repair_tool_call(_call("Bash", command=42), tools)
    assert isinstance(json.loads(repaired["function"]["arguments"])["command"], str)
    assert any("coerced" in r for r in repairs)

def test_unknown_tool_returns_original():
    call = _call("Unknown", x="y")
    repaired, repairs = repair_tool_call(call, [])
    assert repairs == []
    assert repaired is call

def test_unknown_param_dropped():
    tools = [_tool("Bash", command="string")]
    repaired, repairs = repair_tool_call(_call("Bash", command="ls", extra="junk"), tools)
    assert "extra" not in json.loads(repaired["function"]["arguments"])
    assert any("dropped" in r for r in repairs)

def test_id_preserved():
    tools = [_tool("Bash", command="string")]
    call = {"id": "call_orig", "type": "function", "function": {"name": "Bash", "arguments": json.dumps({"cmd": "ls"})}}
    repaired, _ = repair_tool_call(call, tools)
    assert repaired["id"] == "call_orig"
```

- [ ] **Step 2: Run — expect ImportError**

```bash
pytest tests/test_repair.py -v 2>&1 | tail -5
```

### Task 5: Create `tools/repair.py`

- [ ] **Step 1: Read parse.py lines ~685–822** to get the exact `repair_tool_call` body

```bash
grep -n 'def repair_tool_call' /teamspace/studios/this_studio/dikders/tools/parse.py
```

- [ ] **Step 2: Write `tools/repair.py`**

```python
"""
Shin Proxy — Tool call repair.

Extracts repair_tool_call from tools/parse.py.
"""
from __future__ import annotations

import uuid

import msgspec.json as msgjson
import structlog

from tools.coerce import _coerce_value, _fuzzy_match_param

log = structlog.get_logger()
```

Then copy `repair_tool_call` verbatim. Do NOT remove from parse.py yet.

- [ ] **Step 3: Run tests — all 6 pass**

```bash
pytest tests/test_repair.py -v 2>&1 | tail -10
```

- [ ] **Step 4: Full suite**

```bash
pytest tests/ --ignore=tests/integration -q 2>&1 | tail -5
```

- [ ] **Step 5: Commit copy**

```bash
git add tools/repair.py tests/test_repair.py
git commit -m "feat(tools): add repair.py — repair_tool_call extracted from parse.py (copy step)"
```

### Task 6: Update `tools/parse.py` and `tools/budget.py`

- [ ] **Step 1: Add to re-export block in parse.py:** `from tools.repair import repair_tool_call  # noqa: F401`

- [ ] **Step 2: In `tools/budget.py`**, change `from tools.parse import repair_tool_call` → `from tools.repair import repair_tool_call`

- [ ] **Step 3: Delete `repair_tool_call` body from parse.py**

- [ ] **Step 4: Verify**

```bash
python -c "from tools.parse import repair_tool_call; print('OK')"
python -c "from tools.budget import repair_invalid_calls; print('OK')"
python -c "import tools; print('tools __init__ OK')"
```

- [ ] **Step 5: Run parse + budget + repair tests**

```bash
pytest tests/test_parse.py tests/test_parse_extended.py tests/test_budget.py tests/test_repair.py -v 2>&1 | tail -10
```

- [ ] **Step 6: Check parse.py line count — expect ~395**

```bash
wc -l /teamspace/studios/this_studio/dikders/tools/parse.py
```

- [ ] **Step 7: Full suite**

```bash
pytest tests/ --ignore=tests/integration -q 2>&1 | tail -5
```

- [ ] **Step 8: Commit**

```bash
git add tools/parse.py tools/budget.py
git commit -m "refactor(tools): parse.py imports repair_tool_call from tools/repair; budget.py imports direct"
```

---

## Chunk 3: `tools/confidence.py` + wire `CONFIDENCE_THRESHOLD`

### Task 7: Write failing tests

- [ ] **Step 1: Create `tests/test_confidence.py`**

```python
# tests/test_confidence.py
from __future__ import annotations
from tools.confidence import CONFIDENCE_THRESHOLD, is_confident, score_tool_call_confidence, _find_marker_pos


def _call() -> dict:
    return {"id": "c", "type": "function", "function": {"name": "Bash", "arguments": "{}"}}


def test_threshold_is_float():
    assert isinstance(CONFIDENCE_THRESHOLD, float)
    assert 0.0 < CONFIDENCE_THRESHOLD < 1.0

def test_is_confident_true_with_marker():
    assert is_confident("[assistant_tool_calls]\n{}", [_call()]) is True

def test_is_confident_false_empty_calls():
    assert is_confident("anything", []) is False

def test_is_confident_false_low_score():
    assert is_confident("a" * 2000, [_call()]) is False

def test_score_accessible():
    score = score_tool_call_confidence("[assistant_tool_calls]\n{}", [_call()])
    assert 0.0 <= score <= 1.0

def test_find_marker_pos_accessible():
    assert _find_marker_pos("[assistant_tool_calls]\n{}") == 0
```

- [ ] **Step 2: Run — expect ImportError**

```bash
pytest tests/test_confidence.py -v 2>&1 | tail -5
```

### Task 8: Create `tools/confidence.py`

- [ ] **Step 1: Write the file**

```python
"""
Shin Proxy — Tool call confidence scoring.

Provides CONFIDENCE_THRESHOLD as the single source of truth for the 0.3
cutoff hardcoded in parse.py. Re-exports score_tool_call_confidence and
_find_marker_pos from tools/score.

Adds is_confident(text, calls) helper for call sites that don't need the
raw score.
"""
from __future__ import annotations

from tools.score import _find_marker_pos, score_tool_call_confidence  # noqa: F401

CONFIDENCE_THRESHOLD: float = 0.3
"""Minimum confidence score for a tool call to be accepted. Single source of truth."""


def is_confident(text: str, calls: list[dict]) -> bool:
    """Return True if the score meets or exceeds CONFIDENCE_THRESHOLD."""
    return score_tool_call_confidence(text, calls) >= CONFIDENCE_THRESHOLD
```

- [ ] **Step 2: Run tests — all 6 pass**

```bash
pytest tests/test_confidence.py -v 2>&1 | tail -10
```

- [ ] **Step 3: Wire `CONFIDENCE_THRESHOLD` into `parse.py`**

In `tools/parse.py`, find the **one** hardcoded `0.3` reference (verify with `grep -n '0.3' tools/parse.py`) and replace with `CONFIDENCE_THRESHOLD`:

```python
# Add import at top:
from tools.confidence import CONFIDENCE_THRESHOLD

# Find line: if conf < 0.3:
# Replace with:
if conf < CONFIDENCE_THRESHOLD:
```

```bash
grep -n '0.3\|CONFIDENCE_THRESHOLD' /teamspace/studios/this_studio/dikders/tools/parse.py
```

- [ ] **Step 4: Full suite**

```bash
pytest tests/ --ignore=tests/integration -q 2>&1 | tail -5
```

- [ ] **Step 5: Commit**

```bash
git add tools/confidence.py tests/test_confidence.py tools/parse.py
git commit -m "feat(tools): add confidence.py — CONFIDENCE_THRESHOLD constant + is_confident helper; wire into parse.py"
```

---

## Chunk 4: Final validation + UPDATES.md

### Task 9: Final verification

- [ ] **Step 1: Import smoke test**

```bash
cd /teamspace/studios/this_studio/dikders
python -c "
import tools.json_repair
import tools.repair
import tools.confidence
from tools.json_repair import _lenient_json_loads, extract_json_candidates
from tools.repair import repair_tool_call
from tools.confidence import CONFIDENCE_THRESHOLD, is_confident
from tools.parse import _lenient_json_loads, repair_tool_call, extract_json_candidates
from tools.budget import repair_invalid_calls
print('ALL IMPORTS OK')
print('CONFIDENCE_THRESHOLD =', CONFIDENCE_THRESHOLD)
wc = __import__('subprocess').run(['wc', '-l', 'tools/parse.py'], capture_output=True, text=True)
print('parse.py lines:', wc.stdout.strip())
"
```

Expected: ALL IMPORTS OK, `CONFIDENCE_THRESHOLD = 0.3`, parse.py ~395 lines.

- [ ] **Step 2: Run full non-integration test suite**

```bash
pytest tests/ --ignore=tests/integration -q 2>&1 | tail -5
```

Expected: all existing tests pass + 3 new test files pass. Zero new failures.

- [ ] **Step 3: Coverage on new modules**

```bash
pytest tests/test_json_repair.py tests/test_repair.py tests/test_confidence.py \
    --cov=tools.json_repair --cov=tools.repair --cov=tools.confidence \
    --cov-report=term-missing -q 2>&1 | tail -15
```

Expected: >= 80% on each new module.

### Task 10: Update UPDATES.md and push

- [ ] **Step 1: Add session entry to UPDATES.md**

`## Session 148 — tools/ Phase 4: json_repair, repair, confidence (2026-03-26)`

Document: files created, functions moved, why, parse.py final line count, commit SHAs.

- [ ] **Step 2: Commit and push**

```bash
git add UPDATES.md
git commit -m "docs: update UPDATES.md for Session 148 — tools/ Phase 4"
git push
```

---

## Summary

| Chunk | Files | Tests | parse.py lines |
|---|---|---|---|
| 1 | `tools/json_repair.py` | `test_json_repair.py` (21 tests) | ~530 (from 1002) |
| 2 | `tools/repair.py` | `test_repair.py` (6 tests) | ~395 (from 530) |
| 3 | `tools/confidence.py` | `test_confidence.py` (6 tests) | ~395 (CONFIDENCE_THRESHOLD wired) |
| 4 | UPDATES.md | full suite >= 80% | final push |

**Zero new external dependencies. Zero breaking changes. All existing tests pass.**
