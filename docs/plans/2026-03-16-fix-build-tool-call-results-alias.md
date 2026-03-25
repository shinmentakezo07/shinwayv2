# Fix `_build_tool_call_results` — alias rename before strip

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Stop `_build_tool_call_results` from stripping `files` before `repair_tool_call` can rename it to `filePath`, by applying `_PARAM_ALIASES` in the bad-key loop before dropping unknown keys.

**Architecture:** The strip happens at `tools/parse.py:1067-1078` inside `_build_tool_call_results`. At this point `known_props = schema_map.get(name, set())` is available and `bad_keys` is already computed. Before dropping each bad key, attempt an alias lookup: if `_PARAM_ALIASES` maps the normalized bad key to a value that IS in `known_props`, rename it instead of dropping it. This is a 6-line change inside an already-isolated helper. No data needs to flow anywhere new, no schema needed downstream.

**Tech Stack:** Python, pytest, `tools/parse.py`, `tests/test_parse.py`

---

## Background (read before touching any code)

The existing `_PARAM_ALIASES` table (lines 600-671) maps normalized wrong names → canonical param names. It is currently only consulted by `_fuzzy_match_param`, which is called from `repair_tool_call`. But `repair_tool_call` does an early return at line 895 when `schema is None` — which is always the case for backend tools (`read_file`, `read_dir`) because they are never in `params.tools`.

The strip happens earlier, in `_build_tool_call_results` at lines 1067-1078. By the time `repair_tool_call` is called, `arguments` is already `"{}"` — the original value is gone.

Fix: add a rename pass inside `_build_tool_call_results` **before** the drop. For each bad key:
1. Normalize it (already done by `_normalize_name`)
2. Look it up in `_PARAM_ALIASES`
3. If the alias target is in `known_props`, rename the key (preserve value)
4. Otherwise, drop it (existing behavior)

This means `files` → alias lookup → `"filePath"` → `"filePath" in {"filePath"}` → rename. No drop.

---

### Task 1: Add failing regression test

**Files:**
- Modify: `tests/test_parse.py` (append after `test_read_file_files_alias_repaired`)

This test calls `parse_tool_calls_from_text` end-to-end (not `repair_tool_call` directly) to prove the full pipeline fix.

**Step 1: Append this test to `tests/test_parse.py`**

```python
def test_read_file_files_alias_end_to_end():
    """End-to-end: parse_tool_calls_from_text preserves the filePath value when
    the model sends 'files' instead of 'filePath'.

    Regression for the full pipeline bug where:
      1. _build_tool_call_results strips 'files' (not in known_props)
      2. repair_tool_call gets arguments='{}' and schema=None → early return
      3. filePath ends up missing/empty in the delivered tool call
    """
    import json
    from tools.parse import parse_tool_calls_from_text

    text = (
        '[assistant_tool_calls]\n'
        '{"tool_calls": [{"name": "read_file", "arguments": {"files": "/docs/context/rules"}}]}'
    )
    # Client tool list does NOT contain read_file — it is backend-injected
    client_tools: list[dict] = []

    result = parse_tool_calls_from_text(text, client_tools)
    assert result is not None, "read_file call was dropped"
    assert len(result) == 1
    assert result[0]["function"]["name"] == "read_file"
    args = json.loads(result[0]["function"]["arguments"])
    assert args.get("filePath") == "/docs/context/rules", (
        f"Expected filePath='/docs/context/rules', got args={args}. "
        f"The 'files' key was stripped before the alias rename ran."
    )
    assert "files" not in args


def test_read_dir_dir_alias_end_to_end():
    """End-to-end: parse_tool_calls_from_text preserves the dirPath value when
    the model sends 'dir' instead of 'dirPath'."""
    import json
    from tools.parse import parse_tool_calls_from_text

    text = (
        '[assistant_tool_calls]\n'
        '{"tool_calls": [{"name": "read_dir", "arguments": {"dir": "/docs"}}]}'
    )
    client_tools: list[dict] = []

    result = parse_tool_calls_from_text(text, client_tools)
    assert result is not None, "read_dir call was dropped"
    assert result[0]["function"]["name"] == "read_dir"
    args = json.loads(result[0]["function"]["arguments"])
    assert args.get("dirPath") == "/docs", (
        f"Expected dirPath='/docs', got args={args}"
    )
    assert "dir" not in args
```

**Step 2: Run to confirm FAIL**

```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/test_parse.py::test_read_file_files_alias_end_to_end tests/test_parse.py::test_read_dir_dir_alias_end_to_end -v
```

Expected: FAIL — `filePath` will be missing because `files` is stripped before any alias runs.

**Step 3: Commit failing tests**

```bash
cd /teamspace/studios/this_studio/wiwi && git add tests/test_parse.py && git commit -m 'test: add end-to-end failing regression for read_file files→filePath pipeline fix'
```

