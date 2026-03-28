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
        params:   Pipeline parameters for context.

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
