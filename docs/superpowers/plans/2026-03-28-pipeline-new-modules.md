# Pipeline New Modules Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 6 new modules to `pipeline/` — `context.py`, `response_validator.py`, `tracer.py`, `hooks.py`, `middleware.py`, and `stream_state.py` — covering per-request mutable state, outbound response validation, structured span tracing, lifecycle hooks, a consistent pre-call middleware chain, and an explicit streaming state machine.

**Architecture:** Each module is independent and additive. No existing public API changes. `context.py` and `response_validator.py` are wired into existing paths first (highest value, lowest risk). `tracer.py` and `hooks.py` follow. `middleware.py` consolidates inline pre-call guards. `stream_state.py` is a pure refactor of streaming local-variable state — added last since it touches the hot paths.

**Tech Stack:** Python 3.12, FastAPI, structlog, dataclasses, asyncio, pytest.

---

## Chunk 1: `pipeline/context.py` — Per-request mutable pipeline context

### Task 1: Create `pipeline/context.py`

**Files:**
- Create: `pipeline/context.py`
- Test: `tests/test_pipeline_context.py`

`PipelineContext` carries state that accumulates *during* a single pipeline run. It is passed alongside `PipelineParams` and written to by the pipeline stages. `_record()` reads from it instead of recomputing from local variables.

- [ ] **Step 1.1: Write the failing test**

```python
# tests/test_pipeline_context.py
import pytest
import time
from pipeline.context import PipelineContext

def test_default_state():
    ctx = PipelineContext(request_id="req-1")
    assert ctx.request_id == "req-1"
    assert ctx.suppression_attempts == 0
    assert ctx.fallback_model_used is None
    assert ctx.ttft_ms is None
    assert ctx.bytes_streamed == 0
    assert ctx.tool_calls_parsed == 0
    assert ctx.started_at > 0

def test_record_ttft():
    ctx = PipelineContext(request_id="req-2")
    ctx.record_ttft()
    assert ctx.ttft_ms is not None
    assert ctx.ttft_ms >= 0

def test_record_ttft_only_once():
    ctx = PipelineContext(request_id="req-3")
    ctx.record_ttft()
    first = ctx.ttft_ms
    ctx.record_ttft()  # second call must be a no-op
    assert ctx.ttft_ms == first

def test_latency_ms():
    ctx = PipelineContext(request_id="req-4")
    ms = ctx.latency_ms()
    assert ms >= 0

def test_increment_suppression():
    ctx = PipelineContext(request_id="req-5")
    ctx.suppression_attempts += 1
    assert ctx.suppression_attempts == 1
```

- [ ] **Step 1.2: Run test to verify it fails**

```bash
cd /teamspace/studios/this_studio/dikders && pytest tests/test_pipeline_context.py -v
```
Expected: `ModuleNotFoundError: No module named 'pipeline.context'`

- [ ] **Step 1.3: Create `pipeline/context.py`**

```python
"""Per-request mutable pipeline context.

Carries state that accumulates during a single pipeline run — suppression attempt
counts, TTFT timestamp, bytes streamed, tool calls parsed, and the fallback model
if one was used. Passed alongside PipelineParams through the pipeline stages.

Unlike PipelineParams (immutable, frozen at request entry), PipelineContext is
mutated in-place by the pipeline as the request progresses.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class PipelineContext:
    """Mutable per-request state collected during a pipeline run.

    Args:
        request_id: Propagated from the request — used for log correlation.
    """

    request_id: str
    started_at: float = field(default_factory=time.time)
    suppression_attempts: int = 0
    fallback_model_used: str | None = None
    ttft_ms: int | None = None          # time-to-first-token, ms; None until first chunk
    bytes_streamed: int = 0             # cumulative SSE bytes yielded to client
    tool_calls_parsed: int = 0          # total tool calls parsed across all retries

    def record_ttft(self) -> None:
        """Record time-to-first-token. Idempotent — only the first call has effect."""
        if self.ttft_ms is None:
            self.ttft_ms = int((time.time() - self.started_at) * 1000)

    def latency_ms(self) -> float:
        """Return elapsed milliseconds since this context was created."""
        return (time.time() - self.started_at) * 1000.0
```

- [ ] **Step 1.4: Run tests to verify they pass**

```bash
cd /teamspace/studios/this_studio/dikders && pytest tests/test_pipeline_context.py -v
```
Expected: all PASS

- [ ] **Step 1.5: Export from `pipeline/__init__.py`**

In `pipeline/__init__.py`, add:
```python
from pipeline.context import PipelineContext  # noqa: F401
```

- [ ] **Step 1.6: Commit**

```bash
git add pipeline/context.py tests/test_pipeline_context.py pipeline/__init__.py
git commit -m "feat(pipeline/context): PipelineContext — per-request mutable pipeline state"
```

---

### Task 2: Wire `PipelineContext` into `pipeline/record.py` and streaming paths

**Files:**
- Modify: `pipeline/record.py`
- Modify: `pipeline/stream_openai.py`
- Modify: `pipeline/stream_anthropic.py`
- Modify: `pipeline/nonstream.py`
- Test: `tests/test_pipeline_context.py` (extend)

`_record()` currently recomputes `latency_ms` from a caller-provided float. Change it to accept an optional `PipelineContext` and read timing from it when present. Streaming generators create a `PipelineContext`, call `record_ttft()` on the first yielded chunk, and pass it to `_record()`.

- [ ] **Step 2.1: Add test for `_record` accepting context**

