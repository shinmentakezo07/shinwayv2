# tools/ Refactor Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split `tools/parse.py` into focused modules, add full JSON Schema validation, fix `build_tool_instruction` dependency direction, add canonical wire-format encoder and request-scoped tool registry — with zero breaking changes.

**Architecture:** Nine-step atomic extraction. Each step produces a passing test suite before the next begins. Private names used by existing tests are explicitly re-exported. No circular imports. No new external dependencies.

**Tech Stack:** Python 3.12, msgspec, structlog, pytest. All new modules are pure Python with no new pip dependencies.

**Spec:** `docs/superpowers/specs/2026-03-25-tools-refactor-design.md`

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `tools/coerce.py` | CREATE | `_PARAM_ALIASES`, `_levenshtein`, `_fuzzy_match_param`, `_coerce_value` |
| `tools/score.py` | CREATE | `score_tool_call_confidence`, `_find_marker_pos` |
| `tools/streaming.py` | CREATE | `StreamingToolCallParser` |
| `tools/schema.py` | CREATE | `validate_schema` — full JSON Schema enforcement |
| `tools/format.py` | CREATE | `encode_tool_calls` — canonical wire-format encoder |
| `tools/inject.py` | CREATE | `build_tool_instruction`, `_example_value`, `_PARAM_EXAMPLES` |
| `tools/registry.py` | CREATE | `ToolRegistry` — immutable request-scoped registry |
| `tools/parse.py` | MODIFY | Remove extracted code; import from new modules; re-export all names |
| `tools/__init__.py` | MODIFY | Re-export all public names (updated in parallel with parse.py) |
| `converters/cursor_helpers.py` | MODIFY | Re-export `build_tool_instruction`, `_example_value`, `_PARAM_EXAMPLES`, `_assistant_tool_call_text` from new homes |
| `converters/to_cursor.py` | MODIFY | Add explicit re-export of `build_tool_instruction` |
| `tests/test_coerce.py` | CREATE | Unit tests for `tools/coerce.py` |
| `tests/test_score.py` | CREATE | Unit tests for `tools/score.py` |
| `tests/test_streaming.py` | CREATE | Unit tests for `tools/streaming.py` |
| `tests/test_schema.py` | CREATE | Unit tests for `tools/schema.py` |
| `tests/test_format.py` | CREATE | Unit tests for `tools/format.py` |
| `tests/test_inject.py` | CREATE | Unit tests for `tools/inject.py` |
| `tests/test_registry.py` | CREATE | Unit tests for `tools/registry.py` |

---

## Chunk 1: `tools/coerce.py`

### Task 1: Write failing tests for `tools/coerce.py`

**Files:**
- Create: `tests/test_coerce.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_coerce.py
from __future__ import annotations
import pytest
from tools.coerce import (
    _levenshtein,
    _fuzzy_match_param,
    _coerce_value,
    _PARAM_ALIASES,
)


def test_levenshtein_identical():
    assert _levenshtein("abc", "abc") == 0

def test_levenshtein_empty():
    assert _levenshtein("", "abc") == 3
    assert _levenshtein("abc", "") == 3

def test_levenshtein_substitution():
    assert _levenshtein("cat", "bat") == 1

def test_levenshtein_insertion():
    assert _levenshtein("ab", "abc") == 1

def test_levenshtein_deletion():
    assert _levenshtein("abc", "ab") == 1


def test_fuzzy_match_exact():
    assert _fuzzy_match_param("command", {"command"}) == "command"

def test_fuzzy_match_alias():
    # "cmd" → "command" via alias table
    assert _fuzzy_match_param("cmd", {"command"}) == "command"

def test_fuzzy_match_normalized():
    # "file_path" with dashes stripped
    assert _fuzzy_match_param("file-path", {"file_path"}) == "file_path"

def test_fuzzy_match_levenshtein():
    # "comand" (1 typo) → "command"
    assert _fuzzy_match_param("comand", {"command"}) == "command"

def test_fuzzy_match_no_match():
    assert _fuzzy_match_param("zzzzz", {"command"}) is None

def test_fuzzy_match_substring():
    # "filepath" contains "file_path" normalized
    assert _fuzzy_match_param("filepath", {"file_path"}) == "file_path"


def test_coerce_boolean_from_string_true():
    repairs: list[str] = []
    result = _coerce_value("true", {"type": "boolean"}, "flag", repairs)
    assert result is True
    assert repairs

def test_coerce_boolean_from_string_false():
    repairs: list[str] = []
    result = _coerce_value("false", {"type": "boolean"}, "flag", repairs)
    assert result is False

def test_coerce_integer_from_string():
    repairs: list[str] = []
    result = _coerce_value("42", {"type": "integer"}, "count", repairs)
    assert result == 42
    assert repairs

def test_coerce_string_from_int():
    repairs: list[str] = []
    result = _coerce_value(42, {"type": "string"}, "label", repairs)
    assert result == "42"
    assert repairs

def test_coerce_array_wraps_scalar():
    repairs: list[str] = []
    result = _coerce_value("item", {"type": "array"}, "items", repairs)
    assert result == ["item"]

def test_coerce_no_change_when_type_matches():
    repairs: list[str] = []
    result = _coerce_value("hello", {"type": "string"}, "msg", repairs)
    assert result == "hello"
    assert not repairs

def test_param_aliases_not_empty():
    assert isinstance(_PARAM_ALIASES, dict)
    assert len(_PARAM_ALIASES) > 10
    assert "cmd" in _PARAM_ALIASES
```

- [ ] **Step 2: Run — expect ImportError**

```bash
cd /teamspace/studios/this_studio/dikders
pytest tests/test_coerce.py -v 2>&1 | tail -5
```

Expected: `ModuleNotFoundError: No module named 'tools.coerce'`

### Task 2: Create `tools/coerce.py`

**Files:**
- Create: `tools/coerce.py`

- [ ] **Step 1: Write the file**

Extract verbatim from `tools/parse.py`: `_PARAM_ALIASES` (dict, lines ~706–774), `_fuzzy_match_param` (~lines 777–835), `_coerce_value` (~lines 838–925), `_levenshtein` (~lines 928–946).

