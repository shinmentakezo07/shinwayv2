"""
Shin Proxy — Full tool call validation.

Composes validate_tool_call (structural: name + required presence) and
validate_schema (type, enum, bounds) into a single sequential gate.
validate_schema is only called when validate_tool_call passes, so required-
field errors are never duplicated.
"""
from __future__ import annotations

import msgspec.json as msgjson

from tools.metrics import inc_schema_validation
from tools.parse import validate_tool_call
from tools.schema import validate_schema


def validate_tool_call_full(
    call: dict,
    tools: list[dict],
) -> tuple[bool, list[str]]:
    """Full validation: name + required presence + JSON Schema type/enum/bounds.

    Sequential gate:
    1. validate_tool_call — structural check (name present, required params present).
       Returns early on failure — no point running schema on a broken call.
    2. validate_schema — type, enum, minLength/maxLength, minimum/maximum, minItems/maxItems.
       Only called when step 1 passes, so required-field errors are never duplicated.

    Args:
        call:  Single tool call in OpenAI format
               {"id": ..., "type": "function", "function": {"name": ..., "arguments": ...}}
        tools: List of tool definitions in OpenAI format.

    Returns:
        (is_valid, errors). errors is empty when valid.

    Example:
        >>> import json
        >>> call = {"id": "c1", "type": "function", "function": {"name": "Bash", "arguments": json.dumps({"command": "ls"})}}
        >>> tool = {"type": "function", "function": {"name": "Bash", "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}}}
        >>> validate_tool_call_full(call, [tool])
        (True, [])
    """
    # Step 1: structural check (name present, required params present, tool exists)
    ok, errors = validate_tool_call(call, tools)
    if not ok:
        return False, errors

    # Step 2: find the matching tool's parameters schema
    fn = call.get("function", {})
    name = fn.get("name", "")
    parameters: dict | None = None
    for t in tools or []:
        fn_def = t.get("function", {})
        if fn_def.get("name") == name:
            parameters = fn_def.get("parameters", {})
            break

    if parameters is None:
        return True, []

    # Step 3: parse arguments to dict
    args_raw = fn.get("arguments", "{}")
    if isinstance(args_raw, str):
        try:
            args_dict: dict = msgjson.decode(args_raw.encode()) if args_raw else {}
        except Exception:
            return False, [f"arguments is not valid JSON for tool '{name}'"]
    elif isinstance(args_raw, dict):
        args_dict = args_raw
    else:
        args_dict = {}

    # Step 4: full schema enforcement (type, enum, bounds)
    ok, errors = validate_schema(args_dict, parameters, tool_name=name)
    inc_schema_validation("passed" if ok else "failed")
    return ok, errors