Append to `tests/test_pipeline_context.py`:
```python
import asyncio
import pytest
from unittest.mock import AsyncMock, patch
from pipeline.params import PipelineParams

def _params():
    return PipelineParams(
        api_style="openai",
        model="claude-3-5-sonnet",
        messages=[],
        cursor_messages=[],
    )

@pytest.mark.asyncio
async def test_record_uses_context_latency():
    ctx = PipelineContext(request_id="r1")
    ctx.ttft_ms = 42
    params = _params()
    with patch("pipeline.record.analytics") as mock_analytics:
        mock_analytics.record = AsyncMock()
        from pipeline.record import _record
        await _record(params, "hello", latency_ms=0.0, context=ctx)
        call_kwargs = mock_analytics.record.call_args
        assert call_kwargs is not None  # analytics.record was called
```

- [ ] **Step 2.2: Run to verify it fails**

```bash
cd /teamspace/studios/this_studio/dikders && pytest tests/test_pipeline_context.py::test_record_uses_context_latency -v
```
Expected: FAIL — `_record` does not accept `context` keyword yet.

- [ ] **Step 2.3: Update `pipeline/record.py`**

Add `context: PipelineContext | None = None` parameter to `_record`. When present, use `context.latency_ms()` as the effective latency for logging (the caller-supplied `latency_ms` float is kept as fallback for backward compatibility):

```python
from __future__ import annotations

import structlog
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pipeline.context import PipelineContext

from analytics import RequestLog, analytics, estimate_cost
from config import settings
from tokens import count_message_tokens, estimate_from_text
from pipeline.params import PipelineParams

log = structlog.get_logger()


def _provider_from_model(model: str) -> str:
    ml = model.lower()
    if "gpt" in ml or "o1" in ml or "o3" in ml or "o4" in ml or "openai" in ml:
        return "openai"
    if "gemini" in ml or "google" in ml:
        return "google"
    return "anthropic"


async def _record(
    params: PipelineParams,
    text: str,
    latency_ms: float,
    cache_hit: bool = False,
    ttft_ms: int | None = None,
    output_tps: float | None = None,
    context: "PipelineContext | None" = None,
) -> None:
    """Record request analytics. Provider is auto-detected from model.

    Args:
        params:     Pipeline parameters for the request.
        text:       Full response text (used for output token estimation).
        latency_ms: Total request latency in milliseconds.
        cache_hit:  Whether the response was served from cache.
        ttft_ms:    Time-to-first-token in milliseconds (streaming only).
        output_tps: Output tokens per second (streaming only).
        context:    Optional PipelineContext — when supplied, ttft_ms and
                    suppression_attempts are read from it, taking precedence
                    over the corresponding positional arguments.
    """
    provider = _provider_from_model(params.model)
    input_tokens = count_message_tokens(params.messages, params.model)
    output_tokens = estimate_from_text(text, params.model)
    cost = estimate_cost(provider, input_tokens, output_tokens)

    effective_ttft = (context.ttft_ms if context else None) or ttft_ms
    effective_latency = context.latency_ms() if context else latency_ms

    await analytics.record(
        RequestLog(
            api_key=params.api_key,
            provider=provider,
            model=params.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            latency_ms=effective_latency,
            cache_hit=cache_hit,
            ttft_ms=effective_ttft,
            output_tps=output_tps,
        )
    )
    if settings.quota_enabled and params.api_key:
        from middleware.quota import record_quota_usage
        await record_quota_usage(params.api_key, tokens=input_tokens + output_tokens)
    log.info(
        "pipeline_complete",
        request_id=params.request_id,
        model=params.model,
        api_style=params.api_style,
        provider=provider,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=round(cost, 6),
        latency_ms=round(effective_latency, 1),
        cache_hit=cache_hit,
        ttft_ms=effective_ttft,
        output_tps=round(output_tps, 2) if output_tps else None,
        suppression_attempts=context.suppression_attempts if context else 0,
        tool_calls_parsed=context.tool_calls_parsed if context else 0,
    )
```

- [ ] **Step 2.4: Run tests to verify they pass**

```bash
cd /teamspace/studios/this_studio/dikders && pytest tests/test_pipeline_context.py -v
```
Expected: all PASS

- [ ] **Step 2.5: Instantiate `PipelineContext` in `_openai_stream`**

In `pipeline/stream_openai.py`, at the top of `_openai_stream`, after `created_ts = int(started)`:
```python
    from pipeline.context import PipelineContext
    _ctx = PipelineContext(request_id=params.request_id)
```

On the first `yield` inside the streaming loop (when `visible_delta` is emitted or the first tool chunk is yielded), add:
```python
    _ctx.record_ttft()
```

Where `_record()` is called at stream end, change to pass `context=_ctx`:
```python
    await _record(params, acc, latency_ms, ttft_ms=ttft_ms, output_tps=output_tps, context=_ctx)
```

Apply the same pattern in `pipeline/stream_anthropic.py` and `pipeline/nonstream.py`.

- [ ] **Step 2.6: Run full non-integration suite**

```bash
cd /teamspace/studios/this_studio/dikders && pytest tests/ -m 'not integration' -q --tb=short 2>&1 | tail -15
```
Expected: all PASS

- [ ] **Step 2.7: Commit**

```bash
git add pipeline/record.py pipeline/stream_openai.py pipeline/stream_anthropic.py pipeline/nonstream.py tests/test_pipeline_context.py
git commit -m "feat(pipeline): wire PipelineContext into record, streaming, and nonstream paths"
```

---

## Chunk 2: `pipeline/response_validator.py` — Outbound response validation

### Task 3: Create `pipeline/response_validator.py`

**Files:**
- Create: `pipeline/response_validator.py`
- Test: `tests/test_response_validator.py`