```python
"""
Shin Proxy — Tool parameter coercion and fuzzy name matching.

Extracted from tools/parse.py. No imports from other tools/ modules.
"""
from __future__ import annotations

import re

import msgspec.json as msgjson
import structlog

log = structlog.get_logger()

# ── Common param aliases the model tends to use wrong ──────────────────────
# Maps normalized wrong name → canonical param name.
_PARAM_ALIASES: dict[str, str] = {
    "cmd": "command",
    "bash": "command",
    "shell": "command",
    "script": "command",
    "run": "command",
    "file": "file_path",
    "filepath": "file_path",
    "filename": "file_path",
    "path": "file_path",
    "old": "old_string",
    "oldstr": "old_string",
    "oldstring": "old_string",
    "original": "old_string",
    "search": "old_string",
    "find": "old_string",
    "new": "new_string",
    "newstr": "new_string",
    "newstring": "new_string",
    "replacement": "new_string",
    "replace": "new_string",
    "body": "content",
    "data": "content",
    "contents": "content",
    "glob": "pattern",
    "match": "pattern",
    "filter": "pattern",
    "query": "pattern",
    "regex": "pattern",
    "searchpattern": "pattern",
    "searchquery": "query",
    "searchterm": "query",
    "term": "query",
    "keywords": "query",
    "link": "url",
    "uri": "url",
    "webpage": "url",
    "website": "url",
    "task": "prompt",
    "instruction": "prompt",
    "instructions": "prompt",
    "message": "prompt",
    "desc": "description",
    "title": "subject",
    "name": "subject",
    "id": "taskId",
    "taskid": "taskId",
    "status": "status",
    "files": "filePath",
    "dir": "dirPath",
}


def _levenshtein(a: str, b: str) -> int:
    """Compute Levenshtein edit distance between two strings."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        curr = [i + 1]
        for j, cb in enumerate(b):
            curr.append(min(
                prev[j + 1] + 1,
                curr[j] + 1,
                prev[j] + (ca != cb),
            ))
        prev = curr
    return prev[len(b)]


def _fuzzy_match_param(supplied: str, known_keys: set[str]) -> str | None:
    """Find the best matching known param for a supplied (possibly wrong) param name.

    Strategy order (first match wins):
    1. Exact match (already checked by caller)
    2. Alias table lookup
    3. Normalized exact match (strip - _ spaces, lowercase)
    4. Levenshtein distance <= 2 for short keys
    5. Substring containment (one contains the other)
    6. Shared prefix >= 5 chars
    """
    norm = re.sub(r"[-_\s]", "", supplied.lower())

    alias_target = _PARAM_ALIASES.get(norm)
    if alias_target and alias_target in known_keys:
        return alias_target

    norm_known = {k: re.sub(r"[-_\s]", "", k.lower()) for k in known_keys}

    for k, nk in norm_known.items():
        if norm == nk:
            return k

    if len(norm) <= 12:
        best_k: str | None = None
        best_dist = 3
        for k, nk in norm_known.items():
            if abs(len(norm) - len(nk)) > 2:
                continue
            dist = _levenshtein(norm, nk)
            if dist < best_dist:
                best_dist = dist
                best_k = k
        if best_k is not None:
            return best_k

    if len(norm) >= 5:
        for k, nk in norm_known.items():
            if norm in nk or nk in norm:
                return k

    for k, nk in norm_known.items():
        prefix_len = 0
        for a, b in zip(norm, nk):
            if a == b:
                prefix_len += 1
            else:
                break
        if prefix_len >= 5:
            return k

    return None


def _coerce_value(value: object, prop_schema: dict, key: str, repairs: list[str]) -> object:
    """Coerce a value to match the type declared in the property schema."""
    expected = prop_schema.get("type")
    if not expected or value is None:
        return value

    if expected == "boolean":
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            if value.lower() in ("true", "1", "yes"):
                repairs.append(f"coerced '{key}': string '{value}' \u2192 true")
                return True
            if value.lower() in ("false", "0", "no", ""):
                repairs.append(f"coerced '{key}': string '{value}' \u2192 false")
                return False
        if isinstance(value, (int, float)):
            repairs.append(f"coerced '{key}': number {value} \u2192 bool")
            return bool(value)

    if expected in ("number", "integer"):
        if isinstance(value, (int, float)):
            return value
        if isinstance(value, str):
            try:
                coerced = int(value) if expected == "integer" else float(value)
                repairs.append(f"coerced '{key}': string '{value}' \u2192 {expected}")
                return coerced
            except (ValueError, TypeError):
                pass

    if expected == "string":
        if isinstance(value, str):
            return value
        if isinstance(value, (int, float, bool)):
            repairs.append(f"coerced '{key}': {type(value).__name__} \u2192 string")
            return str(value)
        if isinstance(value, (dict, list)):
            repairs.append(f"coerced '{key}': {type(value).__name__} \u2192 JSON string")
            return msgjson.encode(value).decode("utf-8")

    if expected == "array":
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.startswith("["):
                try:
                    parsed = msgjson.decode(stripped.encode())
                    if isinstance(parsed, list):
                        repairs.append(f"coerced '{key}': JSON string \u2192 array")
                        return parsed
                except Exception:  # nosec B110
                    pass
            repairs.append(f"coerced '{key}': string \u2192 [string]")
            return [value]
        repairs.append(f"coerced '{key}': {type(value).__name__} \u2192 [value]")
        return [value]

    if expected == "object":
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.startswith("{"):
                try:
                    parsed = msgjson.decode(stripped.encode())
                    if isinstance(parsed, dict):
                        repairs.append(f"coerced '{key}': JSON string \u2192 object")
                        return parsed
                except Exception:  # nosec B110
                    pass

    return value
```

- [ ] **Step 2: Run tests — expect PASS**

```bash
cd /teamspace/studios/this_studio/dikders
pytest tests/test_coerce.py -v 2>&1 | tail -10
```

Expected: all 16 tests PASS

- [ ] **Step 3: Run full existing suite — must not regress**

```bash
pytest tests/ --ignore=tests/integration -q 2>&1 | tail -5
```

Expected: same count as baseline (no regressions — `coerce.py` is new, `parse.py` not yet touched)

- [ ] **Step 4: Commit**

```bash
git add tools/coerce.py tests/test_coerce.py
git commit -m "feat(tools): extract coerce.py — _PARAM_ALIASES, _levenshtein, _fuzzy_match_param, _coerce_value"
```

---

## Chunk 2: `tools/score.py`

### Task 3: Write failing tests for `tools/score.py`

**Files:**
- Create: `tests/test_score.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_score.py
from __future__ import annotations
from tools.score import score_tool_call_confidence, _find_marker_pos


def _call(name: str = "bash") -> dict:
    return {"id": "call_abc", "type": "function", "function": {"name": name, "arguments": "{}"}}


def test_find_marker_pos_present():
    text = "[assistant_tool_calls]\n{}"
    assert _find_marker_pos(text) == 0

def test_find_marker_pos_inside_fence_ignored():
    text = "```\n[assistant_tool_calls]\n{}\n```"
    assert _find_marker_pos(text) < 0

def test_find_marker_pos_absent():
    assert _find_marker_pos("no marker here") == -1


def test_confidence_high_with_marker_at_start():
    text = "[assistant_tool_calls]\n{\"tool_calls\": []}"
    score = score_tool_call_confidence(text, [_call()])
    assert score >= 0.7

def test_confidence_zero_no_calls():
    assert score_tool_call_confidence("anything", []) == 0.0

def test_confidence_low_for_example_text():
    text = "For example, you could call: [assistant_tool_calls]\n{}"
    score = score_tool_call_confidence(text, [_call()])
    # "for example" subtracts 0.2 — should be lower than high-confidence
    assert score < 0.9

def test_confidence_clamped_0_to_1():
    text = "[assistant_tool_calls]\n{\"tool_calls\": []}"
    score = score_tool_call_confidence(text, [_call()])
    assert 0.0 <= score <= 1.0

def test_confidence_low_without_marker_long_text():
    text = "a" * 2000  # long text, no marker
    score = score_tool_call_confidence(text, [_call()])
    assert score < 0.3
```

- [ ] **Step 2: Run — expect ImportError**

```bash
pytest tests/test_score.py -v 2>&1 | tail -5
```

Expected: `ModuleNotFoundError: No module named 'tools.score'`

### Task 4: Create `tools/score.py`

