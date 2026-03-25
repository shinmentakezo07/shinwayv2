# Fix `filePath` → `files` special-case rename in `_build_tool_call_results`

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Stop `repair_tool_call` from dropping `filePath` and outputting `{"files": []}` when the client declares `read_file` with a `files` required param and the model sends `filePath`.

**Architecture:** Two minimal changes to `tools/parse.py`:
1. In `_build_tool_call_results`, add a special-case rename after the alias/fuzzy lookup fails: if the bad key normalizes to `filepath` or `file` and `files` is in `known_props`, rename it. This is the only viable path because `filepath` and `files` share no substring, their Levenshtein distance is 4, and `_PARAM_ALIASES` is a single-value dict so `filepath` can only map to one target.
2. `schema_map.update(_CURSOR_BACKEND_TOOLS)` is already fixed (client schemas win). The special case closes the final gap.

**Tech Stack:** Python, pytest, `tools/parse.py`, `tests/test_parse.py`

---

## Context (read before touching anything)

`_PARAM_ALIASES["filepath"] = "file_path"` — this covers standard client tools (Read, Write, Edit) whose schemas use `file_path`. It cannot also map to `files` (dict allows one value per key).

All fuzzy strategies fail between `filepath` and `files`:
- Levenshtein distance = 4 (threshold is ≤ 2)
- No substring match (`files` ≠ substring of `filepath`)
- No shared prefix ≥ 5 chars (`filep` ≠ `files` at position 4)

The rename pass in `_build_tool_call_results` already calls `_fuzzy_match_param` as a fallback when the alias target is not in `known_props`. But `_fuzzy_match_param("filePath", {"files"})` returns `None`. So `filePath` is still stripped. Then `repair_tool_call` finds the client schema, sees `files` is required/string, logs `UNFILLABLE`, and returns `{}`.

Special-case fix location: inside the bad-key rename loop in `_build_tool_call_results`, after the alias/fuzzy block, add:

```python
# Special case: model sends camelCase 'filePath' but client schema uses 'files'.
# No alias or fuzzy strategy bridges these — they share no substring and edit
# distance is 4. This targeted rename closes the gap.
if alias_target is None:
    norm_bad = _normalize_name(bad_key)
    if norm_bad in ("filepath", "file") and "files" in known_props:
        alias_target = "files"
```

This fires ONLY when `files` is a known key for the calling tool — no collision risk.

---

### Task 1: Add failing regression test

**Files:**
- Modify: `tests/test_parse.py` (append after `test_read_dir_dir_alias_end_to_end`)

**Step 1: Append this test**

```python
def test_repair_filepath_when_client_schema_uses_files():
    """Client declares read_file with 'files' param; model sends 'filePath'.

    Regression for production log:
        tool_call_repaired repairs=["dropped unknown param 'filePath'",
                                     "filled missing required 'files' with []"]

    Root cause: _PARAM_ALIASES['filepath'] = 'file_path' (not 'files'),
    no fuzzy strategy bridges 'filepath' → 'files' (distance=4, no substring).
    Fix: targeted special-case in _build_tool_call_results rename pass.
    """
    import json
    from tools.parse import parse_tool_calls_from_text

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

    text = (
        "[assistant_tool_calls]\n"
        '{"tool_calls": [{"name": "read_file", "arguments": {"filePath": "/docs/rules"}}]}'
    )

    result = parse_tool_calls_from_text(text, client_tools)
    assert result is not None, "read_file call was dropped"
    assert result[0]["function"]["name"] == "read_file"
    args = json.loads(result[0]["function"]["arguments"])
    assert args.get("files") == "/docs/rules", (
        f"Expected files='/docs/rules', got args={args}. "
        "filePath was not renamed to files."
    )
    assert "filePath" not in args
```

**Step 2: Run to confirm FAIL**

```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/test_parse.py::test_repair_filepath_when_client_schema_uses_files -v
```

Expected: FAIL — args will be `{}` (filePath stripped, files unfillable).

**Step 3: Commit failing test**

```bash
cd /teamspace/studios/this_studio/wiwi && git add tests/test_parse.py && git commit -m 'test: add failing regression for filePath→files when client schema uses files param'
```

---

### Task 2: Add special-case rename in `_build_tool_call_results`

**Files:**
- Modify: `tools/parse.py` (~line 1077)

**Current code (the bad-key loop, lines ~1076-1094):**

