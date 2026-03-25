# Tool Call Pipeline Bug Fixes — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix three distinct bugs that cause the Shinway proxy to leak raw `[assistant_tool_calls]` markers as plain text or silently drop tool calls instead of returning structured tool call responses to clients.

**Architecture:** Three surgical, independent fixes — one log probe added to the streaming hot path, one string removed from a suppression set, one fallback parse path added to the tool parser. No shared state changes. No API surface changes. All three are backward-compatible.

**Tech Stack:** Python 3.11+, FastAPI, pytest, msgspec, structlog. Test runner: `pytest tests/ -m 'not integration'`.

---

## Bug Summary

| Fix | File | Change |
|-----|------|--------|
| A | `pipeline/stream_openai.py` | Add diagnostic log when marker is detected but `tool_emitter` is None — exposes the root cause without changing behavior |
| B | `pipeline/suppress.py` | Remove `"engineering tasks in your development workspace"` from `_SUPPRESSION_KNOCKOUTS` — it matches the proxy's own injected system prompt and causes false-positive suppression retries |
| C | `tools/parse.py` | When confidence gate drops a call because `_find_marker_pos` returns -1 (marker inside a code fence), strip the outermost fence and retry parsing once before giving up |

---

## File Map

| File | Action | Reason |
|------|--------|--------|
| `pipeline/stream_openai.py` | Modify lines ~137-143 | Add `log.warning` when marker detected with no tool emitter |
| `pipeline/suppress.py` | Modify lines ~63-74 | Remove false-positive knockout phrase |
| `tools/parse.py` | Modify `parse_tool_calls_from_text` ~lines 1395-1414 | Add fenced-marker fallback strip-and-retry |
| `tests/test_suppress.py` | Modify | Add regression test for false-positive knockout |
| `tests/test_parse.py` | Modify | Add test for fenced-marker fallback |
| `tests/test_stream_openai.py` | Modify or create | Add test verifying warning log fires when marker seen without tool_emitter |

---

## Chunk 1: Fix B — Remove false-positive suppression knockout

> **Why first:** Purely additive regression test + one-line deletion. Lowest risk, highest certainty. Sets the TDD baseline.

### Task 1: Regression test for false-positive knockout

**Files:**
- Test: `tests/test_suppress.py`

- [ ] **Step 1: Locate the existing suppress test file**

```bash
pytest tests/test_suppress.py -v --co 2>&1 | head -40
```

Expected: list of existing `_is_suppressed` test cases.

- [ ] **Step 2: Write the failing test**

Open `tests/test_suppress.py` and add at the end:

```python
def test_is_suppressed_does_not_fire_on_own_system_prompt_phrase():
    """Regression: 'engineering tasks in your development workspace' must NOT
    trigger suppression — it is a phrase from the proxy's own injected system
    prompt and causes false-positive retries on legitimate responses."""
    # This is a normal helpful assistant response that happens to echo a
    # fragment of the injected system prompt framing.
    text = (
        "I can help you with engineering tasks in your development workspace. "
        "Let me read that file for you."
    )
    assert not _is_suppressed(text), (
        "'engineering tasks in your development workspace' must not be a "
        "suppression knockout — it matches the proxy's own system prompt."
    )


def test_is_suppressed_still_fires_on_real_signals():
    """Sanity: real suppression signals still trigger after the fix."""
    text = "I can only answer questions about cursor and nothing else."
    assert _is_suppressed(text)
```

- [ ] **Step 3: Run test to confirm it fails before the fix**

```bash
cd /teamspace/studios/this_studio/wiwi
pytest tests/test_suppress.py::test_is_suppressed_does_not_fire_on_own_system_prompt_phrase -v
```

Expected: **FAIL** — `AssertionError: 'engineering tasks in your development workspace' must not be a suppression knockout`

- [ ] **Step 4: Apply the fix**

In `pipeline/suppress.py`, remove the line:
```python
    "engineering tasks in your development workspace",
```
from `_SUPPRESSION_KNOCKOUTS` (currently at approximately line 73).