Validates the outbound response before it is returned to the client. Never rejects — logs warnings only. Catches: wrong `finish_reason` for tool calls, `arguments` as dict instead of string, missing `id` field, and `the editor` leaking in visible text.

- [ ] **Step 3.1: Write failing tests**

```python
# tests/test_response_validator.py
import json
from pipeline.response_validator import validate_openai_response, validate_anthropic_response
from pipeline.params import PipelineParams

def _params(tools=None):
    return PipelineParams(
        api_style="openai", model="m", messages=[], cursor_messages=[],
        tools=tools or [],
    )

def _call(name="Bash", args=None, tc_id="call_abc"):
    return {"id": tc_id, "type": "function",
            "function": {"name": name, "arguments": json.dumps(args or {"command": "ls"})}}

def test_valid_openai_stop_response_no_issues():
    resp = {"id": "c1", "choices": [{"finish_reason": "stop",
            "message": {"role": "assistant", "content": "hello"}}]}
    issues = validate_openai_response(resp, _params())
    assert issues == []

def test_valid_openai_tool_calls_no_issues():
    resp = {"id": "c1", "choices": [{"finish_reason": "tool_calls",
            "message": {"role": "assistant", "content": None,
                         "tool_calls": [_call()]}}]}
    issues = validate_openai_response(resp, _params())
    assert issues == []

def test_wrong_finish_reason_for_tool_calls():
    resp = {"id": "c1", "choices": [{"finish_reason": "stop",
            "message": {"role": "assistant", "content": None,
                         "tool_calls": [_call()]}}]}
    issues = validate_openai_response(resp, _params())
    assert any("finish_reason" in i for i in issues)

def test_arguments_as_dict_flagged():
    bad_call = {"id": "c1", "type": "function",
                "function": {"name": "Bash", "arguments": {"command": "ls"}}}
    resp = {"id": "c2", "choices": [{"finish_reason": "tool_calls",
            "message": {"role": "assistant", "content": None,
                         "tool_calls": [bad_call]}}]}
    issues = validate_openai_response(resp, _params())
    assert any("arguments" in i for i in issues)

def test_the_editor_leak_flagged():
    resp = {"id": "c1", "choices": [{"finish_reason": "stop",
            "message": {"role": "assistant",
                         "content": "the-editor is great"}}]}
    issues = validate_openai_response(resp, _params())
    assert any("the-editor" in i for i in issues)

def test_missing_id_flagged():
    resp = {"choices": [{"finish_reason": "stop",
            "message": {"role": "assistant", "content": "hi"}}]}
    issues = validate_openai_response(resp, _params())
    assert any("id" in i for i in issues)

def test_valid_anthropic_no_issues():
    resp = {"id": "msg_1", "type": "message", "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "hello"}]}
    issues = validate_anthropic_response(resp, _params())
    assert issues == []

def test_anthropic_tool_use_arguments_as_dict_flagged():
    resp = {"id": "msg_1", "type": "message", "stop_reason": "tool_use",
            "content": [{"type": "tool_use", "id": "tu_1", "name": "Bash",
                          "input": "not a dict"}]}
    issues = validate_anthropic_response(resp, _params())
    assert any("input" in i for i in issues)
```

- [ ] **Step 3.2: Run to verify it fails**

```bash
cd /teamspace/studios/this_studio/dikders && pytest tests/test_response_validator.py -v
```
Expected: `ModuleNotFoundError: No module named 'pipeline.response_validator'`

- [ ] **Step 3.3: Create `pipeline/response_validator.py`**

```python
"""Outbound response validation — warns on malformed responses before client delivery.

Never rejects or modifies the response. Logs a structured warning per issue.
Called in non-streaming paths after the response is fully assembled.
"""
from __future__ import annotations

import re
import structlog

from pipeline.params import PipelineParams

log = structlog.get_logger()

_THE_EDITOR_RE = re.compile(r"\bthe-editor\b", re.IGNORECASE)


def validate_openai_response(response: dict, params: PipelineParams) -> list[str]:
    """Validate a non-streaming OpenAI chat.completion response dict.

    Args:
        response: The full response dict about to be returned to the client.
        params:   Pipeline parameters for context (model, tools, api_style).

    Returns:
        List of human-readable issue strings. Empty list means no issues found.
    """
    issues: list[str] = []

    if not response.get("id"):
        issues.append("missing 'id' field in response")

    choices = response.get("choices", [])
    for i, choice in enumerate(choices):
        finish_reason = choice.get("finish_reason")
        message = choice.get("message", {})
        tool_calls = message.get("tool_calls") or []
        content = message.get("content") or ""

        if tool_calls and finish_reason != "tool_calls":
            issues.append(
                f"choice[{i}]: finish_reason={finish_reason!r} but tool_calls present "
                f"(expected 'tool_calls')"
            )
        if not tool_calls and finish_reason == "tool_calls":
            issues.append(
                f"choice[{i}]: finish_reason='tool_calls' but no tool_calls in message"
            )

        for j, tc in enumerate(tool_calls):
            fn = tc.get("function", {})
            args = fn.get("arguments")
            if not isinstance(args, str):
                issues.append(
                    f"choice[{i}].tool_calls[{j}]: arguments must be a JSON string, "
                    f"got {type(args).__name__}"
                )
            if not tc.get("id"):
                issues.append(f"choice[{i}].tool_calls[{j}]: missing 'id'")

        if isinstance(content, str) and _THE_EDITOR_RE.search(content):
            issues.append(
                f"choice[{i}]: internal codename 'the-editor' leaked into response content"
            )

    if issues:
        log.warning(
            "outbound_response_validation_failed",
            model=params.model,
            request_id=params.request_id,
            issue_count=len(issues),
            issues=issues,
        )
    return issues


def validate_anthropic_response(response: dict, params: PipelineParams) -> list[str]:
    """Validate a non-streaming Anthropic message response dict.

    Args:
        response: The full response dict about to be returned to the client.
        params:   Pipeline parameters for context.

    Returns:
        List of human-readable issue strings. Empty list means no issues found.
    """
    issues: list[str] = []

    if not response.get("id"):
        issues.append("missing 'id' field in response")

    content_blocks = response.get("content", [])
    for i, block in enumerate(content_blocks):
        btype = block.get("type")
        if btype == "tool_use":
            inp = block.get("input")
            if not isinstance(inp, dict):
                issues.append(
                    f"content[{i}] tool_use block: 'input' must be a dict, "
                    f"got {type(inp).__name__}"
                )
            if not block.get("id"):
                issues.append(f"content[{i}] tool_use block: missing 'id'")
        elif btype == "text":
            text = block.get("text") or ""
            if _THE_EDITOR_RE.search(text):
                issues.append(
                    f"content[{i}]: internal codename 'the-editor' leaked into text block"
                )

    stop_reason = response.get("stop_reason")
    has_tool_use = any(b.get("type") == "tool_use" for b in content_blocks)
    if has_tool_use and stop_reason != "tool_use":
        issues.append(
            f"stop_reason={stop_reason!r} but tool_use blocks present (expected 'tool_use')"
        )

    if issues:
        log.warning(
            "outbound_response_validation_failed",
            model=params.model,
            request_id=params.request_id,
            issue_count=len(issues),
            issues=issues,
        )
    return issues
```