**Files:**
- Create: `tools/score.py`

- [ ] **Step 1: Write the file**

Extract verbatim from `tools/parse.py`: `_find_marker_pos` (~lines 37–57) and `score_tool_call_confidence` (~lines 1086–1118). These two functions are co-dependent (`score` calls `_find_marker_pos`), so they move together.

```python
"""
Shin Proxy — Tool call confidence scoring.

Extracted from tools/parse.py. No imports from other tools/ modules.
"""
from __future__ import annotations

import re

import structlog

log = structlog.get_logger()

_TOOL_CALL_MARKER_RE = re.compile(
    r"^[ \t]*\[assistant_tool_calls\]",
    re.MULTILINE,
)


def _find_marker_pos(text: str) -> int:
    """Return the character position of a real [assistant_tool_calls] marker.

    A real marker must appear at the start of a line and must NOT be inside
    a backtick code fence. Returns -1 if no such marker exists.
    """
    fence_ranges = [
        (m.start(), m.end())
        for m in re.finditer(r"```.*?```", text, flags=re.DOTALL)
    ]

    def _in_fence(pos: int) -> bool:
        return any(s <= pos < e for s, e in fence_ranges)

    for m in _TOOL_CALL_MARKER_RE.finditer(text):
        if not _in_fence(m.start()):
            return m.start()
    return -1


def score_tool_call_confidence(text: str, calls: list[dict]) -> float:
    """Score how confident we are the model intentionally made a tool call.

    Returns 0.0 (accidental) to 1.0 (definitely intentional).
    """
    if not calls:
        return 0.0

    score = 0.0
    lower = text.lower()

    real_marker_pos = _find_marker_pos(text)
    if real_marker_pos >= 0:
        score += 0.5
        if real_marker_pos <= 1:
            score += 0.2

    if "tool_calls" in lower:
        score += 0.1
    if '"name"' in text and '"arguments"' in text:
        score += 0.1

    if real_marker_pos < 0 and len(text) > 1500:
        score -= 0.3
    if "for example" in lower or "such as" in lower:
        score -= 0.2
    if "```" in text and _find_marker_pos(text) < 0:
        score -= 0.1

    return max(0.0, min(1.0, score))
```

- [ ] **Step 2: Run tests — expect PASS**

```bash
pytest tests/test_score.py -v 2>&1 | tail -10
```

Expected: all 8 tests PASS

- [ ] **Step 3: Full suite — no regressions**

```bash
pytest tests/ --ignore=tests/integration -q 2>&1 | tail -5
```

- [ ] **Step 4: Commit**

```bash
git add tools/score.py tests/test_score.py
git commit -m "feat(tools): extract score.py — score_tool_call_confidence, _find_marker_pos"
```

---

## Chunk 3: `tools/streaming.py`

### Task 5: Write failing tests for `tools/streaming.py`

**Files:**
- Create: `tests/test_streaming.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_streaming.py
from __future__ import annotations
from tools.streaming import StreamingToolCallParser


def _bash_tool() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "Bash",
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
        },
    }


def test_feed_returns_none_before_marker():
    parser = StreamingToolCallParser([_bash_tool()])
    assert parser.feed("Just some text") is None

def test_feed_returns_calls_when_json_complete():
    parser = StreamingToolCallParser([_bash_tool()])
    payload = '[assistant_tool_calls]\n{"tool_calls": [{"name": "Bash", "arguments": {"command": "ls"}}]}'
    # Feed in two chunks
    result = parser.feed(payload[:30])
    result = result or parser.feed(payload[30:])
    assert result is not None
    assert len(result) == 1
    assert result[0]["function"]["name"] == "Bash"

def test_feed_caches_result_after_complete():
    parser = StreamingToolCallParser([_bash_tool()])
    payload = '[assistant_tool_calls]\n{"tool_calls": [{"name": "Bash", "arguments": {"command": "ls"}}]}'
    for i in range(0, len(payload), 10):
        parser.feed(payload[i:i+10])
    # Calling feed again returns cached result
    result = parser.feed("extra")
    assert result is not None

def test_finalize_returns_none_on_empty():
    parser = StreamingToolCallParser([_bash_tool()])
    assert parser.finalize() is None

def test_finalize_recovers_calls_from_complete_buffer():
    parser = StreamingToolCallParser([_bash_tool()])
    payload = '[assistant_tool_calls]\n{"tool_calls": [{"name": "Bash", "arguments": {"command": "echo hi"}}]}'
    parser.feed(payload)
    result = parser.finalize()
    assert result is not None
    assert result[0]["function"]["name"] == "Bash"

def test_marker_inside_fence_not_detected():
    parser = StreamingToolCallParser([_bash_tool()])
    fenced = "```\n[assistant_tool_calls]\n{}\n```"
    result = parser.feed(fenced)
    assert result is None
```

- [ ] **Step 2: Run — expect ImportError**

```bash
pytest tests/test_streaming.py -v 2>&1 | tail -5
```

### Task 6: Create `tools/streaming.py`

**Files:**
- Create: `tools/streaming.py`

- [ ] **Step 1: Write the file**

Extract `StreamingToolCallParser` verbatim from `tools/parse.py` (~lines 1212–1315). It imports `parse_tool_calls_from_text` from `tools.parse` and `_find_marker_pos` from `tools.score`.

```python
"""
Shin Proxy — Stateful streaming tool call parser.

Extracted from tools/parse.py. Imports parse_tool_calls_from_text from
tools.parse (one-directional dependency — no cycle).
"""
from __future__ import annotations

from tools.score import _find_marker_pos


class StreamingToolCallParser:
    """Stateful incremental parser — O(n) total scan across all chunks.

    Maintains marker detection and JSON-complete detection incrementally.
    parse_tool_calls_from_text is called exactly once — when the outermost
    JSON object is complete — instead of on every chunk after marker confirmed.
    """

    _LOOKBACK = len("[assistant_tool_calls]")

    def __init__(self, tools: list[dict]) -> None:
        # Import here to avoid circular import at module load time.
        # tools.parse imports tools.score (score.py), not tools.streaming.
        # tools.streaming imports tools.parse (parse.py). One-directional.
        from tools.parse import parse_tool_calls_from_text as _ptcft
        self._parse = _ptcft
        self._tools = tools
        self.buf = ""
        self._scan_pos = 0
        self._marker_confirmed = False
        self._marker_pos: int = -1
        self._json_start: int = -1
        self._depth: int = 0
        self._in_str: bool = False
        self._esc: bool = False
        self._json_complete: bool = False
        self._last_result: list[dict] | None = None

    def feed(self, chunk: str) -> list[dict] | None:
        """Append chunk and return parsed calls when JSON is complete, else None."""
        self.buf += chunk

        if not self._marker_confirmed:
            rescan_start = max(0, self._scan_pos - self._LOOKBACK)
            relative_pos = _find_marker_pos(self.buf[rescan_start:])
            if relative_pos >= 0:
                self._marker_pos = rescan_start + relative_pos
                self._marker_confirmed = True
                newline_pos = self.buf.find('\n', self._marker_pos)
                after_marker = (
                    newline_pos + 1
                    if newline_pos >= 0
                    else self._marker_pos + len('[assistant_tool_calls]')
                )
                brace_pos = self.buf.find('{', after_marker)
                if brace_pos >= 0:
                    self._json_start = brace_pos
                    self._scan_pos = brace_pos
            else:
                self._scan_pos = max(0, len(self.buf) - self._LOOKBACK)
                return None

        if self._json_complete:
            return self._last_result

        if self._json_start < 0:
            newline_pos = self.buf.find('\n', self._marker_pos)
            after_marker = (
                newline_pos + 1
                if newline_pos >= 0
                else self._marker_pos + len('[assistant_tool_calls]')
            )
            brace_pos = self.buf.find('{', after_marker)
            if brace_pos < 0:
                return None
            self._json_start = brace_pos
            self._scan_pos = brace_pos

        scan_from = max(self._json_start, self._scan_pos)
        i = scan_from
        buf = self.buf
        buf_len = len(buf)
        while i < buf_len:
            ch = buf[i]
            if self._esc:
                self._esc = False
            elif ch == '\\' and self._in_str:
                self._esc = True
            elif ch == '"':
                self._in_str = not self._in_str
            elif not self._in_str:
                if ch == '{':
                    self._depth += 1
                elif ch == '}':
                    self._depth -= 1
                    if self._depth == 0:
                        self._json_complete = True
                        self._scan_pos = i + 1
                        self._last_result = self._parse(
                            buf[self._marker_pos:], self._tools, streaming=True
                        )
                        return self._last_result
            i += 1
        self._scan_pos = buf_len
        return None

    def finalize(self) -> list[dict] | None:
        """Non-streaming parse on the complete buffer — call once stream closes."""
        if not self.buf:
            return None
        parse_slice = self.buf[self._marker_pos:] if self._marker_pos >= 0 else self.buf
        return self._parse(parse_slice, self._tools, streaming=False)
