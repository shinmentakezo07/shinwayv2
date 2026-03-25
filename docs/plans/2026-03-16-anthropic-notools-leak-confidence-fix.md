# Anthropic No-Tools Marker Leak + Confidence Scorer Fix

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix two gaps: (1) `_anthropic_stream` leaks `[assistant_tool_calls]` marker+JSON when no tools are declared, mirroring the existing `_openai_stream` no-tools suppression path; (2) `score_tool_call_confidence` position bonus fires incorrectly when marker is not at position 0.

**Architecture:** Both fixes are surgical single-function edits. Task 1 adds ~12 lines to `_anthropic_stream` in `pipeline.py`. Task 2 is a one-line change to `score_tool_call_confidence` in `tools/parse.py`. Each gets its own commit.

**Tech Stack:** Python 3.12, asyncio, pytest

---

### Task 1: Fix `_anthropic_stream` no-tools marker leak

**Files:**
- Modify: `pipeline.py` (~line 714)
- Test: `tests/test_pipeline.py`

**Background:** `_openai_stream` has a dedicated no-tools path (lines 447-469) that runs `_find_marker_pos` on every delta and holds back all content once the marker appears. `_anthropic_stream` has no equivalent — when `_stream_parser is None` (no tools) and the model spontaneously emits `[assistant_tool_calls]\n{...}`, the text flows straight through to `sanitize_visible_text`. `sanitize_visible_text` does strip the marker, but only if `_looks_like_raw_tool_payload` detects it on the full `candidate` string. There is a window during streaming where partial marker text (before the JSON arrives) passes through as visible text.

The clean fix is: when `_stream_parser is None`, run `_find_marker_pos(acc)` and hold back all text once the marker offset is confirmed — identical to the `_openai_stream` no-tools path.

**Step 1: Write failing test** (add to `tests/test_pipeline.py`)

Find the existing `_FakeCursorClient` class in `tests/test_pipeline.py` — it is already defined and used. Add this test:

```python
@pytest.mark.asyncio
async def test_anthropic_stream_suppresses_marker_when_no_tools(monkeypatch):
    """When no tools are declared, [assistant_tool_calls] must never reach the client."""
    monkeypatch.setattr(pipeline, 'count_message_tokens', lambda m, mo: 1)
    monkeypatch.setattr(pipeline, 'estimate_from_text', lambda t, m: 1)
    monkeypatch.setattr(pipeline, '_record', lambda *a, **k: None)

    params = PipelineParams(
        api_style='anthropic',
        model='anthropic/claude-sonnet-4.6',
        messages=[{'role': 'user', 'content': 'hi'}],
        cursor_messages=[{'role': 'user', 'content': 'hi'}],
        tools=[],
        stream=True,
    )
    raw_events = [
        e async for e in pipeline._anthropic_stream(
            _FakeCursorClient([
                'Visible text. ',
                '\n[assistant_tool_calls]\n{"tool_calls":[{"name":"bash","arguments":{"command":"ls"}}]}',
            ]),
            params,
            anthropic_tools=None,
        )
    ]
    # Concatenate all text_delta values
    text_out = ''
    for event in raw_events:
        if '"type":"text_delta"' in event or 'text_delta' in event:
            import json
            try:
                outer = json.loads(event.removeprefix('data: ').strip())
                delta = outer.get('delta', {})
                if delta.get('type') == 'text_delta':
                    text_out += delta.get('text', '')
            except Exception:
                pass
    assert '[assistant_tool_calls]' not in text_out
    assert '{"tool_calls"' not in text_out
    assert 'Visible text.' in text_out
```

**Step 2: Run test to confirm failure**
```bash
cd /teamspace/studios/this_studio/wiwi
python -m pytest tests/test_pipeline.py::test_anthropic_stream_suppresses_marker_when_no_tools -xvs 2>&1 | tail -20
```
Expected: test should FAIL because the marker text leaks through currently.

**Step 3: Implement the fix in `pipeline.py`**

Read `pipeline.py` fully first. In `_anthropic_stream`, locate the text content section:

```python
            # ── Text content ──
            candidate = final_text if thinking_text is not None else acc
            # Hold back text if tool marker has started appearing
            if _marker_offset >= 0:
                continue
```

The `_marker_offset` is currently only set by `_stream_parser.feed()` (line ~675). When `_stream_parser is None` (no tools), `_marker_offset` stays at -1 forever and the holdback never fires.

Replace the text content section:

```python
            # ── Text content ──
            candidate = final_text if thinking_text is not None else acc

            # When no tools declared, still detect and suppress any spontaneous
            # [assistant_tool_calls] marker the model emits — same logic as _openai_stream
            if _stream_parser is None and _marker_offset < 0:
                _marker_offset = _find_marker_pos(acc)

            # Hold back text if tool marker has started appearing
            if _marker_offset >= 0:
                continue
```

Also update the stream-finish close block to flush clean pre-marker text when no tools.
After the stream loop ends, find the block that closes blocks and emits `end_turn`. Before the `if text_opened:` line at the end, add:

```python
    # If marker suppressed the stream tail but clean text was never flushed, emit it now
    if not tool_mode and _stream_parser is None and _marker_offset >= 0 and not text_opened:
        from converters.from_cursor import _extract_visible_content
        _, visible, _ = _extract_visible_content(acc, params.show_reasoning)
        if visible and len(visible) > text_sent:
            yield anthropic_content_block_start(idx, {"type": "text", "text": ""})
            yield anthropic_content_block_delta(
                idx, {"type": "text_delta", "text": visible[text_sent:]}
            )
            yield anthropic_content_block_stop(idx)
            idx += 1
            text_opened = True  # prevent double-close below
```

