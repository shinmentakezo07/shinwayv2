# Converters Audit — Batch 2 Bug Fixes Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 8 remaining bugs found in the converters audit: unclosed thinking tag leak, sanitize_visible_text skips tag stripping, litellm missing-id gap, assistant content+tool_calls drop, tool pass-through content nulled, prior message tool_use collapse, extract_function_tools whitelist, and _prior_output_to_messages dangling tool_call.

**Architecture:** Surgical edits only across `converters/from_cursor.py`, `converters/to_cursor.py`, and `converters/to_responses.py`. No new files. TDD throughout — test first for every fix. Grouped into 3 chunks by file.

**Tech Stack:** Python 3.11+, pytest, structlog

---

## Chunk 1: `converters/from_cursor.py` — 3 bugs

---

### Task 1: BUG — Unclosed `<thinking>` tag leaks raw markup into visible output

**Files:**
- Modify: `converters/from_cursor.py:307-334` — `split_visible_reasoning`
- Test: `tests/test_from_cursor.py`

**Root cause:** When the upstream model emits `<thinking>` without a closing tag (truncated stream or suppression retry mid-block), `re.findall(r"<thinking>([\s\S]*?)</thinking>", t)` returns empty. The function takes the `if not all_thinking:` branch and returns `(None, final)` where `final` still contains the unclosed `<thinking>` tag in the raw text. This tag is then visible to the client.

**Fix:** After computing `final` in the `if not all_thinking:` branch, strip any unclosed `<thinking>` opening tag and everything after it before returning.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_from_cursor.py`:

```python
def test_split_visible_reasoning_strips_unclosed_thinking_tag():
    """Unclosed <thinking> tag must not leak into visible output."""
    from converters.from_cursor import split_visible_reasoning
    thinking, final = split_visible_reasoning("Let me think. <thinking>partial reasoning")
    assert "<thinking>" not in final, f"Unclosed thinking tag leaked into output: {final!r}"
    assert thinking is None  # no complete thinking block


def test_split_visible_reasoning_preserves_text_before_unclosed_tag():
    """Text before unclosed <thinking> tag must be preserved in visible output."""
    from converters.from_cursor import split_visible_reasoning
    thinking, final = split_visible_reasoning("Here is my answer. <thinking>oops truncated")
    assert "Here is my answer." in final
    assert "<thinking>" not in final
```

- [ ] **Step 2: Run to confirm FAIL**

```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/test_from_cursor.py::test_split_visible_reasoning_strips_unclosed_thinking_tag tests/test_from_cursor.py::test_split_visible_reasoning_preserves_text_before_unclosed_tag -v
```

Expected: FAIL — `<thinking>` leaks through.

- [ ] **Step 3: Fix `split_visible_reasoning` in `converters/from_cursor.py`**

In the `if not all_thinking:` branch (after `final = re.sub(...)`.strip()`), add:

```python
    if not all_thinking:
        # F1: still strip any stray <final> tags even with no <thinking>
        final = re.sub(r"<final>([\s\S]*?)</final>", r"\1", t, flags=re.IGNORECASE).strip()
        # Strip unclosed <thinking> opening tag and everything after it
        # This handles truncated streams where </thinking> never arrived
        final = re.sub(r"<thinking>[\s\S]*$", "", final, flags=re.IGNORECASE).strip()
        return None, final
```

- [ ] **Step 4: Run to confirm PASS**

```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/test_from_cursor.py -v
```

- [ ] **Step 5: Commit**

```bash
git add converters/from_cursor.py tests/test_from_cursor.py
git commit -m "fix(converters): strip unclosed thinking tag from visible output on truncated streams"
```

---

### Task 2: BUG — `sanitize_visible_text` returns early when `parsed_tool_calls` is truthy, skipping `<thinking>` tag stripping

**Files:**
- Modify: `converters/from_cursor.py:375-402` — `sanitize_visible_text`
- Test: `tests/test_from_cursor.py`

**Root cause:** Line 383: `if parsed_tool_calls: return text or "", False` exits immediately when tool calls are present. If the raw text also contains `<thinking>...</thinking>` blocks (which the model emits before calling a tool), those blocks are returned verbatim to the client.