```

- [ ] **Step 2: Run tests — expect PASS**

```bash
pytest tests/test_streaming.py -v 2>&1 | tail -10
```

- [ ] **Step 3: Full suite — no regressions**

```bash
pytest tests/ --ignore=tests/integration -q 2>&1 | tail -5
```

- [ ] **Step 4: Commit**

```bash
git add tools/streaming.py tests/test_streaming.py
git commit -m "feat(tools): extract streaming.py — StreamingToolCallParser"
```

---

## Chunk 4: Update `tools/parse.py` + `tools/__init__.py`

### Task 7: Update `parse.py` to import from new modules; remove extracted code

**Files:**
- Modify: `tools/parse.py`
- Modify: `tools/__init__.py`

- [ ] **Step 1: Add re-export imports at top of `parse.py`** (after `from __future__ import annotations` and existing imports)

```python
# ── Extracted to focused modules — re-exported here for backward compat ──
from tools.coerce import (  # noqa: F401
    _PARAM_ALIASES,
    _levenshtein,
    _fuzzy_match_param,
    _coerce_value,
)
from tools.score import (  # noqa: F401
    _find_marker_pos,
    _TOOL_CALL_MARKER_RE,
    score_tool_call_confidence,
)
from tools.streaming import StreamingToolCallParser  # noqa: F401
```

- [ ] **Step 2: Delete the extracted function bodies from `parse.py`**

Remove these blocks (now imported):
- `_TOOL_CALL_MARKER_RE` regex definition
- `_find_marker_pos` function
- `_PARAM_ALIASES` dict
- `_fuzzy_match_param` function
- `_coerce_value` function
- `_levenshtein` function
- `score_tool_call_confidence` function
- `StreamingToolCallParser` class

Also add `_TOOL_CALL_MARKER_RE` to the exports in `tools/score.py` (it is defined there; add `# noqa: F401` so linters don't complain).

- [ ] **Step 3: Update `tools/__init__.py`**

```python
"""Shin Proxy — tools package public API."""
from tools.coerce import _PARAM_ALIASES, _levenshtein, _fuzzy_match_param, _coerce_value  # noqa: F401
from tools.score import _find_marker_pos, score_tool_call_confidence  # noqa: F401
from tools.streaming import StreamingToolCallParser  # noqa: F401
from tools.parse import (  # noqa: F401
    extract_json_candidates,
    log_tool_calls,
    parse_tool_calls_from_text,
    repair_tool_call,
    validate_tool_call,
    _escape_unescaped_quotes,
    _extract_truncated_args,
    _lenient_json_loads,
    _repair_json_control_chars,
)
```

- [ ] **Step 4: Run existing parse tests — must all pass**

```bash
pytest tests/test_parse.py tests/test_parse_extended.py -v 2>&1 | tail -20
```

Expected: ALL pass. If any fail, a re-export is missing — add it before continuing.

- [ ] **Step 5: Run full suite**

```bash
pytest tests/ --ignore=tests/integration -q 2>&1 | tail -5
```

- [ ] **Step 6: Verify line count**

```bash
wc -l /teamspace/studios/this_studio/dikders/tools/parse.py
```

Expected: ≤ 1,100

- [ ] **Step 7: Commit**

```bash
git add tools/parse.py tools/__init__.py
git commit -m "refactor(tools): parse.py imports from coerce/score/streaming; all re-exports preserved"
```

---

## Chunk 5: `tools/schema.py`

### Task 8: Write failing tests

**Files:**
- Create: `tests/test_schema.py`

- [ ] **Step 1: Write tests**

```python
# tests/test_schema.py
from __future__ import annotations
from tools.schema import validate_schema


def _schema(*required, **props) -> dict:
    properties = {k: (t if isinstance(t, dict) else {"type": t}) for k, t in props.items()}
    return {"type": "object", "properties": properties, "required": list(required)}


def test_valid_all_required_present():
    ok, errs = validate_schema({"cmd": "ls"}, _schema("cmd", cmd="string"))
    assert ok and errs == []

def test_missing_required():
    ok, errs = validate_schema({}, _schema("cmd", cmd="string"))
    assert not ok and any("cmd" in e for e in errs)

def test_wrong_type_string_got_int():
    ok, errs = validate_schema({"x": 42}, _schema("x", x="string"))
    assert not ok and any("string" in e for e in errs)

def test_wrong_type_int_got_string():
    ok, _ = validate_schema({"n": "hello"}, _schema("n", n="integer"))
    assert not ok

def test_correct_type_integer():
    ok, _ = validate_schema({"n": 5}, _schema("n", n="integer"))
    assert ok

def test_enum_valid():
    ok, _ = validate_schema({"c": "red"}, _schema("c", c={"type": "string", "enum": ["red", "blue"]}))
    assert ok

def test_enum_invalid():
    ok, errs = validate_schema({"c": "green"}, _schema("c", c={"type": "string", "enum": ["red", "blue"]}))
    assert not ok and any("enum" in e for e in errs)

def test_min_length_pass():
    ok, _ = validate_schema({"s": "abc"}, _schema("s", s={"type": "string", "minLength": 3}))
    assert ok

def test_min_length_fail():
    ok, _ = validate_schema({"s": "ab"}, _schema("s", s={"type": "string", "minLength": 3}))
    assert not ok

def test_max_length_fail():
    ok, _ = validate_schema({"s": "toolong"}, _schema("s", s={"type": "string", "maxLength": 5}))
    assert not ok

def test_minimum_number():
    ok, _ = validate_schema({"n": -1}, _schema("n", n={"type": "number", "minimum": 0}))
    assert not ok

def test_maximum_number():
    ok, _ = validate_schema({"n": 11}, _schema("n", n={"type": "number", "maximum": 10}))
    assert not ok

def test_min_items():
    ok, _ = validate_schema({"arr": [1]}, _schema("arr", arr={"type": "array", "minItems": 2}))
    assert not ok

def test_max_items():
    ok, _ = validate_schema({"arr": [1, 2, 3]}, _schema("arr", arr={"type": "array", "maxItems": 2}))
    assert not ok

def test_boolean_type():
    ok, _ = validate_schema({"flag": True}, _schema("flag", flag="boolean"))
    assert ok

def test_empty_args_no_required():
    ok, _ = validate_schema({}, _schema(s="string"))
    assert ok

def test_multiple_errors():
    ok, errs = validate_schema({}, _schema("a", "b", a="string", b="integer"))
    assert not ok and len(errs) >= 2
```

