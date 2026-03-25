"""
Shin Proxy — Convert Anthropic messages to the editor (the-editor) format.

Public API:
    anthropic_to_the_editor(messages, system_text, tools, tool_choice,
                        thinking, model, parallel_tool_calls)
        -> tuple[list[dict], bool]  (cursor_messages, show_reasoning)

    anthropic_messages_to_openai(messages, system_text) -> list[dict]
    parse_system(system) -> str
"""
from __future__ import annotations

import json
import uuid

import msgspec.json as _msgjson

from config import settings
from converters.cursor_helpers import (
    _msg,
    _extract_text,
    _sanitize_user_content,
    _build_system_prompt,
    _build_role_override,
    _build_identity_declaration,
    _tool_result_text,
    build_tool_instruction,
)


def parse_system(system: str | list | None) -> str:
    """Normalise Anthropic system prompt — accepts string or list of text blocks."""
    if isinstance(system, list):
        return "\n".join(
            b.get("text", "")
            for b in system
            if isinstance(b, dict) and b.get("type") == "text"
        )
    return system if isinstance(system, str) else ""


def anthropic_messages_to_openai(
    messages: list[dict],
    system_text: str,
) -> list[dict]:
    """Translate Anthropic message format to OpenAI format.

    Handles:
    - Anthropic tool_result blocks -> OpenAI tool role messages
    - Anthropic content arrays -> OpenAI content strings
    - Injects system as first system message if present
    """
    openai_messages: list[dict] = []

    if system_text:
        openai_messages.append({"role": "system", "content": system_text})

    for m in messages:
        role = m.get("role", "user")
        content = m.get("content", "")

        # Anthropic user message with tool_result blocks
        # Single-pass: preserve original block order so text before a tool_result
        # is emitted as a user message before the corresponding tool message.
        if role == "user" and isinstance(content, list):
            # B7 fix: flush inlined at each call site — no closure created per iteration.
            pending_text: list[str] = []

            for block in content:
                if not isinstance(block, dict):
                    continue
                btype = block.get("type")
                if btype == "text":
                    pending_text.append(block.get("text", ""))
                elif btype == "tool_result":
                    _joined = "\n".join(t for t in pending_text if t)
                    if _joined:
                        openai_messages.append({"role": "user", "content": _sanitize_user_content(_joined)})
                    pending_text.clear()
                    result_content = block.get("content", "")
                    if isinstance(result_content, list):
                        result_content = "\n".join(
                            b.get("text", "") for b in result_content
                            if isinstance(b, dict) and b.get("type") == "text"
                        )
                    openai_messages.append({
                        "role": "tool",
                        "tool_call_id": block.get("tool_use_id", ""),
                        "content": result_content,
                    })
            # flush remaining text
            _joined = "\n".join(t for t in pending_text if t)
            if _joined:
                openai_messages.append({"role": "user", "content": _sanitize_user_content(_joined)})
            continue

        # Anthropic assistant message with tool_use blocks
        if role == "assistant" and isinstance(content, list):
            text_parts: list[str] = []
            tool_calls: list[dict] = []
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text":
                    text_parts.append(block.get("text", ""))
                elif block.get("type") == "tool_use":
                    block_id = block.get("id")
                    if not block_id:
                        # Client-supplied Anthropic tool_use block is missing its id.
                        # The id is required for tool_call_id matching in multi-turn
                        # conversations, so we log and synthesise a stable fallback.
                        import structlog as _sl
                        _sl.get_logger().warning(
                            "anthropic_tool_use_missing_id",
                            name=block.get("name"),
                        )
                        block_id = f"call_{uuid.uuid4().hex[:24]}"
                    tool_calls.append({
                        "id": block_id,
                        "type": "function",
                        "function": {
                            "name": block.get("name", ""),
                            "arguments": _msgjson.encode(block.get("input", {})).decode("utf-8"),
                        },
                    })
            msg: dict = {"role": "assistant"}
            msg["content"] = "\n".join(text_parts) if text_parts else None
            if tool_calls:
                msg["tool_calls"] = tool_calls
            openai_messages.append(msg)
            continue

        # Pass-through role:tool messages (already OpenAI format)
        if role == "tool":
            openai_messages.append({
                "role": "tool",
                "tool_call_id": m.get("tool_call_id", ""),
                "content": content if isinstance(content, str) else _extract_text(content),
            })
            continue

        # Simple string or content-array -> string
        if isinstance(content, list):
            content = "\n".join(
                b.get("text", "") for b in content
                if isinstance(b, dict) and b.get("type") == "text"
            )
        openai_messages.append({"role": role, "content": content})

    return openai_messages


