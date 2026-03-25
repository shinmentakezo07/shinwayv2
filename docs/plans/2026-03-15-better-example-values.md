# Better Tool Example Values Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace abstract `<string>` / `<boolean>` placeholder values in tool call examples with concrete typed values so the model has a clearer mental model of what arguments should look like.

**Architecture:** Single function change in `converters/to_cursor.py` — the `_example_value()` function that generates placeholder values for each parameter type. No changes to parsing, repair, pipeline, or any other module.

**Tech Stack:** Python, existing `to_cursor.py` module

---

## Background — What `_example_value` Does

In `converters/to_cursor.py:200-204`, `_example_value(prop)` is called once per required parameter to build the example call shown to the model:

```python
def _example_value(prop: dict) -> str:
    if isinstance(prop.get("enum"), list) and prop["enum"]:
        return "|".join(f'"{{e}}"' if isinstance(e, str) else str(e) for e in prop["enum"][:4])
    return f"<{prop.get('type', 'string')}>"
```

This produces examples like:
```json
{"name": "Write", "arguments": {"file_path": "<string>", "content": "<string>"}}
```

The model sees `<string>` and has to guess what format is expected. A concrete value anchors it:
```json
{"name": "Write", "arguments": {"file_path": "/path/to/file.py", "content": "file content here"}}
```

## Wiring Map

- `_example_value` is defined at `converters/to_cursor.py:200`
- Called at `converters/to_cursor.py:256` and `converters/to_cursor.py:258`
- Output feeds into `tool_examples` list → `examples_str` → the `## Tool Response Format` block in `build_tool_instruction`
- The instruction is injected as a system message in `openai_to_cursor` (line ~363) and `anthropic_to_cursor` (line ~470)
- Nothing downstream parses these example values — they are display-only hints for the model
- The cache key at line 228 uses tool names only, so no cache key change needed

## No-Touch Zones

- `tools/parse.py` — untouched
- `pipeline.py` — untouched
- `routers/` — untouched
- `cursor/` — untouched
- All tests — existing tests stay green

---

## Task 1: Write the failing test

**File:** `tests/test_example_values.py` (create)

**Step 1: Write the failing test**

```python
import sys
sys.path.insert(0, ".")
from converters.to_cursor import _example_value

def test_string_returns_concrete_path():
    prop = {"type": "string"}
    result = _example_value(prop)
    assert result != "<string>", "should return concrete value, not placeholder"
    assert isinstance(result, str)
    assert len(result) > 0

def test_boolean_returns_false_literal():
    prop = {"type": "boolean"}
    result = _example_value(prop)
    assert result is False or result == False

def test_integer_returns_zero():
    prop = {"type": "integer"}
    result = _example_value(prop)
    assert result == 0

def test_number_returns_float():
    prop = {"type": "number"}
    result = _example_value(prop)
    assert isinstance(result, (int, float))

def test_array_returns_empty_list():
    prop = {"type": "array"}
    result = _example_value(prop)
    assert result == []

def test_object_returns_empty_dict():
    prop = {"type": "object"}
    result = _example_value(prop)
    assert result == {}

def test_enum_unchanged():
    prop = {"type": "string", "enum": ["auto", "required", "none"]}
    result = _example_value(prop)
    # enum case should still show the options
    assert "auto" in result

def test_named_param_file_path():
    # When param name is known, return domain-appropriate example
    prop = {"type": "string"}
    result = _example_value(prop, key="file_path")
    assert "/" in result  # should look like a path

def test_named_param_content():
    prop = {"type": "string"}
    result = _example_value(prop, key="content")
    assert isinstance(result, str)
    assert len(result) > 0
```

**Step 2: Run test to confirm it fails**

```bash
pytest tests/test_example_values.py -v
```
Expected: FAIL — `_example_value` takes 1 arg, `key` param doesn't exist yet

---

## Task 2: Implement the new `_example_value`

