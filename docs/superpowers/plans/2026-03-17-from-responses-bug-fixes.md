# from_responses.py — 4 Bug Fixes Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 4 bugs in `converters/from_responses.py` that cause ID mismatches in Responses API streaming, silent text loss when tool_calls and text coexist, phantom empty delta events, and mismatched tool call item IDs.

**Architecture:** All four bugs are in `converters/from_responses.py` — two in `build_response_object` and two in `generate_streaming_events`. Each fix is surgical: no new files, no refactors. Fix order: BUG A (`elif` → `if`) first since it affects both functions; BUG D (item_id passthrough) second; BUG B (msg_id parameter) third; BUG C (empty text guard) last.

**Tech Stack:** Python 3.11+, pytest, structlog

---

## Chunk 1: BUG A and BUG D — Data loss and ID mismatch on tool calls

---

### Task 1: BUG A — `elif text` drops text when both `text` and `tool_calls` are present

**Files:**
- Modify: `converters/from_responses.py:55-60` — `build_response_object`
- Test: `tests/test_responses_converter.py`

**Background:** `build_response_object` uses `elif text` at line 58, so if `tool_calls` is truthy the `text` branch never runs. The Responses API output array can contain both a `message` item and `function_call` items. The `elif` makes this impossible.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_responses_converter.py`:

```python
def test_build_response_object_emits_both_text_and_tool_calls():
    """When both text and tool_calls are present, output must contain both a message and function_call items."""
    tool_calls = [{
        "id": "call_abc",
        "type": "function",
        "function": {"name": "calc", "arguments": "{}"},
    }]
    resp = build_response_object(
        response_id="resp_both",
        model="cursor-small",
        text="I'll call calc now.",
        tool_calls=tool_calls,
        input_tokens=5,
        output_tokens=3,
        params={"tool_choice": "auto", "tools": [], "temperature": 1.0,
                "instructions": None, "previous_response_id": None,
                "metadata": {}, "store": True, "parallel_tool_calls": True},
    )
    output_types = [item["type"] for item in resp["output"]]
    assert "message" in output_types, f"Expected message in output, got: {output_types}"
    assert "function_call" in output_types, f"Expected function_call in output, got: {output_types}"
```

- [ ] **Step 2: Run to confirm FAIL**

```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/test_responses_converter.py::test_build_response_object_emits_both_text_and_tool_calls -v
```

Expected: FAIL — `message` not in output (only `function_call`).

- [ ] **Step 3: Fix `build_response_object` in `converters/from_responses.py`**

Change lines 55-60 from:
```python
    if tool_calls:
        for i, tc in enumerate(tool_calls):
            output.append(_build_function_call_output_item(tc, i))
    elif text:
        msg_id = f"msg_{uuid.uuid4().hex[:24]}"
        output.append(_build_message_output_item(text, msg_id))
```

To:
```python
    if text:
        msg_id = f"msg_{uuid.uuid4().hex[:24]}"
        output.append(_build_message_output_item(text, msg_id))
    if tool_calls:
        for i, tc in enumerate(tool_calls):
            output.append(_build_function_call_output_item(tc, i))
```

(Message item before function_call items — canonical Responses API ordering.)

- [ ] **Step 4: Run to confirm PASS**

```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/test_responses_converter.py -v
```

- [ ] **Step 5: Commit**

```bash
git add converters/from_responses.py tests/test_responses_converter.py
git commit -m "fix(responses): emit both message and function_call items when text and tool_calls coexist"
```

---

### Task 2: BUG D — Tool call `item_id` not passed to `build_response_object`, causing mismatch between streamed events and final response object

**Files:**
- Modify: `converters/from_responses.py:53-57` — `build_response_object` + `generate_streaming_events` tool call loop
- Test: `tests/test_responses_converter.py`

**Background:** `generate_streaming_events` generates `item_id = f"fc_{uuid.uuid4().hex[:8]}"` at line 124 and uses it in `response.output_item.added/done` events. Then at line 57 it calls `_build_function_call_output_item(tc, i)` **without** the `item_id`, so a new `uuid4()` is generated. The two IDs differ — the streamed item ID and the final response object item ID never match.

`_build_function_call_output_item` already accepts `item_id: str | None = None` — the parameter exists, it just isn't passed from `build_response_object`.

**Fix approach:** Add an optional `item_ids: list[str] | None` parameter to `build_response_object`. When provided, pass `item_ids[i]` to `_build_function_call_output_item`. `generate_streaming_events` collects the pre-generated `item_id` values and passes them in.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_responses_converter.py`:

```python
def test_generate_streaming_events_tool_call_item_ids_match_completed_response():
    """item_id in response.output_item.done events must match id in response.completed output items."""
    import json
    tool_calls = [{
        "id": "call_t1",
        "type": "function",
        "function": {"name": "search", "arguments": '{"q": "test"}'},
    }]
    events = generate_streaming_events(
        response_id="resp_tc",
        model="cursor-small",
        text="",
        tool_calls=tool_calls,
        input_tokens=5,
        output_tokens=3,
        params={"tool_choice": "auto", "tools": [], "temperature": 1.0,
                "instructions": None, "previous_response_id": None,
                "metadata": {}, "store": True, "parallel_tool_calls": True},
    )
    # Extract the item_id from response.output_item.done
    streamed_item_id = None
    completed_item_id = None
    for ev in events:
        for line in ev.split("\n"):
            if line.startswith("event: response.output_item.done"):
                pass
            elif line.startswith("data: "):
                data = json.loads(line[len("data: "):])
                if data.get("type") == "response.output_item.done" and data.get("item", {}).get("type") == "function_call":
                    streamed_item_id = data["item"]["id"]
                elif data.get("type") == "response.completed":
                    output = data.get("response", {}).get("output", [])
                    for item in output:
                        if item.get("type") == "function_call":
                            completed_item_id = item["id"]
    assert streamed_item_id is not None, "No function_call item in response.output_item.done"
    assert completed_item_id is not None, "No function_call item in response.completed"
    assert streamed_item_id == completed_item_id, (
        f"ID mismatch: streamed={streamed_item_id!r}, completed={completed_item_id!r}"
    )
```

- [ ] **Step 2: Run to confirm FAIL**

```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/test_responses_converter.py::test_generate_streaming_events_tool_call_item_ids_match_completed_response -v
```

Expected: FAIL — IDs differ.

- [ ] **Step 3: Fix `build_response_object` and `generate_streaming_events`**

In `converters/from_responses.py`:

**3a. Add `item_ids` parameter to `build_response_object`:**

Change signature from:
```python
def build_response_object(
    response_id: str,
    model: str,
    text: str | None,
    tool_calls: list[dict] | None,
    input_tokens: int,
    output_tokens: int,
    params: dict,
) -> dict:
```

To:
```python
def build_response_object(
    response_id: str,
    model: str,
    text: str | None,
    tool_calls: list[dict] | None,
    input_tokens: int,
    output_tokens: int,
    params: dict,
    item_ids: list[str] | None = None,
) -> dict:
```

**3b. Pass `item_ids[i]` when building function call items:**

Change the `if tool_calls:` block to:
```python
    if tool_calls:
        for i, tc in enumerate(tool_calls):
            iid = (item_ids[i] if item_ids and i < len(item_ids) else None)
            output.append(_build_function_call_output_item(tc, i, item_id=iid))
```

**3c. In `generate_streaming_events`, collect `item_id` values and pass them:**

Change the `if tool_calls:` block from:
```python
    if tool_calls:
        for i, tc in enumerate(tool_calls):
            item_id = f"fc_{uuid.uuid4().hex[:8]}"
            item = _build_function_call_output_item(tc, i, item_id=item_id)
            ...
    ...
    completed = build_response_object(
        response_id=response_id, model=model, text=text,
        tool_calls=tool_calls, input_tokens=input_tokens,
        output_tokens=output_tokens, params=params,
    )
```

To:
```python
    tc_item_ids: list[str] = []
    if tool_calls:
        for i, tc in enumerate(tool_calls):
            item_id = f"fc_{uuid.uuid4().hex[:8]}"
            tc_item_ids.append(item_id)
            item = _build_function_call_output_item(tc, i, item_id=item_id)
            item_in_progress = {**item, "status": "in_progress"}
            events.append(responses_sse_event("response.output_item.added", {
                "type": "response.output_item.added",
                "sequence_number": seq, "output_index": i, "item": item_in_progress,
            }))
            seq += 1
            events.append(responses_sse_event("response.output_item.done", {
                "type": "response.output_item.done",
                "sequence_number": seq, "output_index": i, "item": item,
            }))
            seq += 1
    ...
    completed = build_response_object(
        response_id=response_id, model=model, text=text,
        tool_calls=tool_calls, input_tokens=input_tokens,
        output_tokens=output_tokens, params=params,
        item_ids=tc_item_ids if tc_item_ids else None,
    )
```