- [ ] **Step 2: Run — expect ImportError**

```bash
pytest tests/test_schema.py -v 2>&1 | tail -5
```

### Task 9: Create `tools/schema.py`

- [ ] **Step 1: Write the file**

```python
"""
Shin Proxy — Full JSON Schema validation for tool call arguments.

Checks required fields, types, enum membership, string length,
number bounds, and array item count. Pure function — no side effects.
"""
from __future__ import annotations

_TYPE_CHECKS: dict[str, type | tuple[type, ...]] = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "array": list,
    "object": dict,
}


def validate_schema(
    args: dict,
    schema: dict,
    tool_name: str = "",
) -> tuple[bool, list[str]]:
    """Validate args against a JSON Schema 'parameters' object.

    Returns (is_valid, errors). errors is empty when valid.
    """
    errors: list[str] = []
    prefix = f"{tool_name}: " if tool_name else ""
    properties: dict = schema.get("properties", {})
    required: list[str] = schema.get("required", [])

    for req in required:
        if req not in args:
            errors.append(f"{prefix}missing required param '{req}'")

    for key, value in args.items():
        prop = properties.get(key)
        if prop is None:
            continue

        expected_type = prop.get("type")
        if expected_type and expected_type in _TYPE_CHECKS:
            expected_python = _TYPE_CHECKS[expected_type]
            if expected_type == "integer" and isinstance(value, bool):
                errors.append(f"{prefix}param '{key}': expected integer, got bool")
            elif expected_type == "number" and isinstance(value, bool):
                errors.append(f"{prefix}param '{key}': expected number, got bool")
            elif not isinstance(value, expected_python):
                errors.append(
                    f"{prefix}param '{key}': expected {expected_type}, got {type(value).__name__}"
                )
                continue

        enum_vals = prop.get("enum")
        if enum_vals is not None and value not in enum_vals:
            errors.append(f"{prefix}param '{key}': value {value!r} not in enum {enum_vals}")

        if expected_type == "string" and isinstance(value, str):
            min_len = prop.get("minLength")
            max_len = prop.get("maxLength")
            if min_len is not None and len(value) < min_len:
                errors.append(f"{prefix}param '{key}': length {len(value)} < minLength {min_len}")
            if max_len is not None and len(value) > max_len:
                errors.append(f"{prefix}param '{key}': length {len(value)} > maxLength {max_len}")

        if expected_type in ("number", "integer") and isinstance(value, (int, float)) and not isinstance(value, bool):
            minimum = prop.get("minimum")
            maximum = prop.get("maximum")
            if minimum is not None and value < minimum:
                errors.append(f"{prefix}param '{key}': value {value} < minimum {minimum}")
            if maximum is not None and value > maximum:
                errors.append(f"{prefix}param '{key}': value {value} > maximum {maximum}")

        if expected_type == "array" and isinstance(value, list):
            min_items = prop.get("minItems")
            max_items = prop.get("maxItems")
            if min_items is not None and len(value) < min_items:
                errors.append(f"{prefix}param '{key}': {len(value)} items < minItems {min_items}")
            if max_items is not None and len(value) > max_items:
                errors.append(f"{prefix}param '{key}': {len(value)} items > maxItems {max_items}")

    return len(errors) == 0, errors
```

- [ ] **Step 2: Run tests — expect PASS**

```bash
pytest tests/test_schema.py -v 2>&1 | tail -10
```

- [ ] **Step 3: Full suite**

```bash
pytest tests/ --ignore=tests/integration -q 2>&1 | tail -5
```

- [ ] **Step 4: Commit**

```bash
git add tools/schema.py tests/test_schema.py
git commit -m "feat(tools): add schema.py — validate_schema with full JSON Schema enforcement"
```

---

## Chunk 6: `tools/format.py`

### Task 10: Write failing tests

**Files:**
- Create: `tests/test_format.py`

- [ ] **Step 1: Write tests**

```python
# tests/test_format.py
from __future__ import annotations
import json
from tools.format import encode_tool_calls


def _call(name: str, **kwargs) -> dict:
    import msgspec.json as msgjson
    return {
        "id": "call_abc123",
        "type": "function",
        "function": {"name": name, "arguments": msgjson.encode(kwargs).decode()},
    }


def test_encode_produces_marker_line():
    out = encode_tool_calls([_call("Bash", command="ls")])
    assert out.startswith("[assistant_tool_calls]\n")

def test_encode_produces_valid_json():
    out = encode_tool_calls([_call("Bash", command="ls")])
    body = out[len("[assistant_tool_calls]\n"):]
    parsed = json.loads(body)
    assert "tool_calls" in parsed

def test_encode_single_call_structure():
    out = encode_tool_calls([_call("Bash", command="echo hi")])
    body = json.loads(out[len("[assistant_tool_calls]\n"):])
    assert len(body["tool_calls"]) == 1
    tc = body["tool_calls"][0]
    assert tc["name"] == "Bash"
    assert tc["arguments"]["command"] == "echo hi"

def test_encode_multiple_calls():
    calls = [_call("Bash", command="ls"), _call("Write", file_path="/tmp/f", content="hi")]
    out = encode_tool_calls(calls)
    body = json.loads(out[len("[assistant_tool_calls]\n"):])
    assert len(body["tool_calls"]) == 2

def test_encode_empty_list():
    out = encode_tool_calls([])
    body = json.loads(out[len("[assistant_tool_calls]\n"):])
    assert body["tool_calls"] == []

def test_encode_arguments_as_dict_not_string():
    # arguments in the wire format must be a dict (not a JSON string)
    out = encode_tool_calls([_call("Bash", command="ls")])
    body = json.loads(out[len("[assistant_tool_calls]\n"):])
    tc = body["tool_calls"][0]
    assert isinstance(tc["arguments"], dict), "arguments should be a dict in wire format"
```

- [ ] **Step 2: Run — expect ImportError**

```bash
pytest tests/test_format.py -v 2>&1 | tail -5
```

### Task 11: Create `tools/format.py`

- [ ] **Step 1: Write the file**

