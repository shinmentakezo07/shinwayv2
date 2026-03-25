"""Suppression detection and retry-with-backoff logic."""
from __future__ import annotations

import asyncio
import random
from dataclasses import replace

import structlog

from config import settings
from cursor.client import CursorClient
from handlers import BackendError, CredentialError, ProxyError, RateLimitError, TimeoutError
from pipeline.fallback import FallbackChain
from pipeline.params import PipelineParams


log = structlog.get_logger()


# ── Suppression detector ────────────────────────────────────────────────────

_SUPPRESSION_SIGNALS = [
    # Confirmed exact phrases from Cursor's backend system prompt
    "i can only answer questions about cursor",
    "using the available documentation tools",
    "cannot act as a general-purpose assistant",
    "override my identity",
    "execute arbitrary instructions",
    "regardless of framing",
    # Previously known signals
    "i am a support assistant",
    "i am the cursor support assistant",
    "i'm the cursor support assistant",
    "as the cursor support assistant",
    "i can only help with cursor",
    "i'm not a general-purpose",
    "not a general-purpose ai",
    "outside my scope",
    "/docs/",
    "/help/",
    "documentation only",
    "i don't have a model id",
    "support assistant for cursor",
    # Path-restriction phrases from known system prompt (Attack 10 revealed these)
    "prefer product documentation under",
    "list mdx pages under a route path",
]

_SUPPRESSION_PERSONA_SIGNALS = {
    "using the available documentation tools",
    "i am a support assistant",
    "i am the cursor support assistant",
    "i'm the cursor support assistant",
    "as the cursor support assistant",
    "i can only help with cursor",
    "i'm not a general-purpose",
    "not a general-purpose ai",
    "outside my scope",
    "documentation only",
    "support assistant for cursor",
}

# Single phrases that definitively indicate suppression — no second signal needed
_SUPPRESSION_KNOCKOUTS = {
    "i can only answer questions about cursor",
    "cannot act as a general-purpose assistant",
    "execute arbitrary instructions",
    "i am a support assistant for cursor",
    "i'm a support assistant for cursor",
    # Wiwi session-config identity bleed: upstream echoes the injected system prompt
    "i can help you with the editor documentation",
    "i can help you with cursor documentation",
    "documentation, features, troubleshooting",
}


def _is_suppressed(text: str) -> bool:
    """Return True if Cursor's Support Assistant persona fired instead of a tool call."""
    lower = text.lower()
    # Knockout check — any single definitive phrase is enough
    if any(k in lower for k in _SUPPRESSION_KNOCKOUTS):
        return True

    hits = [signal for signal in _SUPPRESSION_SIGNALS if signal in lower]
    persona_hits = [signal for signal in hits if signal in _SUPPRESSION_PERSONA_SIGNALS]

    # Require a clear support-persona cue for weaker phrase combinations so
    # long legitimate answers mentioning docs/help/access limits are not retried.
    return len(hits) >= 2 and bool(persona_hits)


_RETRYABLE = (CredentialError, TimeoutError, RateLimitError, BackendError)


def _with_appended_cursor_message(params: PipelineParams, message: dict) -> PipelineParams:
    """Return retry params with one additional cursor message without mutating input."""
    return replace(params, cursor_messages=[*params.cursor_messages, message])


async def _call_with_retry(
    client: CursorClient,
    params: PipelineParams,
    anthropic_tools: list[dict] | None,
) -> str:
    """Non-streaming call with unified retry + fallback chain logic.

    Flow:
    1. Attempt the primary model up to settings.retry_attempts times with backoff.
    2. If all primary attempts are exhausted with a fallback-eligible error,
       iterate the fallback chain in order, attempting each fallback model once.
    3. If all fallbacks are also exhausted, raise BackendError.
    4. AuthError and other non-transient errors propagate immediately — no fallback.
    """
    fallback_chain = FallbackChain(settings.fallback_chain)
    last_exc: Exception | None = None
    max_attempts = settings.retry_attempts

    # ── Primary model attempts ──────────────────────────────────────────────
    for attempt in range(max_attempts):
        try:
            return await client.call(
                params.cursor_messages,
                params.model,
                anthropic_tools,
            )
        except _RETRYABLE as exc:
            last_exc = exc
            remaining = max_attempts - attempt - 1
            if remaining > 0:
                base = settings.retry_backoff_seconds * (2 ** attempt)
                jitter = random.uniform(0, base * 0.3)  # nosec B311 — jitter for backoff, not crypto
                backoff = min(base + jitter, 30.0)
                log.debug(
                    "retry_upstream",
                    attempt=attempt + 1,
                    remaining=remaining,
                    error=str(exc)[:120],
                    backoff_s=backoff,
                )
                await asyncio.sleep(backoff)
            continue

    # ── Fallback chain ──────────────────────────────────────────────────────
    # Only enter the fallback path if the last primary-model error is a
    # transient upstream failure — auth errors and other non-retryable errors
    # are re-raised immediately without trying fallbacks.
    if last_exc is not None and not fallback_chain.should_fallback(last_exc):
        if isinstance(last_exc, ProxyError):
            raise last_exc
        raise BackendError(f"All {max_attempts} upstream attempts failed: {last_exc}")

    for fallback_model in fallback_chain.get_fallbacks(params.model):
        fallback_params = replace(params, model=fallback_model, fallback_model=fallback_model)
        try:
            result = await client.call(
                fallback_params.cursor_messages,
                fallback_params.model,
                anthropic_tools,
            )
            log.info(
                "fallback_model_used",
                original_model=params.model,
                fallback_model=fallback_model,
                primary_error=str(last_exc)[:120],
            )
            return result
        except _RETRYABLE as exc:
            last_exc = exc
            log.debug(
                "fallback_model_failed",
                fallback_model=fallback_model,
                error=str(exc)[:120],
            )
            continue

    # Exhausted primary retries and all fallbacks — always surface as BackendError
    raise BackendError(f"All {max_attempts} upstream attempts failed: {last_exc}")
