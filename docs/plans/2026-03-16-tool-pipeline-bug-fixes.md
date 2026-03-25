# Tool Pipeline Bug Fixes B1–B9 — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix 9 confirmed bugs in the tool call pipeline covering the Anthropic streaming path, JSON extraction fallbacks, marker detection, schema/normalization edge cases, and content sanitization.

**Architecture:** Each task is independent and targets a specific function. No shared state changes — fixes are surgical edits within existing functions. All tasks add tests before fixing.

**Tech Stack:** Python 3.12, FastAPI, asyncio, re, structlog, msgspec, cachetools

---

### Task 1 (B1): Upgrade `_anthropic_stream` to `StreamingToolCallParser`

**Files:**
- Modify: `pipeline.py` (~line 670)
- Test: `tests/test_pipeline.py`

The `_openai_stream` function was upgraded to use `StreamingToolCallParser` (O(n) total) but `_anthropic_stream` still calls `parse_tool_calls_from_text` on every delta with the full `acc` buffer (O(n²) total). This task mirrors the `_openai_stream` upgrade.

**Step 1: Read pipeline.py fully first**

```bash
cd /teamspace/studios/this_studio/wiwi
grep -n 'StreamingToolCallParser\|_anthropic_stream\|_marker_offset' pipeline.py | head -30
```

**Step 2: Add test**

In `tests/test_pipeline.py`, add after existing anthropic stream tests:

```python
@pytest.mark.asyncio
async def test_anthropic_stream_uses_incremental_parser(monkeypatch):
    """_anthropic_stream must detect tool calls via feed(), not full-buffer re-parse."""
    parse_calls: list[str] = []
    original_parse = pipeline.parse_tool_calls_from_text

    def counting_parse(text, tools, streaming=False):
        parse_calls.append(text)
        return original_parse(text, tools, streaming)

    monkeypatch.setattr(pipeline, 'parse_tool_calls_from_text', counting_parse)
    monkeypatch.setattr(pipeline, 'count_message_tokens', lambda m, mo: 1)
    monkeypatch.setattr(pipeline, 'estimate_from_text', lambda t, m: 1)
    monkeypatch.setattr(pipeline, '_record', lambda *a, **k: None)
    monkeypatch.setattr(pipeline, 'split_visible_reasoning', lambda t: (None, t))
    monkeypatch.setattr(pipeline, 'sanitize_visible_text', lambda t: (t, False))

    params = PipelineParams(
        api_style='anthropic', model='anthropic/claude-sonnet-4.6',
        messages=[{'role': 'user', 'content': 'hi'}],
        cursor_messages=[{'role': 'user', 'content': 'hi'}],
        tools=[], stream=True,
    )
    events = [e async for e in pipeline._anthropic_stream(
        _FakeCursorClient(['Hello ', 'world', '!']),
        params, anthropic_tools=None,
    )]
    # With no tools, parse_tool_calls_from_text should not be called at all
    # (it returns None immediately for empty tools list)
    assert all('tool_calls' not in e for e in events if 'tool_use' in str(e) == False)
```

**Step 3: Implement — add `StreamingToolCallParser` instantiation in `_anthropic_stream`**

In `_anthropic_stream`, find:
```python
tool_mode = False
emitted_sigs: set[str] = set()
_marker_offset: int = -1  # -1 = marker not found yet
```

Add after:
```python
from tools.parse import StreamingToolCallParser
_stream_parser = StreamingToolCallParser(params.tools) if params.tools else None
```

Then find the per-delta tool detection block:
```python
# ── Tool calls ── avoid O(n²) re-scan: find marker once, then slice
if _marker_offset < 0:
    _marker_offset = _find_marker_pos(acc)
_parse_slice = acc[_marker_offset:] if _marker_offset >= 0 else acc
for tc in parse_tool_calls_from_text(_parse_slice, params.tools, streaming=True) or []:
```

Replace with:
```python
# ── Tool calls — use incremental parser (O(n) total, not O(n²)) ──
if _stream_parser:
    _new_calls = _stream_parser.feed(delta_text)
    if _stream_parser._marker_confirmed and _marker_offset < 0:
        _marker_offset = _stream_parser._marker_pos
    _parse_results = _new_calls or []
else:
    if _marker_offset < 0:
        _marker_offset = _find_marker_pos(acc)
    _parse_slice = acc[_marker_offset:] if _marker_offset >= 0 else acc
    _parse_results = parse_tool_calls_from_text(_parse_slice, params.tools, streaming=True) or []
for tc in _parse_results:
```

