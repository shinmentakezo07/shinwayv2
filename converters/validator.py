"""Converters — pre-conversion semantic validation.

Validates message lists and tool call lists for semantic correctness
before they reach format-specific converters. Returns a list of
human-readable issue strings. An empty list means no issues found.

Never mutates input. Never raises — callers decide whether issues are
fatal (raise) or advisory (log).
"""
from __future__ import annotations

import json

import structlog

log = structlog.get_logger()


class ConversionValidationError(ValueError):
    """Raised by callers that treat validation issues as fatal."""


def validate_tool_calls(tool_calls: list[dict]) -> list[str]:
    """Validate a list of OpenAI-format tool_call objects.

    Checks:
    - Each entry has an 'id' field.
    - Each entry has function.name.
    - Each entry has function.arguments as a JSON string.

    Args:
        tool_calls: List of tool call dicts.

    Returns:
        List of issue strings. Empty means valid.
    """
    issues: list[str] = []
    for i, tc in enumerate(tool_calls or []):
        if not isinstance(tc, dict):
            issues.append(f"tool_calls[{i}]: not a dict")
            continue
        if not tc.get("id"):
            issues.append(f"tool_calls[{i}]: missing id")
        fn = tc.get("function") or {}
        if not fn.get("name"):
            issues.append(f"tool_calls[{i}]: missing function.name")
        args = fn.get("arguments")
        if not isinstance(args, str):
            issues.append(
                f"tool_calls[{i}]: arguments must be a JSON string, "
                f"got {type(args).__name__}"
            )
        else:
            try:
                json.loads(args)
            except json.JSONDecodeError:
                issues.append(f"tool_calls[{i}]: arguments is not valid JSON")
    return issues


def validate_openai_messages(messages: list[dict]) -> list[str]:
    """Validate a list of OpenAI-format messages for semantic correctness.

    Checks:
    - tool_call_ids in role=tool messages have a matching prior tool_call.
    - assistant tool_calls have valid ids and string arguments.

    Args:
        messages: OpenAI message list.

    Returns:
        List of issue strings. Empty means valid.
    """
    issues: list[str] = []
    seen_call_ids: set[str] = set()

    for i, msg in enumerate(messages or []):
        if not isinstance(msg, dict):
            issues.append(f"messages[{i}]: not a dict")
            continue
        role = msg.get("role", "user")

        if role == "assistant" and isinstance(msg.get("tool_calls"), list):
            for issue in validate_tool_calls(msg["tool_calls"]):
                issues.append(f"messages[{i}].{issue}")
            for tc in msg["tool_calls"]:
                if isinstance(tc, dict) and tc.get("id"):
                    seen_call_ids.add(tc["id"])

        elif role == "tool":
            call_id = msg.get("tool_call_id", "")
            if call_id and call_id not in seen_call_ids:
                issues.append(
                    f"messages[{i}]: tool result references unknown "
                    f"tool_call_id={call_id!r} (no prior assistant tool_call)"
                )

    if issues:
        log.warning(
            "openai_message_validation_issues",
            issue_count=len(issues),
            issues=issues,
        )
    return issues


def validate_anthropic_messages(messages: list[dict]) -> list[str]:
    """Validate a list of Anthropic-format messages for semantic correctness.

    Checks:
    - tool_use blocks have an id.
    - tool_result blocks reference a known tool_use id.

    Args:
        messages: Anthropic message list.

    Returns:
        List of issue strings. Empty means valid.
    """
    issues: list[str] = []
    seen_tool_use_ids: set[str] = set()

    for i, msg in enumerate(messages or []):
        if not isinstance(msg, dict):
            issues.append(f"messages[{i}]: not a dict")
            continue
        content = msg.get("content", [])
        if not isinstance(content, list):
            continue

        for j, block in enumerate(content):
            if not isinstance(block, dict):
                continue
            btype = block.get("type")

            if btype == "tool_use":
                block_id = block.get("id", "")
                if not block_id:
                    issues.append(
                        f"messages[{i}].content[{j}]: tool_use block missing id "
                        f"(name={block.get('name')!r})"
                    )
                else:
                    seen_tool_use_ids.add(block_id)

            elif btype == "tool_result":
                use_id = block.get("tool_use_id", "")
                if use_id and use_id not in seen_tool_use_ids:
                    issues.append(
                        f"messages[{i}].content[{j}]: tool_result references "
                        f"unknown tool_use_id={use_id!r}"
                    )

    if issues:
        log.warning(
            "anthropic_message_validation_issues",
            issue_count=len(issues),
            issues=issues,
        )
    return issues
