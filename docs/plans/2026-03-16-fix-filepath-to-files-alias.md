# Fix `filePath` → `files` alias when client schema uses `files` param

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Stop `repair_tool_call` from dropping `filePath` and fabricating empty `files` when the client declares `read_file` with `files` as its required param.

**Architecture:** Two surgical changes to `tools/parse.py`:
1. `schema_map.update(_CURSOR_BACKEND_TOOLS)` clobbers client-declared schemas — change to only insert backend schemas for tools NOT already in `schema_map` (so client's `read_file {files}` wins over backend's `{filePath}`).
2. Add `"filepath": "files"` to `_PARAM_ALIASES` so when `repair_tool_call` sees `filePath` as a bad key against a schema that has `files`, it renames rather than drops. The alias is guarded by `alias_target in known_keys`, so it only fires when `files` is actually a known key for that tool.

**Tech Stack:** Python, pytest, `tools/parse.py`, `tests/test_parse.py`

---

## Background

**Production scenario:**
- Client (Claude Code) sends `read_file` tool with schema `{files: string}` (their own tool definition)
- The model calls `read_file` with `{filePath: "/docs/rules"}` (backend convention from the-editor)
- In `_build_tool_call_results`, `schema_map["read_file"]` should be `{"files"}` (client schema)
- BUT `schema_map.update(_CURSOR_BACKEND_TOOLS)` at line 1216 **overwrites** it with `{"filePath"}`
- So `_build_tool_call_results` lets `filePath` through cleanly
- Then `repair_tool_call` uses `params.tools` (client schema `{files: required}`) → sees `filePath` as unknown → drops it → tries to fill `files` → UNFILLABLE string → `files` gets `[]`

**Fix 1 — schema_map priority:** Don't let backend schemas override client-declared schemas.

**Fix 2 — alias:** When `filePath` arrives at `repair_tool_call` against client schema `{files}`, `_fuzzy_match_param` needs to map it. `"filepath"` normalizes to `"filepath"`. Strategy 2 checks `_PARAM_ALIASES.get("filepath")` — currently maps to `"file_path"`, which is NOT in `{"files"}`. Need to add `"filepath": "files"`. But wait — `"filepath" → "files"` would fire for ANY tool whose schema has a `files` param. The guard `alias_target in known_keys` makes this safe — it only fires when `files` is a known key.

However adding `"filepath": "files"` to `_PARAM_ALIASES` would SHADOW the existing `"filepath": "file_path"` entry (dict keys must be unique). The alias table is a single `dict[str, str]`. We cannot have `"filepath"` map to two different targets.

**Resolution:** The alias `"filepath": "file_path"` covers the standard Read/Write/Edit tools. For `read_file` with `files`, the normalized exact match (Strategy 3) won't work (`filepath` ≠ `files`). Levenshtein: `filepath`(8) vs `files`(5) — distance is 3+ (too high). Substring: `files` in `filepath` — YES. `"files"` (5 chars) is a substring of `"filepath"` (8 chars) and len ≥ 5. Strategy 5 fires.

So Fix 2 (new alias) is NOT needed — Strategy 5 (substring) in `_fuzzy_match_param` already handles `filePath → files`. The only real fix needed is Fix 1: don't let `schema_map.update` override client schemas.

Verify with a test before implementing.

---

### Task 1: Add failing regression test

**Files:**
- Modify: `tests/test_parse.py` (append)

**Step 1: Append this test**