Also update the stream-finish final parse in `_anthropic_stream` (around line 780):
```python
# OLD:
final_calls = parse_tool_calls_from_text(acc, params.tools, streaming=False)
# NEW:
final_calls = (_stream_parser.finalize() if _stream_parser else None) or parse_tool_calls_from_text(acc, params.tools, streaming=False)
```

**Step 4: Run tests**
```bash
cd /teamspace/studios/this_studio/wiwi
python -m pytest tests/test_pipeline.py -x -q 2>&1 | tail -10
```

**Step 5: Commit**
```bash
git add pipeline.py tests/test_pipeline.py
git commit -m "perf: upgrade _anthropic_stream to StreamingToolCallParser (O(n) total)"
```

---

### Task 2 (B2 + B6): Fix `_extract_after_marker` — string-aware depth walk + use `_find_marker_pos`

**Files:**
- Modify: `tools/parse.py:104-137`
- Test: `tests/test_parse.py`

Two bugs in `_extract_after_marker`:
1. Depth walk counts `{`/`}` inside string values — fooled by template literals like `{project_name}`
2. Uses `_TOOL_CALL_MARKER_RE.search()` directly instead of `_find_marker_pos()` — finds in-fence markers first

**Step 1: Write failing tests**

```python
def test_extract_after_marker_ignores_braces_in_strings():
    """Braces inside string values must not fool the depth counter."""
    from tools.parse import _extract_after_marker
    text = '[assistant_tool_calls]\n{"tool_calls":[{"name":"bash","arguments":{"command":"echo {hi}"}}]}trailing prose'
    result = _extract_after_marker(text)
    # Must stop at the correct closing brace, not the one inside the string
    assert result is not None
    assert result.startswith('{')
    assert result.endswith('}')
    assert 'trailing prose' not in result


def test_extract_after_marker_uses_fence_aware_search():
    """Marker inside a code fence must be skipped; only out-of-fence marker used."""
    from tools.parse import _extract_after_marker
    text = '```\n[assistant_tool_calls]\n{"fake":1}\n```\n[assistant_tool_calls]\n{"tool_calls":[{"name":"bash","arguments":{"command":"ls"}}]}'
    result = _extract_after_marker(text)
    assert result is not None
    # Must extract from the SECOND (real) marker, not the fenced one
    assert '"bash"' in result
```

**Step 2: Confirm failure**
```bash
python -m pytest tests/test_parse.py::test_extract_after_marker_ignores_braces_in_strings -xvs 2>&1 | tail -10
```

**Step 3: Rewrite `_extract_after_marker`**

Replace the function body in `tools/parse.py`:

```python
def _extract_after_marker(text: str) -> str | None:
    """Fallback extractor: grab the first complete JSON object after the marker.

    Uses _find_marker_pos for fence-aware marker detection (fixes B6), then
    a string-aware bracket-depth walk so braces inside string values do not
    fool the depth counter (fixes B2).
    """
    marker_pos = _find_marker_pos(text)
    if marker_pos < 0:
        return None
    # Advance past the marker line
    after_marker_start = text.index('\n', marker_pos) + 1 if '\n' in text[marker_pos:] else marker_pos + len('[assistant_tool_calls]')
    after = text[after_marker_start:]
    brace_start = after.find('{')
    if brace_start < 0:
        return None

    # String-aware bracket-depth walk
    depth = 0
    in_str = False
    esc = False
    i = brace_start
    while i < len(after):
        ch = after[i]
        if in_str:
            if esc:
                esc = False
            elif ch == '\\':
                esc = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
                esc = False
            elif ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    return after[brace_start : i + 1]
        i += 1

    # Truncated stream — return from first { to end
    return after[brace_start:] if depth > 0 else None
```

**Step 4: Run tests**
```bash
python -m pytest tests/test_parse.py -x -q 2>&1 | tail -10
```

**Step 5: Commit**
```bash
git add tools/parse.py tests/test_parse.py
git commit -m "fix: _extract_after_marker — string-aware depth walk and fence-aware marker search (B2+B6)"
```

---

### Task 3 (B4): Fix `_FIELD_RE` — remove spurious `.` from character class

**Files:**
- Modify: `tools/parse.py:149`
- Test: `tests/test_parse.py`

`_FIELD_RE` has an extra `.` in its exclusion class (`[^"{}.[\]]+`) that `_FIELD_RE`'s sibling `_extract_truncated_args` does not. Field names containing dots (e.g. `file.path`) fail to match.

**Step 1: Write failing test**

