"""Analytics recording helper and provider detection."""
from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from analytics import RequestLog, analytics, estimate_cost
from config import settings
from tokens import count_message_tokens, estimate_from_text
from pipeline.params import PipelineParams

if TYPE_CHECKING:
    from pipeline.context import PipelineContext


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
    """Record request analytics. Provider is auto-detected from model."""
    effective_ttft = (context.ttft_ms if context else None) or ttft_ms
    effective_latency = context.latency_ms() if context else latency_ms

    provider = _provider_from_model(params.model)
    # Fix #6: use count_message_tokens for consistent token counts across streaming and non-streaming
    input_tokens = count_message_tokens(params.messages, params.model)
    output_tokens = estimate_from_text(text, params.model)
    cost = estimate_cost(provider, input_tokens, output_tokens)

    # Capture prompt/response only when enabled — stored for UI inspection
    prompt_data: list[dict] | None = None
    response_data: str | None = None
    if settings.prompt_logging_enabled:
        prompt_data = params.messages
        max_chars = settings.prompt_logging_max_response_chars
        response_data = text[:max_chars] + "…" if len(text) > max_chars else text

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
            request_id=params.request_id,
            prompt=prompt_data,
            response=response_data,
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
