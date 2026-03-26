"""
Shin Proxy — Tool call budget enforcement.

limit_tool_calls and repair_invalid_calls extracted from pipeline/tools.py.
repair_invalid_calls now uses validate_tool_call_full (full schema enforcement)
instead of validate_tool_call (structural only).
"""
from __future__ import annotations

import structlog

from tools.metrics import inc_tool_repair
from tools.parse import repair_tool_call
from tools.validate import validate_tool_call_full

log = structlog.get_logger()


def limit_tool_calls(calls: list[dict], parallel: bool) -> list[dict]:
    """Enforce parallel_tool_calls limit.

    If parallel=False, returns only the first call.
    If parallel=True or calls is empty, returns unchanged.
    """
    if calls and not parallel:
        return calls[:1]
    return calls


def repair_invalid_calls(
    calls: list[dict],
    tools: list[dict],
) -> list[dict]:
    """Validate each call with full schema enforcement; attempt repair if invalid.

    Four-case behavior:
    1. validate_tool_call_full passes -> append unchanged.
    2. Fails -> repair_tool_call produces repairs -> re-validate passes -> append repaired.
    3. Fails -> repair_tool_call produces repairs -> re-validate still fails -> drop, warn.
    4. Fails -> repair_tool_call produces no repairs -> pass through original, warn (non-fatal).
    """
    out: list[dict] = []
    for call in calls:
        ok, errs = validate_tool_call_full(call, tools)
        if ok:
            out.append(call)
            inc_tool_repair("passed")
            continue
        repaired, repairs = repair_tool_call(call, tools)
        if repairs:
            ok2, errs2 = validate_tool_call_full(repaired, tools)
            if ok2:
                out.append(repaired)
                inc_tool_repair("repaired")
            else:
                log.warning(
                    "tool_call_unrepairable",
                    tool=call.get("function", {}).get("name"),
                    original_errors=errs,
                    post_repair_errors=errs2,
                )
                inc_tool_repair("dropped")
        else:
            log.warning(
                "tool_call_validation_failed",
                tool=call.get("function", {}).get("name"),
                errors=errs,
            )
            out.append(call)  # case 4: pass through — non-fatal
            inc_tool_repair("passed_through")
    return out


def deduplicate_tool_calls(calls: list[dict]) -> list[dict]:
    """Remove duplicate tool calls by (name, arguments) signature.

    Preserves the first occurrence. Does not mutate the input list.
    """
    seen: set[str] = set()
    out: list[dict] = []
    for call in calls:
        fn = call.get("function", {})
        sig = fn.get("name", "") + fn.get("arguments", "{}")
        if sig not in seen:
            seen.add(sig)
            out.append(call)
    return out
