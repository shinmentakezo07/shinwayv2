"""
Shin Proxy — OpenAI-format token counting endpoint.

Anthropics /v1/messages/count_tokens already exists (routers/anthropic.py).
This adds the OpenAI equivalent so clients using the chat completions format
can estimate token costs before submitting.

Endpoints:
    POST /v1/chat/count_tokens
"""
from __future__ import annotations

import litellm
import msgspec.json as _msgjson
import structlog
from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse

from middleware.auth import verify_bearer
from middleware.rate_limit import enforce_rate_limit
from routers.model_router import resolve_model
from tokens import count_message_tokens, count_tool_instruction_tokens
from tools.normalize import normalize_openai_tools

router = APIRouter()
log = structlog.get_logger()


@router.post("/v1/chat/count_tokens")
async def count_tokens_openai(
    request: Request,
    authorization: str | None = Header(default=None),
):
    """Count tokens for an OpenAI-format chat completions request.

    Accepts the same payload shape as POST /v1/chat/completions.
    Returns token count before the request is sent upstream — useful
    for budget estimation and context window management.
    """
    api_key = await verify_bearer(authorization)
    enforce_rate_limit(api_key, request=request)

    payload = await request.json()
    model = resolve_model(payload.get("model"))
    messages = payload.get("messages", [])
    tools_raw = payload.get("tools", [])
    tools = normalize_openai_tools(tools_raw)
    tool_choice = payload.get("tool_choice", "auto")

    try:
        message_tokens = litellm.token_counter(model=model, messages=messages)
    except Exception:
        log.debug("litellm_token_counter_failed", model=model, exc_info=True)
        message_tokens = count_message_tokens(messages, model)

    tool_tokens = 0
    if tools:
        try:
            tool_text = _msgjson.encode(tools).decode("utf-8")
            tool_tokens = litellm.token_counter(model=model, text=tool_text)
        except Exception:
            tool_tokens = count_tool_instruction_tokens(tools, tool_choice, model)

    total = message_tokens + tool_tokens

    log.info("token_count_openai", model=model, messages=len(messages), tools=len(tools), total=total)
    return JSONResponse({
        "input_tokens": total,
        "message_tokens": message_tokens,
        "tool_tokens": tool_tokens,
        "model": model,
    })
