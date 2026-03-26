"""
Shin Proxy — Tool call repair.

Extracts repair_tool_call from tools/parse.py.
Applies fuzzy param name matching, type coercion, required param filling,
and unknown param dropping.
"""
from __future__ import annotations

import uuid

import msgspec.json as msgjson
import structlog

from tools.coerce import _coerce_value, _fuzzy_match_param

log = structlog.get_logger()


def repair_tool_call(
    call: dict,
    tools: list[dict],
) -> tuple[dict, list[str]]:
    """Attempt to repair a malformed tool call using the schema.

    Repair strategies (applied in order):
    1. Alias table: known wrong names → canonical names
    2. Normalized exact match: strip separators + lowercase
    3. Levenshtein distance ≤ 2 for short param names
    4. Substring containment match
    5. Shared prefix ≥ 4 chars
    6. Fill missing required params — safe typed fallbacks only (string params with no enum are skipped to prevent fabricating empty destructive values)
    7. Coerce wrong value types (str→int, str→bool, etc.)
    8. Drop params that cannot be mapped to any known key

    Args:
        call:  Single tool call in OpenAI format.
        tools: Tool definitions.

    Returns:
        (repaired_call, repairs) — repairs is a list of human-readable descriptions.
        Returns original call and [] if no repairs were needed.
    """
    repairs: list[str] = []

    fn = call.get("function", {})
    name = fn.get("name", "")
    args_raw = fn.get("arguments", "{}")

    # Parse args
    if isinstance(args_raw, str):
        try:
            args_dict: dict = msgjson.decode(args_raw.encode()) if args_raw else {}
        except Exception:
            args_dict = {}
    elif isinstance(args_raw, dict):
        args_dict = dict(args_raw)
    else:
        args_dict = {}

    # Find schema for this tool
    schema: dict | None = None
    for t in tools or []:
        fn_def = t.get("function", {})
        if fn_def.get("name") == name:
            schema = fn_def
            break

    if schema is None:
        # Return original call unchanged. Empty repairs list is indistinguishable from "no repairs needed" — intentional: unknown-schema tools (read_file, read_dir) are backend-injected and pass through unmodified.
        return call, repairs

    params = schema.get("parameters", {})
    known_props: dict = params.get("properties", {})
    known_keys = set(known_props.keys())
    required = set(params.get("required", []))

    repaired_args: dict = {}

    # Pass 1 — map each supplied arg to a known param
    for supplied_key, value in args_dict.items():
        if supplied_key in known_keys:
            repaired_args[supplied_key] = value
            continue

        best = _fuzzy_match_param(supplied_key, known_keys)
        if best:
            # Coerce value type if schema specifies one
            value = _coerce_value(value, known_props.get(best, {}), supplied_key, repairs)
            repaired_args[best] = value
            repairs.append(f"param '{supplied_key}' → '{best}'")
        else:
            repairs.append(f"dropped unknown param '{supplied_key}'")

    # Pass 2 — coerce types for already-mapped params
    for key in list(repaired_args.keys()):
        if key in known_props:
            repaired_args[key] = _coerce_value(
                repaired_args[key], known_props[key], key, repairs
            )

    # Pass 3 — fill missing required params with type-appropriate fallback.
    # String params with no enum are NOT filled — fabricating an empty string
    # for a param like 'command' or 'path' would silently run destructive ops.
    for req in required:
        if req not in repaired_args:
            prop_schema = known_props.get(req, {})
            prop_type = prop_schema.get("type", "string")
            enum_vals = prop_schema.get("enum")
            if enum_vals:
                fallback = enum_vals[0]  # use first enum value
                repairs.append(f"filled missing required '{req}' with first enum value '{fallback}'")
            elif prop_type == "array":
                fallback = []
                repairs.append(f"filled missing required '{req}' with []")
            elif prop_type == "object":
                fallback = {}
                repairs.append(f"filled missing required '{req}' with {{}}")
            elif prop_type == "boolean":
                fallback = False
                repairs.append(f"filled missing required '{req}' with false")
            elif prop_type == "number" or prop_type == "integer":
                fallback = 0
                repairs.append(f"filled missing required '{req}' with 0")
            else:
                # Cannot safely fabricate a string value for an unknown required param —
                # empty string is dangerous (e.g. empty 'command' runs bare shell, empty
                # 'path' writes to cwd). Mark as unfillable; validation will drop the call.
                repairs.append(f"UNFILLABLE: missing required string '{req}' has no safe default")
                continue
            repaired_args[req] = fallback

    if not repairs:
        return call, []

    # Rebuild call with repaired args.
    # Preserve the id from the input call — it was assigned in _build_tool_call_results
    # and must not change here; changing it would break tool_call_id matching downstream.
    tc_id = call.get("id")
    if not tc_id:
        log.warning("repair_tool_call_missing_id", tool=name)
        tc_id = f"call_{uuid.uuid4().hex[:24]}"
    arg_str = msgjson.encode(repaired_args).decode("utf-8")
    repaired_call = {
        "id": tc_id,
        "type": "function",
        "function": {"name": name, "arguments": arg_str},
    }
    log.info(
        "tool_call_repaired",
        tool=name,
        repairs=repairs,
    )
    return repaired_call, repairs