```python
"""
Shin Proxy — Canonical tool call wire-format encoder.

Encodes tool calls to the [assistant_tool_calls]\n{...} format used
between the proxy and Cursor's /api/chat endpoint.

This is the single authoritative implementation. converters/cursor_helpers.py
re-exports encode_tool_calls as _assistant_tool_call_text for backward compat.
"""
from __future__ import annotations

import json

import msgspec.json as msgjson


def encode_tool_calls(calls: list[dict]) -> str:
    """Encode tool calls to [assistant_tool_calls]\n{"tool_calls":[...]} wire format.

    Arguments are serialised as dicts (not JSON strings) in the wire format,
    matching the format Cursor's /api/chat endpoint emits and expects.
    """
    serialized: list[dict] = []
    for c in calls:
        fn = c.get("function") or {}
        args = fn.get("arguments", "{}")
        try:
            parsed = msgjson.decode(args.encode()) if isinstance(args, str) else args
        except Exception:
            parsed = args
        serialized.append({"name": fn.get("name"), "arguments": parsed})
    return "[assistant_tool_calls]\n" + json.dumps(
        {"tool_calls": serialized}, ensure_ascii=False
    )
```

- [ ] **Step 2: Run tests — expect PASS**

```bash
pytest tests/test_format.py -v 2>&1 | tail -10
```

- [ ] **Step 3: Full suite**

```bash
pytest tests/ --ignore=tests/integration -q 2>&1 | tail -5
```

- [ ] **Step 4: Commit**

```bash
git add tools/format.py tests/test_format.py
git commit -m "feat(tools): add format.py — encode_tool_calls canonical wire-format encoder"
```

---

## Chunk 7: `tools/inject.py` + converters backward compat

### Task 12: Write failing tests

**Files:**
- Create: `tests/test_inject.py`

- [ ] **Step 1: Write tests**

```python
# tests/test_inject.py
from __future__ import annotations
from tools.inject import build_tool_instruction, _example_value, _PARAM_EXAMPLES


def _tool(name: str, **props) -> dict:
    properties = {k: {"type": t} for k, t in props.items()}
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": f"Run {name}",
            "parameters": {"type": "object", "properties": properties},
        },
    }


def test_build_tool_instruction_returns_string():
    tools = [_tool("Bash", command="string"), _tool("Write", file_path="string", content="string")]
    result = build_tool_instruction(tools)
    assert isinstance(result, str)
    assert len(result) > 0

def test_build_tool_instruction_contains_tool_name():
    tools = [_tool("Bash", command="string")]
    result = build_tool_instruction(tools)
    assert "Bash" in result

def test_build_tool_instruction_contains_param_names():
    tools = [_tool("Bash", command="string")]
    result = build_tool_instruction(tools)
    assert "command" in result

def test_build_tool_instruction_empty_list():
    result = build_tool_instruction([])
    assert isinstance(result, str)

def test_example_value_known_key():
    # file_path is in _PARAM_EXAMPLES
    val = _example_value({"type": "string"}, key="file_path")
    assert isinstance(val, str)
    assert val  # not empty

def test_example_value_type_fallback_string():
    val = _example_value({"type": "string"}, key="unknown_param")
    assert isinstance(val, str)

def test_example_value_type_fallback_integer():
    val = _example_value({"type": "integer"}, key="unknown_param")
    assert isinstance(val, int)

def test_example_value_type_fallback_boolean():
    val = _example_value({"type": "boolean"}, key="unknown_param")
    assert isinstance(val, bool)

def test_example_value_type_fallback_array():
    val = _example_value({"type": "array"}, key="unknown_param")
    assert isinstance(val, list)

def test_param_examples_is_dict():
    assert isinstance(_PARAM_EXAMPLES, dict)
    assert "file_path" in _PARAM_EXAMPLES
    assert "command" in _PARAM_EXAMPLES

def test_backward_compat_cursor_helpers():
    """build_tool_instruction must remain importable from converters.cursor_helpers."""
    from converters.cursor_helpers import build_tool_instruction as bti
    assert callable(bti)

def test_backward_compat_to_cursor():
    """build_tool_instruction must remain importable from converters.to_cursor."""
    from converters.to_cursor import build_tool_instruction as bti
    assert callable(bti)
```

- [ ] **Step 2: Run — expect ImportError**

```bash
pytest tests/test_inject.py -v 2>&1 | tail -5
```

### Task 13: Create `tools/inject.py` (COPY — do not remove from cursor_helpers yet)

**Files:**
- Create: `tools/inject.py`

- [ ] **Step 1: Read the current `build_tool_instruction` and helpers in `converters/cursor_helpers.py`**

```bash
grep -n 'def _example_value\|_PARAM_EXAMPLES\|def build_tool_instruction\|_tool_instruction_cache' \
    /teamspace/studios/this_studio/dikders/converters/cursor_helpers.py
```

Note the exact line numbers, then read those sections before writing.

- [ ] **Step 2: Write `tools/inject.py`** with the copied logic

```python
"""
Shin Proxy — Tool instruction block builder.

Builds the tool instruction text injected into the system prompt to teach
the upstream model the [assistant_tool_calls] wire format.

Extracted from converters/cursor_helpers.py. converters/ keeps backward-compat
re-exports. tools/ has zero dependency on converters/.
"""
from __future__ import annotations

import hashlib
import json

from cachetools import LRUCache

# ── Parameter example values ─────────────────────────────────────────────────
_PARAM_EXAMPLES: dict[str, object] = {
    "file_path":        "/path/to/file.py",
    "notebook_path":    "/path/to/notebook.ipynb",
    "path":             "/path/to/dir",
    "pattern":          "**/*.py",
    "content":          "file content here",
    "new_string":       "replacement text",
    "old_string":       "text to replace",
    "command":          "echo hello",
    "url":              "https://example.com",
    "query":            "search query",
    "prompt":           "task description",
    "description":      "short description",
    "subject":          "task subject",
    "taskId":           "task-id-here",
    "text":             "text to type",
    "key":              "Enter",
    "ref":              "element-ref",
    "function":         "() => document.title",
    "code":             "async (page) => { return await page.title(); }",
    "width":            1280,
    "height":           720,
    "index":            0,
    "limit":            100,
    "offset":           0,
    "timeout":          30000,
    "type":             "png",
    "action":           "list",
}

_tool_instruction_cache: LRUCache = LRUCache(maxsize=128)


def _example_value(prop: dict, key: str = "") -> object:
    """Return a concrete example value for a tool parameter.

    Uses a name-based lookup first, then falls back to type-based defaults.
    """
    # Name-based lookup
    if key in _PARAM_EXAMPLES:
        return _PARAM_EXAMPLES[key]
    # Type-based fallback
    t = prop.get("type", "string")
    enum_vals = prop.get("enum")
    if enum_vals:
        return enum_vals[0]
    if t == "string":
        return f"<{key or 'value'}>"
    if t in ("integer", "number"):
        return 0
    if t == "boolean":
        return False
    if t == "array":
        return []
    if t == "object":
        return {}
    return f"<{key or 'value'}>"


def build_tool_instruction(tools: list[dict]) -> str:
    """Build the tool instruction block injected into the system prompt.

    Generates a JSON-formatted example showing the model exactly how to
    invoke each tool using the [assistant_tool_calls] wire format.
    Cached by a hash of the tool list to avoid repeated serialisation.
    """
    if not tools:
        return ""
    cache_key = hashlib.sha256(
        json.dumps([t.get("function", {}).get("name") for t in tools], sort_keys=True).encode()
    ).hexdigest()[:16]
    cached = _tool_instruction_cache.get(cache_key)
    if cached is not None:
        return cached

    tool_docs: list[str] = []
    for tool in tools:
        fn = tool.get("function", {})
        name = fn.get("name", "")
        description = fn.get("description", "")
        params = fn.get("parameters", {})
        properties = params.get("properties", {})

        example_args: dict = {}
        for param_name, prop in properties.items():
            example_args[param_name] = _example_value(prop, key=param_name)

        example = json.dumps(
            {"tool_calls": [{"name": name, "arguments": example_args}]},
            ensure_ascii=False,
            indent=None,
        )
        tool_doc = f"- **{name}**: {description}\n  Example: `[assistant_tool_calls]\n{example}`"
        tool_docs.append(tool_doc)

    result = (
        "When using tools, respond with this format:\n\n"
        + "```\n[assistant_tool_calls]\n"
        + '{"tool_calls":[{"name":"<tool_name>","arguments":{...}}]}\n'
        + "```\n\nAvailable tools:\n"
        + "\n".join(tool_docs)
    )
    _tool_instruction_cache[cache_key] = result
    return result