**Fix:** Apply `split_visible_reasoning` before the early return, extract and discard the thinking portion, return only the final text.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_from_cursor.py`:

```python
def test_sanitize_visible_text_strips_thinking_even_with_tool_calls():
    """<thinking> tags must be stripped even when parsed_tool_calls is truthy."""
    from converters.from_cursor import sanitize_visible_text
    tool_calls = [{"id": "c1", "function": {"name": "run", "arguments": "{}"}}]
    text = "<thinking>I should call run</thinking>Calling run now."
    result, suppressed = sanitize_visible_text(text, parsed_tool_calls=tool_calls)
    assert "<thinking>" not in result, f"thinking tag leaked: {result!r}"
    assert "I should call run" not in result, f"thinking content leaked: {result!r}"
    assert "Calling run now." in result
    assert not suppressed
```

- [ ] **Step 2: Run to confirm FAIL**

```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/test_from_cursor.py::test_sanitize_visible_text_strips_thinking_even_with_tool_calls -v
```

Expected: FAIL — thinking tag is returned verbatim.

- [ ] **Step 3: Fix `sanitize_visible_text` in `converters/from_cursor.py`**

Replace lines 383-384:
```python
    if parsed_tool_calls:
        return text or "", False
```

With:
```python
    if parsed_tool_calls:
        # Strip any thinking blocks before returning — model may emit reasoning
        # before a tool call, and it must not leak to the client.
        _, visible = split_visible_reasoning(text or "")
        return visible, False
```

- [ ] **Step 4: Run to confirm PASS**

```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/test_from_cursor.py -v
```

- [ ] **Step 5: Commit**

```bash
git add converters/from_cursor.py tests/test_from_cursor.py
git commit -m "fix(converters): strip thinking tags in sanitize_visible_text even when tool calls present"
```

---

### Task 3: BUG — litellm converter path does not synthesize missing `id` before passing tool calls

**Files:**
- Modify: `converters/from_cursor.py:275-302` — `convert_tool_calls_to_anthropic`
- Test: `tests/test_from_cursor.py`

**Root cause:** `_manual_convert_tool_calls_to_anthropic` synthesizes a fallback `id` when a tool call has none. But when litellm's converter is present and succeeds, it receives the tool_calls list before any id synthesis — so a tool_call with `id: None` or missing `id` is passed to litellm, which may produce a `tool_use` block with `id: None`. This is an invalid Anthropic block.

**Fix:** Apply `id` synthesis to tool calls BEFORE branching to litellm vs. manual. This is a pre-processing step, not specific to either path.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_from_cursor.py`:

```python
def test_convert_tool_calls_synthesizes_id_before_litellm():
    """Tool calls with missing id must have id synthesized before litellm sees them."""
    from unittest.mock import patch
    import converters.from_cursor as fc_mod

    received_ids = []

    def capturing_converter(tcs):
        for tc in tcs:
            received_ids.append(tc.get("id"))
        return []  # trigger manual fallback

    fake_utils = type("U", (), {"convert_to_anthropic_tool_use": staticmethod(capturing_converter)})()
    fake_litellm = type("L", (), {"utils": fake_utils})()

    with patch.object(fc_mod, "litellm", fake_litellm):
        fc_mod.convert_tool_calls_to_anthropic(
            [{"function": {"name": "run", "arguments": "{}"}}]  # no "id" key
        )

    assert received_ids, "litellm was not called"
    assert received_ids[0] is not None, "id must be synthesized before litellm sees the tool call"
    assert isinstance(received_ids[0], str) and received_ids[0].startswith("call_")
```

- [ ] **Step 2: Run to confirm FAIL**

```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/test_from_cursor.py::test_convert_tool_calls_synthesizes_id_before_litellm -v
```

Expected: FAIL — litellm receives `id: None`.

- [ ] **Step 3: Fix `convert_tool_calls_to_anthropic` in `converters/from_cursor.py`**

Add id synthesis as a pre-processing step at the top of the function, before the litellm/manual branch:

