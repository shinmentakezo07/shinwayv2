"""Pipeline-level pre-call middleware chain.

Consolidates guards that must run before every upstream call regardless
of streaming/non-streaming or OpenAI/Anthropic format:

  1. Context window preflight — raises ContextWindowError if request exceeds
     the model's hard token limit.

All guards accept PipelineParams and return (possibly modified) PipelineParams.
Raising an exception aborts the request before any upstream call is made.

Usage::

    params = await run_pipeline_middleware(params)
"""
from __future__ import annotations

from pipeline.params import PipelineParams
from utils.context import context_engine


async def run_pipeline_middleware(params: PipelineParams) -> PipelineParams:
    """Run all pre-call middleware guards on params.

    Guards run in declaration order. Any guard may raise to abort the request.

    Args:
        params: Pipeline parameters for the current request.

    Returns:
        The same PipelineParams instance (guards do not replace it).

    Raises:
        ContextWindowError: If the request exceeds the model's hard context limit.
    """
    # Guard 1: context window preflight — raises ContextWindowError on hard limit breach.
    # Pass cursor_messages when available for more accurate token counting.
    context_engine.check_preflight(
        params.messages,
        params.tools,
        params.model,
        params.cursor_messages or None,
    )
    return params
