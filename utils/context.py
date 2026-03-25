"""
Shin Proxy — Context Engine.

Pre-flight context window check, smart message trimming, and budget breakdown.
Prevents 40K overflow errors by enforcing token limits before sending to Cursor.
"""

from __future__ import annotations

import structlog

from converters.to_cursor import build_tool_instruction, _build_role_override
from tokens import (
    count_message_tokens,
    count_cursor_messages,
    count_tool_instruction_tokens,
    count_tool_tokens,
    count_tokens,
    context_window_for,
)

from config import settings
from handlers import ContextWindowError

log = structlog.get_logger()

MIN_KEEP = settings.trim_min_keep_messages


class ContextResult:
    """Result from a context pre-flight check."""

    def __init__(
        self,
        token_count: int,
        within_budget: bool,
        safe_limit: int,
        hard_limit: int,
        recommendation: str = "",
    ) -> None:
        self.token_count = token_count
        self.within_budget = within_budget
        self.safe_limit = safe_limit
        self.hard_limit = hard_limit
        self.recommendation = recommendation

    def __repr__(self) -> str:
        return (
            f"ContextResult(tokens={self.token_count}, "
            f"within_budget={self.within_budget}, "
            f"safe_limit={self.safe_limit})"
        )


class ContextEngine:
    """
    Manages context window budgeting for all requests.

    Responsibilities:
    - Accurate token counting per model
    - Smart message trimming (preserve tool results, preserve last N turns)
    - Tool schema token budget estimation
    - Overflow rejection with clear error
    - Per-section budget breakdown for debugging
    """

    def check_preflight(
        self,
        messages: list[dict],
        tools: list[dict],
        model: str,
        cursor_messages: list[dict] | None = None,
    ) -> ContextResult:
        """
        Run before sending to Cursor.

        Returns ContextResult with token_count, within_budget, safe_limit,
        hard_limit, recommendation.

        Raises ContextWindowError if over the hard limit.
        """
        safe_limit = settings.max_context_tokens
        hard_limit = settings.hard_context_limit

        # Count from cursor_messages if provided (more accurate), else from messages
        if cursor_messages:
            token_count = count_cursor_messages(cursor_messages, model)
        else:
            message_tokens = count_message_tokens(messages, model)
            tool_schema_tokens = self.estimate_tool_schema_tokens(tools, model)
            token_count = message_tokens + tool_schema_tokens

        within_budget = token_count <= safe_limit

        if token_count > hard_limit:
            msg = (
                f"Request context is {token_count:,} tokens, which exceeds the hard "
                f"limit of {hard_limit:,} tokens for model {model!r}. "
                f"Enable SHINWAY_TRIM_CONTEXT=true or reduce your message history."
            )
            log.error(
                "context_hard_limit_exceeded",
                token_count=token_count,
                hard_limit=hard_limit,
                model=model,
            )
            raise ContextWindowError(msg)

        recommendation = ""
        if not within_budget:
            recommendation = (
                f"Token count {token_count:,} exceeds soft limit {safe_limit:,}. "
                "Consider trimming messages or reducing tool schemas."
            )
            log.warning(
                "context_soft_limit_exceeded",
                token_count=token_count,
                safe_limit=safe_limit,
                model=model,
            )
        else:
            log.debug(
                "context_preflight_ok",
                token_count=token_count,
                safe_limit=safe_limit,
                model=model,
            )

        return ContextResult(
            token_count=token_count,
            within_budget=within_budget,
            safe_limit=safe_limit,
            hard_limit=hard_limit,
            recommendation=recommendation,
        )

    def trim_to_budget(
        self,
        messages: list[dict],
        model: str,
        max_tokens: int | None = None,
        tools: list[dict] | None = None,
    ) -> tuple[list[dict], int]:
        """
        Smart trim preserving:
        1. System messages (always keep)
        2. Tool result messages (high value, keep longer)
        3. Last N turns minimum (never drop recent context)
        4. Paired tool call + result (never split a pair)

        Drops: oldest non-system, non-tool messages first.

        Returns:
            (trimmed_messages, token_count)
        """
        budget = max_tokens if max_tokens is not None else settings.max_context_tokens

        # Subtract tool schema overhead from budget
        tool_overhead = self.estimate_tool_schema_tokens(tools or [], model)
        effective_budget = budget - tool_overhead

        total = count_message_tokens(messages, model)
        if total <= effective_budget:
            return messages, total

        system_msgs = [m for m in messages if m.get("role") == "system"]
        conv_msgs = [m for m in messages if m.get("role") != "system"]

        if not conv_msgs:
            return messages, total

        pair_groups = _build_atomic_message_groups(conv_msgs)

        # Always keep last MIN_KEEP conversation turns when they fit.
        kept_indices = _expand_with_atomic_groups(
            set(range(max(0, len(conv_msgs) - MIN_KEEP), len(conv_msgs))),
            pair_groups,
        )
        kept_indices = _trim_kept_indices_to_budget(
            conv_msgs,
            system_msgs,
            kept_indices,
            pair_groups,
            effective_budget,
            model,
        )

        # Score each message: tool results = 2 (high value), tool calls = 1.5, others = 1
        # Sort by: score descending, then index descending (prefer recent)
        scored = []
        for i, m in enumerate(conv_msgs):
            if i in kept_indices:
                continue
            if _is_tool_result(m):
                score = 2.0
            elif _is_tool_call(m):
                score = 1.5
            else:
                score = 1.0
            scored.append((score, i, m))

        # Greedily add more messages prioritising tool results, then recency
        for _score, i, _m in sorted(scored, key=lambda x: (-x[0], -x[1])):
            candidate_indices = _expand_with_atomic_groups(kept_indices | {i}, pair_groups)
            candidate = [conv_msgs[j] for j in sorted(candidate_indices)]
            test_total = count_message_tokens(system_msgs + candidate, model)
            if test_total > effective_budget:
                continue
            kept_indices = candidate_indices

        kept = [conv_msgs[i] for i in sorted(kept_indices)]
        trimmed = system_msgs + kept
        final_count = count_message_tokens(trimmed, model)
        dropped = len(messages) - len(trimmed)

        if dropped > 0:
            log.warning(
                "context_trimmed",
                dropped_messages=dropped,
                original_count=len(messages),
                trimmed_count=len(trimmed),
                token_count=final_count,
                budget=effective_budget,
                model=model,
            )

        return trimmed, final_count

    def estimate_tool_schema_tokens(
        self,
        tools: list[dict],
        model: str,
    ) -> int:
        """
        Count tokens consumed by the injected tool instruction block.

        Includes: schema JSON + build_tool_instruction() text overhead.
        """
        if not tools:
            return 0

        instruction_tokens = count_tool_instruction_tokens(tools, "auto", model)

        # Count role override overhead
        try:
            override_text = _build_role_override(tools, attempt=0)
            override_tokens = count_tokens(override_text, model)
        except Exception:
            override_tokens = 120  # reasonable estimate

        return instruction_tokens + override_tokens

    def budget_breakdown(
        self,
        messages: list[dict],
        tools: list[dict],
        model: str,
    ) -> dict:
        """
        Returns per-section token breakdown for debugging.

        Returns:
            {
              "system_messages": 1240,
              "tool_instruction": 890,
              "role_override": 120,
              "conversation": 28450,
              "tool_schemas": 440,
              "total": 31140,
              "limit": 200000,
              "headroom": 168860,
              "model": "anthropic/claude-sonnet-4.6",
            }
        """
        system_msgs = [m for m in messages if m.get("role") == "system"]
        conv_msgs = [m for m in messages if m.get("role") != "system"]

        system_tokens = count_message_tokens(system_msgs, model) if system_msgs else 0
        conv_tokens = count_message_tokens(conv_msgs, model) if conv_msgs else 0
        tool_schema_tokens = count_tool_tokens(tools, model)

        try:
            instruction_text = build_tool_instruction(tools, "auto")
            tool_instruction_tokens = count_tokens(instruction_text, model)
        except Exception:
            tool_instruction_tokens = tool_schema_tokens

        try:
            override_text = _build_role_override(tools, attempt=0)
            role_override_tokens = count_tokens(override_text, model)
        except Exception:
            role_override_tokens = 0

        limit = context_window_for(model) or settings.hard_context_limit
        total = system_tokens + conv_tokens + tool_instruction_tokens + role_override_tokens
        headroom = max(0, limit - total)

        return {
            "system_messages": system_tokens,
            "tool_instruction": tool_instruction_tokens,
            "role_override": role_override_tokens,
            "conversation": conv_tokens,
            "tool_schemas": tool_schema_tokens,
            "total": total,
            "limit": limit,
            "headroom": headroom,
            "model": model,
        }


