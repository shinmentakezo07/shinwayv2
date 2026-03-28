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
    ttft_ms: int | None = None
    bytes_streamed: int = 0
    tool_calls_parsed: int = 0

    def record_ttft(self) -> None:
        """Record time-to-first-token. Idempotent — only the first call has effect."""
        if self.ttft_ms is None:
            self.ttft_ms = int((time.time() - self.started_at) * 1000)

    def latency_ms(self) -> float:
        """Return elapsed milliseconds since this context was created."""
        return (time.time() - self.started_at) * 1000.0
