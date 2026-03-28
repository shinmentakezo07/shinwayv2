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