```python
def test_repair_filepath_when_client_schema_uses_files():
    """Client declares read_file with 'files' param; model sends 'filePath'.

    Regression for:
        tool_call_repaired repairs=["dropped unknown param 'filePath'",
                                     "filled missing required 'files' with []"]

    The full pipeline: parse_tool_calls_from_text uses schema_map which should
    respect the client's 'files' schema. repair_tool_call then renames filePath→files
    via fuzzy matching (Strategy 5 substring: 'files' in 'filepath').
    """
    import json
    from tools.parse import parse_tool_calls_from_text

    # Client sends read_file with 'files' as the param (e.g. Claude Code's own tool)
    client_tools = [
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read a file.",
                "parameters": {
                    "type": "object",
                    "properties": {"files": {"type": "string", "description": "path"}},
                    "required": ["files"],
                },
            },
        }
    ]

    # Model calls read_file with filePath (backend convention)
    text = (
        "[assistant_tool_calls]\n"
        '{"tool_calls": [{"name": "read_file", "arguments": {"filePath": "/docs/rules"}}]}'
    )

    result = parse_tool_calls_from_text(text, client_tools)
    assert result is not None, "read_file call was dropped"
    assert result[0]["function"]["name"] == "read_file"
    args = json.loads(result[0]["function"]["arguments"])
    # After fix: filePath should be renamed to files
    assert args.get("files") == "/docs/rules", (
        f"Expected files='/docs/rules', got args={args}. "
        f"filePath was dropped instead of being renamed to files."
    )
    assert "filePath" not in args
```

**Step 2: Run to confirm FAIL**

```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/test_parse.py::test_repair_filepath_when_client_schema_uses_files -v
```

Expected: FAIL — `args` will be `{}` or `{"files": []}` because `filePath` is dropped and `files` is unfillable.

**Step 3: Commit failing test**

```bash
cd /teamspace/studios/this_studio/wiwi && git add tests/test_parse.py && git commit -m 'test: add failing regression for filePath→files when client schema uses files param'
```

---

### Task 2: Fix `schema_map` — do not override client-declared schemas

**Files:**
- Modify: `tools/parse.py` line ~1216

**Current code (line 1215-1216):**
```python
    # Add schema for backend tools
    schema_map.update(_CURSOR_BACKEND_TOOLS)
```

**Replace with:**
```python
    # Add backend tool schemas only for tools NOT declared by the client.
    # Client-declared schemas take priority — if the client defines read_file
    # with 'files' param, their schema wins over the backend's 'filePath' schema.
    for _bt, _bt_props in _CURSOR_BACKEND_TOOLS.items():
        if _bt not in schema_map:
            schema_map[_bt] = _bt_props
```

With this change, `schema_map["read_file"]` will be `{"files"}` (from client schema) when the client declares it, and `{"filePath"}` only when the client does not declare `read_file` at all (pure backend-injected case).

Now `_build_tool_call_results` will see `filePath` as a bad key against `{"files"}`. The alias rename pass (added in previous fix) will try `_PARAM_ALIASES.get("filepath")` = `"file_path"`, which is NOT in `{"files"}` → alias fails. But the call then passes to `repair_tool_call`, which calls `_fuzzy_match_param("filePath", {"files"})` → Strategy 5 (substring): `"files"` (5 chars) is in `"filepath"` (8 chars) → returns `"files"`. Rename succeeds.

Wait — `_build_tool_call_results` strips bad keys and passes the stripped call to `_repair_invalid_calls`. The stripping still happens in `_build_tool_call_results`. After the schema_map fix, `filePath` becomes a bad key (since `schema_map["read_file"] = {"files"}`). The alias rename pass runs first — `_PARAM_ALIASES.get("filepath") = "file_path"`, not in `{"files"}` → alias fails → `filePath` is still bad → still stripped → `args_dict = {}`.

So after stripping, `repair_tool_call` gets `arguments='{}'`. Schema IS found (client declared `read_file`). No args to repair. `files` is required but UNFILLABLE (string). Same problem.

We need the alias rename in `_build_tool_call_results` to also handle `filePath → files` via the fuzzy strategies, not just the alias table. OR we need to add `"filepath": "files"` to `_PARAM_ALIASES`.

But `"filepath"` already maps to `"file_path"` in the alias table. We can't have both.

**Solution:** In `_build_tool_call_results`, use `_fuzzy_match_param` instead of just `_PARAM_ALIASES` for