```

**Important:** Do NOT remove `_example_value`, `_PARAM_EXAMPLES`, or `build_tool_instruction` from `converters/cursor_helpers.py` yet. That happens in Task 14.

- [ ] **Step 3: Run tests — expect PASS on all except backward compat tests (those will pass too since cursor_helpers still has originals)**

```bash
pytest tests/test_inject.py -v 2>&1 | tail -15
```

- [ ] **Step 4: Full suite**

```bash
pytest tests/ --ignore=tests/integration -q 2>&1 | tail -5
```

- [ ] **Step 5: Commit**

```bash
git add tools/inject.py tests/test_inject.py
git commit -m "feat(tools): add inject.py — build_tool_instruction, _example_value, _PARAM_EXAMPLES (copy; cursor_helpers originals intact)"
```

### Task 14: Update `converters/cursor_helpers.py` and `converters/to_cursor.py`

**Files:**
- Modify: `converters/cursor_helpers.py`
- Modify: `converters/to_cursor.py`

- [ ] **Step 1: In `converters/cursor_helpers.py`, replace the original definitions with re-exports**

Find and remove the following from `cursor_helpers.py`:
- `_PARAM_EXAMPLES` dict
- `_example_value` function
- `_tool_instruction_cache` LRUCache instantiation
- `build_tool_instruction` function

Replace with imports at the top of the file (after existing imports):

```python
# build_tool_instruction and helpers moved to tools/inject.py — re-exported here
from tools.inject import (  # noqa: F401
    _PARAM_EXAMPLES,
    _example_value,
    _tool_instruction_cache,
    build_tool_instruction,
)
```

Also replace `_assistant_tool_call_text` function body with a re-export from `tools.format`:

```python
# _assistant_tool_call_text replaced by tools.format.encode_tool_calls
from tools.format import encode_tool_calls as _assistant_tool_call_text  # noqa: F401
```

- [ ] **Step 2: In `converters/to_cursor.py`, add explicit re-export**

`converters/to_cursor.py` already imports `build_tool_instruction` from `cursor_helpers` (line 22). That import chain now resolves to `tools.inject` via the shim. Verify it works:

```bash
python -c "from converters.to_cursor import build_tool_instruction; print('OK')"
```

If it prints `OK`, no further change needed. If it fails, add an explicit import to `to_cursor.py`:

```python
from tools.inject import build_tool_instruction  # noqa: F401
```

- [ ] **Step 3: Run backward compat tests**

```bash
pytest tests/test_inject.py tests/test_to_cursor.py tests/test_cursor_helpers.py -v 2>&1 | tail -15
```

- [ ] **Step 4: Full suite**

```bash
pytest tests/ --ignore=tests/integration -q 2>&1 | tail -5
```

- [ ] **Step 5: Commit**

```bash
git add converters/cursor_helpers.py converters/to_cursor.py
git commit -m "refactor(converters): cursor_helpers re-exports build_tool_instruction and _assistant_tool_call_text from tools/"
```

---

## Chunk 8: `tools/registry.py`

### Task 15: Write failing tests

**Files:**
- Create: `tests/test_registry.py`

- [ ] **Step 1: Write tests**

```python
# tests/test_registry.py
from __future__ import annotations
import pytest
from tools.registry import ToolRegistry


def _tool(name: str, **props) -> dict:
    properties = {k: {"type": t} for k, t in props.items()}
    return {
        "type": "function",
        "function": {
            "name": name,
            "parameters": {"type": "object", "properties": properties},
        },
    }


def test_canonical_name_exact():
    reg = ToolRegistry([_tool("Bash", command="string")])
    assert reg.canonical_name("Bash") == "Bash"

def test_canonical_name_fuzzy():
    reg = ToolRegistry([_tool("Bash", command="string")])
    # "bash" normalized matches "Bash"
    assert reg.canonical_name("bash") == "Bash"

def test_canonical_name_unknown():
    reg = ToolRegistry([_tool("Bash", command="string")])
    assert reg.canonical_name("unknown_xyz") is None

def test_known_params():
    reg = ToolRegistry([_tool("Bash", command="string")])
    assert reg.known_params("Bash") == {"command"}

def test_known_params_unknown_tool():
    reg = ToolRegistry([_tool("Bash", command="string")])
    assert reg.known_params("NoSuch") == set()

def test_schema_returns_params_dict():
    reg = ToolRegistry([_tool("Bash", command="string")])
    schema = reg.schema("Bash")
    assert schema is not None
    assert "properties" in schema

def test_schema_unknown_tool():
    reg = ToolRegistry([_tool("Bash", command="string")])
    assert reg.schema("NoSuch") is None

def test_backend_tools_at_construction():
    reg = ToolRegistry(
        [_tool("Bash", command="string")],
        backend_tools={"read_file": {"filePath"}},
    )
    assert reg.canonical_name("read_file") == "read_file"
    assert reg.known_params("read_file") == {"filePath"}

def test_allowed_exact_returns_dict():
    reg = ToolRegistry([_tool("Bash", command="string")])
    ae = reg.allowed_exact()
    assert isinstance(ae, dict)
    assert "bash" in ae or "Bash" in ae.values()

def test_schema_map_returns_dict():
    reg = ToolRegistry([_tool("Bash", command="string")])
    sm = reg.schema_map()
    assert isinstance(sm, dict)
    assert "Bash" in sm

def test_registry_is_immutable_after_construction():
    """Mutating the input list after construction does not affect the registry."""
    tools = [_tool("Bash", command="string")]
    reg = ToolRegistry(tools)
    tools.append(_tool("Write", file_path="string"))
    assert reg.canonical_name("Write") is None
```

- [ ] **Step 2: Run — expect ImportError**

```bash
pytest tests/test_registry.py -v 2>&1 | tail -5
```

### Task 16: Create `tools/registry.py`

- [ ] **Step 1: Write the file**

```python
"""
Shin Proxy — Request-scoped tool registry.

Built once per request from the client's tool list. Immutable after init.
Replaces per-call rebuilding of allowed_exact / schema_map in parse.py.
"""
from __future__ import annotations

import re
from copy import deepcopy

from tools.coerce import _fuzzy_match_param


def _normalize_name(name: str) -> str:
    return re.sub(r"[-_\s]", "", (name or "").lower())