Note: check if `_extract_visible_content` is already imported at the top of `pipeline.py` before adding the import — it may already be there.

**Step 4: Run test to confirm pass**
```bash
cd /teamspace/studios/this_studio/wiwi
python -m pytest tests/test_pipeline.py::test_anthropic_stream_suppresses_marker_when_no_tools -xvs 2>&1 | tail -15
```

**Step 5: Run full suite**
```bash
python -m pytest tests/ -k 'not integration and not cookie_rotation and not test_malformed_json and not test_non_json' -q 2>&1 | tail -10
```
All must pass.

**Step 6: Commit**
```bash
git add pipeline.py tests/test_pipeline.py
git commit -m "fix: suppress [assistant_tool_calls] in _anthropic_stream when no tools declared"
```

---

### Task 2: Fix `score_tool_call_confidence` position bonus threshold

**Files:**
- Modify: `tools/parse.py` (~line 984)
- Test: `tests/test_parse.py`

**Background:** The current check is:
```python
if real_marker_pos <= 5:  # starts the response
    score += 0.2
```
The intent is "the marker is the very first thing in the response". But `_find_marker_pos` returns the position of the `[` character of the marker, which is 0 for a true first-line marker. A marker on the second line of text like `"Hello\n[assistant_tool_calls]\n{...}"` has `real_marker_pos == 6` — correctly excluded.

However, the `<= 5` threshold exists to handle cases where the marker is preceded by optional leading whitespace or a `\n`. Let's verify: `_TOOL_CALL_MARKER_RE` is `^[ \t]*\[assistant_tool_calls\]` with `re.MULTILINE`. The `^` matches start-of-line. If the first line is blank (`\n[assistant_tool_calls]`), `_find_marker_pos` would return `0` (the `\n`) then `1` for the actual marker. But the marker starts at 0 for `[assistant_tool_calls]\n{...}` (no prefix). In practice `<= 5` is overly generous — it awards the bonus when up to 5 characters of text precede the marker, which is not "starts the response".

The correct threshold is `== 0` for a response that opens directly with the marker. Use `<= 1` as a safe bound (allows for a leading newline).

**Step 1: Write test** (add to `tests/test_parse.py`)

```python
def test_confidence_position_bonus_only_for_response_opening_marker():
    from tools.parse import score_tool_call_confidence, _find_marker_pos
    calls = [{'function': {'name': 'bash', 'arguments': '{"command":"ls"}'}}]

    # Marker at position 0 — should get bonus
    t_at_zero = '[assistant_tool_calls]\n{"tool_calls":[]}'
    assert _find_marker_pos(t_at_zero) == 0
    s_zero = score_tool_call_confidence(t_at_zero, calls)
    assert s_zero >= 0.7, f'expected >= 0.7 for pos-0 marker, got {s_zero}'

    # Marker after 6+ chars of text — must NOT get position bonus
    t_after_text = 'Hello!\n[assistant_tool_calls]\n{"tool_calls":[]}'
    assert _find_marker_pos(t_after_text) >= 6
    s_after = score_tool_call_confidence(t_after_text, calls)
    # Should have real_marker_pos bonus (0.5) but NOT the +0.2 position bonus
    assert s_after < s_zero, f'after-text marker should score lower than pos-0 marker'
    assert s_after >= 0.5, f'should still have marker bonus, got {s_after}'

    # Marker at position 1 (leading newline) — should get bonus (within threshold)
    t_leading_newline = '\n[assistant_tool_calls]\n{"tool_calls":[]}'
    pos_leading = _find_marker_pos(t_leading_newline)
    s_leading = score_tool_call_confidence(t_leading_newline, calls)
    assert s_leading >= 0.7, f'leading-newline marker should get position bonus, got {s_leading}'
```

**Step 2: Run test to see current behavior**
```bash
cd /teamspace/studios/this_studio/wiwi
python -m pytest tests/test_parse.py::test_confidence_position_bonus_only_for_response_opening_marker -xvs 2>&1 | tail -15
```

**Step 3: Fix in `tools/parse.py`**

Find (around line 984):
```python
    if real_marker_pos >= 0:
        score += 0.5
        if real_marker_pos <= 5:  # starts the response
            score += 0.2
```

Replace:
```python
    if real_marker_pos >= 0:
        score += 0.5
        if real_marker_pos <= 1:  # marker isthe very start of the response (position 0 or 1 for leading newline)
        score += 0.2
```

**Step 4: Run test to confirm pass**
```bash
cd /teamspace/studios/this_studio/wiwi
python -m pytest tests/test_parse.py::test_confidence_position_bonus_only_for_response_opening_marker -xvs 2>&1 | tail -15
```

**Step 5: Run full suite**
```bash
python -m pytest tests/ -k 'not integration and not cookie_rotation and not test_malformed_json and not test_non_json' -q 2>&1 | tail -10
```
All must pass.

**Step 6: Commit**
```bash
git add tools/parse.py tests/test_parse.py
git commit -m "fix: tighten confidence position bonus threshold to <= 1 (real_marker_pos <= 5 was too loose)"
```

---

### Final verification

```bash
cd /teamspace/studios/this_studio/wiwi
python -m pytest tests/ -k 'not integration and not cookie_rotation and not test_malformed_json and not test_non_json' -q 2>&1 | tail -10
git log --oneline -5
git push
```