```python
def convert_tool_calls_to_anthropic(tool_calls: list[dict]) -> list[dict]:
    """Convert OpenAI-style tool_calls to Anthropic tool_use blocks.

    litellm's converter expects arguments as a JSON string (OpenAI wire format).
    Argument parsing to dict is deferred to the manual fallback path only.
    id synthesis is applied before either path so both receive valid IDs.
    """
    tool_calls = copy.deepcopy(tool_calls or [])

    # Synthesize missing ids before any converter sees the list.
    # A missing id is a pipeline invariant violation; log and patch.
    for tc in tool_calls:
        if not tc.get("id"):
            log.warning("tool_call_missing_id_in_converter", name=(tc.get("function") or {}).get("name"))
            tc["id"] = f"call_{uuid.uuid4().hex[:24]}"

    converter = getattr(getattr(litellm, "utils", None), "convert_to_anthropic_tool_use", None)
    if converter is None:
        # No litellm — parse arguments inline for manual converter
        for tc in tool_calls:
            fn = tc.get("function")
            if isinstance(fn, dict):
                fn["arguments"] = _parse_tool_call_arguments(fn.get("arguments", {}))
        return _manual_convert_tool_calls_to_anthropic(tool_calls)

    try:
        return converter(tool_calls)
    except Exception as exc:
        log.warning("litellm_anthropic_tool_use_conversion_failed", error=str(exc))
        for tc in tool_calls:
            fn = tc.get("function")
            if isinstance(fn, dict):
                fn["arguments"] = _parse_tool_call_arguments(fn.get("arguments", {}))
        return _manual_convert_tool_calls_to_anthropic(tool_calls)
```

- [ ] **Step 4: Run to confirm PASS**

```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/test_from_cursor.py -v
```

- [ ] **Step 5: Commit**

```bash
git add converters/from_cursor.py tests/test_from_cursor.py
git commit -m "fix(converters): synthesize missing tool_call id before litellm converter"
```

---

## Chunk 2: `converters/to_cursor.py` — 3 bugs

---

### Task 4: BUG — `openai_to_cursor` drops `content` when assistant message has both `content` and `tool_calls`

**Files:**
- Modify: `converters/to_cursor.py:488-497` — `openai_to_cursor` message loop
- Test: `tests/test_to_cursor.py`

**Root cause:** Lines 488-494: when `role == "assistant"` and `msg.get("tool_calls")` is non-empty, the code emits only `_assistant_tool_call_text(msg["tool_calls"])` and never checks `msg.get("content")`. The OpenAI spec allows assistant messages to have both a text `content` and `tool_calls` simultaneously. The content (often model reasoning) is silently discarded.

**Fix:** When an assistant message has both `content` and `tool_calls`, emit a separate text message for the content before the tool call message.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_to_cursor.py`:

```python
def test_openai_to_cursor_assistant_content_preserved_alongside_tool_calls():
    """Assistant message with both content and tool_calls must emit both."""
    msgs = openai_to_cursor(
        messages=[
            {
                "role": "assistant",
                "content": "I will call the tool now.",
                "tool_calls": [{
                    "id": "call_x",
                    "type": "function",
                    "function": {"name": "run", "arguments": "{}"},
                }],
            }
        ],
        model="cursor-small",
    )
    # Find all assistant messages
    assistant_msgs = [m for m in msgs if m["role"] == "assistant"]
    texts = [m["parts"][0]["text"] for m in assistant_msgs]
    # One message must contain the prose content
    assert any("I will call the tool now." in t for t in texts), (
        f"assistant content was dropped. Got texts: {texts}"
    )
    # One message must contain the tool call marker
    assert any("[assistant_tool_calls]" in t for t in texts), (
        f"tool call message missing. Got texts: {texts}"
    )
```

- [ ] **Step 2: Run to confirm FAIL**

```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/test_to_cursor.py::test_openai_to_cursor_assistant_content_preserved_alongside_tool_calls -v
```

Expected: FAIL — content not found in texts.

- [ ] **Step 3: Fix `openai_to_cursor` in `converters/to_cursor.py`**

Replace lines 488-494:
```python
        elif (
            role == "assistant"
            and isinstance(msg.get("tool_calls"), list)
            and msg.get("tool_calls")
        ):
            text = _assistant_tool_call_text(msg["tool_calls"])
            cursor_messages.append(_msg("assistant", text))
```

With:
```python
        elif (
            role == "assistant"
            and isinstance(msg.get("tool_calls"), list)
            and msg.get("tool_calls")
        ):
            # Emit prose content first if present — model may reason before calling a tool
            assistant_content = _extract_text(msg.get("content") or "")
            if assistant_content:
                cursor_messages.append(_msg("assistant", _sanitize_user_content(assistant_content)))
            text = _assistant_tool_call_text(msg["tool_calls"])
            cursor_messages.append(_msg("assistant", text))