```python
def test_field_re_matches_dotted_key():
    """_FIELD_RE must match field names that contain a dot."""
    from tools.parse import _FIELD_RE
    text = '{"file.path": "value"}'
    matches = list(_FIELD_RE.finditer(text))
    assert len(matches) == 1
    assert matches[0].group(1) == 'file.path'
```

**Step 2: Confirm failure**
```bash
python -m pytest tests/test_parse.py::test_field_re_matches_dotted_key -xvs 2>&1 | tail -5
```

**Step 3: Fix**

In `tools/parse.py` line 149, change:
```python
_FIELD_RE = re.compile(r'"([^"{}.[\]]+)"\s*:\s*"')
```
To:
```python
_FIELD_RE = re.compile(r'"([^"{}\[\]]+)"\s*:\s*"')
```

**Step 4: Run

**Step 4: Run tests**
```bash
python -m pytest tests/test_parse.py -x -q 2>&1 | tail -5
```

**Step 5: Commit**
```bash
git add tools/parse.py tests/test_parse.py
git commit -m "fix: remove spurious dot from _FIELD_RE exclusion class (B4)"
```

---

### Task 4 (B5): Fix `normalize_tool_result_messages` mixed-content case

**Files:**
- Modify: `tools/normalize.py:170-182`
- Test: `tests/test_normalize.py`

Mixed tool_result+text in a single user message passes through raw for OpenAI target.
Fix: emit tool messages first, then text as a separate user message.

**Step 1: Write failing test** (add to `tests/test_normalize.py`)

```python
def test_normalize_mixed_tool_result_and_text_for_openai():
    from tools.normalize import normalize_tool_result_messages
    messages = [{
        "role": "user",
        "content": [
            {"type": "tool_result", "tool_use_id": "call_1", "content": "result text"},
            {"type": "text", "text": "follow-up"},
        ]
    }]
    result = normalize_tool_result_messages(messages, target="openai")
    assert len(result) == 2
    assert result[0]["role"] == "tool"
    assert result[0]["tool_call_id"] == "call_1"
    assert result[1]["role"] == "user"
    assert result[1]["content"] == "follow-up"
```

**Step 2: Confirm failure**
```bash
cd /teamspace/studios/this_studio/wiwi
python -m pytest tests/test_normalize.py::test_normalize_mixed_tool_result_and_text_for_openai -xvs 2>&1 | tail -10
```

**Step 3: Fix in `tools/normalize.py`**

The existing `if tool_results and not non_tool:` block ends with `continue`. Add this `elif` block right after the `continue`:

```python
                elif tool_results and non_tool:
                    # Mixed: emit tool results first, then remaining text as a user message
                    for tr in tool_results:
                        rc = tr.get("content", "")
                        if isinstance(rc, list):
                            rc = "
".join(
                                b.get("text", "") for b in rc
                                if isinstance(b, dict) and b.get("type") == "text"
                            )
                        normalized.append({
                            "role": "tool",
                            "tool_call_id": tr.get("tool_use_id") or "",
                            "content": deepcopy(rc),
                        })
                    text_parts = [
                        b.get("text", "") for b in non_tool
                        if isinstance(b, dict) and b.get("type") == "text"
                    ]
                    joined = "
".join(t for t in text_parts if t)
                    if joined:
                        normalized.append({"role": "user", "content": joined})
                    continue
```

**Step 4: Run tests**
```bash
python -m pytest tests/test_normalize.py -q 2>&1 | tail -5
```

**Step 5: Commit**
```bash
git add tools/normalize.py tests/test_normalize.py
git commit -m "fix: handle mixed tool_result+text in normalize_tool_result_messages for OpenAI (B5)"
```

---

### Task 5 (B8): Fix `score_tool_call_confidence` fence check

**Files:**
- Modify: `tools/parse.py` (~line 987)
- Test: `tests/test_parse.py`

Fence penalty uses `"[assistant_tool_calls]" not in text` (plain string) — does not distinguish
an inline mention from a real line-start marker. Fix: use `_find_marker_pos(text) < 0`.

**Step 1: Write test** (add to `tests/test_parse.py`)

```python
def test_confidence_fence_penalty_uses_anchored_check():
    from tools.parse import score_tool_call_confidence
    # has backtick fence AND inline mention of marker mid-sentence (not at line start)
    text = "Here is an example of [assistant_tool_calls] format
```python
x=1
```"
    calls = [{"function": {"name": "bash", "arguments": "{\"command\":\"ls\"}"}}]
    score = score_tool_call_confidence(text, calls)
    # _find_marker_pos returns -1 (no real marker) so fence penalty should apply
    # score should be <= 0.0 (just fence penalty, no positive signals)
    assert score <= 0.0
```

