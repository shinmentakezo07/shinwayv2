# Three Bug Fixes — Partial Marker Leak, Rate Limiter TOCTOU, EmptyResponseError Retry Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix three confirmed bugs: partial `[assistant_tool_calls]` marker characters leaking to clients during streaming, a TOCTOU race in the dual-bucket rate limiter, and `EmptyResponseError` silently killing requests instead of triggering retry.

**Architecture:** Surgical edits to three independent files. No new files. TDD throughout — failing test first, minimal fix, verify pass, commit. Each task is self-contained and can be executed in parallel.

**Tech Stack:** Python 3.11+, FastAPI, asyncio, pytest, structlog

---

## Chunk 1: Bug 1 — Partial marker leak during streaming

### Task 1: Hold back partial `[assistant_tool_calls]` prefixes before emitting visible deltas

**Root cause:** `_find_marker_pos` requires the **complete** string `[assistant_tool_calls]` to match. During streaming, the marker arrives chunk-by-chunk. When `acc` ends with a prefix like `[assistant_tool_` but not the closing `]`, `_find_marker_pos` returns `-1`, the holdback condition is not triggered, and those bytes are yielded to the client. By the time `]` arrives the holdback fires, but the leading fragment is already sent.

**Files:**
- Modify: `pipeline/stream_openai.py` (no-tools emit path, ~lines 126–148 and ~176–209)
- Test: `tests/test_pipeline.py`

**Exact fix:** Before any `yield openai_sse(...)` in the per-delta loop, compute how many trailing bytes of `visible_text` are a known prefix of `[assistant_tool_calls]`, and trim them from the emitted slice. At stream-end, the full `acc` is already passed through `_extract_visible_content` which does a complete marker scan — so the end-of-stream flush is unaffected.

Add a module-level helper to `pipeline/stream_openai.py` (above `_openai_stream`):

```python
_TOOL_MARKER = "[assistant_tool_calls]"
_TOOL_MARKER_PREFIXES: frozenset[str] = frozenset(
    _TOOL_MARKER[:i] for i in range(1, len(_TOOL_MARKER) + 1)
)


def _safe_emit_len(text: str) -> int:
    """Return the number of leading characters of text safe to emit now.

    Holds back any trailing suffix that is a prefix of [assistant_tool_calls]
    so partial markers never reach the client during streaming.
    Scans at most len(_TOOL_MARKER) chars from the end — O(1).
    """
    max_hold = len(_TOOL_MARKER)
    for hold in range(min(max_hold, len(text)), 0, -1):
        if text[-hold:] in _TOOL_MARKER_PREFIXES:
            return len(text) - hold
    return len(text)
```

Then in **both** emit sites in the no-tools branch (the one inside the `tool_emitter is None` block and the one inside the tools-enabled non-marker path), change:

```python
# BEFORE (no-tools path, ~line 142):
if len(visible_text) > text_sent:
    visible_delta = visible_text[text_sent:]
    if visible_delta:
        yield openai_sse(
            openai_chunk(cid, model, delta={"content": visible_delta}, created=created_ts)
        )
    text_sent = len(visible_text)
```

To:

```python
# AFTER:
safe_end = _safe_emit_len(visible_text)
if safe_end > text_sent:
    visible_delta = visible_text[text_sent:safe_end]
    if visible_delta:
        yield openai_sse(
            openai_chunk(cid, model, delta={"content": visible_delta}, created=created_ts)
        )
    text_sent = safe_end
```

Apply the same replacement to the second emit site (tools-enabled non-marker path, ~lines 203–209).

- [ ] **Step 1: Write failing test in `tests/test_pipeline.py`**

Add after the existing imports:

```python
from pipeline.stream_openai import _safe_emit_len, _TOOL_MARKER, _TOOL_MARKER_PREFIXES
```

Add these tests:

```python
# ── Bug 1: partial marker holdback ────────────────────────────────────────────

def test_safe_emit_len_full_text_no_marker():
    """Text with no marker prefix returns full length — nothing held back."""
    assert _safe_emit_len("hello world") == len("hello world")


def test_safe_emit_len_empty_string():
    """Empty string returns 0."""
    assert _safe_emit_len("") == 0


def test_safe_emit_len_holds_back_single_char_prefix():
    """Text ending with '[' holds back 1 character."""
    text = "hello ["
    result = _safe_emit_len(text)
    assert result == len(text) - 1


def test_safe_emit_len_holds_back_partial_marker():
    """Text ending with '[assistant_tool_' holds back 16 chars."""
    prefix = "[assistant_tool_"
    assert len(prefix) == 16
    text = "some visible text" + prefix
    result = _safe_emit_len(text)
    assert result == len(text) - 16


def test_safe_emit_len_does_not_hold_back_full_marker():
    """Complete [assistant_tool_calls] is held back in full (22 chars)."""
    marker = "[assistant_tool_calls]"
    assert len(marker) == 22
    text = "prefix text" + marker
    result = _safe_emit_len(text)
    assert result == len(text) - 22


def test_safe_emit_len_does_not_hold_back_non_prefix_bracket():
    """A '[' that is part of unrelated text like '[1]' is not held back."""
    # "[1]" — '[' followed by '1' is not a prefix of [assistant_tool_calls]
    text = "result [1] and more"
    assert _safe_emit_len(text) == len(text)


def test_tool_marker_prefixes_contains_all_prefixes():
    """_TOOL_MARKER_PREFIXES contains every prefix from length 1 to 22."""
    assert len(_TOOL_MARKER_PREFIXES) == len(_TOOL_MARKER)
    for i in range(1, len(_TOOL_MARKER) + 1):
        assert _TOOL_MARKER[:i] in _TOOL_MARKER_PREFIXES
```

- [ ] **Step 2: Run to confirm FAIL**

```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/test_pipeline.py::test_safe_emit_len_full_text_no_marker tests/test_pipeline.py::test_safe_emit_len_holds_back_partial_marker -v
```

Expected: `ImportError` or `AttributeError` — `_safe_emit_len` does not exist yet.

- [ ] **Step 3: Add `_safe_emit_len` and constants to `pipeline/stream_openai.py`**

Insert after the `log = structlog.get_logger()` line and before `def _extract_visible_content`:

```python
_TOOL_MARKER = "[assistant_tool_calls]"
_TOOL_MARKER_PREFIXES: frozenset[str] = frozenset(
    _TOOL_MARKER[:i] for i in range(1, len(_TOOL_MARKER) + 1)
)


def _safe_emit_len(text: str) -> int:
    """Return the number of leading characters of text safe to emit now.

    Holds back any trailing suffix that is a prefix of [assistant_tool_calls]
    so partial markers never reach the client during streaming.
    Scans at most len(_TOOL_MARKER)=22 chars from the end — O(1).
    """
    max_hold = len(_TOOL_MARKER)
    for hold in range(min(max_hold, len(text)), 0, -1):
        if text[-hold:] in _TOOL_MARKER_PREFIXES:
            return len(text) - hold
    return len(text)
```

- [ ] **Step 4: Run unit tests to confirm PASS**

```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/test_pipeline.py::test_safe_emit_len_full_text_no_marker tests/test_pipeline.py::test_safe_emit_len_holds_back_partial_marker tests/test_pipeline.py::test_safe_emit_len_holds_back_single_char_prefix tests/test_pipeline.py::test_safe_emit_len_does_not_hold_back_full_marker tests/test_pipeline.py::test_tool_marker_prefixes_contains_all_prefixes -v
```

Expected: all PASS.

- [ ] **Step 5: Patch the no-tools emit site in `pipeline/stream_openai.py`**

Locate the no-tools emit block (inside the `if tool_emitter is None:` branch). It reads:

```python
                    if len(visible_text) > text_sent:
                        visible_delta = visible_text[text_sent:]
                        if visible_delta:
                            yield openai_sse(
                                openai_chunk(cid, model, delta={"content": visible_delta}, created=created_ts)
                            )
                        text_sent = len(visible_text)
```

Replace with:

```python
                    safe_end = _safe_emit_len(visible_text)
                    if safe_end > text_sent:
                        visible_delta = visible_text[text_sent:safe_end]
                        if visible_delta:
                            yield openai_sse(
                                openai_chunk(cid, model, delta={"content": visible_delta}, created=created_ts)
                            )
                        text_sent = safe_end
```

- [ ] **Step 6: Patch the tools-enabled non-marker emit site in `pipeline/stream_openai.py`**

Locate the second emit block (inside the tools-enabled path, after the `if _marker_offset >= 0:` guard). It reads:

```python
                if len(visible_text) > text_sent:
                    visible_delta = visible_text[text_sent:]
                    if visible_delta:
                        yield openai_sse(
                            openai_chunk(cid, model, delta={"content": visible_delta}, created=created_ts)
                        )
                    text_sent = len(visible_text)
```

Replace with:

```python
                safe_end = _safe_emit_len(visible_text)
                if safe_end > text_sent:
                    visible_delta = visible_text[text_sent:safe_end]
                    if visible_delta:
                        yield openai_sse(
                            openai_chunk(cid, model, delta={"content": visible_delta}, created=created_ts)
                        )
                    text_sent = safe_end
```

- [ ] **Step 7: Write integration-level streaming test**

Add to `tests/test_pipeline.py`:

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pipeline
from pipeline import PipelineParams
from pipeline.stream_openai import _openai_stream


class _ChunkClient:
    """Fake CursorClient that yields a pre-configured list of string chunks."""
    def __init__(self, chunks: list[str]):
        self._chunks = chunks

    async def stream(self, cursor_messages, model, anthropic_tools):
        for chunk in self._chunks:
            yield chunk


@pytest.mark.asyncio
async def test_partial_marker_not_emitted_to_client(monkeypatch):
    """[assistant_tool_calls] prefix chars must not leak to the client mid-stream.

    The marker arrives in two chunks: '[assistant_tool_' then 'calls]\n{...}'.
    The first chunk must not be emitted as visible content.
    """
    monkeypatch.setattr(pipeline, "split_visible_reasoning", lambda text: (None, text))
    monkeypatch.setattr(pipeline, "sanitize_visible_text", lambda text, parsed=None: (text, False))
    monkeypatch.setattr(pipeline, "count_message_tokens", lambda messages, model: 10)
    monkeypatch.setattr(pipeline, "estimate_from_text", lambda text, model: 5)
    async def _fake_record(*args, **kwargs): pass
    monkeypatch.setattr(pipeline, "_record", _fake_record)

    # No tools — exercises the no-tools holdback path
    params = PipelineParams(
        api_style="openai",
        model="cursor-fast",
        messages=[{"role": "user", "content": "hi"}],
        cursor_messages=[{"role": "user", "content": "hi"}],
        tools=None,
        tool_choice=None,
        stream=True,
        show_reasoning=False,
        reasoning_effort=None,
        parallel_tool_calls=True,
        json_mode=False,
        api_key="sk-test",
        system_text="",
        max_tokens=None,
        include_usage=False,
        thinking_budget_tokens=None,
        stop=None,
        request_id="test-req-1",
    )

    # Marker arrives split: visible text + partial marker in chunk 1,
    # then the closing chars in chunk 2
    chunks = ["Some visible text[assistant_tool_", "calls]\n{\"tool_calls\": []}"]
    client = _ChunkClient(chunks)

    collected_content: list[str] = []
    async for sse_line in _openai_stream(client, params, anthropic_tools=None):
        if '"content"' in sse_line and 'data:' in sse_line:
            import json as _json
            payload = _json.loads(sse_line.removeprefix('data: ').strip())
            for choice in payload.get('choices', []):
                delta = choice.get('delta', {})
                if 'content' in delta and delta['content']:
                    collected_content.append(delta['content'])

    combined = ''.join(collected_content)
    # The partial marker fragment must NOT appear in emitted content
    assert '[assistant_tool_' not in combined, (
        f"Partial marker leaked to client: {combined!r}"
    )
    # Visible text before the marker IS expected
    assert 'Some visible text' in combined
