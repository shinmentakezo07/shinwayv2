# Streaming Pipeline Fixes — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development to implement this plan.

**Goal:** Fix 7 streaming pipeline bugs affecting correctness (UTF-8 corruption), performance (O(n²) rescanning), and observability (missing TTFT/TPS metrics).

**Architecture:** Surgical fixes across 4 files. No changes to external API or SSE format. Each chunk is independently committable and testable.

**Tech Stack:** Python 3.12, asyncio, structlog, httpx, codecs (stdlib)

---

## Chunk 1: Quick wins — trivial one-liner fixes

### Task 1: Bug 4 — Remove unnecessary `chunk.encode("utf-8")` in StreamMonitor

**Files:**
- Modify: `utils/stream_monitor.py:109`

The current code:
```python
self._byte_count += len(chunk.encode("utf-8"))
```
Re-encodes an already-decoded string on every chunk purely to count bytes. Character count is sufficient for throughput stats.

- [ ] **Step 1:** Read `utils/stream_monitor.py` fully to understand context.

- [ ] **Step 2:** Change line 109:
```python
# BEFORE
self._byte_count += len(chunk.encode("utf-8"))

# AFTER
self._byte_count += len(chunk)  # character count — avoids re-encoding on every chunk
```

- [ ] **Step 3:** Run tests:
```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/ -m 'not integration' -q --ignore=tests/test_client_headers.py --ignore=tests/test_context.py 2>&1 | tail -5
```
Expected: all pass.

- [ ] **Step 4:** Commit:
```bash
cd /teamspace/studios/this_studio/wiwi && git add utils/stream_monitor.py && git commit -m 'perf: remove unnecessary chunk.encode() in StreamMonitor — use len(chunk) directly'
```

---

### Task 2: Bug 5 — Cache `started` timestamp, reuse in `openai_chunk` instead of `time.time()` per chunk

**Files:**
- Modify: `converters/from_cursor.py`
- Modify: `pipeline.py`

`openai_chunk()` calls `int(time.time())` on every invocation. The `created` field in OpenAI chunks should be the request creation time, not the chunk emission time. `started = time.time()` already exists at the top of `_openai_stream` and `_anthropic_stream`.

- [ ] **Step 1:** Read `converters/from_cursor.py` — find `openai_chunk()` and `now_ts()` definitions.

- [ ] **Step 2:** Read `pipeline.py` lines 409-435 to see how `openai_chunk` is called.

- [ ] **Step 3:** In `converters/from_cursor.py`, change `openai_chunk` signature to accept optional `created` param:
```python
def openai_chunk(
    cid: str,
    model: str,
    delta: dict | None = None,
    finish_reason: str | None = None,
    created: int | None = None,
) -> dict:
    """Build an OpenAI streaming chunk dict.

    created: request creation timestamp. If None, uses current time (backwards compat).
    """
    return {
        "id": cid,
        "object": "chat.completion.chunk",
        "created": created if created is not None else now_ts(),
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": delta or {},
                "finish_reason": finish_reason,
            }
        ],
    }
```

- [ ] **Step 4:** In `pipeline.py`, `_openai_stream` already has `started = time.time()`. Change to compute `created_ts = int(started)` once, and pass it to every `openai_chunk(cid, model, ..., created=created_ts)` call in the function. There are calls at:
  - The role chunk (line ~424)
  - The text delta yield (lines ~465, ~515)
  - The finish chunk (line ~588)
  - Tool call chunks from `_OpenAIToolEmitter` — these use the `cid` and `model` passed at construction; add `created` there too if the emitter stores it.

Check `_OpenAIToolEmitter.__init__` signature and update if needed.

- [ ] **Step 5:** Run tests:
```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/ -m 'not integration' -q --ignore=tests/test_client_headers.py --ignore=tests/test_context.py 2>&1 | tail -5
```
Expected: all pass.

- [ ] **Step 6:** Commit:
```bash
cd /teamspace/studios/this_studio/wiwi && git add converters/from_cursor.py pipeline.py && git commit -m 'perf: cache request created_ts once per stream — eliminate time.time() syscall per chunk'
```

---

### Task 3: Bug 6 — Increase Anthropic tool argument chunk size from 12 to 96 bytes

**Files:**
- Modify: `pipeline.py` — find `chunk_size=12` in `_stream_anthropic_tool_input`

The 12-byte chunk size generates ~42 SSE events for a 500-char tool argument. The OpenAI path uses 96 bytes. Standardise.

- [ ] **Step 1:** Search for the chunk size constant:
```bash
grep -n 'chunk_size' /teamspace/studios/this_studio/wiwi/pipeline.py
```