The set after the fix:
```python
_SUPPRESSION_KNOCKOUTS = {
    "i can only answer questions about cursor",
    "cannot act as a general-purpose assistant",
    "execute arbitrary instructions",
    "i am a support assistant for cursor",
    "i'm a support assistant for cursor",
    # Wiwi session-config identity bleed: upstream echoes the injected system prompt intro
    "i can help you with the editor documentation",
    "i can help you with cursor documentation",
    "documentation, features, troubleshooting",
}
```

- [ ] **Step 5: Run both new tests and existing suppress tests**

```bash
pytest tests/test_suppress.py -v
```

Expected: **ALL PASS**

- [ ] **Step 6: Commit**

```bash
git add pipeline/suppress.py tests/test_suppress.py
git commit -m "fix(suppress): remove false-positive knockout phrase that matches own system prompt"
```

---

## Chunk 2: Fix A — Diagnostic log when marker detected without tool emitter

> **Why second:** No behavior change — pure observability. A one-line `log.warning` addition inside an already-existing `if` branch. Makes Fix A diagnosable in production without touching any data path.

### Task 2: Test that the warning fires when marker seen with no tool emitter

**Files:**
- Test: `tests/test_stream_openai.py` (create if absent)
- Modify: `pipeline/stream_openai.py` lines ~137-143

- [ ] **Step 1: Check if the stream test file exists**

```bash
ls tests/test_stream_openai.py 2>/dev/null && echo EXISTS || echo MISSING
```

- [ ] **Step 2: Write the failing test**

If the file exists, append. If missing, create `tests/test_stream_openai.py`:

```python
"""Tests for pipeline/stream_openai.py — streaming hot path."""
from __future__ import annotations

import pytest
import structlog
import structlog.testing

from pipeline.stream_openai import _safe_emit_len, _TOOL_MARKER


class TestSafeEmitLen:
    """Unit tests for _safe_emit_len — partial marker holdback."""

    def test_full_text_no_marker_prefix(self):
        assert _safe_emit_len("hello world") == len("hello world")

    def test_holds_back_partial_marker(self):
        text = "some text [assistant_tool"
        safe = _safe_emit_len(text)
        # Must hold back the partial marker suffix
        assert safe < len(text)
        assert text[:safe] == "some text "

    def test_full_marker_held_completely(self):
        text = "[assistant_tool_calls]"
        assert _safe_emit_len(text) == 0

    def test_empty_string(self):
        assert _safe_emit_len("") == 0

    def test_text_ending_with_non_marker_bracket(self):
        # '[' alone is not a prefix of the marker
        text = "result = arr["
        assert _safe_emit_len(text) == len(text)
```

- [ ] **Step 3: Run test to confirm it passes (pure unit test — no fix needed)**

```bash
pytest tests/test_stream_openai.py::TestSafeEmitLen -v
```

Expected: **ALL PASS** — these test existing code.

- [ ] **Step 4: Write the diagnostic log test**

Append to `tests/test_stream_openai.py`:

```python
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from pipeline.params import PipelineParams


def _make_params(tools=None):
    """Minimal PipelineParams for testing — no tools by default."""
    return PipelineParams(
        api_style="openai",
        model="claude-opus-4-6",
        messages=[{"role": "user", "content": "hi"}],
        cursor_messages=[{"role": "user", "parts": [{"type": "text", "text": "hi"}], "id": "abc"}],
        tools=tools or [],
        stream=True,
    )


class TestMarkerDetectedNoToolEmitter:
    """Verify a warning is emitted when [assistant_tool_calls] appears in the
    stream but the request was made without tools (tool_emitter is None).

    This makes the root cause of Fix A diagnosable in production logs.
    """

    def test_warning_logged_when_marker_seen_without_tools(self):
        """When a no-tools request gets a response containing the tool marker,
        a structured warning must appear in the log."""
        # The stream returns a response with the marker but no tools were requested
        marker_response = "[assistant_tool_calls]\n{\"tool_calls\": [{\"name\": \"Bash\", \"arguments\": {}}]}"

        async def _run():
            mock_client = MagicMock()
            mock_client.stream = AsyncMock(return_value=_async_iter([marker_response]))

            params = _make_params(tools=[])  # no tools

            with structlog.testing.capture_logs() as cap:
                from pipeline.stream_openai import _openai_stream
                chunks = []
                async for chunk in _openai_stream(mock_client, params, None):
                    chunks.append(chunk)

            warning_events = [
                e for e in cap
                if e.get("log_level") == "warning"
                and "marker" in e.get("event", "").lower()
            ]
            assert warning_events, (
                "Expected a warning log when [assistant_tool_calls] marker is "
                "detected in a no-tools stream. Got log events: " + str(cap)
            )

        asyncio.run(_run())


async def _async_iter(items):
    for item in items:
        yield item
```