```

- [ ] **Step 8: Run integration test to confirm PASS**

```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/test_pipeline.py::test_partial_marker_not_emitted_to_client -v
```

Expected: PASS.

- [ ] **Step 9: Run full test suite**

```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/ -m 'not integration' -v
```

Expected: all existing tests still PASS.

- [ ] **Step 10: Commit**

```bash
cd /teamspace/studios/this_studio/wiwi && git add pipeline/stream_openai.py tests/test_pipeline.py
git commit -m "fix(pipeline): hold back partial [assistant_tool_calls] prefixes to prevent marker fragment leak during streaming"
```

---

## Chunk 2: Bug 2 — Rate limiter TOCTOU race

### Task 2: Eliminate peek+consume split in `DualBucketRateLimiter`

**Root cause:** `DualBucketRateLimiter.consume()` does four independent lock acquisitions: `_rps.peek` → `_rpm.peek` → `_rps.consume` → `_rpm.consume`. Two concurrent requestors can both pass both peeks before either consume lands. Additionally, the return values from `_rps.consume()` and `_rpm.consume()` on lines 90–91 are silently discarded — even if a race is lost and `consume()` returns `False`, the caller still returns `True, ""`.

**Runtime impact:** In the current single-worker asyncio deployment (no `await` between peek and consume, single event loop thread) the race cannot fire. It is latent and activates the moment any executor or thread touches the rate limiter. The discarded return values are a code correctness bug regardless.

**Files:**
- Modify: `middleware/rate_limit.py` (`TokenBucket`, `DualBucketRateLimiter`)
- Test: `tests/test_rate_limit.py`

**Exact fix:** Add `refund()` to `TokenBucket`. Rewrite `DualBucketRateLimiter.consume()` to use the return values from `consume()` calls and refund RPS if RPM fails. Remove the `peek()` calls from the hot path.

- [ ] **Step 1: Write failing test in `tests/test_rate_limit.py`**

Add after existing tests:

```python
def test_dual_bucket_consume_return_values_are_used():
    """DualBucketRateLimiter.consume() must check actual consume() results,
    not peek() results. Verifies the discard bug is fixed.

    With rpm_limit=1: first consume passes, second must fail.
    The fix ensures the second consume call's False return is honoured.
    """
    limiter = DualBucketRateLimiter(
        rate_rps=1000.0,
        burst_rps=1000,
        rate_rpm=1.0,   # 1 token in RPM bucket
        burst_rpm=1,
    )
    key = "discard-return-test"
    # First consume drains the RPM bucket
    allowed, reason = limiter.consume(key)
    assert allowed is True
    # Second must fail — RPM bucket is empty
    allowed, reason = limiter.consume(key)
    assert allowed is False
    assert "RPM" in reason


def test_token_bucket_refund_restores_token():
    """refund() must restore a previously consumed token, capped at burst."""
    bucket = TokenBucket(rate=0.001, burst=1)
    key = "refund-test"
    # Consume the single token
    assert bucket.consume(key) is True
    assert bucket.consume(key) is False  # empty
    # Refund it
    bucket.refund(key)
    # Now consume should succeed again
    assert bucket.consume(key) is True


def test_token_bucket_refund_capped_at_burst():
    """refund() must not exceed burst capacity."""
    bucket = TokenBucket(rate=0.001, burst=2)
    key = "refund-cap-test"
    # Bucket starts full (burst=2). Refund should not push above 2.
    bucket.refund(key)  # should be a no-op effectively (capped)
    assert bucket.consume(key) is True
    assert bucket.consume(key) is True
    assert bucket.consume(key) is False  # still empty after 2


def test_token_bucket_refund_disabled_when_rate_zero():
    """refund() on a disabled bucket (rate=0) must not raise."""
    bucket = TokenBucket(rate=0, burst=10)
    bucket.refund("any-key")  # must not raise