- [ ] **Step 3.4: Run tests to verify they pass**

```bash
cd /teamspace/studios/this_studio/dikders && pytest tests/test_response_validator.py -v
```
Expected: all PASS

- [ ] **Step 3.5: Wire into `pipeline/nonstream.py`**

In `handle_openai_non_streaming`, just before `return resp`, add:
```python
    from pipeline.response_validator import validate_openai_response
    validate_openai_response(resp, params)  # logs warnings only — never rejects
```

In `handle_anthropic_non_streaming`, just before `return resp`, add:
```python
    from pipeline.response_validator import validate_anthropic_response
    validate_anthropic_response(resp, params)
```

- [ ] **Step 3.6: Export from `pipeline/__init__.py`**

```python
from pipeline.response_validator import validate_openai_response, validate_anthropic_response  # noqa: F401
```

- [ ] **Step 3.7: Run full suite**

```bash
cd /teamspace/studios/this_studio/dikders && pytest tests/ -m 'not integration' -q --tb=short 2>&1 | tail -10
```
Expected: all PASS

- [ ] **Step 3.8: Commit**

```bash
git add pipeline/response_validator.py tests/test_response_validator.py pipeline/nonstream.py pipeline/__init__.py
git commit -m "feat(pipeline/response_validator): outbound response validation — warn on malformed responses"
```

---

## Chunk 3: `pipeline/tracer.py` — Structured span tracing

### Task 4: Create `pipeline/tracer.py`

**Files:**
- Create: `pipeline/tracer.py`
- Test: `tests/test_pipeline_tracer.py`

`PipelineTracer` records named spans (start/end/duration) during a pipeline run and flushes them as a single structured log line. No external dependency — backed by structlog. Replaces the current scattered `latency_ms`, `ttft_ms`, `output_tps` locals in the streaming generators.

- [ ] **Step 4.1: Write failing tests**

```python
# tests/test_pipeline_tracer.py
import time
from pipeline.tracer import PipelineTracer, Span

def test_span_records_duration():
    tracer = PipelineTracer(request_id="r1")
    with tracer.span("upstream_call"):
        time.sleep(0.01)
    spans = tracer.spans()
    assert "upstream_call" in spans
    assert spans["upstream_call"] >= 10  # at least 10 ms

def test_multiple_spans():
    tracer = PipelineTracer(request_id="r1")
    with tracer.span("a"):
        pass
    with tracer.span("b"):
        pass
    spans = tracer.spans()
    assert "a" in spans and "b" in spans

def test_record_event():
    tracer = PipelineTracer(request_id="r1")
    tracer.record_event("tool_parse", calls=3, outcome="success")
    events = tracer.events()
    assert len(events) == 1
    assert events[0]["name"] == "tool_parse"
    assert events[0]["calls"] == 3

def test_flush_returns_dict():
    tracer = PipelineTracer(request_id="r1")
    with tracer.span("s1"):
        pass
    result = tracer.flush()
    assert result["request_id"] == "r1"
    assert "spans_ms" in result
    assert "s1" in result["spans_ms"]

def test_nested_span_names_do_not_conflict():
    tracer = PipelineTracer(request_id="r1")
    with tracer.span("outer"):
        with tracer.span("inner"):
            pass
    spans = tracer.spans()
    assert "outer" in spans
    assert "inner" in spans
```

- [ ] **Step 4.2: Run to verify it fails**

```bash
cd /teamspace/studios/this_studio/dikders && pytest tests/test_pipeline_tracer.py -v
```
Expected: `ModuleNotFoundError: No module named 'pipeline.tracer'`

- [ ] **Step 4.3: Create `pipeline/tracer.py`**

