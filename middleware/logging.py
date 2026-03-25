"""
Shin Proxy — Request/response lifecycle logging.

Provides RequestContext (one per request) stored on request.state.ctx.
The middleware emits two structlog events per request:
  - request_start: method, path, request_id
  - request_end:   status, latency_ms, model, api_key_prefix, tokens,
                   finish_reason, tool_calls_returned, stream

No request/response bodies are ever logged — metadata only.
Sampling is controlled by SHINWAY_LOG_SAMPLE_RATE (default 1.0 = all).
"""
from __future__ import annotations

import random
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import structlog
from fastapi import Request

from config import settings

log = structlog.get_logger()


@dataclass
class RequestContext:
    """Per-request correlation context. Stored on request.state.ctx."""

    request_id: str
    method: str
    path: str
    api_key_prefix: str = ""
    model: str = ""
    stream: bool = False
    input_tokens: int = 0
    output_tokens: int = 0
    finish_reason: str | None = None
    tool_calls_returned: bool = False
    started_at: float = field(default_factory=time.monotonic)

    def set_api_key(self, api_key: str) -> None:
        """Store a prefix of the api_key — never the full value."""
        self.api_key_prefix = (api_key[:8] + "...") if api_key else ""

    def latency_ms(self) -> float:
        """Milliseconds elapsed since request start."""
        return round((time.monotonic() - self.started_at) * 1000, 1)


def get_ctx(request: Request) -> RequestContext | None:
    """Return the RequestContext for this request, or None if not set."""
    return getattr(getattr(request, "state", None), "ctx", None)


async def request_context_middleware(request: Request, call_next) -> Any:
    """FastAPI middleware: create RequestContext, log start + end."""
    ctx = RequestContext(
        request_id=uuid.uuid4().hex[:16],
        method=request.method,
        path=request.url.path,
    )
    request.state.ctx = ctx
    # Backwards-compat: keep request.state.request_id for any code that reads it directly
    request.state.request_id = ctx.request_id

    log.info(
        "request_start",
        request_id=ctx.request_id,
        method=ctx.method,
        path=ctx.path,
    )

    response = await call_next(request)

    response.headers["X-Request-ID"] = ctx.request_id

    # Sampling: skip request_end log if sample rate < 1.0
    try:
        sample_rate = settings.log_sample_rate
    except AttributeError:
        sample_rate = 1.0
    if sample_rate >= 1.0 or random.random() < sample_rate:
        log.info(
            "request_end",
            request_id=ctx.request_id,
            method=ctx.method,
            path=ctx.path,
            status=response.status_code,
            latency_ms=ctx.latency_ms(),
            api_key_prefix=ctx.api_key_prefix or None,
            model=ctx.model or None,
            stream=ctx.stream,
            input_tokens=ctx.input_tokens or None,
            output_tokens=ctx.output_tokens or None,
            finish_reason=ctx.finish_reason,
            tool_calls_returned=ctx.tool_calls_returned or None,
        )

    return response
