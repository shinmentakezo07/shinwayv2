"""
Shin Proxy — Responses API input converter.

Converts OpenAI Responses API input[] + instructions + prior history
into OpenAI messages[] for pipeline.py.
"""
from __future__ import annotations

import json
import uuid
import structlog

log = structlog.get_logger()

BUILTIN_TOOL_TYPES: frozenset[str] = frozenset({
    "web_search_preview",
    "web_search_preview_2025_03_11",
    "web_search",
    "code_interpreter",
    "file_search",
    "computer",
    "computer_use_preview",
    "image_generation",
})


def _output_text_from_content(content: list[dict] | str) -> str:
    if isinstance(content, str):
        return content
    return "\n".join(
        b.get("text", "") for b in content
        if isinstance(b, dict) and b.get("type") in ("output_text", "text", "input_text")
    )


def _prior_output_to_messages(prior_output: list[dict]) -> list[dict]:
    msgs: list[dict] = []

    for item in prior_output:
        t = item.get("type")

        if t == "message":
            role = item.get("role", "assistant")
            content = item.get("content", [])
            # Detect tool_use blocks and reconstruct as tool_calls — do not collapse to empty string
            if isinstance(content, list):
                tool_use_blocks = [
                    b for b in content
                    if isinstance(b, dict) and b.get("type") == "tool_use"
                ]
                if tool_use_blocks:
                    text = _output_text_from_content(content)
                    if text:
                        msgs.append({"role": role, "content": text})
                    msgs.append({
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": b.get("id", f"call_{uuid.uuid4().hex[:8]}"),
                                "type": "function",
                                "function": {
                                    "name": b.get("name", ""),
                                    "arguments": json.dumps(b.get("input", {})),
                                },
                            }
                            for b in tool_use_blocks
                        ],
                    })
                    continue
            text = _output_text_from_content(content)
            msgs.append({"role": role, "content": text})

        elif t == "function_call":
            msgs.append({
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": item.get("call_id", f"call_{uuid.uuid4().hex[:8]}"),
                    "type": "function",
                    "function": {
                        "name": item.get("name", ""),
                        "arguments": item.get("arguments", "{}"),
                    },
                }],
            })

        elif t == "function_call_output":
            msgs.append({
                "role": "tool",
                "tool_call_id": item.get("call_id", ""),
                "content": item.get("output", ""),
            })

        elif t == "reasoning":
            # Preserve reasoning summaries as assistant messages for multi-turn continuity.
            summary_parts = [
                s.get("text", "")
                for s in item.get("summary") or []
                if isinstance(s, dict) and s.get("type") == "summary_text"
            ]
            text = "\n".join(p for p in summary_parts if p)
            if text:
                msgs.append({"role": "assistant", "content": text})
            else:
                log.debug("to_responses_skip_prior_item", item_type=t)

        else:
            log.debug("to_responses_skip_prior_item", item_type=t)

    return msgs


def input_to_messages(
    input_data: str | list,
    instructions: str | None = None,
    prior_output: list[dict] | None = None,
) -> list[dict]:
    msgs: list[dict] = []

    if instructions:
        msgs.append({"role": "system", "content": instructions})

    if prior_output:
        msgs.extend(_prior_output_to_messages(prior_output))

    if isinstance(input_data, str):
        msgs.append({"role": "user", "content": input_data})
        return msgs

    for item in input_data:
        if not isinstance(item, dict):
            continue
        t = item.get("type")
        role = item.get("role")

        if t == "function_call_output":
            msgs.append({
                "role": "tool",
                "tool_call_id": item.get("call_id", ""),
                "content": item.get("output", ""),
            })
        elif t == "function_call":
            msgs.append({
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": item.get("call_id", f"call_{uuid.uuid4().hex[:8]}"),
                    "type": "function",
                    "function": {
                        "name": item.get("name", ""),
                        "arguments": item.get("arguments", "{}"),
                    },
                }],
            })
        elif role in ("user", "assistant", "system", "developer"):
            actual_role = "system" if role == "developer" else role
            content = item.get("content", "")
            if isinstance(content, list):
                text_parts: list[str] = []
                for p in content:
                    if not isinstance(p, dict):
                        continue
                    btype = p.get("type")
                    if btype in ("input_text", "text", "output_text"):
                        text_parts.append(p.get("text", ""))
                    elif btype is not None:
                        log.warning(
                            "input_to_messages_dropped_non_text_block",
                            block_type=btype,
                            role=actual_role,
                        )
                content = "\n".join(text_parts)
            msgs.append({"role": actual_role, "content": content})
        else:
            log.debug("to_responses_skip_item", item_type=t)

    return msgs


def extract_function_tools(tools: list[dict]) -> list[dict]:
    out: list[dict] = []
    for t in tools or []:
        tool_type = t.get("type")
        if tool_type in BUILTIN_TOOL_TYPES:
            continue
        if tool_type != "function":
            # Whitelist approach: only explicit function tools pass through.
            if tool_type is not None:
                log.warning("extract_function_tools_skipped_unknown_type", tool_type=tool_type)
            else:
                log.warning("extract_function_tools_skipped_missing_type", tool_name=t.get("name"))
            continue
        fn = {
            "type": "function",
            "function": {
                "name": t.get("name", ""),
                "description": t.get("description", ""),
                "parameters": t.get("parameters", {"type": "object", "properties": {}}),
            },
        }
        out.append(fn)
    return out


def has_builtin_tools(tools: list[dict]) -> bool:
    return any(t.get("type") in BUILTIN_TOOL_TYPES for t in tools or [])