```

- [ ] **Step 2: Run to confirm FAIL**

```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/test_rate_limit.py::test_token_bucket_refund_restores_token tests/test_rate_limit.py::test_dual_bucket_consume_return_values_are_used -v
```

Expected: `AttributeError: 'TokenBucket' object has no attribute 'refund'`.

- [ ] **Step 3: Add `refund()` to `TokenBucket` in `middleware/rate_limit.py`**

Add after the `peek()` method:

```python
    def refund(self, key: str, tokens: float = 1.0) -> None:
        """Return tokens to the bucket (undo a consume). Capped at burst capacity."""
        if self.rate <= 0:
            return
        now = time.monotonic()
        with self._lock:
            level, last = self._buckets.get(key, (self.burst, now))
            self._buckets[key] = (min(self.burst, level + tokens), last)
```

- [ ] **Step 4: Rewrite `DualBucketRateLimiter.consume()` in `middleware/rate_limit.py`**

Replace the existing `consume` method:

```python
    def consume(self, key: str) -> tuple[bool, str]:
        """Atomically check and consume one token from both buckets.

        Consumes RPS first, then RPM. If RPM fails, refunds the RPS token.
        Eliminates the peek+consume split that allowed two threads to both
        pass peek before either consume landed.
        """
        if not self._rps.consume(key):
            return False, "RPS limit exceeded"
        if not self._rpm.consume(key):
            self._rps.refund(key)
            return False, "RPM limit exceeded"
        return True, ""
```

- [ ] **Step 5: Run all rate limiter tests to confirm PASS**

```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/test_rate_limit.py -v
```

Expected: all PASS. The existing `test_rate_limiter_rps_rpm_combo`, `test_dual_bucket_rpm_blocks_after_burst`, `test_enforce_per_key_rate_limit_raises_when_exhausted` must all still pass — they test observable behaviour that is unchanged.

- [ ] **Step 6: Run full test suite**

```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/ -m 'not integration' -v
```

Expected: all passing.

- [ ] **Step 7: Commit**

```bash
cd /teamspace/studios/this_studio/wiwi && git add middleware/rate_limit.py tests/test_rate_limit.py
git commit -m "fix(rate_limit): eliminate peek+consume TOCTOU race; add TokenBucket.refund() for atomic RPM-fail rollback"
```

---

## Chunk 3: Bug 3 — `EmptyResponseError` never retried

### Task 3: Add `EmptyResponseError` to the retry path in `cursor/client.py`

**Root cause:** In `cursor/client.py`, the bare `except Exception as exc: raise exc` block (lines 254–258) immediately re-raises `EmptyResponseError` without attempting a retry. `EmptyResponseError` is raised by `iter_deltas` when the upstream returns HTTP 200 with an empty body — a transient infrastructure condition identical in nature to a `TimeoutError`. The `_RETRYABLE` tuple in `pipeline/suppress.py` also lacks `EmptyResponseError`, but since the error never reaches that layer (it is re-raised at the client level before the pipeline retry loop can catch it), the fix belongs in `cursor/client.py`.

**Files:**
- Modify: `cursor/client.py` (stream retry loop, ~lines 254–258)
- Test: `tests/test_cursor_client.py`

**Exact fix:** Add a specific `except EmptyResponseError` handler **before** the bare `except Exception` block, identical in structure to the `except (httpx.ReadTimeout, httpx.ConnectTimeout)` handler: mark credential as errored, wrap in `BackendError`, backoff, and `continue` to the next retry attempt.

`EmptyResponseError` is already imported in `cursor/sse.py` and exported from `handlers`. Import it at the top of `cursor/client.py` and add the handler.

- [ ] **Step 1: Read `tests/test_cursor_client.py` to understand test style**

```bash
cd /teamspace/studios/this_studio/wiwi && head -60 tests/test_cursor_client.py
```

- [ ] **Step 2: Write failing test in `tests/test_cursor_client.py`**

Add after existing imports and tests:

```python
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from handlers import EmptyResponseError, BackendError
from cursor.client import CursorClient


