"""
Shin Proxy — Tool call parser.

Extracts structured tool call objects from raw Cursor response text.
All `arguments` values are guaranteed to be JSON strings on output.
"""

from __future__ import annotations

import re
import uuid
from typing import TYPE_CHECKING

import msgspec.json as msgjson
import structlog

if TYPE_CHECKING:
    from tools.registry import ToolRegistry

from tools.metrics import inc_parse_outcome

log = structlog.get_logger()

# ── Extracted to focused modules — re-exported here for backward compat ──────
from tools.coerce import (  # noqa: F401
    _PARAM_ALIASES,
    _levenshtein,
    _fuzzy_match_param,
    _coerce_value,
)
from tools.score import (  # noqa: F401
    _TOOL_CALL_MARKER_RE,
    _find_marker_pos,
    score_tool_call_confidence,
)
from tools.confidence import CONFIDENCE_THRESHOLD  # noqa: F401
from tools.streaming import StreamingToolCallParser  # noqa: F401
from tools.results import _build_tool_call_results  # noqa: F401

from tools.results import _normalize_name  # noqa: F401 — defined in results.py, shared here
from tools.repair import repair_tool_call  # noqa: F401
from tools.json_repair import (  # noqa: F401
    _repair_json_control_chars,
    _escape_unescaped_quotes,
    _extract_after_marker,
    _lenient_json_loads,
    _decode_json_escapes,
    _extract_truncated_args,
    extract_json_candidates,
)


def log_tool_calls(
    calls: list[dict],
    context: str = "parsed",
    request_id: str | None = None,
    raw: str = "",
    outcome: str = "success",
) -> None:
    """Emit a structured log entry for each tool call.

    Args:
        calls:      Normalized tool call list (OpenAI format with id/type/function).
        context:    Label for where in the pipeline this log was emitted
                    (e.g. "parsed", "streaming", "retry").
        request_id: Optional request identifier for correlation.
        raw:        Raw marker+JSON text slice from the upstream stream.
        outcome:    Parse outcome label passed to the audit ring buffer.
    """
    from tools.audit import tool_call_audit  # lazy — avoids circular at module load
    tool_call_audit.record(calls or [], raw=raw, outcome=outcome, request_id=request_id or "")
    for call in calls or []:
        fn = call.get("function", {})
        name = fn.get("name", "unknown")
        args_raw = fn.get("arguments", "{}")
        try:
            args_dict = msgjson.decode(args_raw.encode()) if isinstance(args_raw, str) else args_raw
        except Exception:
            args_dict = {}
        log.info(
            "tool_call",
            context=context,
            tool=name,
            call_id=call.get("id", ""),
            arg_keys=sorted(args_dict.keys()) if isinstance(args_dict, dict) else [],
            arg_count=len(args_dict) if isinstance(args_dict, dict) else 0,
            **({"request_id": request_id} if request_id else {}),
        )


def validate_tool_call(
    call: dict,
    tools: list[dict],
) -> tuple[bool, list[str]]:
    """Validate a single tool call against the tool schema.

    Pure helper — no side effects, no mutation.

    Args:
        call:  Single tool call in OpenAI format
               {"id": ..., "type": "function", "function": {"name": ..., "arguments": ...}}
        tools: List of tool definitions in OpenAI format.

    Returns:
        (is_valid, errors) — errors is an empty list when valid.
    """
    errors: list[str] = []

    fn = call.get("function", {})
    name = fn.get("name")
    args_raw = fn.get("arguments", "{}")

    if not name:
        errors.append("missing tool name")
        return False, errors

    # Parse arguments
    if isinstance(args_raw, str):
        try:
            args_dict = msgjson.decode(args_raw.encode()) if args_raw else {}
        except Exception as exc:
            errors.append(f"arguments is not valid JSON: {exc}")
            return False, errors
    elif isinstance(args_raw, dict):
        args_dict = args_raw
    else:
        errors.append(f"arguments has unexpected type: {type(args_raw).__name__}")
        return False, errors

    # Find matching tool schema
    schema: dict | None = None
    for t in tools or []:
        fn_def = t.get("function", {})
        if fn_def.get("name") == name:
            schema = fn_def
            break

    if schema is None:
        errors.append(f"tool '{name}' not found in schema")
        return False, errors

    params = schema.get("parameters", {})
    known_props = set(params.get("properties", {}).keys())
    required = set(params.get("required", []))

    # Check required params are present
    for req in required:
        if req not in args_dict:
            errors.append(f"missing required param '{req}'")

    # Check for unknown params
    if known_props:
        unknown = set(args_dict.keys()) - known_props
        for uk in sorted(unknown):
            errors.append(f"unknown param '{uk}'")

    return len(errors) == 0, errors