# ── Helpers ─────────────────────────────────────────────────────────────────

def _is_tool_result(m: dict) -> bool:
    """Return True if this message contains a tool result (high value — keep longer)."""
    if m.get("role") == "tool":
        return True
    content = m.get("content", [])
    if isinstance(content, list):
        return any(
            isinstance(b, dict) and b.get("type") == "tool_result"
            for b in content
        )
    return False


def _is_tool_call(m: dict) -> bool:
    """Return True if this message is an assistant tool call."""
    return (
        m.get("role") == "assistant"
        and isinstance(m.get("tool_calls"), list)
        and bool(m.get("tool_calls"))
    )


def _assistant_tool_call_ids(m: dict) -> set[str]:
    """Return OpenAI-style tool call IDs emitted by an assistant message."""
    if not _is_tool_call(m):
        return set()
    return {
        tool_call.get("id")
        for tool_call in m.get("tool_calls") or []
        if isinstance(tool_call, dict) and isinstance(tool_call.get("id"), str)
    }


def _tool_result_call_id(m: dict) -> str | None:
    """Return OpenAI-style tool result call ID when present."""
    if m.get("role") != "tool":
        return None
    tool_call_id = m.get("tool_call_id")
    return tool_call_id if isinstance(tool_call_id, str) else None