---

### Task 2: Fix `_build_tool_call_results` — alias rename before strip

**Files:**
- Modify: `tools/parse.py` lines 1067-1078

**The current code (lines 1067-1078):**

```python
        # Validate param names against schema — drop unknown params
        known_props = schema_map.get(name, set())
        if known_props:
            bad_keys = set(args_dict.keys()) - known_props
            if bad_keys:
                log.warning(
                    "tool_param_name_mismatch",
                    tool=name,
                    bad_keys=sorted(bad_keys),
                    expected=sorted(known_props),
                )
                args_dict = {k: v for k, v in args_dict.items() if k in known_props}
```

**Replace it with:**

```python
        # Validate param names against schema — alias-rename before dropping unknown params.
        # This handles backend-injected tools (read_file, read_dir) whose schema is known
        # here via schema_map but is never in params.tools, so repair_tool_call cannot
        # reach them. We apply _PARAM_ALIASES as a rename pass before the drop.
        known_props = schema_map.get(name, set())
        if known_props:
            bad_keys = set(args_dict.keys()) - known_props
            if bad_keys:
                # Attempt alias rename for each bad key before dropping it.
                # _PARAM_ALIASES is keyed by normalized name (lowercase, no separators).
                renamed: dict = dict(args_dict)
                for bad_key in bad_keys:
                    alias_target = _PARAM_ALIASES.get(_normalize_name(bad_key))
                    if alias_target and alias_target in known_props and bad_key in renamed:
                        renamed[alias_target] = renamed.pop(bad_key)
                args_dict = renamed
                # Recompute bad_keys after rename — some may now be valid
                still_bad = set(args_dict.keys()) - known_props
                if still_bad:
                    log.warning(
                        "tool_param_name_mismatch",
                        tool=name,
                        bad_keys=sorted(still_bad),
                        expected=sorted(known_props),
                    )
                    args_dict = {k: v for k, v in args_dict.items() if k in known_props}
```

**Step 1: Make the edit**

In `tools/parse.py`, find the block starting with `# Validate param names against schema — drop unknown params` (line ~1067) and replace it exactly as shown above.

**Step 2: Run the two new end-to-end tests — expect PASS**

```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/test_parse.py::test_read_file_files_alias_end_to_end tests/test_parse.py::test_read_dir_dir_alias_end_to_end -v
```

**Step 3: Run the full parse test suite — expect all pass**

```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/test_parse.py -v
```

Expected: all pass (the previous repair_tool_call unit tests `test_read_file_files_alias_repaired` and `test_read_dir_alias_repaired[*]` also still pass because `repair_tool_call` is not changed).

**Step 4: Run the broader unit test suite**

```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/ -m 'not integration' -v 2>&1 | tail -20
```

Expected: all pass.

**Step 5: Commit the fix**

```bash
cd /teamspace/studios/this_studio/wiwi && git add tools/parse.py && git commit -m 'fix: alias-rename bad params before stripping in _build_tool_call_results'
```

---

### Task 3: Update UPDATES.md

**Files:**
- Modify: `UPDATES.md` (append to Session 16 section already at bottom)

Find the Session 16 section added earlier. Append an addendum under it:

```markdown
#### Addendum — root fix in `_build_tool_call_results`

The alias entries added to `_PARAM_ALIASES` were unreachable for backend tools because
`repair_tool_call` exits early when `schema is None` (backend tools are never in `params.tools`).
The strip already happened in `_build_tool_call_results` before repair ran.

**Real fix:** Added an alias-rename pass inside `_build_tool_call_results` at the bad-key check
(lines ~1067-1085). For each bad key, `_PARAM_ALIASES` is consulted before dropping. If the alias
target is in `known_props`, the key is renamed instead of dropped. The `tool_param_name_mismatch`
warning is now only logged for keys that remain bad after the rename pass.

- Files changed: `tools/parse.py` (`_build_tool_call_results`), `tests/test_parse.py`
```

Then add commit SHAs for the two new commits.

**Step 1: Commit UPDATES.md**

```bash
cd /teamspace/studios/this_studio/wiwi && git add UPDATES.md && git commit -m 'docs: Session 16 addendum — root fix in _build_tool_call_results'
```

---

## Safety Notes

- The rename only fires when `alias_target in known_props` — exact same guard as `_fuzzy_match_param`. No cross-tool collision possible.
- If a bad key maps to an alias target that is ALSO a bad key (two bad keys both alias to same target), the second one wins — but this is an extreme edge case and the result is still correct (one valid arg instead of two bad ones).
- `_PARAM_ALIASES` normalization uses `_normalize_name` which is already defined in the same file.
- `tool_param_name_mismatch` warning is now only emitted for keys that are truly unresolvable — reduces false-alarm noise in logs.
- Do NOT push until instructed.
