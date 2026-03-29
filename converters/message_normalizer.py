"""Converters — pre-conversion message normalization.

Normalizes OpenAI and Anthropic message lists before they reach the
format-specific converters. Handles: None/missing content, empty content
arrays, missing role. Never mutates input — always returns new list.

Does NOT collapse adjacent same-role messages — that is the converter's
responsibility. These normalizers only enforce structural invariants.
"""
from __future__ import annotations

from copy import deepcopy


def normalize_openai_messages(messages: list[dict]) -> list[dict]:
    """Normalise a list of OpenAI-format messages before conversion.

    Invariants enforced:
    - Non-dict entries are dropped.
    - Missing `role` defaults to 'user'.
    - `content: None` or `content: []` is coerced to empty string ''
      for non-tool messages. Tool messages keep content as-is because
      empty string is a valid (and meaningful) tool result.

    Args:
        messages: Raw OpenAI message list from the client request.

    Returns:
        New list with all invariants satisfied. Input is not mutated.
    """
    out: list[dict] = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        m = deepcopy(msg)
        if "role" not in m:
            m["role"] = "user"
        # Only coerce content for non-tool messages
        if m["role"] != "tool":
            content = m.get("content")
            if content is None or content == []:
                m["content"] = ""
        out.append(m)
    return out


def normalize_anthropic_messages(messages: list[dict]) -> list[dict]:
    """Normalise a list of Anthropic-format messages before conversion.

    Invariants enforced:
    - Non-dict entries are dropped.
    - Missing `role` defaults to 'user'.
    - `content: None` is coerced to empty list `[]`.
    - String content and list content are both preserved as-is.

    Args:
        messages: Raw Anthropic message list from the client request.

    Returns:
        New list with all invariants satisfied. Input is not mutated.
    """
    out: list[dict] = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        m = deepcopy(msg)
        if "role" not in m:
            m["role"] = "user"
        content = m.get("content")
        if content is None:
            m["content"] = []
        out.append(m)
    return out


_NO_COLLAPSE_ROLES: frozenset[str] = frozenset({"tool", "system"})


def collapse_adjacent_same_role(messages: list[dict]) -> list[dict]:
    """Collapse adjacent messages with the same role into one.

    Rules:
    - 'tool' and 'system' role messages are NEVER collapsed — each carries
      distinct metadata (tool_call_id, scope).
    - Messages with 'tool_calls' on the assistant role are never merged.
    - Non-dict entries are dropped.
    - Content is joined with a newline separator.

    This is the general-purpose collapser. Format-specific variants
    (collapse_openai_messages, collapse_anthropic_messages) apply
    additional format rules on top.

    Args:
        messages: Input message list.

    Returns:
        New list with adjacent same-role messages merged. Input is not mutated.
    """
    out: list[dict] = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        role = msg.get("role", "user")
        if role in _NO_COLLAPSE_ROLES:
            out.append(deepcopy(msg))
            continue
        if msg.get("tool_calls"):
            out.append(deepcopy(msg))
            continue
        if (
            out
            and out[-1].get("role") == role
            and not out[-1].get("tool_calls")
            and out[-1].get("role") not in _NO_COLLAPSE_ROLES
        ):
            prev = out[-1]
            prev_content = prev.get("content") or ""
            this_content = msg.get("content") or ""
            if isinstance(prev_content, str) and isinstance(this_content, str):
                prev["content"] = (prev_content + "\n" + this_content) if prev_content else this_content
            else:
                out.append(deepcopy(msg))
        else:
            out.append(deepcopy(msg))
    return out


def collapse_openai_messages(messages: list[dict]) -> list[dict]:
    """Collapse adjacent same-role OpenAI messages.

    Delegates to collapse_adjacent_same_role which handles
    tool and system role exclusions. OpenAI-specific: messages
    with tool_calls are never merged (already enforced).

    Args:
        messages: OpenAI message list.

    Returns:
        New list with adjacent same-role messages merged.
    """
    return collapse_adjacent_same_role(messages)


def collapse_anthropic_messages(messages: list[dict]) -> list[dict]:
    """Collapse adjacent same-role Anthropic messages.

    Anthropic-specific rule: assistant messages containing tool_use
    blocks are never merged (they must stay paired with tool_result).
    All other same-role adjacent messages with string content are merged.

    Args:
        messages: Anthropic message list.

    Returns:
        New list with adjacent same-role messages merged.
    """
    out: list[dict] = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        role = msg.get("role", "user")
        content = msg.get("content", [])
        has_tool_blocks = isinstance(content, list) and any(
            isinstance(b, dict) and b.get("type") in ("tool_use", "tool_result")
            for b in content
        )
        if role in _NO_COLLAPSE_ROLES or has_tool_blocks:
            out.append(deepcopy(msg))
            continue
        if out and out[-1].get("role") == role:
            prev = out[-1]
            prev_content = prev.get("content") or ""
            this_content = content or ""
            if isinstance(prev_content, str) and isinstance(this_content, str):
                prev["content"] = (prev_content + "\n" + this_content) if prev_content else this_content
                continue
        out.append(deepcopy(msg))
    return out