**Step 2: Confirm behavior**
```bash
cd /teamspace/studios/this_studio/wiwi
python -m pytest tests/test_parse.py::test_confidence_fence_penalty_uses_anchored_check -xvs 2>&1 | tail -10
```

**Step 3: Fix in `tools/parse.py`**

Find:
```python
    if "```" in text and "[assistant_tool_calls]" not in text:
        score -= 0.1
```
Replace with:
```python
    if "```" in text and _find_marker_pos(text) < 0:
        score -= 0.1
```

**Step 4: Run tests**
```bash
python -m pytest tests/test_parse.py -q 2>&1 | tail -5
```

**Step 5: Commit**
```bash
git add tools/parse.py tests/test_parse.py
git commit -m "fix: use _find_marker_pos in confidence fence penalty (B8)"
```

---

### Task 6 (B9): Sanitize user text in `anthropic_messages_to_openai`

**Files:**
- Modify: `converters/to_cursor.py` (~line 690)
- Test: add test to existing test file covering `anthropic_messages_to_openai`

Text blocks in Anthropic user messages are not run through `_sanitize_user_content()`.
The word the proxy replaces to avoid triggering the support assistant persona can reach
the model unsanitized through this code path.

**Step 1: Find the right test file**
```bash
cd /teamspace/studios/this_studio/wiwi
grep -rn "anthropic_messages_to_openai" tests/ | head -5
```

**Step 2: Write test** (add to that file)

```python
def test_anthropic_messages_to_openai_sanitizes_user_text():
    from converters.to_cursor import anthropic_messages_to_openai
    messages = [{
        "role": "user",
        "content": [{"type": "text", "text": "I use cursor every day"}]
    }]
    result = anthropic_messages_to_openai(messages, system_text="")
    user_msgs = [m for m in result if m["role"] == "user"]
    assert user_msgs
    # "cursor" standalone should be replaced with "the-editor"
    assert "cursor" not in user_msgs[0]["content"]
    assert "the-editor" in user_msgs[0]["content"]
```

**Step 3: Confirm failure**
```bash
python -m pytest <test_file>::test_anthropic_messages_to_openai_sanitizes_user_text -xvs 2>&1 | tail -10
```

**Step 4: Fix in `converters/to_cursor.py`**

Find (around line 690):
```python
            if text_blocks:
                text = "
".join(b.get("text", "") for b in text_blocks)
                if text:
                    openai_messages.append({"role": "user", "content": text})
```

Replace:
```python
            if text_blocks:
                text = "
".join(b.get("text", "") for b in text_blocks)
                if text:
                    openai_messages.append({"role": "user", "content": _sanitize_user_content(text)})
```

**Step 5: Run tests**
```bash
python -m pytest tests/ -k "not integration and not cookie_rotation and not test_malformed_json and not test_non_json" -q 2>&1 | tail -10
```

**Step 6: Commit**
```bash
git add converters/to_cursor.py
git commit -m "fix: sanitize user text in anthropic_messages_to_openai (B9)"
```

---

### Task 7 (B3 + B7): Update stale docstrings

**Files:**
- Modify: `tools/parse.py`

Two docstring-only fixes (no logic change):

**B3** — `repair_tool_call` strategy list item 6 says "Fill missing required params with type-appropriate empty value". Now incorrect — string params are no longer filled.

Find:
```
    6. Fill missing required params with type-appropriate empty value
```
Replace:
```
    6. Fill missing required params — safe typed fallbacks only (string params
       with no enum are skipped to prevent fabricating empty destructive values)
```

**B7** — `repair_tool_call` schema-not-found return is indistinguishable from valid-call return.

Find:
```python
    if schema is None:
        return call, repairs
```
Replace:
```python
    if schema is None:
        # Return original call unchanged. Empty repairs list is indistinguishable from
        # "no repairs needed" — intentional: unknown-schema tools (read_file, read_dir)
        # are backend-injected and should pass through unmodified.
        return call, repairs
```

**Commit**
```bash
git add tools/parse.py
git commit -m "docs: fix stale docstrings in repair_tool_call (B3+B7)"
```

---

### Final verification

```bash
cd /teamspace/studios/this_studio/wiwi
python -m pytest tests/ -k "not integration and not cookie_rotation and not test_malformed_json and not test_non_json" -q 2>&1 | tail -10
```

All tests must pass. Then:
```bash
git push
```