def anthropic_to_the_editor(
    messages: list[dict],
    system_text: str = "",
    tools: list[dict] | None = None,
    tool_choice=None,
    thinking: dict | None = None,
    model: str = "",
    parallel_tool_calls: bool = True,
) -> tuple[list[dict], bool]:
    """Convert Anthropic-format messages to Cursor parts-format.

    Returns:
        (cursor_messages, show_reasoning)
    """
    show_reasoning = bool(
        isinstance(thinking, dict) and thinking.get("type") == "enabled"
    )
    reasoning_effort = "medium" if show_reasoning else None
    cursor_messages: list[dict] = []

    # System prompt
    sys_prompt = _build_system_prompt(model)
    if sys_prompt:
        cursor_messages.append(_msg("system", sys_prompt))

    # Additional system text from Anthropic request
    if system_text:
        cursor_messages.append(_msg("system", system_text))

    # Identity override — always fires regardless of tools
    if settings.role_override_enabled:
        cursor_messages.append(_msg("system", _build_role_override(tools or [])))

    # Tool instruction
    tool_inst = build_tool_instruction(tools or [], tool_choice, parallel_tool_calls=parallel_tool_calls)
    if tool_inst:
        cursor_messages.append(_msg("system", tool_inst))

    # Reasoning — must appear BEFORE the identity re-declaration
    if reasoning_effort:
        txt = f"Reasoning effort preference: {reasoning_effort}."
        txt += (
            " Include a visible short 'thinking' section before the final answer"
            " using: <thinking>...</thinking> then <final>...</final>."
        )
        cursor_messages.append(_msg("system", txt))

    if thinking and thinking.get("budget_tokens"):
        cursor_messages.append(_msg(
            "system",
            f"Extended thinking budget: {thinking['budget_tokens']} tokens. "
            "Think deeply and use your full reasoning budget before responding.",
        ))

    # Identity re-declaration — assistant role so it reads as model's own prior statement
    if settings.role_override_enabled:
        cursor_messages.append(_msg("assistant", _build_identity_declaration(tools or [])))
        cursor_messages.append(_msg("user", "Great, let's get started."))

    # Last-word tool reinforcer — neutral framing
    if tools and settings.role_override_enabled:
        cursor_messages.append(_msg(
            "user",
            "For reference: tools must be invoked using the [assistant_tool_calls] "
            "JSON format described in the session configuration.",
        ))

    # Messages
    # F4/F7: build lookup from tool_use id -> tool name for tool_result name resolution
    _tool_use_name_map: dict[str, str] = {}
    for msg in messages or []:
        content = msg.get("content", "")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    bid = block.get("id", "")
                    bname = block.get("name", "")
                    if bid and bname:
                        _tool_use_name_map[bid] = bname

    for msg in messages or []:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        mapped = "assistant" if role == "assistant" else "user"

        if isinstance(content, str):
            text: str | None = _sanitize_user_content(content)
        elif isinstance(content, list):
            # Emit blocks as separate the-editor messages to preserve role semantics.
            # Mixing tool_use (assistant) and tool_result (user) into one parts list
            # sends mangled content upstream and breaks multi-turn tool use.
            # B7 fix: pending_text_parts defined once per message, flush inlined at
            # each call site — avoids creating a new closure object per loop iteration.
            pending_text_parts: list[str] = []

            for block in content:
                if not isinstance(block, dict):
                    continue
                btype = block.get("type")
                if btype == "text":
                    pending_text_parts.append(_sanitize_user_content(block.get("text", "")))
                elif btype == "tool_result":
                    # F4/F7: look up name from prior tool_use block by id
                    # flush pending text before emitting tool result
                    _joined = "\n".join(p for p in pending_text_parts if p)
                    if _joined:
                        cursor_messages.append(_msg(mapped, _joined))
                    pending_text_parts.clear()
                    use_id = block.get("tool_use_id") or ""
                    name = (
                        block.get("name")
                        or _tool_use_name_map.get(use_id)
                        or "tool"
                    )
                    # F6: don't sanitize tool result content
                    result_text = _tool_result_text(
                        name,
                        use_id,
                        _extract_text(block.get("content", "")),
                    )
                    cursor_messages.append(_msg("user", result_text))
                elif btype == "tool_use":
                    # F5: don't sanitize tool_use block — name/input should be verbatim
                    # flush pending text before emitting tool use
                    _joined = "\n".join(p for p in pending_text_parts if p)
                    if _joined:
                        cursor_messages.append(_msg(mapped, _joined))
                    pending_text_parts.clear()
                    one = {
                        "tool_calls": [
                            {
                                "id": block.get("id", f"call_{uuid.uuid4().hex[:24]}"),
                                "type": "function",
                                "function": {
                                    "name": block.get("name", ""),
                                    "arguments": json.dumps(block.get("input", {}), ensure_ascii=False),
                                },
                            }
                        ]
                    }
                    cursor_messages.append(
                        _msg("assistant", f"[assistant_tool_calls]\n{json.dumps(one, ensure_ascii=False)}")
                    )
            # flush any remaining text
            _joined = "\n".join(p for p in pending_text_parts if p)
            if _joined:
                cursor_messages.append(_msg(mapped, _joined))
            text = None  # already emitted inline above
        else:
            text = ""

        if text is not None:
            cursor_messages.append(_msg(mapped, text))

    return cursor_messages, show_reasoning