- [ ] **Step 5: Run test to confirm it FAILS before the fix**

```bash
pytest tests/test_stream_openai.py::TestMarkerDetectedNoToolEmitter -v
```

Expected: **FAIL** — no warning log is emitted yet.

- [ ] **Step 6: Apply the fix in `pipeline/stream_openai.py`**

Locate the no-tools holdback block (approximately lines 137-143):

```python
            # ── No tools — still must suppress any [assistant_tool_calls] the model emits ──
            if tool_emitter is None:
                if _marker_offset < 0:
                    _marker_offset = _find_marker_pos(acc)
                # Hold back everything once the marker starts appearing
                if _marker_offset >= 0:
                    acc_visible_processed = len(acc)
                    continue
```

Change to:

```python
            # ── No tools — still must suppress any [assistant_tool_calls] the model emits ──
            if tool_emitter is None:
                if _marker_offset < 0:
                    pos = _find_marker_pos(acc)
                    if pos >= 0:
                        _marker_offset = pos
                        log.warning(
                            "marker_detected_no_tool_emitter",
                            marker_pos=pos,
                            acc_snippet=acc[max(0, pos - 20):pos + 60],
                            model=model,
                            request_id=params.request_id,
                        )
                # Hold back everything once the marker starts appearing
                if _marker_offset >= 0:
                    acc_visible_processed = len(acc)
                    continue
```

Key change: `_find_marker_pos` result is stored in `pos` first. The warning fires exactly once — on first detection. `_marker_offset` is only assigned when a real marker is found.

- [ ] **Step 7: Run ALL stream tests to confirm PASS after fix**

```bash
pytest tests/test_stream_openai.py -v
```

Expected: **ALL PASS**

- [ ] **Step 8: Commit**

```bash
git add pipeline/stream_openai.py tests/test_stream_openai.py
git commit -m "fix(pipeline): log warning when tool marker detected in no-tools stream"
```

---

## Chunk 3: Fix C — Fenced-marker fallback in `parse_tool_calls_from_text`

> **Why third:** Most complex change. Adds a new fallback parse path that strips the outermost code fence and retries when the confidence gate drops a call because the marker was inside a fence. No existing paths are modified — only a new block inserted after the existing fallback.

### Task 3: Test and implement fenced tool call recovery

**Files:**
- Test: `tests/test_parse.py`
- Modify: `tools/parse.py` — `parse_tool_calls_from_text`

- [ ] **Step 1: Check existing test patterns**

```bash
pytest tests/test_parse.py -v --co 2>&1 | head -60
```

Note the import style and fixture patterns used in that file.

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_parse.py`:

```python
# ── Fix C: fenced marker fallback ───────────────────────────────────────────