**File:** `converters/to_cursor.py:200-204`

**Step 1: Read the current function**

Current (lines 200-204):
```python
def _example_value(prop: dict) -> str:
    """Return a placeholder example value for a tool parameter."""
    if isinstance(prop.get("enum"), list) and prop["enum"]:
        return "|".join(f'"{{e}}"' if isinstance(e, str) else str(e) for e in prop["enum"][:4])
    return f"<{prop.get('type', 'string')}>"
```

**Step 2: Replace with concrete-value version**

Replace the function with:

```python
# Concrete example values keyed by known parameter names.
# The model anchors on these to produce correctly-formatted arguments.
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


def _example_value(prop: dict, key: str = "") -> object:
    """Return a concrete example value for a tool parameter.

    Uses a name-based lookup first, then falls back to type-based defaults.
    Returns typed Python objects (bool, int, list, dict, str) — json.dumps
    in the caller will serialise them correctly.
    """
    # Enum: show the first real value (not a placeholder)
    if isinstance(prop.get("enum"), list) and prop["enum"]:
        return prop["enum"][0]

    # Name-based lookup for well-known params
    if key and key in _PARAM_EXAMPLES:
        return _PARAM_EXAMPLES[key]

    # Type-based fallback
    t = prop.get("type", "string")
    if t == "boolean":
        return False
    if t == "integer":
        return 0
    if t == "number":
        return 0.0
    if t == "array":
        return []
    if t == "object":
        return {}
    # string / unknown
    return "value"
```

**Step 3: Update the two call sites to pass `key=`**

At line ~256:
```python
# Before:
example_args = {k: _example_value(v) for k, v in props.items() if k in required}
if not example_args and props:
    example_args = {k: _example_value(v) for k, v in list(props.items())[:1]}

# After:
example_args = {k: _example_value(v, key=k) for k, v in props.items() if k in required}
if not example_args and props:
    example_args = {k: _example_value(v, key=k) for k, v in list(props.items())[:1]}
```

**Step 4: Run tests**

```bash
pytest tests/test_example_values.py -v
```
Expected: All 8 tests PASS

**Step 5: Run full test suite to confirm no regressions**

```bash
pytest tests/ -v --tb=short 2>&1 | tail -30
```
Expected: existing tests green

**Step 6: Commit**

```bash
git add converters/to_cursor.py tests/test_example_values.py
git commit -m "feat: concrete example values in tool call schema — improves model argument accuracy"
git push shinway main
```

---

## Verification

After commit, manually inspect the instruction output:

```bash
python - <<'EOF'
import sys; sys.path.insert(0, ".")
from converters.to_cursor import build_tool_instruction

tools = [
    {"type": "function", "function": {
        "name": "Write",
        "description": "Write a file",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string"},
                "content": {"type": "string"}
            },
            "required": ["file_path", "content"]
        }
    }},
    {"type": "function", "function": {
        "name": "Bash",
        "description": "Run a command",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "run_in_background": {"type": "boolean"}
            },
            "required": ["command"]
        }
    }},
]

instruction = build_tool_instruction(tools, "auto")
# Print just the example section
lines = instruction.split("\n")
for i, line in enumerate(lines):
    if "Tool Response Format" in line:
        print("\n".join(lines[i:i+15]))
        break
EOF
```

Expected output shows concrete values:
```
[assistant_tool_calls]
{"tool_calls":[
  {"name":"Write","arguments":{"file_path":"/path/to/file.py","content":"file content here"}},
  {"name":"Bash","arguments":{"command":"echo hello"}}
]}
```
Not:
```
{"file_path": "<string>", "content": "<string>"}
```

---

## Risk: None

- `_example_value` output is display-only — only the model reads it
- No parsing code reads these values
- Repair logic is unaffected
- Pipeline is unaffected
- Cache key unchanged
- Worst case: a slightly wrong example value — still better than `<string>`