def _build_atomic_message_groups(messages: list[dict]) -> list[set[int]]:
    """Build index groups for assistant tool calls and matching tool results."""
    assistant_by_call_id: dict[str, int] = {}
    for index, message in enumerate(messages):
        for tool_call_id in _assistant_tool_call_ids(message):
            assistant_by_call_id[tool_call_id] = index

    groups: dict[int, set[int]] = {}
    for index, message in enumerate(messages):
        tool_call_id = _tool_result_call_id(message)
        assistant_index = assistant_by_call_id.get(tool_call_id or "")
        if assistant_index is None:
            continue
        group = groups.setdefault(assistant_index, {assistant_index})
        group.add(index)

    return list(groups.values())


def _expand_with_atomic_groups(indices: set[int], atomic_groups: list[set[int]]) -> set[int]:
    """Include full atomic groups whenever any member index is selected."""
    expanded = set(indices)
    changed = True
    while changed:
        changed = False
        for group in atomic_groups:
            if expanded.intersection(group) and not group.issubset(expanded):
                expanded.update(group)
                changed = True
    return expanded


def _trim_kept_indices_to_budget(
    conv_msgs: list[dict],
    system_msgs: list[dict],
    kept_indices: set[int],
    atomic_groups: list[set[int]],
    effective_budget: int,
    model: str,
) -> set[int]:
    """Drop oldest kept indices, or their atomic group, until the set fits budget."""
    trimmed_indices = set(kept_indices)
    while trimmed_indices:
        candidate = [conv_msgs[j] for j in sorted(trimmed_indices)]
        if count_message_tokens(system_msgs + candidate, model) <= effective_budget:
            return trimmed_indices

        oldest_index = min(trimmed_indices)
        group_to_remove = next(
            (group for group in atomic_groups if oldest_index in group),
            {oldest_index},
        )
        trimmed_indices = trimmed_indices - group_to_remove

    return trimmed_indices


# Module-level singleton
context_engine = ContextEngine()