class _EmptyThenGoodSSE:
    """Fake httpx response that raises EmptyResponseError on first call,
    then yields a real delta on the second.
    """
    def __init__(self):
        self.status_code = 200
        self.headers = {}
        self._call_count = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    def aiter_bytes(self, chunk_size=65536):
        self._call_count += 1
        if self._call_count == 1:
            async def _empty():
                # Yield nothing so iter_deltas raises EmptyResponseError
                return
                yield  # makes it an async generator
            return _empty()
        else:
            async def _good():
                yield b'data: {"delta": "hello"}\ndata: [DONE]\n'
            return _good()


@pytest.mark.asyncio
async def test_empty_response_error_is_retried():
    """EmptyResponseError from iter_deltas must trigger a retry, not bubble immediately.

    First upstream call returns empty body (EmptyResponseError).
    Second call returns a valid delta. The stream must yield 'hello' from the second call.
    """
    import httpx
    from cursor.client import CursorClient
    from cursor.credentials import CredentialPool

    fake_response = _EmptyThenGoodSSE()
    call_count = 0

    async def fake_stream_ctx(method, url, **kwargs):
        nonlocal call_count
        call_count += 1
        return fake_response

    # Build a minimal fake httpx client whose stream() context manager
    # returns our fake_response object on each call
    fake_http = MagicMock()
    fake_http.stream = MagicMock()
    fake_http.stream.return_value.__aenter__ = AsyncMock(return_value=fake_response)
    fake_http.stream.return_value.__aexit__ = AsyncMock(return_value=False)

    fake_pool = MagicMock()
    fake_pool.next.return_value = None
    fake_pool.build_request_headers.return_value = {"Cookie": "test"}
    fake_pool.mark_error = MagicMock()
    fake_pool.mark_success = MagicMock()

    client = CursorClient(http_client=fake_http, pool=fake_pool)

    # Patch asyncio.sleep to avoid real waits
    with patch("cursor.client.asyncio.sleep", new=AsyncMock()):
        # Patch settings.retry_attempts to 2 so the second call is made
        with patch("cursor.client.settings") as mock_settings:
            mock_settings.retry_attempts = 2
            mock_settings.retry_backoff_seconds = 0.01
            mock_settings.cursor_base_url = "https://cursor.com"
            mock_settings.cursor_context_file_path = "/workspace"
            mock_settings.user_agent = "test-agent"

            collected = []
            async for delta in client.stream([{"role": "user", "content": "hi"}], "cursor-fast"):
                collected.append(delta)

    assert collected == ["hello"], (
        f"Expected ['hello'] after retry but got {collected!r}. "
        "EmptyResponseError was not retried."
    )
```

- [ ] **Step 3: Run to confirm FAIL**

```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/test_cursor_client.py::test_empty_response_error_is_retried -v
```

Expected: test fails — `EmptyResponseError` is re-raised immediately, `collected` is empty or the test raises.

- [ ] **Step 4: Add `EmptyResponseError` import to `cursor/client.py`**

At the top of `cursor/client.py`, find the existing `handlers` import:

```python
from handlers import (
    BackendError,
    CredentialError,
    RateLimitError,
    TimeoutError,
)
```

Add `EmptyResponseError`:

```python
from handlers import (
    BackendError,
    CredentialError,
    EmptyResponseError,
    RateLimitError,
    TimeoutError,
)
```

- [ ] **Step 5: Add `except EmptyResponseError` handler in `cursor/client.py`**

In the `stream()` method retry loop, find the bare exception handler:

```python
            except Exception as exc:
                # If it's another error (e.g. EmptyResponseError), just bubble it or break
                if _cred:
                    self._pool.mark_error(_cred)
                raise exc
```

Insert a new handler **before** it:

```python
            except EmptyResponseError as exc:
                if _cred:
                    self._pool.mark_error(_cred)
                last_exc = BackendError(f"Empty upstream response (attempt {attempt + 1}): {exc}")
                if attempt + 1 < settings.retry_attempts:
                    base = settings.retry_backoff_seconds * (2 ** attempt)
                    jitter = random.uniform(0, base * 0.3)  # nosec B311 — jitter, not crypto
                    await asyncio.sleep(min(base + jitter, 30.0))
                continue
            except Exception as exc:
                # If it's another error (e.g. EmptyResponseError), just bubble it or break
                if _cred:
                    self._pool.mark_error(_cred)
                raise exc
