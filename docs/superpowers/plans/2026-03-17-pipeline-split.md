# pipeline.py Split Into Sub-modules — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development to implement this plan.

**Goal:** Split the 1165-line `pipeline.py` into focused sub-modules under a `pipeline/` package with zero behaviour change.

**Architecture:** Create `pipeline/` package with 6 focused modules. `pipeline/__init__.py` re-exports every name currently imported by `routers/unified.py`, `routers/responses.py`, and `tests/test_pipeline.py` so no import changes are needed anywhere. The original `pipeline.py` is deleted only after tests confirm the package works.

**Tech Stack:** Python 3.12, dataclasses, asyncio, structlog. No new dependencies.

---

## Module map

| Module | Lines (approx) | Contents |
|--------|---------------|----------|
| `pipeline/params.py` | ~40 | `PipelineParams` dataclass |
| `pipeline/tools.py` | ~230 | `_compute_tool_signature`, `_parse_tool_arguments`, `_serialize_tool_arguments`, `_stream_anthropic_tool_input`, `_limit_tool_calls`, `_repair_invalid_calls`, `_OpenAIToolEmitter`, `_parse_score_repair` |
| `pipeline/suppress.py` | ~80 | `_SUPPRESSION_*` constants, `_is_suppressed`, `_with_appended_cursor_message`, `_call_with_retry`, `_RETRYABLE` |
| `pipeline/stream_openai.py` | ~230 | `_openai_stream`, `_extract_visible_content` (shared helper) |
| `pipeline/stream_anthropic.py` | ~260 | `_anthropic_stream` |
| `pipeline/nonstream.py` | ~230 | `handle_openai_non_streaming`, `handle_anthropic_non_streaming` |
| `pipeline/record.py` | ~30 | `_record`, `_provider_from_model` |
| `pipeline/__init__.py` | ~20 | Re-exports all public names |

---

## Chunk 1: Foundation — create package skeleton

### Task 1: Create `pipeline/` directory and empty `__init__.py`

**Files:**
- Create: `pipeline/__init__.py`

- [ ] **Step 1:** Create the directory and empty init:
```bash
mkdir -p /teamspace/studios/this_studio/wiwi/pipeline
touch /teamspace/studios/this_studio/wiwi/pipeline/__init__.py
```

- [ ] **Step 2:** Verify `pipeline` resolves to the FILE not the directory:
```bash
cd /teamspace/studios/this_studio/wiwi && python -c "import pipeline; print(pipeline.__file__)"
```
Expected output: path ending in `pipeline.py` (the old file still exists, package not yet active).

---

### Task 2: Create `pipeline/params.py`

**Files:**
- Create: `pipeline/params.py`

Contents — copy `PipelineParams` dataclass verbatim from `pipeline.py` lines 68-89:

- [ ] **Step 1:** Create `pipeline/params.py`:
```python
"""
Shin Proxy — Pipeline parameters.

PipelineParams is the single struct threaded through every stage of the pipeline.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PipelineParams:
    """All parameters needed for a single request through the pipeline."""

    api_style: str  # "openai" or "anthropic"
    model: str
    messages: list[dict]
    cursor_messages: list[dict]
    tools: list[dict] = field(default_factory=list)
    tool_choice: Any = "auto"
    stream: bool = False
    show_reasoning: bool = False
    reasoning_effort: str | None = None
    parallel_tool_calls: bool = True
    json_mode: bool = False
    api_key: str = ""
    system_text: str = ""  # Anthropic only
    max_tokens: int | None = None
    include_usage: bool = True
    thinking_budget_tokens: int | None = None
    stop: list[str] | None = None
    request_id: str = ""
```

---

### Task 3: Create `pipeline/record.py`

**Files:**
- Create: `pipeline/record.py`

Contents — `_provider_from_model` and `_record` from `pipeline.py` lines 94-101 and 1139-1165:

- [ ] **Step 1:** Create `pipeline/record.py`:
```python
"""
Shin Proxy — Analytics recording helper.
"""
from __future__ import annotations

import structlog

from analytics import RequestLog, analytics, estimate_cost
from pipeline.params import PipelineParams
from tokens import count_message_tokens, estimate_from_text

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
) -> None:
    """Record request analytics. Provider is auto-detected from model."""
    provider = _provider_from_model(params.model)
    input_tokens = count_message_tokens(params.messages, params.model)
    output_tokens = estimate_from_text(text, params.model)
    cost = estimate_cost(provider, input_tokens, output_tokens)
    await analytics.record(
        RequestLog(
            api_key=params.api_key,
            provider=provider,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            latency_ms=latency_ms,
            cache_hit=cache_hit,
            ttft_ms=ttft_ms,
            output_tps=output_tps,
        )
    )
```

---

### Task 4: Create `pipeline/suppress.py`

**Files:**
- Create: `pipeline/suppress.py`

Contents — suppression constants + `_is_suppressed`, `_RETRYABLE`, `_with_appended_cursor_message`, `_call_with_retry`.

Read `pipeline.py` lines 220-350 to get the exact constants and implementations. Copy them verbatim.

- [ ] **Step 1:** Create `pipeline/suppress.py` with:
  - All `_SUPPRESSION_*` constant lists (copy from `pipeline.py` ~lines 220-286)
  - `_is_suppressed(text)` function
  - `_RETRYABLE` tuple
  - `_with_appended_cursor_message(params, message)` function
  - `_call_with_retry(client, params, anthropic_tools)` async function