class TestFencedMarkerFallback:
    """When the model wraps its tool call block inside triple backticks,
    _find_marker_pos returns -1 (fenced markers are excluded). The parser
    must strip the outermost fence and retry before giving up."""

    _TOOLS = [
        {
            "type": "function",
            "function": {
                "name": "Bash",
                "description": "Run a shell command",
                "parameters": {
                    "type": "object",
                    "properties": {"command": {"type": "string"}},
                    "required": ["command"],
                },
            },
        }
    ]

    def test_bare_fenced_tool_call_recovered(self):
        """Tool call wrapped in ``` ... ``` is recovered via fence-strip fallback."""
        text = (
            "```\n"
            "[assistant_tool_calls]\n"
            '{"tool_calls": [{"name": "Bash", "arguments": {"command": "echo hi"}}]}\n'
            "```"
        )
        result = parse_tool_calls_from_text(text, self._TOOLS, streaming=False)
        assert result is not None, "Expected tool calls to be recovered from fenced block"
        assert len(result) == 1
        assert result[0]["function"]["name"] == "Bash"

    def test_json_fenced_tool_call_recovered(self):
        """Tool call wrapped in ```json ... ``` is also recovered."""
        text = (
            "```json\n"
            "[assistant_tool_calls]\n"
            '{"tool_calls": [{"name": "Bash", "arguments": {"command": "ls -la"}}]}\n'
            "```"
        )
        result = parse_tool_calls_from_text(text, self._TOOLS, streaming=False)
        assert result is not None
        assert result[0]["function"]["name"] == "Bash"

    def test_unfenced_tool_call_still_works(self):
        """Unfenced tool calls (the normal case) are unaffected by this change."""
        text = (
            "[assistant_tool_calls]\n"
            '{"tool_calls": [{"name": "Bash", "arguments": {"command": "pwd"}}]}'
        )
        result = parse_tool_calls_from_text(text, self._TOOLS, streaming=False)
        assert result is not None
        assert result[0]["function"]["name"] == "Bash"

    def test_fenced_marker_not_recovered_during_streaming(self):
        """During streaming the fenced fallback must NOT fire — streaming only
        parses when the marker is confirmed by _find_marker_pos."""
        text = (
            "```\n"
            "[assistant_tool_calls]\n"
            '{"tool_calls": [{"name": "Bash", "arguments": {"command": "echo hi"}}]}\n'
            "```"
        )
        result = parse_tool_calls_from_text(text, self._TOOLS, streaming=True)
        assert result is None

    def test_accidental_json_without_marker_still_dropped(self):
        """Accidental JSON that looks like a tool call but has no marker at all
        must still be dropped — the confidence gate must not be bypassed."""
        text = '{"tool_calls": [{"name": "Bash", "arguments": {"command": "rm -rf /"}}]}'
        result = parse_tool_calls_from_text(text, self._TOOLS, streaming=False)
        assert result is None
```

- [ ] **Step 3: Run tests to confirm FAIL before fix**

```bash
pytest tests/test_parse.py::TestFencedMarkerFallback -v
```

Expected: `test_bare_fenced_tool_call_recovered` and `test_json_fenced_tool_call_recovered` **FAIL**. The other three **PASS**.

- [ ] **Step 4: Apply the fix in `tools/parse.py`**

Locate the existing fallback block inside `parse_tool_calls_from_text` (around line 1397):

```python
    if not objs and marker_pos >= 0 and not streaming:
        fallback_raw = _extract_after_marker(text)
        if fallback_raw:
            parsed = _lenient_json_loads(fallback_raw)
            if parsed is not None:
                objs.append(parsed)
                log.info(
                    "tool_parse_fallback_extraction",
                    raw_len=len(fallback_raw),
                )
```

Insert the following block **immediately after** that block (before the `if not objs:` warning log block):

```python
    # Fenced-marker fallback: the model wrapped the entire tool call block in
    # ``` ... ```. _find_marker_pos returns -1 for fenced markers (correct —
    # avoids false positives on prose examples). When the whole response IS the
    # fenced block, strip the fence and retry parsing once. Non-streaming only.
    if not objs and marker_pos < 0 and not streaming:
        stripped = _JSON_FENCE_RE.sub(lambda m: m.group(1), text).strip()
        if stripped != text.strip():
            fenced_marker_pos = _find_marker_pos(stripped)
            if fenced_marker_pos >= 0:
                log.info("tool_parse_fenced_marker_fallback", stripped_len=len(stripped))
                fenced_parse_text = stripped[fenced_marker_pos:]
                for raw in extract_json_candidates(fenced_parse_text):
                    parsed = _lenient_json_loads(raw)
                    if parsed is not None:
                        objs.append(parsed)
                if not objs:
                    fallback_raw = _extract_after_marker(stripped)
                    if fallback_raw:
                        parsed = _lenient_json_loads(fallback_raw)
                        if parsed is not None:
                            objs.append(parsed)
