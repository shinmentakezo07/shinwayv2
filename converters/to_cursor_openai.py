"""
Shin Proxy — Convert OpenAI messages to the editor (the-editor) format.

Public API:
    openai_to_cursor(messages, tools, tool_choice, reasoning_effort,
                     show_reasoning, model, json_mode, parallel_tool_calls)
        -> list[dict]  (the-editor parts-format messages)
"""
from __future__ import annotations

import json
import uuid

from config import settings
from converters.cursor_helpers import (
    _msg,
    _extract_text,
    _sanitize_user_content,
    _build_system_prompt,
    _build_role_override,
    _build_identity_declaration,
    _tool_result_text,
    _assistant_tool_call_text,
    build_tool_instruction,
)


def openai_to_cursor(
    messages: list[dict],
    tools: list[dict] | None = None,
    tool_choice=None,
    reasoning_effort: str | None = None,
    show_reasoning: bool = False,
    model: str = "",
    json_mode: bool = False,
    parallel_tool_calls: bool = True,
) -> list[dict]:
    """Convert OpenAI-format messages to Cursor parts-format.

    KEY INVARIANT: this function ALWAYS returns cursor_messages,
    regardless of stream/cache path. Call it BEFORE branching.
    """
    cursor_messages: list[dict] = []

    # System prompt
    sys_prompt = _build_system_prompt(model)
    if sys_prompt:
        cursor_messages.append(_msg("system", sys_prompt))

    # Identity override — always fires regardless of tools
    if settings.role_override_enabled:
        cursor_messages.append(_msg("system", _build_role_override(tools or [])))

    # JSON mode
    if json_mode:
        cursor_messages.append(_msg(
            "system",
            "Response format for this request: valid JSON only. "
            "No prose, no markdown fences, no explanation. "
            "Output a raw JSON object or array.",
        ))

    # Tool instruction
    tool_inst = build_tool_instruction(tools or [], tool_choice, parallel_tool_calls=parallel_tool_calls)
    if tool_inst:
        cursor_messages.append(_msg("system", tool_inst))

    # Reasoning effort
    if reasoning_effort:
        txt = f"Reasoning effort preference: {reasoning_effort}."
        if show_reasoning:
            txt += (
                " Include a visible short 'thinking' section before the final answer"
                " using: <thinking>...</thinking> then <final>...</final>."
            )
        else:
            txt += " Keep reasoning internal; return concise final answers."
        cursor_messages.append(_msg("system", txt))

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

    # User / assistant / tool messages
    # F4/F7: build a lookup from tool_call_id -> tool name from prior assistant messages
    _tool_call_name_map: dict[str, str] = {}
    for msg in messages or []:
        if msg.get("role") == "assistant" and isinstance(msg.get("tool_calls"), list):
            for tc in msg["tool_calls"]:
                tc_id = tc.get("id", "")
                tc_name = tc.get("function", {}).get("name", "")
                if tc_id and tc_name:
                    _tool_call_name_map[tc_id] = tc_name

    for msg in messages or []:
        role = msg.get("role", "user")

        if role == "tool":
            call_id = msg.get("tool_call_id") or ""
            # F4/F7: look up name from prior tool_calls, fall back to msg.name, then "tool"
            name = (
                _tool_call_name_map.get(call_id)  # authoritative: name from prior assistant tool_calls
                or msg.get("name")               # fallback: caller-supplied name
                or "tool"
            )
            # F6: do NOT sanitize tool result content — it may contain code output
            # with legitimate references that should reach the model unchanged
            text = _tool_result_text(
                name,
                call_id,
                _extract_text(msg.get("content", "")),
            )
            cursor_messages.append(_msg("user", text))
        elif (
            role == "assistant"
            and isinstance(msg.get("tool_calls"), list)
            and msg.get("tool_calls")
        ):
            # Emit prose content first if present — model may reason before calling a tool
            assistant_content = _extract_text(msg.get("content") or "")
            if assistant_content:
                cursor_messages.append(_msg("assistant", _sanitize_user_content(assistant_content)))
            text = _assistant_tool_call_text(msg["tool_calls"])
            cursor_messages.append(_msg("assistant", text))
        else:
            text = _sanitize_user_content(_extract_text(msg.get("content", "")))
            cursor_messages.append(_msg(role, text))

    return cursor_messages