```

- [ ] **Step 4: Run to confirm PASS**

```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/test_to_cursor.py -v
```

- [ ] **Step 5: Commit**

```bash
git add converters/to_cursor.py tests/test_to_cursor.py
git commit -m "fix(converters): preserve assistant content alongside tool_calls in openai_to_cursor"
```

---

### Task 5: BUG — `anthropic_messages_to_openai` nulls list content on `role == "tool"` pass-through

**Files:**
- Modify: `converters/to_cursor.py:747-753` — `anthropic_messages_to_openai` tool pass-through
- Test: `tests/test_to_cursor.py`

**Root cause:** Lines 748-752: `"content": content if isinstance(content, str) else ""`. A `tool` role message with list content (valid in proxied pipelines) silently becomes an empty string.

**Fix:** Apply `_extract_text(content)` when content is not a string.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_to_cursor.py`:

```python
def test_anthropic_messages_to_openai_tool_role_list_content_extracted():
    """role:tool message with list content must have text extracted, not nulled."""
    from converters.to_cursor import anthropic_messages_to_openai
    msgs = anthropic_messages_to_openai(
        messages=[
            {
                "role": "tool",
                "tool_call_id": "call_abc",
                "content": [{"type": "text", "text": "result text"}],
            }
        ],
        system_text="",
    )
    tool_msg = next((m for m in msgs if m["role"] == "tool"), None)
    assert tool_msg is not None
    assert tool_msg["content"] == "result text", (
        f"Expected 'result text', got: {tool_msg['content']!r}"
    )
```

- [ ] **Step 2: Run to confirm FAIL**

```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/test_to_cursor.py::test_anthropic_messages_to_openai_tool_role_list_content_extracted -v
```

Expected: FAIL — content is `""`.

- [ ] **Step 3: Fix `anthropic_messages_to_openai` in `converters/to_cursor.py`**

Replace lines 748-752:
```python
        if role == "tool":
            openai_messages.append({
                "role": "tool",
                "tool_call_id": m.get("tool_call_id", ""),
                "content": content if isinstance(content, str) else "",
            })
            continue
```

With:
```python
        if role == "tool":
            openai_messages.append({
                "role": "tool",
                "tool_call_id": m.get("tool_call_id", ""),
                "content": content if isinstance(content, str) else _extract_text(content),
            })
            continue
```

- [ ] **Step 4: Run to confirm PASS**

```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/test_to_cursor.py -v
```

- [ ] **Step 5: Commit**

```bash
git add converters/to_cursor.py tests/test_to_cursor.py
git commit -m "fix(converters): extract text from list content in anthropic_messages_to_openai tool pass-through"
```

---

### Task 6: BUG — `_extract_text` drops `image_url`/`image_file` blocks with no warning

**Files:**
- Modify: `converters/to_cursor.py:70-87` — `_extract_text`
- Test: `tests/test_to_cursor.py`

**Root cause:** `_extract_text` silently ignores any block whose type is not `"text"` or whose `content` key is not a string. No warning is emitted. Callers have no visibility into dropped content.

**Fix:** Log a WARNING when a non-text block type is encountered in a list, so dropped vision/file content is observable in production logs.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_to_cursor.py`:

```python
def test_extract_text_logs_warning_for_image_url_block(caplog):
    """image_url blocks in content list must emit a warning — they are silently dropped."""
    import logging
    from converters.to_cursor import _extract_text
    with caplog.at_level(logging.WARNING):
        result = _extract_text([{"type": "image_url", "image_url": {"url": "https://example.com/img.png"}}])
    assert result == ""
    assert any("image_url" in r.message or "dropped" in r.message.lower() for r in caplog.records), (
        f"Expected warning for dropped image_url block, got: {[r.message for r in caplog.records]}"
    )