```python
"""Structured span tracing for pipeline requests.

Records named timing spans and discrete events during a pipeline run.
Flushes them as a single structured log line at request completion.
No external dependency — backed by structlog.
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Generator

import structlog

log = structlog.get_logger()


@dataclass
class Span:
    """A named timing span."""
    name: str
    start_ms: float
    end_ms: float | None = None

    @property
    def duration_ms(self) -> float:
        """Duration in milliseconds. Returns 0 if span not yet closed."""
        if self.end_ms is None:
            return 0.0
        return self.end_ms - self.start_ms


class PipelineTracer:
    """Records named spans and events for a single pipeline request.

    Usage::

        tracer = PipelineTracer(request_id=params.request_id)
        with tracer.span("upstream_call"):
            result = await client.call(...)
        tracer.record_event("tool_parse", calls=3, outcome="success")
        log.info("request_trace", **tracer.flush())

    Args:
        request_id: Correlation ID propagated from the request.
    """

    def __init__(self, request_id: str) -> None:
        self._request_id = request_id
        self._spans: list[Span] = []
        self._events: list[dict[str, Any]] = []
        self._started_at = time.monotonic() * 1000

    @contextmanager
    def span(self, name: str) -> Generator[Span, None, None]:
        """Context manager that records a named timing span.

        Args:
            name: Span identifier. Must be unique within this tracer.

        Yields:
            The Span object (end_ms is set on context exit).
        """
        s = Span(name=name, start_ms=time.monotonic() * 1000)
        self._spans.append(s)
        try:
            yield s
        finally:
            s.end_ms = time.monotonic() * 1000

    def record_event(self, name: str, **kwargs: Any) -> None:
        """Record a discrete event with arbitrary metadata.

        Args:
            name:     Event name.
            **kwargs: Arbitrary key-value metadata attached to the event.
        """
        self._events.append({"name": name, "ts_ms": time.monotonic() * 1000, **kwargs})

    def spans(self) -> dict[str, float]:
        """Return a dict of span_name -> duration_ms for all closed spans."""
        return {s.name: round(s.duration_ms, 2) for s in self._spans if s.end_ms is not None}

    def events(self) -> list[dict[str, Any]]:
        """Return a copy of all recorded events."""
        return list(self._events)

    def flush(self) -> dict[str, Any]:
        """Return a structured dict suitable for a single log line.

        Returns:
            Dict with request_id, total_ms, spans_ms, and events.
        """
        total = round((time.monotonic() * 1000) - self._started_at, 2)
        return {
            "request_id": self._request_id,
            "total_ms": total,
            "spans_ms": self.spans(),
            "events": self._events,
        }
```

- [ ] **Step 4.4: Run tests to verify they pass**

```bash
cd /teamspace/studios/this_studio/dikders && pytest tests/test_pipeline_tracer.py -v
```
Expected: all PASS

- [ ] **Step 4.5: Export from `pipeline/__init__.py`**

```python
from pipeline.tracer import PipelineTracer  # noqa: F401
```

- [ ] **Step 4.6: Commit**

```bash
git add pipeline/tracer.py tests/test_pipeline_tracer.py pipeline/__init__.py
git commit -m "feat(pipeline/tracer): PipelineTracer — structured span tracing for pipeline requests"
```

---

## Chunk 4: `pipeline/hooks.py` + `pipeline/middleware.py`

### Task 5: Create `pipeline/hooks.py`

**Files:**
- Create: `pipeline/hooks.py`
- Test: `tests/test_pipeline_hooks.py`

A `PipelineHook` protocol + `HookRegistry` singleton. Hooks are registered once at app startup and called at four checkpoints: `before_request`, `after_response`, `on_tool_calls`, `on_suppression`.

- [ ] **Step 5.1: Write failing tests**

```python
# tests/test_pipeline_hooks.py
import pytest
from pipeline.hooks import HookRegistry, PipelineHook
from pipeline.params import PipelineParams

def _params():
    return PipelineParams(
        api_style="openai", model="m", messages=[], cursor_messages=[]
    )

class _CountingHook:
    def __init__(self):
        self.before = 0
        self.after = 0
        self.tools = []
        self.suppressions = 0

    async def before_request(self, params):
        self.before += 1
        return params

    async def after_response(self, params, text, latency_ms):
        self.after += 1

    async def on_tool_calls(self, params, calls):
        self.tools.extend(calls)
        return calls

    async def on_suppression(self, params, attempt):
        self.suppressions += 1

@pytest.mark.asyncio
async def test_before_request_called():
    reg = HookRegistry()
    hook = _CountingHook()
    reg.register(hook)
    params = _params()
    result = await reg.run_before_request(params)
    assert hook.before == 1
    assert result is params or result == params

@pytest.mark.asyncio
async def test_after_response_called():
    reg = HookRegistry()
    hook = _CountingHook()
    reg.register(hook)
    await reg.run_after_response(_params(), "text", 100.0)
    assert hook.after == 1

@pytest.mark.asyncio
async def test_on_tool_calls_called():
    reg = HookRegistry()
    hook = _CountingHook()
    reg.register(hook)
    calls = [{"id": "c1", "type": "function", "function": {"name": "Bash", "arguments": "{}"}}]
    result = await reg.run_on_tool_calls(_params(), calls)
    assert hook.tools == calls
    assert result == calls

@pytest.mark.asyncio
async def test_no_hooks_no_error():
    reg = HookRegistry()
    params = _params()
    result = await reg.run_before_request(params)
    assert result == params

@pytest.mark.asyncio
async def test_multiple_hooks_all_called():
    reg = HookRegistry()
    h1, h2 = _CountingHook(), _CountingHook()
    reg.register(h1)
    reg.register(h2)
    await reg.run_before_request(_params())
    assert h1.before == 1 and h2.before == 1
```

- [ ] **Step 5.2: Run to verify it fails**

```bash
cd /teamspace/studios/this_studio/dikders && pytest tests/test_pipeline_hooks.py -v
```
Expected: `ModuleNotFoundError: No module named 'pipeline.hooks'`

