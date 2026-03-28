"""
Shin Proxy — Tool call result builder.

Extracts _build_tool_call_results from tools/parse.py.
Builds normalized tool call dicts from merged parsed candidates.
"""
from __future__ import annotations

import re
import uuid

import msgspec.json as msgjson
import structlog

from tools.coerce import _fuzzy_match_param

log = structlog.get_logger()


def _normalize_name(name: str) -> str:
    """Normalize tool name for fuzzy matching — lowercase, strip separators."""
    return re.sub(r"[-_\s]", "", (name or "").lower())


def _build_tool_call_results(
    *,
    merged: list[dict],
    allowed_exact: dict[str, str],
    schema_map: dict[str, set[str]],
    streaming: bool,
) -> list[dict]:
    """Build normalized tool call results from merged parsed candidates."""
    out: list[dict] = []
    for c in merged:
        if not isinstance(c, dict):
            continue
        # Handle both {"function": {"name": ...}} and {"name": ...}
        if isinstance(c.get("function"), dict):
            name = c["function"].get("name")
            args = c["function"].get("arguments", {})
        else:
            name = c.get("name")
            args = c.get("arguments", {})

        if not isinstance(name, str):
            continue

        # Fix 2 — fuzzy name matching: normalize and look up canonical name
        norm = _normalize_name(name)
        if norm not in allowed_exact:
            if not streaming:
                log.warning(
                    "tool_parse_name_not_allowed",
                    got_name=name,
                    allowed_names=list(allowed_exact.values()),
                )
            continue

        canonical_name = allowed_exact[norm]
        if name != canonical_name:
            log.info(
                "tool_name_fuzzy_corrected",
                from_name=name,
                to_name=canonical_name,
            )
        name = canonical_name

        # Parse args to dict for validation
        if isinstance(args, str):
            try:
                args_dict: dict = msgjson.decode(args.encode()) if args else {}
                # Handle double-encoded JSON
                if isinstance(args_dict, str):
                    args_dict = msgjson.decode(args_dict.encode())
            except Exception:
                args_dict = {}
        else:
            args_dict = args if isinstance(args, dict) else {}

        # Validate param names against schema — rename known aliases, drop rest
        known_props = schema_map.get(name, set())
        if known_props:
            bad_keys = set(args_dict.keys()) - known_props
            if bad_keys:
                for bad_key in list(bad_keys):
                    canonical = _fuzzy_match_param(bad_key, known_props)
                    if canonical:
                        args_dict[canonical] = args_dict.pop(bad_key)
                        bad_keys.discard(bad_key)
                if bad_keys:
                    log.warning(
                        "tool_param_name_mismatch",
                        tool=name,
                        bad_keys=sorted(bad_keys),
                        expected=sorted(known_props),
                    )
                    args_dict = {k: v for k, v in args_dict.items() if k in known_props}

        # INVARIANT: arguments is always a JSON string
        arg_str = msgjson.encode(args_dict).decode("utf-8")
        from config import settings
        if len(arg_str) > settings.max_tool_args_bytes:
            log.warning(
                "tool_args_oversized_dropped",
                tool=name,
                size=len(arg_str),
                limit=settings.max_tool_args_bytes,
            )
            continue
        # Preserve any id that was already present in the parsed payload;
        # only generate a fresh id when none exists.  This is the single
        # canonical assignment point — downstream code must not re-generate.
        tc_id = c.get("id") or f"call_{uuid.uuid4().hex[:24]}"
        out.append(
            {
                "id": tc_id,
                "type": "function",
                "function": {"name": name, "arguments": arg_str},
            }
        )

    return out
