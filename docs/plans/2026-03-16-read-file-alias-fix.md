# read_file `files` → `filePath` Alias Fix

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Stop the proxy from filling `filePath` with `[]` when the model sends `files` as the param name for `read_file`/`read_dir` backend tools.

**Architecture:** Add `files → filePath` and `dir → dirPath` to the `_PARAM_ALIASES` fast-path table in `tools/parse.py`. This is the minimal surgical fix — the alias table is applied in `repair_tool_call` Pass 1 before any fuzzy matching or fallback filling, so the bad key gets renamed to the correct key instead of being stripped and then fabricated as `[]`. No other code paths are touched.

**Tech Stack:** Python, pytest, `tools/parse.py`, `tests/test_parse.py`

---

### Task 1: Add failing regression tests

**Files:**
- Modify: `tests/test_parse.py` (append after the existing `test_cursor_backend_read_dir_not_dropped` test)

**Step 1: Write the failing tests**

Append these two tests to `tests/test_parse.py`:

```python
def test_read_file_files_alias_repaired():
    """Model sends `files` instead of `filePath` for read_file — must be repaired.

    Regression for the warning:
        tool_param_name_mismatch bad_keys=['files'] expected=['filePath']
    followed by:
        tool_call_repaired repairs=["filled missing required 'filePath' with []"]
    """
    import json
    from tools.parse import repair_tool_call

    call = {
        "id": "call_test",
        "type": "function",
        "function": {
            "name": "read_file",
            "arguments": '{"files": "/docs/context/rules"}',
        },
    }
    tools = [
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read documentation content.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "filePath": {"type": "string"},
                    },
                    "required": ["filePath"],
                },
            },
        }
    ]
    repaired, repairs = repair_tool_call(call, tools)
    args = json.loads(repaired["function"]["arguments"])
    assert args.get("filePath") == "/docs/context/rules", (
        f"Expected filePath='/docs/context/rules', got args={args}"
    )
    assert "files" not in args
    assert any("filePath" in r for r in repairs), f"No repair logged for filePath: {repairs}"


def test_read_dir_dir_alias_repaired():
    """Model sends `dir` instead of `dirPath` for read_dir — must be repaired."""
    import json
    from tools.parse import repair_tool_call

    call = {
        "id": "call_test2",
        "type": "function",
        "function": {
            "name": "read_dir",
            "arguments": '{"dir": "/docs"}',
        },
    }
    tools = [
        {
            "type": "function",
            "function": {
                "name": "read_dir",
                "description": "List MDX pages under a route path.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "dirPath": {"type": "string"},
                    },
                    "required": ["dirPath"],
                },
            },
        }
    ]
    repaired, repairs = repair_tool_call(call, tools)
    args = json.loads(repaired["function"]["arguments"])
    assert args.get("dirPath") == "/docs", (
        f"Expected dirPath='/docs', got args={args}"
    )
    assert "dir" not in args
    assert any("dirPath" in r for r in repairs), f"No repair logged for dirPath: {repairs}"
```

**Step 2: Run tests to confirm they FAIL**

```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/test_parse.py::test_read_file_files_alias_repaired tests/test_parse.py::test_read_dir_dir_alias_repaired -v
```

Expected: both FAIL — `filePath` will be `[]` or missing, not the original path string.

**Step 3: Commit the failing tests**

```bash
git add tests/test_parse.py
git commit -m "test: add failing regression for read_file files→filePath alias"
```

---

### Task 2: Add aliases to `_PARAM_ALIASES`

**Files:**
- Modify: `tools/parse.py` lines 597–663 (`_PARAM_ALIASES` dict)

**Step 1: Add entries**

In `tools/parse.py`, find the `_PARAM_ALIASES` dict. After the `# Read / Write / Edit` block (around line 608), add a new section:

```python
    # read_file / read_dir (backend documentation tools)
    # The model often sends 'files' or 'file' instead of 'filePath',
    # and 'dir' instead of 'dirPath'.
    "files": "filePath",
    "dirpath": "dirPath",
    "dir": "dirPath",
    "directory": "dirPath",
    "folder": "dirPath",
```

Note on `filePath`: `"file"` and `"filepath"` already map to `file_path` (for the client-side `Read` tool). The backend `read_file` uses camelCase `filePath`. The alias table lookup in `_fuzzy_match_param` checks the alias value against `known_keys` for the actual tool — so `"file" → "file_path"` will only apply when `file_path` is a known key, and `"files" → "filePath"` will only apply when `filePath` is a known key. They do not collide.

**Step 2: Run the tests — expect PASS**

```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/test_parse.py::test_read_file_files_alias_repaired tests/test_parse.py::test_read_dir_dir_alias_repaired -v
```

Expected: both PASS.

**Step 3: Run the full parse test suite to confirm no regressions**

```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/test_parse.py -v
```

Expected: all pass.

**Step 4: Run the broader unit test suite**

```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/ -m 'not integration' -v
```

Expected: all pass.

**Step 5: Commit the fix**

```bash
git add tools/parse.py
git commit -m "fix: add files→filePath and dir→dirPath aliases for read_file/read_dir backend tools"
```

---

### Task 3: Update UPDATES.md

**Files:**
- Modify: `UPDATES.md` (append new session section at bottom)

Add a new session entry documenting:
- Root cause: model sends `files` instead of `filePath`; `_build_tool_call_results` strips it; repair fills it with `[]`
- Fix: added `files → filePath`, `dir/dirPath/directory/folder → dirPath` to `_PARAM_ALIASES`
- Files changed: `tools/parse.py`, `tests/test_parse.py`
- Commit SHAs

**Step 1: Commit UPDATES.md**

```bash
git add UPDATES.md
git commit -m "docs: Session 16 — fix read_file files→filePath param alias"
```

---

## Safety Notes

- `_PARAM_ALIASES` is only consulted when the supplied key is NOT already in `known_keys`. If the model sends the correct `filePath`, the alias is never reached.
- The alias value is always validated against `known_keys` before being applied (see `_fuzzy_match_param` line ~700). A wrong-tool collision is impossible.
- `"file" → "file_path"` and `"files" → "filePath"` are distinct normalized keys (`file` vs `files`) — no conflict.
- Do NOT push until instructed.