```

- [ ] **Step 6: Run to confirm PASS**

```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/test_cursor_client.py::test_empty_response_error_is_retried -v
```

Expected: PASS.

- [ ] **Step 7: Run full cursor client test suite**

```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/test_cursor_client.py tests/test_sse.py -v
```

Expected: all PASS.

- [ ] **Step 8: Run full test suite**

```bash
cd /teamspace/studios/this_studio/wiwi && python -m pytest tests/ -m 'not integration' -v
```

Expected: all passing.

- [ ] **Step 9: Commit**

```bash
cd /teamspace/studios/this_studio/wiwi && git add cursor/client.py tests/test_cursor_client.py
git commit -m "fix(client): retry EmptyResponseError with backoff instead of re-raising immediately"
```

---

## Final: Update UPDATES.md and push

- [ ] **Step 1: Update `UPDATES.md`**

Add a new session entry at the bottom:

```markdown
## Session 61 — Three bug fixes: partial marker leak, rate limiter TOCTOU, EmptyResponseError retry (2026-03-18)

### What changed

| File | Change |
|---|---|
| `pipeline/stream_openai.py` | Added `_TOOL_MARKER`, `_TOOL_MARKER_PREFIXES`, `_safe_emit_len()`. Replaced both per-delta emit sites to use `safe_end = _safe_emit_len(visible_text)` instead of `len(visible_text)`. |
| `middleware/rate_limit.py` | Added `TokenBucket.refund()`. Rewrote `DualBucketRateLimiter.consume()` to use consume return values and refund RPS on RPM failure, eliminating the peek+consume TOCTOU race and the silent discard of consume() return values. |
| `cursor/client.py` | Added `EmptyResponseError` to imports. Added `except EmptyResponseError` handler in `stream()` retry loop, wrapping as `BackendError` and continuing with backoff. |
| `tests/test_pipeline.py` | Added 7 unit tests for `_safe_emit_len` and 1 integration test for the partial marker holdback behaviour. |
| `tests/test_rate_limit.py` | Added 4 tests: `test_dual_bucket_consume_return_values_are_used`, `test_token_bucket_refund_restores_token`, `test_token_bucket_refund_capped_at_burst`, `test_token_bucket_refund_disabled_when_rate_zero`. |
| `tests/test_cursor_client.py` | Added `test_empty_response_error_is_retried` with fake two-call response fixture. |

### Why

- **Bug 1:** `_find_marker_pos` requires the complete `[assistant_tool_calls]` string. Partial chunks arriving mid-stream were emitted before the holdback could fire, leaking the marker prefix to the client.
- **Bug 2:** `DualBucketRateLimiter.consume()` used four separate lock acquisitions (peek+peek+consume+consume). The return values of both consume calls were silently discarded. Structural TOCTOU race latent under any thread-parallel access.
- **Bug 3:** `EmptyResponseError` hit the bare `except Exception: raise exc` in `cursor/client.py`, bypassing the retry loop entirely. One transient empty response killed the whole request.

### Commits

| SHA | Description |
|---|---|
| TBD | fix(pipeline): hold back partial [assistant_tool_calls] prefixes |
| TBD | fix(rate_limit): eliminate peek+consume TOCTOU race; add TokenBucket.refund() |
| TBD | fix(client): retry EmptyResponseError with backoff instead of re-raising immediately |
```

- [ ] **Step 2: Commit UPDATES.md**

```bash
cd /teamspace/studios/this_studio/wiwi && git add UPDATES.md
git commit -m "docs: update UPDATES.md for session 61 — three bug fixes"
```

- [ ] **Step 3: Push**

```bash
cd /teamspace/studios/this_studio/wiwi && git push
```

---

Plan complete and saved to `docs/superpowers/plans/2026-03-18-three-bug-fixes.md`. Ready to execute?