Imports needed:
```python
from __future__ import annotations
import asyncio
import random
import time
import structlog
from config import settings
from cursor.client import CursorClient
from handlers import BackendError, CredentialError, RateLimitError, StreamAbortError, TimeoutError
from pipeline.params import PipelineParams
from converters.to_cursor import _msg
from dataclasses import replace
```

---

### Task 5: Create `pipeline/tools.py`

**Files:**
- Create: `pipeline/tools.py`

Contents — all tool-call helpers. Read `pipeline.py` lines 103-195 and 351-415 and 890-913.

- [ ] **Step 1:** Create `pipeline/tools.py` with:
  - `_compute_tool_signature`
  - `_parse_tool_arguments`
  - `_serialize_tool_arguments`
  - `_stream_anthropic_tool_input`
  - `_limit_tool_calls`
  - `_repair_invalid_calls`
  - `_OpenAIToolEmitter` class
  - `_parse_score_repair`

Imports needed:
```python
from __future__ import annotations
import uuid
import msgspec.json as msgjson
import structlog
from config import settings
from converters.from_cursor import openai_chunk, openai_sse
from pipeline.params import PipelineParams
from tools.parse import parse_tool_calls_from_text, score_tool_call_confidence, log_tool_calls, validate_tool_call, repair_tool_call
```

**Note:** `_parse_score_repair` depends on `_limit_tool_calls` and `_repair_invalid_calls` which are in the same file — no circular imports.

---

## Chunk 2: Stream generators

### Task 6: Create `pipeline/stream_openai.py`

**Files:**
- Create: `pipeline/stream_openai.py`

Contents — `_extract_visible_content` (shared) and `_openai_stream`.

Read `pipeline.py` lines 197-285 (`_extract_visible_content`) and lines 414-635 (`_openai_stream`) carefully.

- [ ] **Step 1:** Create `pipeline/stream_openai.py`.

All imports from `pipeline.py` top needed here:
```python
from __future__ import annotations
import re
import time
import uuid
from typing import AsyncIterator
import structlog
from cache import response_cache
from config import settings
from converters.from_cursor import (
    openai_chunk, openai_done, openai_sse, openai_usage_chunk,
    sanitize_visible_text, scrub_support_preamble, split_visible_reasoning, now_ts,
)
from cursor.client import CursorClient
from handlers import StreamAbortError, TimeoutError
from pipeline.params import PipelineParams
from pipeline.record import _record
from pipeline.suppress import _call_with_retry, _with_appended_cursor_message, _is_suppressed, _RETRYABLE
from pipeline.tools import _OpenAIToolEmitter, _limit_tool_calls, _parse_score_repair, _repair_invalid_calls
from tools.parse import _find_marker_pos, StreamingToolCallParser, parse_tool_calls_from_text, log_tool_calls
import utils.stream_monitor as _stream_monitor_mod
```

- [ ] **Step 2:** Copy `_extract_visible_content` and `_openai_stream` verbatim from `pipeline.py`.

---

### Task 7: Create `pipeline/stream_anthropic.py`

**Files:**
- Create: `pipeline/stream_anthropic.py`

Contents — `_anthropic_stream` only.

Read `pipeline.py` lines 637-888 carefully.

- [ ] **Step 1:** Create `pipeline/stream_anthropic.py` with all needed imports and `_anthropic_stream`.

All imports needed:
```python
from __future__ import annotations
import re
import time
import uuid
from typing import AsyncIterator
import structlog
from cache import response_cache
from config import settings
from converters.from_cursor import (
    anthropic_content_block_delta, anthropic_content_block_start,
    anthropic_content_block_stop, anthropic_message_delta,
    anthropic_message_start, anthropic_message_stop,
    anthropic_sse_event, convert_tool_calls_to_anthropic,
    sanitize_visible_text, scrub_support_preamble, split_visible_reasoning,
)
from cursor.client import CursorClient
from handlers import StreamAbortError, TimeoutError
from pipeline.params import PipelineParams
from pipeline.record import _record
from pipeline.suppress import _call_with_retry, _with_appended_cursor_message, _is_suppressed, _RETRYABLE
from pipeline.tools import _limit_tool_calls, _stream_anthropic_tool_input
from tools.parse import _find_marker_pos, StreamingToolCallParser, parse_tool_calls_from_text, log_tool_calls
import utils.stream_monitor as _stream_monitor_mod
```

---

## Chunk 3: Non-streaming handlers + package init

### Task 8: Create `pipeline/nonstream.py`

**Files:**
- Create: `pipeline/nonstream.py`

Contents — `handle_openai_non_streaming` and `handle_anthropic_non_streaming`.

Read `pipeline.py` lines 915-1135 carefully.

- [ ] **Step 1:** Create `pipeline/nonstream.py` with all needed imports:
```python
from __future__ import annotations
import time
from typing import Any
import structlog
from app import get_http_client
from cache import response_cache
from config import settings
from converters.from_cursor import (
    anthropic_non_streaming_response, convert_tool_calls_to_anthropic,
    openai_non_streaming_response,
)
from cursor.client import CursorClient
from pipeline.params import PipelineParams
from pipeline.record import _record
from pipeline.suppress import _call_with_retry, _with_appended_cursor_message, _is_suppressed, _build_role_override_msg
from pipeline.tools import _parse_score_repair
from tools.parse import log_tool_calls
```

Copy `handle_openai_non_streaming` and `handle_anthropic_non_streaming` verbatim.

---

### Task 9: Create `pipeline/__init__.py`

**Files:**
- Create: `pipeline/__init__.py`

This is the CRITICAL file. It re-exports everything the external world imports. The routers and tests must need no changes.

-