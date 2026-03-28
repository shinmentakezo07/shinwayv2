"""Pipeline parameter dataclass."""
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
    max_tokens: int | None = None  # pass-through from client; not yet forwarded upstream  # pass-through from client request
    include_usage: bool = True  # stream_options.include_usage — default True (usage always emitted)
    thinking_budget_tokens: int | None = None  # Anthropic extended thinking budget
    stop: list[str] | None = None  # stop sequences requested by client (informational — not enforced upstream)
    request_id: str = ""  # propagated from request_id middleware
    fallback_model: str | None = None  # set by _call_with_retry when a fallback is active; None on primary
    temperature: float | None = None  # pass-through from client; informational only (upstream ignores it but we record it)