- [ ] **Step 4: Run to confirm PASS**

```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/test_responses_converter.py -v
```

- [ ] **Step 5: Commit**

```bash
git add converters/from_responses.py tests/test_responses_converter.py
git commit -m "fix(responses): pass pre-generated item_ids to build_response_object to prevent tool call ID mismatch"
```

---

## Chunk 2: BUG B and BUG C — msg_id mismatch and phantom empty delta

---

### Task 3: BUG B — `msg_id` generated independently in streaming events and final response object

**Files:**
- Modify: `converters/from_responses.py:59,138,174,181` — `build_response_object` + `generate_streaming_events` text branch
- Test: `tests/test_responses_converter.py`

**Background:** Line 138 generates `msg_id` for the streaming events. Line 59 inside `build_response_object` generates a second independent `msg_id`. The `response.output_item.done` event carries the streaming `msg_id`, but `response.completed.output[0].id` carries the `build_response_object` `msg_id`. They never match.

**Fix approach:** Add `msg_id: str | None = None` parameter to `build_response_object`. When provided, use it instead of generating a new one. `generate_streaming_events` generates `msg_id` once and passes it to both the events and `build_response_object`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_responses_converter.py`:

```python
def test_generate_streaming_events_msg_id_matches_completed_response():
    """msg_id in response.output_item.done must match id in response.completed output[0]."""
    import json
    events = generate_streaming_events(
        response_id="resp_msgid",
        model="cursor-small",
        text="Hello world!",
        tool_calls=None,
        input_tokens=5,
        output_tokens=3,
        params={"tool_choice": "auto", "tools": [], "temperature": 1.0,
                "instructions": None, "previous_response_id": None,
                "metadata": {}, "store": True, "parallel_tool_calls": True},
    )
    streamed_msg_id = None
    completed_msg_id = None
    for ev in events:
        for line in ev.split("\n"):
            if line.startswith("data: "):
                data = json.loads(line[len("data: "):])
                if data.get("type") == "response.output_item.done" and data.get("item", {}).get("type") == "message":
                    streamed_msg_id = data["item"]["id"]
                elif data.get("type") == "response.completed":
                    output = data.get("response", {}).get("output", [])
                    for item in output:
                        if item.get("type") == "message":
                            completed_msg_id = item["id"]
    assert streamed_msg_id is not None, "No message item in response.output_item.done"
    assert completed_msg_id is not None, "No message item in response.completed"
    assert streamed_msg_id == completed_msg_id, (
        f"msg_id mismatch: streamed={streamed_msg_id!r}, completed={completed_msg_id!r}"
    )
```

- [ ] **Step 2: Run to confirm FAIL**

```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/test_responses_converter.py::test_generate_streaming_events_msg_id_matches_completed_response -v
```

Expected: FAIL — IDs differ.

- [ ] **Step 3: Fix `build_response_object` and `generate_streaming_events` in `converters/from_responses.py`**

**3a. Add `msg_id: str | None = None` parameter to `build_response_object`.**

Change the text branch inside the function from:
```python
    if text:
        msg_id = f"msg_{uuid.uuid4().hex[:24]}"
        output.append(_build_message_output_item(text, msg_id))
```
To:
```python
    if text:
        _msg_id = msg_id or f"msg_{uuid.uuid4().hex[:24]}"
        output.append(_build_message_output_item(text, _msg_id))
```

**3b. In `generate_streaming_events`, initialize `msg_id = None` before the `if tool_calls` block, set it in the text branch, and pass it to `build_response_object`.**

Add `msg_id = None` before `if tool_calls:`. The existing text branch already sets `msg_id = f"msg_..."` — no change needed there. Change the final `build_response_object` call to:

```python
    completed = build_response_object(
        response_id=response_id, model=model, text=text,
        tool_calls=tool_calls, input_tokens=input_tokens,
        output_tokens=output_tokens, params=params,
        item_ids=tc_item_ids if tc_item_ids else None,
        msg_id=msg_id,
    )