def parse_tool_calls_from_text(
    text: str,
    tools: list[dict] | None,
    streaming: bool = False,
    registry: "ToolRegistry | None" = None,
) -> list[dict] | None:
    """Parse tool calls from assistant response text.

    Returns None if no valid tool calls are found.
    Each returned item has the shape:
        {"id": "call_...", "type": "function",
         "function": {"name": "...", "arguments": "<json string>"}}
    """
    if not tools:
        log.debug("tool_parse_skipped_no_tools")
        return None

    if registry is not None:
        allowed_exact = registry.allowed_exact()
        schema_map = registry.schema_map()
        # NOTE: ToolRegistry silently overwrites on tool name collision.
        # The no-registry path emits a tool_name_normalization_collision warning.
        # Accepted trade-off for the rebuild elimination.
    else:
        # Build exact and fuzzy name lookups: normalized → canonical name.
        # Detect normalization collisions (e.g. write_file vs write-file both → writefile)
        # and warn — the last tool registered would silently win otherwise.
        allowed_exact: dict[str, str] = {}
        for t in tools:
            if isinstance(t, dict):
                orig = t.get("function", {}).get("name", "")
                if orig:
                    norm = _normalize_name(orig)
                    if norm in allowed_exact and allowed_exact[norm] != orig:
                        log.warning(
                            "tool_name_normalization_collision",
                            name_a=allowed_exact[norm],
                            name_b=orig,
                            normalized=norm,
                        )
                    allowed_exact[norm] = orig

        # Always allow the-editor's backend documentation tools — the backend injects
        # read_file/read_dir into every session regardless of the client's tool list.
        # Without this, any time the model calls a docs tool the call is dropped.
        _CURSOR_BACKEND_TOOLS: dict[str, set[str]] = {
            "read_file": {"filePath"},
            "read_dir": {"dirPath"},
        }
        for _bt in _CURSOR_BACKEND_TOOLS:
            allowed_exact[_normalize_name(_bt)] = _bt

        # Build schema lookup: canonical name → valid param names
        schema_map: dict[str, set[str]] = {}
        for t in tools:
            fn = t.get("function", {})
            tname = fn.get("name", "")
            props = fn.get("parameters", {}).get("properties", {})
            if tname:
                schema_map[tname] = set(props.keys())

        # Add schema for backend tools
        schema_map.update(_CURSOR_BACKEND_TOOLS)

    # During streaming, only look at text AFTER the [assistant_tool_calls] marker.
    # Use the strict anchored marker detection so we don't pick up the marker
    # when it's mentioned inside a code block or prose example.
    parse_text = text
    marker_pos = _find_marker_pos(text)
    if marker_pos >= 0:
        parse_text = text[marker_pos:]
    elif streaming:
        # No real marker yet during streaming — nothing to parse
        return None

    objs: list = []
    raw_candidates = extract_json_candidates(parse_text)
    for raw in raw_candidates:
        parsed = _lenient_json_loads(raw)
        if parsed is not None:
            objs.append(parsed)

    # Fallback: if marker was found but bracket matching couldn't extract valid
    # JSON (usually because Cursor's output contains unescaped quotes inside
    # string values like code blocks in attempt_completion), grab everything
    # from the first { after the marker to the last } and try lenient parsing.
    # Only run at stream end (not during streaming) to avoid log spam.
    if not objs and marker_pos >= 0 and not streaming:
        fallback_raw = _extract_after_marker(text)
        if fallback_raw:
            parsed = _lenient_json_loads(fallback_raw)
            if parsed is not None:
                objs.append(parsed)
                log.info(
                    "tool_parse_fallback_extraction",
                    raw_len=len(fallback_raw),
                )

    if not objs:
        if not streaming and marker_pos >= 0:
            log.debug(
                "tool_parse_marker_found_no_json",
                text_snippet=text[:300],
            )
        return None

    # Fix 3 — handle more JSON shapes from Cursor
    merged: list[dict] = []
    for obj in objs:
        # Shape 1: [{"name":...}]
        if isinstance(obj, list):
            merged.extend(obj)
        # Shape 2: {"tool_calls": [...]}  ← standard Cursor
        elif isinstance(obj, dict) and isinstance(obj.get("tool_calls"), list):
            merged.extend(obj["tool_calls"])
        # Shape 3: {"name": ..., "arguments": ...}  ← single call as bare object
        elif isinstance(obj, dict) and "name" in obj:
            merged.append(obj)
        # Shape 4: {"function": {"name":...}}  ← OpenAI native format
        elif isinstance(obj, dict) and isinstance(obj.get("function"), dict):
            merged.append(obj)
        # Shape 5: nested {"result": {"tool_calls": [...]}} or similar
        elif isinstance(obj, dict):
            for val in obj.values():
                if isinstance(val, list):
                    for item in val:
                        if isinstance(item, dict) and (
                            "name" in item or "function" in item
                        ):
                            merged.append(item)

    if not merged:
        # Only warn if there was a non-trivial JSON structure parsed
        # (skip empty lists [] which appear constantly during streaming)
        non_empty = [o for o in objs if o != [] and o != {} and o is not None]
        if non_empty and not streaming:
            log.warning(
                "tool_parse_json_structure_unknown",
                parsed_shapes=[type(o).__name__ for o in non_empty],
                snippet=str(non_empty)[:200],
            )
        return None

    out = _build_tool_call_results(
        merged=merged,
        allowed_exact=allowed_exact,
        schema_map=schema_map,
        streaming=streaming,
    )

    if not out and merged:
        if not streaming:
            log.warning("tool_parse_all_calls_dropped", candidates=len(merged))

    if not out:
        return None

    # Deduplicate by (name, arguments) signature — the-editor sometimes emits
    # the same tool call twice at stream boundaries when the buffer is re-parsed.
    seen_sigs: set[str] = set()
    deduped: list[dict] = []
    for call in out:
        sig = call["function"]["name"] + call["function"]["arguments"]
        if sig not in seen_sigs:
            seen_sigs.add(sig)
            deduped.append(call)
    if len(deduped) < len(out):
        log.debug("tool_calls_deduplicated", original=len(out), after=len(deduped))
    out = deduped

    # Confidence gate — drop accidental JSON that happens to look like a tool call.
    # Applied here so it covers both streaming and non-streaming paths uniformly.
    conf = score_tool_call_confidence(text, out)
    if conf < CONFIDENCE_THRESHOLD:
        log.debug("tool_parse_low_confidence_dropped", score=conf)
        inc_parse_outcome("low_confidence_dropped")
        return None

    inc_parse_outcome("success", len(out))
    return out