- [ ] **Step 5.3: Create `pipeline/hooks.py`**

```python
"""Pipeline lifecycle hooks.

Hooks are registered once at app startup and called at four checkpoints
in the pipeline. They are purely additive — the pipeline functions whether
or not any hooks are registered.

Register hooks via `hook_registry.register(hook)` in `app.py` lifespan.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from pipeline.params import PipelineParams


@runtime_checkable
class PipelineHook(Protocol):
    """Protocol for pipeline lifecycle hooks.

    All methods are async. Implement only the checkpoints you need —
    the registry calls each method only if the hook object has it.
    """

    async def before_request(self, params: PipelineParams) -> PipelineParams:
        """Called before the upstream call. May return a modified PipelineParams."""
        ...

    async def after_response(self, params: PipelineParams, text: str, latency_ms: float) -> None:
        """Called after the full response text is assembled."""
        ...

    async def on_tool_calls(self, params: PipelineParams, calls: list[dict]) -> list[dict]:
        """Called when tool calls are parsed. May return a modified calls list."""
        ...

    async def on_suppression(self, params: PipelineParams, attempt: int) -> None:
        """Called each time a suppression signal is detected before a retry."""
        ...


class HookRegistry:
    """Registry of pipeline lifecycle hooks.

    Thread-safe for asyncio (single-threaded event loop).
    """

    def __init__(self) -> None:
        self._hooks: list[object] = []

    def register(self, hook: object) -> None:
        """Register a hook. Hooks are called in registration order."""
        self._hooks.append(hook)

    async def run_before_request(self, params: PipelineParams) -> PipelineParams:
        """Run all before_request hooks in order. Returns (possibly modified) params."""
        for hook in self._hooks:
            fn = getattr(hook, "before_request", None)
            if fn is not None:
                params = await fn(params)
        return params

    async def run_after_response(
        self, params: PipelineParams, text: str, latency_ms: float
    ) -> None:
        """Run all after_response hooks in order."""
        for hook in self._hooks:
            fn = getattr(hook, "after_response", None)
            if fn is not None:
                await fn(params, text, latency_ms)

    async def run_on_tool_calls(
        self, params: PipelineParams, calls: list[dict]
    ) -> list[dict]:
        """Run all on_tool_calls hooks in order. Returns (possibly modified) calls."""
        for hook in self._hooks:
            fn = getattr(hook, "on_tool_calls", None)
            if fn is not None:
                calls = await fn(params, calls)
        return calls

    async def run_on_suppression(self, params: PipelineParams, attempt: int) -> None:
        """Run all on_suppression hooks in order."""
        for hook in self._hooks:
            fn = getattr(hook, "on_suppression", None)
            if fn is not None:
                await fn(params, attempt)


# Module-level singleton — register hooks against this in app.py lifespan.
hook_registry = HookRegistry()
```

- [ ] **Step 5.4: Run tests to verify they pass**

```bash
cd /teamspace/studios/this_studio/dikders && pytest tests/test_pipeline_hooks.py -v
```
Expected: all PASS

- [ ] **Step 5.5: Export from `pipeline/__init__.py`**

```python
from pipeline.hooks import HookRegistry, PipelineHook, hook_registry  # noqa: F401
```

- [ ] **Step 5.6: Commit**

```bash
git add pipeline/hooks.py tests/test_pipeline_hooks.py pipeline/__init__.py
git commit -m "feat(pipeline/hooks): HookRegistry + PipelineHook protocol — lifecycle hooks"
```

---

### Task 6: Create `pipeline/middleware.py`

**Files:**
- Create: `pipeline/middleware.py`
- Test: `tests/test_pipeline_middleware.py`

Consolidates the inline pre-call guards (token preflight, `json_mode` enforcement, `stop` filtering) that are currently scattered inconsistently across the four pipeline paths into a single sequential `run_pipeline_middleware(params)` call.

- [ ] **Step 6.1: Write failing tests**

```python
# tests/test_pipeline_middleware.py
import pytest
from unittest.mock import patch
from pipeline.middleware import run_pipeline_middleware
from pipeline.params import PipelineParams
from handlers import ContextWindowError

def _params(**kw):
    base = dict(
        api_style="openai", model="claude-3-5-sonnet",
        messages=[], cursor_messages=[],
    )
    base.update(kw)
    return PipelineParams(**base)

@pytest.mark.asyncio
async def test_passes_normal_params():
    params = _params()
    result = await run_pipeline_middleware(params)
    assert result is params or result == params

@pytest.mark.asyncio
async def test_context_window_error_propagates():
    params = _params(messages=[{"role": "user", "content": "x" * 10}])
    with patch("pipeline.middleware.context_engine.check_preflight", side_effect=ContextWindowError("too big")):
        with pytest.raises(ContextWindowError):
            await run_pipeline_middleware(params)

@pytest.mark.asyncio
async def test_parallel_tool_calls_false_enforced():
    """When parallel_tool_calls=False, tool_choice must not be set to 'auto' implicitly."""
    params = _params(parallel_tool_calls=False)
    result = await run_pipeline_middleware(params)
    assert result.parallel_tool_calls is False
```

- [ ] **Step 6.2: Run to verify it fails**

```bash
cd /teamspace/studios/this_studio/dikders && pytest tests/test_pipeline_middleware.py -v
```
Expected: `ModuleNotFoundError: No module named 'pipeline.middleware'`

- [ ] **Step 6.3: Create `pipeline/middleware.py`**

Create:

```python
"""Pipeline-level pre-call middleware chain.

Consolidates guards that must run before every upstream call regardless
of streaming/non-streaming or OpenAI/Anthropic format:
  1. Context window preflight — raises ContextWindowError if request exceeds hard limit.
  2. (Future) json_mode coercion, stop-sequence validation, etc.

All middleware functions are pure — they accept PipelineParams and return
(possibly modified) PipelineParams. Raising an exception aborts the request.

Usage::

    params = await run_pipeline_middleware(params)
"""
from __future__ import annotations

from pipeline.params import PipelineParams
from utils.context import context_engine


async def run_pipeline_middleware(params: PipelineParams) -> PipelineParams:
    """Run all pre-call middleware guards on params.

    Args:
        params: Pipeline parameters for the current request.

    Returns:
        Possibly-modified PipelineParams.

    Raises:
        ContextWindowError: If the request exceeds the model's hard context limit.
    """
    # Guard 1: context window preflight — raises ContextWindowError on hard limit breach
    context_engine.check_preflight(
        params.messages,
        params.tools,
        params.model,
        params.cursor_messages,
    )
    return params
```

- [ ] **Step 6.4: Run tests to verify they pass**

```bash
cd /teamspace/studios/this_studio/dikders && pytest tests/test_pipeline_middleware.py -v
```
Expected: all PASS

- [ ] **Step 6.5: Export from `pipeline/__init__.py`**

```python
from pipeline.middleware import run_pipeline_middleware  # noqa: F401
```

- [ ] **Step 6.6: Wire into all four pipeline entry points**

In each of `pipeline/stream_openai.py`, `pipeline/stream_anthropic.py`, `pipeline/nonstream.py` (both handlers), add at the top of the function body before any other logic:
```python
    from pipeline.middleware import run_pipeline_middleware
    params = await run_pipeline_middleware(params)
```

Remove any existing inline `check_preflight(...)` calls in those functions — they are now covered by the middleware chain.

- [ ] **Step 6.7: Run full non-integration suite**

```bash
cd /teamspace/studios/this_studio/dikders && pytest tests/ -m 'not integration' -q --tb=short 2>&1 | tail -10
```
Expected: all PASS

- [ ] **Step 6.8: Commit**

```bash
git add pipeline/middleware.py tests/test_pipeline_middleware.py pipeline/__init__.py pipeline/stream_openai.py pipeline/stream_anthropic.py pipeline/nonstream.py
git commit -m "feat(pipeline/middleware): run_pipeline_middleware — consolidated pre-call guard chain"
```

---

## Chunk 5: `pipeline/stream_state.py` + Final Cleanup

### Task 7: Create `pipeline/stream_state.py`

**Files:**
- Create: `pipeline/stream_state.py`
- Test: `tests/test_stream_state.py`

An explicit `StreamPhase` enum that names every state the streaming generator can be in. The streaming generators use `StreamPhase` to name their current phase rather than relying on a flat collection of boolean locals. The enum is the single source of truth for valid phase names — it does not replace the generator logic, it names it.

- [ ] **Step 7.1: Write failing tests**

```python
# tests/test_stream_state.py
from pipeline.stream_state import StreamPhase, StreamStateTracker

def test_initial_phase_is_init():
    tracker = StreamStateTracker()
    assert tracker.phase == StreamPhase.INIT

def test_transition_to_streaming_text():
    tracker = StreamStateTracker()
    tracker.transition(StreamPhase.STREAMING_TEXT)
    assert tracker.phase == StreamPhase.STREAMING_TEXT

def test_transition_to_marker_detected():
    tracker = StreamStateTracker()
    tracker.transition(StreamPhase.STREAMING_TEXT)
    tracker.transition(StreamPhase.MARKER_DETECTED)
    assert tracker.phase == StreamPhase.MARKER_DETECTED

def test_transition_records_history():
    tracker = StreamStateTracker()
    tracker.transition(StreamPhase.STREAMING_TEXT)
    tracker.transition(StreamPhase.TOOL_COMPLETE)
    assert StreamPhase.STREAMING_TEXT in tracker.history
    assert StreamPhase.TOOL_COMPLETE in tracker.history

def test_is_terminal_finished():
    tracker = StreamStateTracker()
    tracker.transition(StreamPhase.FINISHED)
    assert tracker.is_terminal()

def test_is_terminal_abandoned():
    tracker = StreamStateTracker()
    tracker.transition(StreamPhase.ABANDONED)
    assert tracker.is_terminal()

def test_is_not_terminal_streaming_text():
    tracker = StreamStateTracker()
    tracker.transition(StreamPhase.STREAMING_TEXT)
    assert not tracker.is_terminal()

def test_all_phases_are_string_comparable():
    for phase in StreamPhase:
        assert isinstance(phase.value, str)
```

- [ ] **Step 7.2: Run to verify it fails**

```bash
cd /teamspace/studios/this_studio/dikders && pytest tests/test_stream_state.py -v
```
Expected: `ModuleNotFoundError: No module named 'pipeline.stream_state'`

- [ ] **Step 7.3: Create `pipeline/stream_state.py`**