```

- [ ] **Step 4: Run to confirm PASS**

```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/test_responses_converter.py -v
```

- [ ] **Step 5: Commit**

```bash
git add converters/from_responses.py tests/test_responses_converter.py
git commit -m "fix(responses): pass msg_id from streaming events to build_response_object to prevent message ID mismatch"
```

---

### Task 4: BUG C — Empty text produces phantom empty delta event

**Files:**
- Modify: `converters/from_responses.py:137-179` — `generate_streaming_events` text/else branch
- Test: `tests/test_responses_converter.py`

**Background:** When `text` is `""`, `max(1, len(text))` = 1, so `range(0, 1, 40)` yields one iteration with `chunk = ""`. This emits one `response.output_text.delta` event with `delta: ""`. Also, the whole `else` block runs for empty text, emitting item events while `build_response_object` emits `output: []` — the two halves disagree about whether a message item exists.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_responses_converter.py`:

```python
def test_generate_streaming_events_empty_text_emits_no_delta_events():
    """Empty text must not produce response.output_text.delta events with empty delta."""
    import json
    events = generate_streaming_events(
        response_id="resp_empty",
        model="cursor-small",
        text="",
        tool_calls=None,
        input_tokens=5,
        output_tokens=0,
        params={"tool_choice": "auto", "tools": [], "temperature": 1.0,
                "instructions": None, "previous_response_id": None,
                "metadata": {}, "store": True, "parallel_tool_calls": True},
    )
    delta_events = []
    for ev in events:
        for line in ev.split("\n"):
            if line.startswith("data: "):
                data = json.loads(line[len("data: "):])
                if data.get("type") == "response.output_text.delta":
                    delta_events.append(data)
    empty_deltas = [e for e in delta_events if e.get("delta") == ""]
    assert not empty_deltas, (
        f"Empty delta events must not be emitted, got: {empty_deltas}"
    )
```

- [ ] **Step 2: Run to confirm FAIL**

```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/test_responses_converter.py::test_generate_streaming_events_empty_text_emits_no_delta_events -v
```

Expected: FAIL — one empty delta event is emitted.

- [ ] **Step 3: Fix `generate_streaming_events` in `converters/from_responses.py`**

Change the `else:` branch to `if not tool_calls and text:` and remove the `max(1, ...)` guard:

```python
    msg_id = None
    if not tool_calls and text:
        msg_id = f"msg_{uuid.uuid4().hex[:24]}"
        events.append(responses_sse_event("response.output_item.added", {
            "type": "response.output_item.added",
            "sequence_number": seq, "output_index": 0,
            "item": {"type": "message", "id": msg_id, "role": "assistant",
                     "status": "in_progress", "content": []},
        }))
        seq += 1
        events.append(responses_sse_event("response.content_part.added", {
            "type": "response.content_part.added",
            "sequence_number": seq, "item_id": msg_id,
            "output_index": 0, "content_index": 0,
            "part": {"type": "output_text", "text": "", "annotations": []},
        }))
        seq += 1
        for i in range(0, len(text), 40):
            chunk = text[i:i + 40]
            events.append(responses_sse_event("response.output_text.delta", {
                "type": "response.output_text.delta",
                "sequence_number": seq, "item_id": msg_id,
                "output_index": 0, "content_index": 0, "delta": chunk,
            }))
            seq += 1
        events.append(responses_sse_event("response.output_text.done", {
            "type": "response.output_text.done",
            "sequence_number": seq, "item_id": msg_id,
            "output_index": 0, "content_index": 0, "text": text,
        }))
        seq += 1
        events.append(responses_sse_event("response.content_part.done", {
            "type": "response.content_part.done",
            "sequence_number": seq, "item_id": msg_id,
            "output_index": 0, "content_index": 0,
            "part": {"type": "output_text", "text": text, "annotations": []},
        }))
        seq += 1
        completed_item = _build_message_output_item(text, msg_id)
        events.append(responses_sse_event("response.output_item.done", {
            "type": "response.output_item.done",
            "sequence_number": seq, "output_index": 0, "item": completed_item,
        }))
        seq += 1
```

- [ ] **Step 4: Run all converter tests**

```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/test_responses_converter.py -v
```

- [ ] **Step 5: Run full suite**

```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/ -m 'not integration' -v 2>&1 | tail -10
```

- [ ] **Step 6: Commit**

```bash
git add converters/from_responses.py tests/test_responses_converter.py
git commit -m "fix(responses): guard text streaming branch on non-empty text, remove phantom empty delta"
```

---

## Final Step: UPDATES.md

- [ ] **Update `UPDATES.md`** at the bottom with a new session entry covering all 4 bugs, files modified, and commit SHAs.

```bash
git add UPDATES.md
git commit -m "docs: update UPDATES.md for from_responses 4 bug fixes"
git push
```