- [ ] **Step 2:** Find `_stream_anthropic_tool_input` function and change:
```python
# BEFORE
chunk_size=12

# AFTER
chunk_size=96  # match OpenAI path — 8x fewer SSE events per tool argument
```

- [ ] **Step 3:** Run tests:
```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/ -m 'not integration' -q --ignore=tests/test_client_headers.py --ignore=tests/test_context.py 2>&1 | tail -5
```
Expected: all pass.

- [ ] **Step 4:** Commit:
```bash
cd /teamspace/studios/this_studio/wiwi && git add pipeline.py && git commit -m 'perf: increase Anthropic tool argument chunk size 12→96 bytes — 8x fewer SSE events'
```

---

## Chunk 2: UTF-8 fix + observability metrics

### Task 4: Bug 1 — UTF-8 incremental decoder in `cursor/sse.py`

**Files:**
- Modify: `cursor/sse.py:106-110`

When `aiter_bytes(chunk_size=65536)` splits a TCP packet, a multi-byte UTF-8 sequence (CJK, emoji) at the boundary of a line is partially decoded. `errors="ignore"` silently drops the partial bytes, corrupting the character.

**Fix:** Use `codecs.getincrementaldecoder` to hold partial sequences across chunks.

- [ ] **Step 1:** Read `cursor/sse.py` fully.

- [ ] **Step 2:** Write a failing test in `tests/test_sse.py` (or the nearest existing SSE test file — check with `ls tests/`):

```python
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

def test_utf8_multibyte_across_chunk_boundary():
    """3-byte UTF-8 char (e.g. U+4E2D, '中') split across two aiter_bytes chunks
    must arrive intact, not be dropped or corrupted."""
    # '中' = bytes b'\xe4\xb8\xad' — split after first byte
    payload_line = 'data: {"delta": "中"}\n'
    payload_bytes = payload_line.encode("utf-8")  # b'data: {"delta": "\xe4\xb8\xad"}\n'
    # Split: first chunk ends in the middle of the 3-byte sequence
    # b'data: {"delta": "\xe4' and b'\xb8\xad"}\n'
    split_pos = payload_bytes.index(b'\xe4') + 1  # split after first byte of '中'
    chunk1 = payload_bytes[:split_pos]
    chunk2 = payload_bytes[split_pos:]

    from cursor.sse import iter_deltas
    from unittest.mock import MagicMock

    async def run():
        resp = MagicMock()
        async def aiter_bytes(chunk_size=65536):
            yield chunk1
            yield chunk2
            # [DONE]
            yield b'data: [DONE]\n'
        resp.aiter_bytes = aiter_bytes
        deltas = []
        async for d in iter_deltas(resp, anthropic_tools=None):
            deltas.append(d)
        return deltas

    deltas = asyncio.run(run())
    assert deltas == ["中"], f"Expected ['中'] but got {deltas!r}"
```

- [ ] **Step 3:** Run test to confirm it FAILS (currently `errors="ignore"` drops the partial byte):
```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/test_sse.py::test_utf8_multibyte_across_chunk_boundary -v 2>&1 | tail -15
```
Expected: FAIL or test file doesn't exist yet — either way, confirm the current code fails the scenario.

- [ ] **Step 4:** Fix `cursor/sse.py`. Add `import codecs` at the top. In `iter_deltas`, replace the per-line decode with an incremental decoder:

```python
async def iter_deltas(
    response: "httpx.Response",
    anthropic_tools: list[dict] | None,
) -> AsyncIterator[str]:
    got_any = False
    acc_check = ""

    buf = b""
    # Incremental UTF-8 decoder: holds partial multi-byte sequences across chunk boundaries.
    # errors="ignore" only fires on permanently undecodable bytes (not partial sequences).
    _utf8 = codecs.getincrementaldecoder("utf-8")("ignore")

    async for chunk in response.aiter_bytes(chunk_size=65536):
        buf += _utf8.decode(chunk)  # decode bytes incrementally, completing partial sequences
        # ... rest of loop body unchanged, but buf is now str not bytes
```

Wait — `buf` needs to remain bytes for the `b"\n"` split. The correct approach is:

```python
    _utf8 = codecs.getincrementaldecoder("utf-8")("ignore")
    raw_buf = b""  # bytes buffer for line splitting

    async for chunk in response.aiter_bytes(chunk_size=65536):
        raw_buf += chunk
        while b"\n" in raw_buf:
            line_bytes, raw_buf = raw_buf.split(b"\n", 1)
            line = _utf8.decode(line_bytes, final=False).strip()
            # rest of line processing unchanged...
```

The incremental decoder holds partial sequences in its internal state across `decode()` calls. `final=False` means "more data may follow".

After the `async for` loop ends (stream done), flush decoder:
```python
    # Flush any remaining partial sequence (should be empty