```

**Note:** `_JSON_FENCE_RE` is already defined at the top of `tools/parse.py`. Do not re-import or re-declare it.

- [ ] **Step 5: Run failing tests to confirm PASS after fix**

```bash
pytest tests/test_parse.py::TestFencedMarkerFallback -v
```

Expected: **ALL 5 PASS**

- [ ] **Step 6: Run full test suite to check for regressions**

```bash
pytest tests/ -m 'not integration' -v --tb=short 2>&1 | tail -30
```

Expected: **ALL PASS** — zero regressions.

- [ ] **Step 7: Commit**

```bash
git add tools/parse.py tests/test_parse.py
git commit -m "fix(parse): recover tool calls wrapped in code fences via fence-strip fallback"
```

---

## Chunk 4: Final verification and UPDATES.md

### Task 4: Full regression run and session documentation

**Files:**
- Modify: `UPDATES.md`

- [ ] **Step 1: Run entire non-integration test suite**

```bash
cd /teamspace/studios/this_studio/wiwi
pytest tests/ -m 'not integration' -v --tb=short 2>&1 | tail -30
```

Expected: ALL tests pass, 0 failures, 0 errors.

- [ ] **Step 2: Verify all three fix commits are present**

```bash
git log --oneline -5
```

Expected: three fix commits visible on top.

- [ ] **Step 3: Append session entry to UPDATES.md**

Add at the bottom of `UPDATES.md`:

```markdown
## Session 51 — Tool call pipeline bug fixes (2026-03-21)

### What changed
- `pipeline/suppress.py` — `_SUPPRESSION_KNOCKOUTS` set
- `pipeline/stream_openai.py` — no-tools marker holdback branch
- `tools/parse.py` — `parse_tool_calls_from_text` fenced-marker fallback
- `tests/test_suppress.py` — regression tests for knockout false positive
- `tests/test_stream_openai.py` — new or extended: `TestSafeEmitLen`, `TestMarkerDetectedNoToolEmitter`
- `tests/test_parse.py` — `TestFencedMarkerFallback` class (5 tests)

### Which lines / functions
- `pipeline/suppress.py:_SUPPRESSION_KNOCKOUTS` — removed `"engineering tasks in your development workspace"` (~line 73)
- `pipeline/stream_openai.py:_openai_stream` — no-tools marker detection block now emits `log.warning("marker_detected_no_tool_emitter", ...)` on first detection (~lines 137-143)
- `tools/parse.py:parse_tool_calls_from_text` — fenced-marker fallback block inserted after existing `tool_parse_fallback_extraction` block (~line 1407)

### Why
- **Fix B (suppress.py):** `"engineering tasks in your development workspace"` was in `_SUPPRESSION_KNOCKOUTS` but exactly matches a phrase from the proxy's own injected system prompt. When the upstream model echoes any fragment of the injected framing, `_is_suppressed()` fires a false positive, kills the stream, and retries with rotated credentials — discarding a valid response and wasting a round trip.
- **Fix A (stream_openai.py):** When `params.tools` is falsy, `tool_emitter` is `None` and the entire structured tool call path is disabled. The marker is silently held back but never parsed, so the client receives a text response with no tool calls. A `log.warning` now surfaces this immediately in production logs.
- **Fix C (parse.py):** When the upstream model wraps its tool call block in triple backticks, `_find_marker_pos` correctly returns -1. The confidence gate then scores 0.0 and drops the call. The new fenced-marker fallback strips the outermost fence at stream end and retries parsing — recovering the call without relaxing the fence exclusion rule for streaming.

### Commits
| SHA | Description |
|-----|-------------|
| (fill after commit) | fix(suppress): remove false-positive knockout phrase that matches own system prompt |
| (fill after commit) | fix(pipeline): log warning when tool marker detected in no-tools stream |
| (fill after commit) | fix(parse): recover tool calls wrapped in code fences via fence-strip fallback |
| (fill after commit) | docs: update UPDATES.md for session 51 — tool call pipeline bug fixes |
```

- [ ] **Step 4: Commit UPDATES.md**

```bash
git add UPDATES.md
git commit -m "docs: update UPDATES.md for session 51 — tool call pipeline bug fixes"
```

- [ ] **Step 5: Push**

```bash
git push
```

---

## Execution Notes for Subagents

- Each chunk is fully independent. Chunks 1, 2, 3 can be dispatched in parallel to separate subagents — they touch non-overlapping files.
- Chunk 4 (UPDATES.md + final test run) must run after all three fix chunks are committed.
- Each subagent should run the full `pytest tests/ -m 'not