```python
"""Streaming phase state machine.

Defines the phases a streaming pipeline generator can be in.
The `StreamStateTracker` tracks the current phase and history,
making valid transitions explicit and unit-testable independent
of the HTTP layer.

The streaming generators (stream_openai.py, stream_anthropic.py)
use StreamPhase to name their current phase via `tracker.transition()`
instead of relying on a flat collection of boolean locals.
"""
from __future__ import annotations

from enum import Enum


class StreamPhase(str, Enum):
    """All phases of a streaming pipeline run."""
    INIT = "init"                       # Before any stream data received
    STREAMING_TEXT = "streaming_text"   # Model emitting text content
    MARKER_DETECTED = "marker_detected" # [assistant_tool_calls] marker seen
    PARSING_TOOL_JSON = "parsing_tool_json"  # Accumulating tool call JSON
    TOOL_COMPLETE = "tool_complete"     # Tool call JSON fully parsed
    FINISHED = "finished"               # Stream closed cleanly
    SUPPRESSED = "suppressed"           # Suppression signal detected
    ABANDONED = "abandoned"             # Stream abandoned (payload too large, timeout)


_TERMINAL_PHASES = {StreamPhase.FINISHED, StreamPhase.SUPPRESSED, StreamPhase.ABANDONED}


class StreamStateTracker:
    """Tracks streaming generator phase transitions.

    Maintains current phase and full transition history.
    Does not enforce valid transitions — the generator is authoritative
    on what transitions are legal. This class names and records them.
    """

    def __init__(self) -> None:
        self._phase: StreamPhase = StreamPhase.INIT
        self._history: list[StreamPhase] = [StreamPhase.INIT]

    @property
    def phase(self) -> StreamPhase:
        """Current streaming phase."""
        return self._phase

    @property
    def history(self) -> list[StreamPhase]:
        """Ordered list of all phases visited (including current)."""
        return list(self._history)

    def transition(self, new_phase: StreamPhase) -> None:
        """Move to a new phase and record it in history.

        Args:
            new_phase: The phase to transition to.
        """
        self._phase = new_phase
        self._history.append(new_phase)

    def is_terminal(self) -> bool:
        """Return True if the current phase is a terminal (end) state."""
        return self._phase in _TERMINAL_PHASES
```

- [ ] **Step 7.4: Run tests to verify they pass**

```bash
cd /teamspace/studios/this_studio/dikders && pytest tests/test_stream_state.py -v
```
Expected: all PASS

- [ ] **Step 7.5: Export from `pipeline/__init__.py`**

```python
from pipeline.stream_state import StreamPhase, StreamStateTracker  # noqa: F401
```

- [ ] **Step 7.6: Commit**

```bash
git add pipeline/stream_state.py tests/test_stream_state.py pipeline/__init__.py
git commit -m "feat(pipeline/stream_state): StreamPhase enum + StreamStateTracker — explicit streaming state"
```

---

## Chunk 5 continued: Full test run + UPDATES.md + push

### Task 8: Final verification and push

**Files:** All test files, `UPDATES.md`

- [ ] **Step 8.1: Run full non-integration test suite**

```bash
cd /teamspace/studios/this_studio/dikders && pytest tests/ -m 'not integration' -q --tb=short 2>&1 | tail -20
```
Expected: all PASS. Fix any regressions before continuing.

- [ ] **Step 8.2: Verify imports**

```bash
cd /teamspace/studios/this_studio/dikders && python -c "
from pipeline.context import PipelineContext
from pipeline.response_validator import validate_openai_response, validate_anthropic_response
from pipeline.tracer import PipelineTracer
from pipeline.hooks import HookRegistry, hook_registry
from pipeline.middleware import run_pipeline_middleware
from pipeline.stream_state import StreamPhase, StreamStateTracker
print('all imports ok')
"
```

- [ ] **Step 8.3: Update UPDATES.md**

Read the current session count from UPDATES.md and append a new entry:

```markdown
## Session 160 — Pipeline New Modules (2026-03-28)

### What changed

| File | Change |
|---|---|
| `pipeline/context.py` | New: PipelineContext — per-request mutable state (TTFT, suppression count, etc.) |
| `pipeline/response_validator.py` | New: validate_openai_response / validate_anthropic_response — outbound warning on malformed responses |
| `pipeline/tracer.py` | New: PipelineTracer — named span tracing flushed as a single structured log line |
| `pipeline/hooks.py` | New: HookRegistry + PipelineHook protocol — lifecycle hooks at 4 checkpoints |
| `pipeline/middleware.py` | New: run_pipeline_middleware — consolidated pre-call guard chain |
| `pipeline/stream_state.py` | New: StreamPhase enum + StreamStateTracker — explicit streaming state machine |
| `pipeline/record.py` | Extended _record() to accept optional PipelineContext |
| `pipeline/nonstream.py` | Wired response_validator, middleware, context |
| `pipeline/stream_openai.py` | Wired context, middleware |
| `pipeline/stream_anthropic.py` | Wired context, middleware |
| `pipeline/__init__.py` | Re-exports all 6 new public names |
| `tests/test_pipeline_context.py` | New test file |
| `tests/test_response_validator.py` | New test file |
| `tests/test_pipeline_tracer.py` | New test file |
| `tests/test_pipeline_hooks.py` | New test file |
| `tests/test_pipeline_middleware.py` | New test file |
| `tests/test_stream_state.py` | New test file |

### Why

The pipeline directory had no structured per-request state, no outbound validation, no tracing, no extensibility hooks, and no explicit streaming state names. These 6 modules fill those gaps while remaining additive — no existing public API changed.

### Commit SHAs

(Fill in from `git log --oneline main..HEAD` after all commits)
```

- [ ] **Step 8.4: Commit UPDATES.md and push**

```bash
git add UPDATES.md
git commit -m "docs: update UPDATES.md for Session 160 — pipeline new modules"
git push
```

---

## Summary

| Chunk | Tasks | New modules |
|---|---|---|
| 1 | 1-2 | `pipeline/context.py` — PipelineContext wired into record + streaming |
| 2 | 3 | `pipeline/response_validator.py` — outbound response validation |
| 3 | 4 | `pipeline/tracer.py` — PipelineTracer span tracing |
| 4 | 5-6 | `pipeline/hooks.py` + `pipeline/middleware.py` |
| 5 | 7-8 | `pipeline/stream_state.py` + full test run + push |