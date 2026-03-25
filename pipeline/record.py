"""Analytics recording helper and provider detection."""
from __future__ import annotations

import structlog

from analytics import RequestLog, analytics, estimate_cost
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
) -> None:
    """Record request analytics. Provider is auto-detected from model."""
    provider = _provider_from_model(params.model)
    # Fix #6: use count_message_tokens for consistent token counts across streaming and non-streaming
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
    log.info(
        "pipeline_complete",
        request_id=params.request_id,
        model=params.model,
        api_style=params.api_style,
        provider=provider,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=round(cost, 6),
        latency_ms=round(latency_ms, 1),
        cache_hit=cache_hit,
        ttft_ms=ttft_ms,
        output_tps=round(output_tps, 2) if output_tps else None,
    )