_CURSOR_BACKEND_TOOLS: dict[str, set[str]] = {
    "read_file": {"filePath"},
    "read_dir": {"dirPath"},
}


class ToolRegistry:
    """Immutable request-scoped registry of canonical tool names and schemas.

    Build once per request via ToolRegistry(tools). All state is frozen
    at construction; no mutation after __init__.
    """

    def __init__(
        self,
        tools: list[dict],
        backend_tools: dict[str, set[str]] | None = None,
    ) -> None:
        # Deep-copy so mutations to the input list cannot affect this registry.
        _tools = deepcopy(tools or [])
        _extra = dict(backend_tools or _CURSOR_BACKEND_TOOLS)

        # allowed_exact: normalized_name → canonical_name
        _ae: dict[str, str] = {}
        # schema_map: canonical_name → set of valid param names
        _sm: dict[str, set[str]] = {}
        # full params schema: canonical_name → parameters dict
        _schemas: dict[str, dict] = {}

        for t in _tools:
            if not isinstance(t, dict):
                continue
            fn = t.get("function", {})
            name = fn.get("name", "")
            if not name:
                continue
            norm = _normalize_name(name)
            _ae[norm] = name
            params = fn.get("parameters", {})
            _sm[name] = set(params.get("properties", {}).keys())
            _schemas[name] = params

        for bt_name, bt_params in _extra.items():
            norm = _normalize_name(bt_name)
            _ae[norm] = bt_name
            _sm[bt_name] = bt_params
            _schemas[bt_name] = {"type": "object", "properties": {p: {} for p in bt_params}}

        # Freeze: store as private, expose via methods only
        self.__allowed_exact: dict[str, str] = _ae
        self.__schema_map: dict[str, set[str]] = _sm
        self.__schemas: dict[str, dict] = _schemas

    def canonical_name(self, raw_name: str) -> str | None:
        """Return the canonical tool name for raw_name, or None if unknown."""
        norm = _normalize_name(raw_name)
        exact = self.__allowed_exact.get(norm)
        if exact:
            return exact
        # Fuzzy fallback over canonical names
        known = set(self.__allowed_exact.values())
        return _fuzzy_match_param(raw_name, known)

    def schema(self, canonical_name: str) -> dict | None:
        """Return the 'parameters' schema dict for a canonical tool name."""
        return self.__schemas.get(canonical_name)

    def known_params(self, canonical_name: str) -> set[str]:
        """Return the set of known parameter names for a canonical tool name."""
        return self.__schema_map.get(canonical_name, set())

    def allowed_exact(self) -> dict[str, str]:
        """Return normalized_name → canonical_name mapping. Plain method."""
        return self.__allowed_exact

    def schema_map(self) -> dict[str, set[str]]:
        """Return canonical_name → param set mapping. Plain method."""
        return self.__schema_map
```

- [ ] **Step 2: Run tests — expect PASS**

```bash
pytest tests/test_registry.py -v 2>&1 | tail -15
```

- [ ] **Step 3: Full suite**

```bash
pytest tests/ --ignore=tests/integration -q 2>&1 | tail -5
```

- [ ] **Step 4: Commit**

```bash
git add tools/registry.py tests/test_registry.py
git commit -m "feat(tools): add registry.py — ToolRegistry immutable request-scoped tool lookup"
```

---

## Chunk 9: Final validation + UPDATES.md

### Task 17: Full verification

- [ ] **Step 1: Import smoke test — verify no circular imports**

```bash
cd /teamspace/studios/this_studio/dikders
python -c "
import tools.coerce
import tools.score
import tools.streaming
import tools.schema
import tools.format
import tools.inject
import tools.registry
import tools.parse
import tools
from converters.cursor_helpers import build_tool_instruction, _assistant_tool_call_text
from converters.to_cursor import build_tool_instruction as bti2
print('All imports OK')
"
```

Expected: `All imports OK`

- [ ] **Step 2: Verify parse.py line count**

```bash
wc -l /teamspace/studios/this_studio/dikders/tools/parse.py
```

Expected: ≤ 1,100

- [ ] **Step 3: Run ALL non-integration tests**

```bash
pytest tests/ --ignore=tests/integration -q 2>&1 | tail -10
```

Expected: all existing tests pass + new test files all pass. Zero failures.

- [ ] **Step 4: Check coverage on new modules**

```bash
pytest tests/test_coerce.py tests/test_score.py tests/test_streaming.py \
       tests/test_schema.py tests/test_format.py tests/test_inject.py \
       tests/test_registry.py \
       --cov=tools.coerce --cov=tools.score --cov=tools.streaming \
       --cov=tools.schema --cov=tools.format --cov=tools.inject \
       --cov=tools.registry \
       --cov-report=term-missing -q 2>&1 | tail -20
```

Expected: ≥ 80% coverage on each module.

### Task 18: Update UPDATES.md and push

- [ ] **Step 1: Update UPDATES.md**

Add a new `## Session N — tools/ Refactor (2026-03-25)` section at the bottom of `UPDATES.md` with:
- Files created: `tools/coerce.py`, `tools/score.py`, `tools/streaming.py`, `tools/schema.py`, `tools/format.py`, `tools/inject.py`, `tools/registry.py`
- Files modified: `tools/parse.py`, `tools/__init__.py`, `converters/cursor_helpers.py`, `converters/to_cursor.py`
- Test files created: `tests/test_coerce.py`, `tests/test_score.py`, `tests/test_streaming.py`, `tests/test_schema.py`, `tests/test_format.py`, `tests/test_inject.py`, `tests/test_registry.py`
- Why: split 1490-line parse.py into focused modules; add full JSON Schema validation; fix dependency direction for build_tool_instruction; add canonical wire-format encoder; add immutable request-scoped ToolRegistry
- Commit SHAs: list all commits from this session (`git log --oneline -10`)

- [ ] **Step 2: Commit UPDATES.md**

```bash
git add UPDATES.md
git commit -m "docs: update UPDATES.md for tools/ refactor session"
```

- [ ] **Step 3: Push**

```bash
git push
```

---

## Summary

| Chunk | Files | Tests | Key outcome |
|---|---|---|---|
| 1 | `tools/coerce.py` | `test_coerce.py` (16 tests) | Param aliases, fuzzy match, type coercion extracted |
| 2 | `tools/score.py` | `test_score.py` (8 tests) | Confidence scoring + marker detection extracted |
| 3 | `tools/streaming.py` | `test_streaming.py` (6 tests) | Incremental parser extracted |
| 4 | `tools/parse.py` + `__init__.py` | existing tests unchanged | parse.py ≤ 1,100 lines; all re-exports preserved |
| 5 | `tools/schema.py` | `test_schema.py` (17 tests) | Full JSON Schema enforcement added |
| 6 | `tools/format.py` | `test_format.py` (6 tests) | Canonical wire encoder added |
| 7 | `tools/inject.py` + converters shims | `test_inject.py` (12 tests) | build_tool_instruction moved; 3 import paths work |
| 8 | `tools/registry.py` | `test_registry.py` (11 tests) | Immutable request-scoped registry added |
| 9 | UPDATES.md | full suite (80%+ coverage) | Final validation and push |

**Zero new external dependencies. Zero breaking changes. All existing tests pass.**