```

- [ ] **Step 2: Run to confirm FAIL**

```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/test_to_cursor.py::test_extract_text_logs_warning_for_image_url_block -v
```

Expected: FAIL — no warning emitted.

- [ ] **Step 3: Fix `_extract_text` in `converters/to_cursor.py`**

Replace the `if isinstance(content, list):` branch in `_extract_text` (lines 74-84):

```python
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, dict):
                if part.get("type") == "text" and isinstance(part.get("text"), str):
                    parts.append(part["text"])
                elif isinstance(part.get("content"), str):
                    parts.append(part["content"])
                else:
                    # Non-text block (image_url, image_file, document, etc.) — log and skip.
                    # These cannot be forwarded to the-editor as text.
                    btype = part.get("type", "unknown")
                    if btype not in ("text", None):
                        import structlog as _sl
                        _sl.get_logger().warning(
                            "extract_text_dropped_non_text_block",
                            block_type=btype,
                        )
            elif isinstance(part, str):
                parts.append(part)
        return "".join(parts)
```

Note: `structlog` is already imported at the top of `to_cursor.py` — check the imports first. If `log` is already defined, use `log.warning(...)` instead of importing structlog inline.

- [ ] **Step 4: Run to confirm PASS**

```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/test_to_cursor.py -v
```

- [ ] **Step 5: Commit**

```bash
git add converters/to_cursor.py tests/test_to_cursor.py
git commit -m "fix(converters): log warning when non-text blocks are dropped in _extract_text"
```

---

## Chunk 3: `converters/to_responses.py` — 2 bugs

---

### Task 7: BUG — `_prior_output_to_messages` collapses `message` items with `tool_use` content to empty string

**Files:**
- Modify: `converters/to_responses.py:41-45` — `_prior_output_to_messages` message handler
- Test: `tests/test_responses_converter.py`

**Root cause:** The `t == "message"` branch calls `_output_text_from_content(content)` which only joins `output_text`/`text`/`input_text` blocks. An assistant message from a prior Responses API turn that contained `tool_use` blocks has those blocks silently reduced to an empty string. The message is emitted as `{"role": "assistant", "content": ""}`, erasing the tool call history.

**Fix:** Detect `tool_use` blocks in the content and reconstruct them as `tool_calls` in the OpenAI format, paralleling the `function_call` handler.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_responses_converter.py`:

```python
def test_prior_message_with_tool_use_content_reconstructed_as_tool_calls():
    """Prior assistant message with tool_use content blocks must produce tool_calls, not empty content."""
    prior_output = [
        {
            "type": "message",
            "role": "assistant",
            "content": [
                {"type": "output_text", "text": "Let me run the tool."},
                {"type": "tool_use", "id": "toolu_prior1", "name": "calc", "input": {"x": 2}},
            ],
        },
    ]
    msgs = input_to_messages("continue", prior_output=prior_output)
    assistant_msg = next((m for m in msgs if m.get("role") == "assistant" and m.get("tool_calls")), None)
    assert assistant_msg is not None, (
        f"Prior message with tool_use content must produce tool_calls message. Got: {msgs}"
    )
    assert assistant_msg["tool_calls"][0]["function"]["name"] == "calc"
    assert assistant_msg["tool_calls"][0]["id"] == "toolu_prior1"
```

- [ ] **Step 2: Run to confirm FAIL**

```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/test_responses_converter.py::test_prior_message_with_tool_use_content_reconstructed_as_tool_calls -v
```

Expected: FAIL — no `tool_calls` message found.

- [ ] **Step 3: Fix `_prior_output_to_messages` in `converters/to_responses.py`**

Replace the `t == "message"` handler (lines 41-45):
```python
        if t == "message":
            role = item.get("role", "assistant")
            content = item.get("content", [])
            text = _output_text_from_content(content)
            msgs.append({"role": role, "content": text})
```

With:
```python
        if t == "message":
            role = item.get("role", "assistant")
            content = item.get("content", [])
            # Check for tool_use blocks — reconstruct as tool_calls instead of dropping them
            if isinstance(content, list):
                tool_use_blocks = [b for b in content if isinstance(b, dict) and b.get("type") == "tool_use"]
                if tool_use_blocks:
                    # Emit prose text first if present
                    text = _output_text_from_content(content)
                    if text:
                        msgs.append({"role": role, "content": text})
                    # Emit tool_calls message for the tool_use blocks
                    msgs.append({
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": b.get("id", f"call_{uuid.uuid4().hex[:8]}"),
                                "type": "function",
                                "function": {
                                    "name": b.get("name", ""),
                                    "arguments": json.dumps(b.get("input", {})),
                                },
                            }
                            for b in tool_use_blocks
                        ],
                    })
                    continue
            text = _output_text_from_content(content)
            msgs.append({"role": role, "content": text})
```

