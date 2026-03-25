"""
Shin Proxy — Responses API output converter.

Translates pipeline output (OpenAI format) into Responses API
response object shape and SSE event sequence.
"""
from __future__ import annotations

import json
import time
import uuid

import structlog

log = structlog.get_logger()


def responses_sse_event(event_type: str, data: dict) -> str:
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


def _build_message_output_item(text: str, msg_id: str) -> dict:
    return {
        "type": "message",
        "id": msg_id,
        "role": "assistant",
        "status": "completed",
        "content": [{"type": "output_text", "text": text, "annotations": []}],
    }


def _build_function_call_output_item(tc: dict, idx: int, item_id: str | None = None) -> dict:
    fn = tc.get("function", {})
    return {
        "type": "function_call",
        "id": item_id or f"fc_{uuid.uuid4().hex[:8]}",
        "call_id": tc.get("id", f"call_{uuid.uuid4().hex[:8]}"),
        "name": fn.get("name", ""),
        "arguments": fn.get("arguments", "{}"),
        "status": "completed",
    }


def build_response_object(
    response_id: str,
    model: str,
    text: str | None,
    tool_calls: list[dict] | None,
    input_tokens: int,
    output_tokens: int,
    params: dict,
    item_ids: list[str] | None = None,
    msg_id: str | None = None,
) -> dict:
    output: list[dict] = []

    if text:
        _msg_id = msg_id or f"msg_{uuid.uuid4().hex[:24]}"
        output.append(_build_message_output_item(text, _msg_id))
    if tool_calls:
        for i, tc in enumerate(tool_calls):
            iid = (item_ids[i] if item_ids and i < len(item_ids) else None)
            output.append(_build_function_call_output_item(tc, i, item_id=iid))

    return {
        "id": response_id,
        "object": "response",
        "created_at": int(time.time()),
        "model": model,
        "status": "completed",
        "output": output,
        "usage": {
            "input_tokens": input_tokens,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens": output_tokens,
            "output_tokens_details": {"reasoning_tokens": 0},
            "total_tokens": input_tokens + output_tokens,
        },
        "tool_choice": params.get("tool_choice", "auto"),
        "tools": params.get("tools", []),
        "parallel_tool_calls": params.get("parallel_tool_calls", True),
        "truncation": "disabled",
        "temperature": params.get("temperature", 1.0),
        "store": params.get("store", True),
        "instructions": params.get("instructions"),
        "previous_response_id": params.get("previous_response_id"),
        "metadata": params.get("metadata") or {},
        "error": None,
        "incomplete_details": None,
    }


def build_in_progress_response(response_id: str, model: str, params: dict) -> dict:
    resp = build_response_object(
        response_id=response_id,
        model=model,
        text=None,
        tool_calls=None,
        input_tokens=0,
        output_tokens=0,
        params=params,
    )
    resp["status"] = "in_progress"
    return resp


def generate_streaming_events(
    response_id: str,
    model: str,
    text: str,
    tool_calls: list[dict] | None,
    input_tokens: int,
    output_tokens: int,
    params: dict,
) -> list[str]:
    seq = 0
    events: list[str] = []

    in_progress = build_in_progress_response(response_id, model, params)
    events.append(responses_sse_event("response.created", {
        "type": "response.created", "sequence_number": seq, "response": in_progress
    }))
    seq += 1

    msg_id: str | None = None
    tc_item_ids: list[str] = []

    # Message item (output_index=0) — emit first when text is present,
    # matching the canonical order in build_response_object.
    if text:
        msg_id = f"msg_{uuid.uuid4().hex[:24]}"
        events.append(responses_sse_event("response.output_item.added", {
            "type": "response.output_item.added",
            "sequence_number": seq, "output_index": 0,
            "item": {"type": "message", "id": msg_id, "role": "assistant",
                     "status": "in_progress", "content": []},
        }))
        seq += 1
        events.append(responses_sse_event("response.content_part.added", {
            "type": "response.content_part.added",
            "sequence_number": seq, "item_id": msg_id,
            "output_index": 0, "content_index": 0,
            "part": {"type": "output_text", "text": "", "annotations": []},
        }))
        seq += 1
        for i in range(0, len(text), 40):
            chunk = text[i:i + 40]
            events.append(responses_sse_event("response.output_text.delta", {
                "type": "response.output_text.delta",
                "sequence_number": seq, "item_id": msg_id,
                "output_index": 0, "content_index": 0, "delta": chunk,
            }))
            seq += 1
        events.append(responses_sse_event("response.output_text.done", {
            "type": "response.output_text.done",
            "sequence_number": seq, "item_id": msg_id,
            "output_index": 0, "content_index": 0, "text": text,
        }))
        seq += 1
        events.append(responses_sse_event("response.content_part.done", {
            "type": "response.content_part.done",
            "sequence_number": seq, "item_id": msg_id,
            "output_index": 0, "content_index": 0,
            "part": {"type": "output_text", "text": text, "annotations": []},
        }))
        seq += 1
        completed_item = _build_message_output_item(text, msg_id)
        events.append(responses_sse_event("response.output_item.done", {
            "type": "response.output_item.done",
            "sequence_number": seq, "output_index": 0, "item": completed_item,
        }))
        seq += 1

    # Tool call items — when text is present, message occupies output_index=0,
    # so tool calls start at index 1; otherwise they start at index 0.
    tc_output_offset = 1 if text else 0
    if tool_calls:
        for i, tc in enumerate(tool_calls):
            item_id = f"fc_{uuid.uuid4().hex[:8]}"
            tc_item_ids.append(item_id)
            item = _build_function_call_output_item(tc, i, item_id=item_id)
            item_in_progress = {**item, "status": "in_progress"}
            arguments = tc.get("function", {}).get("arguments", "{}")
            events.append(responses_sse_event("response.output_item.added", {
                "type": "response.output_item.added",
                "sequence_number": seq, "output_index": tc_output_offset + i,
                "item": item_in_progress,
            }))
            seq += 1
            events.append(responses_sse_event("response.function_call_arguments.delta", {
                "type": "response.function_call_arguments.delta",
                "sequence_number": seq, "item_id": item_id,
                "output_index": tc_output_offset + i,
                "delta": arguments,
            }))
            seq += 1
            events.append(responses_sse_event("response.function_call_arguments.done", {
                "type": "response.function_call_arguments.done",
                "sequence_number": seq, "item_id": item_id,
                "output_index": tc_output_offset + i,
                "arguments": arguments,
            }))
            seq += 1
            events.append(responses_sse_event("response.output_item.done", {
                "type": "response.output_item.done",
                "sequence_number": seq, "output_index": tc_output_offset + i,
                "item": item,
            }))
            seq += 1

    completed = build_response_object(
        response_id=response_id, model=model, text=text,
        tool_calls=tool_calls, input_tokens=input_tokens,
        output_tokens=output_tokens, params=params,
        item_ids=tc_item_ids if tc_item_ids else None,
        msg_id=msg_id,
    )
    events.append(responses_sse_event("response.completed", {
        "type": "response.completed", "sequence_number": seq, "response": completed,
    }))
    seq += 1
    events.append(responses_sse_event("response.done", {
        "type": "response.done",
        "sequence_number": seq,
        "response": completed,
    }))

    return events