```python
                for bad_key in bad_keys:
                    # Try alias table first, then full fuzzy matching as fallback.
                    alias_target = _PARAM_ALIASES.get(_normalize_name(bad_key))
                    if alias_target and alias_target not in known_props:
                        # Alias points to a param not in this tool's schema — try fuzzy instead.
                        alias_target = _fuzzy_match_param(bad_key, known_props)
                    elif not alias_target:
                        alias_target = _fuzzy_match_param(bad_key, known_props)
                    if alias_target and alias_target in known_props and bad_key in renamed and alias_target not in renamed:
                        renamed[alias_target] = renamed.pop(bad_key)
                    elif alias_target and alias_target in known_props and bad_key in renamed and alias_target in renamed:
                        # Both the canonical key and a bad alias are present — canonical value wins.
                        log.warning(
                            "tool_param_alias_collision",
                            tool=name,
                            bad_key=bad_key,
                            alias_target=alias_target,
                        )
                        renamed.pop(bad_key)
```

**Replace with:**

```python
                for bad_key in bad_keys:
                    # Try alias table first, then full fuzzy matching as fallback.
                    alias_target = _PARAM_ALIASES.get(_normalize_name(bad_key))
                    if alias_target and alias_target not in known_props:
                        # Alias points to a param not in this tool's schema — try fuzzy instead.
                        alias_target = _fuzzy_match_param(bad_key, known_props)
                    elif not alias_target:
                        alias_target = _fuzzy_match_param(bad_key, known_props)
                    # Special case: model sends camelCase 'filePath' but client schema uses 'files'.
                    # No alias or fuzzy strategy bridges these — Levenshtein distance is 4 and
                    # they share no substring. This targeted rename closes the gap.
                    if alias_target is None:
                        norm_bad = _normalize_name(bad_key)
                        if norm_bad in ("filepath", "file") and "files" in known_props:
                            alias_target = "files"
                    if alias_target and alias_target in known_props and bad_key in renamed and alias_target not in renamed:
                        renamed[alias_target] = renamed.pop(bad_key)
                    elif alias_target and alias_target in known_props and bad_key in renamed and alias_target in renamed:
                        # Both the canonical key and a bad alias are present — canonical value wins.
                        log.warning(
                            "tool_param_alias_collision",
                            tool=name,
                            bad_key=bad_key,
                            alias_target=alias_target,
                        )
                        renamed.pop(bad_key)
```

**Step 1: Apply the edit** using the Edit tool — replace the `for bad_key in bad_keys:` block exactly as shown.

**Step 2: Run the new regression test — expect PASS**

```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/test_parse.py::test_repair_filepath_when_client_schema_uses_files -v
```

**Step 3: Run the full parse test suite — expect all pass**

```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/test_parse.py -v
```

**Step 4: Run the full unit suite**

```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/ -m 'not integration' 2>&1 | tail -5
```

**Step 5: Commit**

```bash
cd /teamspace/studios/this_studio/wiwi && git add tools/parse.py && git commit -m 'fix: rename filePath→files when client schema uses files param (special-case in _build_tool_call_results)'
```

---

### Task 3: Update UPDATES.md

Append to the Session 16 addendum already at the bottom of `UPDATES.md`:

```markdown
#### Addendum 2 — filePath→files special-case rename

Production log showed `repairs=["dropped 'filePath'", "filled missing required 'files' with []"]`.
The client (Claude Code) declares `read_file` with `files` as required param; the model sends
`filePath` (backend convention). `_PARAM_ALIASES["filepath"]` maps to `file_path` (not `files`),
and no fuzzy strategy bridges them (Levenshtein=4, no substring).

Fix: added special-case check in `_build_tool_call_results` bad-key rename loop — when alias and
fuzzy both return None, if the bad key normalizes to `filepath`/`file` and `files` is in
`known_props`, rename to `files`. Guarded by `known_props` so it cannot fire for any tool
that does not have a `files` param.

- File changed: `tools/parse.py` (`_build_tool_call_results`), `tests/test_parse.py`
```

Then add commit SHAs. Commit UPDATES.md:

```bash
cd /teamspace/studios/this_studio/wiwi && git add UPDATES.md && git commit -m 'docs: Session 16 addendum 2 — filePath→files special-case rename'
```

---

## Safety notes

- `if alias_target is None` guard means the special case only runs when all other strategies have already failed. It cannot override a valid alias or fuzzy match.
- `"files" in known_props` guard means it only fires for tools whose schema actually has a `files` param. No collateral damage to Bash, Edit, Write, Glob, etc.
- Do NOT push until instructed.