Also add `import json` at the top of `to_responses.py` if not already present (check first).

- [ ] **Step 4: Run to confirm PASS**

```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/test_responses_converter.py -v
```

- [ ] **Step 5: Commit**

```bash
git add converters/to_responses.py tests/test_responses_converter.py
git commit -m "fix(converters): reconstruct tool_use content blocks as tool_calls in _prior_output_to_messages"
```

---

### Task 8: BUG — `extract_function_tools` uses blacklist instead of whitelist, passing through tools with no `type` field

**Files:**
- Modify: `converters/to_responses.py:144-158` — `extract_function_tools`
- Test: `tests/test_responses_converter.py`

**Root cause:** `extract_function_tools` skips tools whose `type` is in `BUILTIN_TOOL_TYPES`. Any tool dict with no `type` key (`t.get("type")` returns `None`) passes through silently — `None not in BUILTIN_TOOL_TYPES` is always True. A malformed tool entry with no type field is forwarded as if it were a function tool.

**Fix:** Change to a whitelist: only include tools where `t.get("type") == "function"`. Log a WARNING for tools with unrecognised types.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_responses_converter.py`:

```python
def test_extract_function_tools_requires_explicit_function_type():
    """Tools with no type field must not be included — whitelist only function type."""
    tools = [
        {"name": "no_type_tool", "description": "missing type", "parameters": {}},
        {"type": "function", "name": "good_tool", "description": "valid", "parameters": {}},
        {"type": "web_search_preview"},  # builtin, excluded
    ]
    result = extract_function_tools(tools)
    names = [r["function"]["name"] for r in result]
    assert "good_tool" in names, f"valid function tool missing: {names}"
    assert "no_type_tool" not in names, f"tool with no type field must be excluded: {names}"
    assert len(result) == 1
```

- [ ] **Step 2: Run to confirm FAIL**

```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/test_responses_converter.py::test_extract_function_tools_requires_explicit_function_type -v
```

Expected: FAIL — `no_type_tool` passes through.

- [ ] **Step 3: Fix `extract_function_tools` in `converters/to_responses.py`**

Replace lines 144-158:
```python
def extract_function_tools(tools: list[dict]) -> list[dict]:
    out: list[dict] = []
    for t in tools or []:
        if t.get("type") in BUILTIN_TOOL_TYPES:
            continue
        fn = {
            "type": "function",
            "function": {
                "name": t.get("name", ""),
                "description": t.get("description", ""),
                "parameters": t.get("parameters", {"type": "object", "properties": {}}),
            },
        }
        out.append(fn)
    return out
```

With:
```python
def extract_function_tools(tools: list[dict]) -> list[dict]:
    out: list[dict] = []
    for t in tools or []:
        tool_type = t.get("type")
        if tool_type in BUILTIN_TOOL_TYPES:
            continue
        if tool_type != "function":
            # Whitelist approach: only explicit function tools pass through.
            # Unknown or missing types are logged and skipped.
            if tool_type is not None:
                log.warning("extract_function_tools_skipped_unknown_type", tool_type=tool_type)
            else:
                log.warning("extract_function_tools_skipped_missing_type", tool_name=t.get("name"))
            continue
        fn = {
            "type": "function",
            "function": {
                "name": t.get("name", ""),
                "description": t.get("description", ""),
                "parameters": t.get("parameters", {"type": "object", "properties": {}}),
            },
        }
        out.append(fn)
    return out
```

- [ ] **Step 4: Run to confirm PASS**

```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/test_responses_converter.py -v
```

- [ ] **Step 5: Run full suite**

```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/ -m 'not integration' -v 2>&1 | tail -10
```

- [ ] **Step 6: Commit**

```bash
git add converters/to_responses.py tests/test_responses_converter.py
git commit -m "fix(converters): whitelist function type in extract_function_tools, warn on unknown/missing types"
```

---

## Final Step: UPDATES.md

- [ ] **Update `UPDATES.md`** at the bottom with a new session entry covering all 8 bugs, all files, and all commit SHAs.

```bash
git add UPDATES.md
git commit -m "docs: update UPDATES.md for converters audit batch 2"
git push
```