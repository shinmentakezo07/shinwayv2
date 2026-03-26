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
from tools.streaming import StreamingToolCallParser  # noqa: F401
from tools.results import _build_tool_call_results  # noqa: F401

_JSON_FENCE_RE = re.compile(
    r"```(?:json)?\s*([\s\S]*?)\s*```", flags=re.IGNORECASE
)


from tools.results import _normalize_name  # noqa: F401 — defined in results.py, shared here


def _repair_json_control_chars(text: str) -> str:
    """Escape unescaped control characters inside JSON string values.

    Cursor sometimes outputs literal newlines, tabs, and carriage returns
    inside JSON string values — technically invalid but common in practice
    for large tool results like attempt_completion's 'result' field.

    This repair pass re-encodes them as their proper JSON escape sequences
    (\\n, \\r, \\t) without touching anything outside string values.
    """
    result: list[str] = []
    in_str = False
    esc = False
    _CTRL = {"\n": "\\n", "\r": "\\r", "\t": "\\t"}

    for ch in text:
        if in_str:
            if esc:
                result.append(ch)
                esc = False
            elif ch == "\\":
                result.append(ch)
                esc = True
            elif ch == '"':
                result.append(ch)
                in_str = False
            elif ord(ch) < 32:
                # Unescaped control char inside a string — fix it
                result.append(_CTRL.get(ch, f"\\u{ord(ch):04x}"))
            else:
                result.append(ch)
        else:
            if ch == '"':
                in_str = True
            result.append(ch)

    return "".join(result)


# Characters that legally follow a closing '"' in well-formed JSON (excluding ']'
# which is ambiguous — handled separately via bracket depth tracking).
_JSON_AFTER_CLOSE_QUOTE = frozenset(',}: \t\r\n')


def _escape_unescaped_quotes(text: str) -> str:
    """Escape bare double-quote chars inside JSON string values.

    The upstream model sometimes emits literal '"' chars inside string values
    (e.g. Python subscripts like captured_calls[3]["key"]), which breaks every
    JSON parser and bracket-walker that uses naive in_str toggling.

    Strategy:
    - Track square bracket depth inside each string value.
    - When inside a string and we see '"' followed by ']': if square_depth > 0
      (we opened a '[' inside this string), treat '"' as interior and escape it
      while decrementing bracket depth.  Otherwise treat as real terminator.
    - When inside a string and we see '"' followed by any other JSON structural
      char (, } : or whitespace/end): real terminator.
    - Anything else: interior literal quote, escape it.
    """
    result: list[str] = []
    in_str = False
    esc = False
    square_depth = 0  # '[' depth opened *inside* the current string value
    i = 0
    n = len(text)

    while i < n:
        ch = text[i]
        if in_str:
            if esc:
                result.append(ch)
                esc = False
            elif ch == '\\':
                result.append(ch)
                esc = True
            elif ch == '[':
                square_depth += 1
                result.append(ch)
            elif ch == ']':
                if square_depth > 0:
                    square_depth -= 1
                result.append(ch)
            elif ch == '"':
                # Look ahead past inline whitespace to determine if real terminator.
                j = i + 1
                while j < n and text[j] in ' \t':
                    j += 1
                next_ch = text[j] if j < n else ''
                if next_ch == ']' and square_depth > 0:
                    # Closing quote of a subscript key like ["key"] — interior
                    result.append('\\"')
                    # Do NOT decrement square_depth here; the ']' char will do it
                elif next_ch in _JSON_AFTER_CLOSE_QUOTE or next_ch == '' or next_ch == '"' or (next_ch == ']' and square_depth == 0):
                    # Real string terminator
                    result.append(ch)
                    in_str = False
                    square_depth = 0
                else:
                    # Interior literal quote — escape it
                    result.append('\\"')
            else:
                result.append(ch)
        else:
            if ch == '"':
                in_str = True
                esc = False
                square_depth = 0
            result.append(ch)
        i += 1

    return ''.join(result)


def _extract_after_marker(text: str) -> str | None:
    """Fallback extractor: grab the first complete JSON object after the marker.

    Uses _find_marker_pos for fence-aware marker detection and a string-aware
    bracket-depth walk so braces inside string values do not fool the counter.
    """
    marker_pos = _find_marker_pos(text)
    if marker_pos < 0:
        return None
    # Advance past the marker line to reach the JSON payload
    newline_pos = text.find('\n', marker_pos)
    after = text[newline_pos + 1:] if newline_pos >= 0 else text[marker_pos + len('[assistant_tool_calls]'):]
    brace_start = after.find('{')
    if brace_start < 0:
        return None

    # String-aware bracket-depth walk
    depth = 0
    in_str = False
    esc = False
    i = brace_start
    while i < len(after):
        ch = after[i]
        if in_str:
            if esc:
                esc = False
            elif ch == '\\':
                esc = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
                esc = False
            elif ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    return after[brace_start : i + 1]
        i += 1

    # Truncated stream — return from first { to end
    return after[brace_start:] if depth > 0 else None


# Regex to extract individual tool calls from malformed JSON.
# Matches: {"name": "...", "arguments": { ... }}  with greedy nested braces.
_TOOL_CALL_RE = re.compile(
    r'\{\s*"name"\s*:\s*"([^"]+)"\s*,\s*"arguments"\s*:\s*(\{)',
    flags=re.DOTALL,
)

# Pre-compiled for Strategy 3 field extraction — avoids re-compilation on every invocation
_KV_OPEN_RE = re.compile(r'\{\s*"([^"]+)"\s*:\s*"', re.DOTALL)
_FIELD_RE = re.compile(r'"([^"{}\[\]]+)"\s*:\s*"')


def _lenient_json_loads(raw: str) -> dict | list | None:
    """Try progressively more lenient JSON parsing strategies.

    Strategy 1: msgjson.decode (strict)
    Strategy 2: repair control chars + msgjson.decode
    Strategy 3: regex extraction of tool_calls structure — handles the case
                where 'arguments' values contain unescaped quotes (code blocks
                in attempt_completion result, write_to_file content, etc.)
    Strategy 4: truncated JSON recovery — when the stream was cut off mid-
                response and the JSON never closes properly
    """
    # Strategy 1: strict
    try:
        return msgjson.decode(raw.encode())
    except Exception:  # nosec B110 — parse strategy fallthrough; next strategy follows
        pass

    # Strategy 2: repair control chars
    try:
        repaired = _repair_json_control_chars(raw)
        result = msgjson.decode(repaired.encode())
        log.debug("json_repaired_control_chars", raw_len=len(raw))
        return result
    except Exception:  # nosec B110 — parse strategy fallthrough; next strategy follows
        pass

    # Pre-compute once; reused by Strategy 2b and Strategy 3.
    try:
        _escaped_raw = _escape_unescaped_quotes(raw)
    except Exception:
        _escaped_raw = raw

    # Strategy 2b: escape structurally-ambiguous unescaped quotes
    if _escaped_raw != raw:
        try:
            result = msgjson.decode(_escaped_raw.encode())
            log.debug("json_repaired_unescaped_quotes", raw_len=len(raw))
            return result
        except Exception:  # nosec B110 — parse strategy fallthrough; next strategy follows
            pass

    # Strategy 3: regex extraction of tool name + brute-force argument extraction
    # This handles the common case where the JSON is well-formed EXCEPT for
    # the "arguments" value which contains literal newlines and unescaped quotes.
    # Also try the Strategy-2b escaped form so the bracket walk sees valid JSON.
    _s3_inputs = [raw] if _escaped_raw == raw else [raw, _escaped_raw]
    calls = []
    truncated_calls = []
    for _s3_raw in _s3_inputs:
        if calls or truncated_calls:
            break  # already got results from first input
        for m in _TOOL_CALL_RE.finditer(_s3_raw):
            tool_name = m.group(1)
            args_start = m.start(2)  # position of the opening { of arguments

            # Find matching closing brace using a string-aware depth counter.
            # Counts { / } only when outside a JSON string so that brace characters
            # inside argument values (e.g. code blocks, templates, regexes) do not
            # cause the walk to terminate at the wrong position.
            depth = 0
            args_end = None
            in_str = False
            esc = False
            i = args_start
            while i < len(_s3_raw):
                ch = _s3_raw[i]
                if esc:
                    esc = False
                elif ch == "\\" and in_str:
                    esc = True
                elif ch == '"':
                    in_str = not in_str
                elif not in_str:
                    if ch == "{":
                        depth += 1
                    elif ch == "}":
                        depth -= 1
                        if depth == 0:
                            args_end = i
                            break
                i += 1

            if args_end is None:
                # Strategy 4: truncated JSON — the stream was cut off.
                # Extract what we can from the arguments.
                args_raw = _s3_raw[args_start:]
                args_dict = _extract_truncated_args(args_raw)
                if args_dict is not None:
                    truncated_calls.append({"name": tool_name, "arguments": args_dict})
                continue

            args_raw = _s3_raw[args_start : args_end + 1]

            # Try parsing the arguments block first with repair
            args_dict = None
            try:
                args_dict = msgjson.decode(args_raw.encode())
            except Exception:
                try:
                    args_dict = msgjson.decode(_repair_json_control_chars(args_raw).encode())
                except Exception:
                    # Last resort: extract key-value pairs manually
                    # For single-key args like {"result": "..."} — extremely common
                    kv_match = _KV_OPEN_RE.match(args_raw)
                    if kv_match:
                        # Find all key positions upfront so we can distinguish
                        # non-last fields (forward scan — clean values like file paths)
                        # from the last field (backward scan — may contain unescaped
                        # quotes, e.g. code in Write `content` or Edit `new_string`).
                        key_matches = list(_FIELD_RE.finditer(args_raw))
                        if len(key_matches) > 1:
                            # Multi-field: forward scan for all-but-last, backward for last
                            extracted: dict = {}
                            for idx, km in enumerate(key_matches):
                                fkey = km.group(1)
                                fval_start = km.end()
                                is_last = idx == len(key_matches) - 1
                                if is_last:
                                    # Backward scan: last field may have unescaped quotes
                                    val_end = len(args_raw) - 1
                                    while val_end > fval_start and args_raw[val_end] != '"':
                                        val_end -= 1
                                    fval_raw = args_raw[fval_start:val_end] if val_end > fval_start else ""
                                else:
                                    # Forward scan: stops at next field boundary
                                    next_key_start = key_matches[idx + 1].start()
                                    j = fval_start
                                    while j < next_key_start:
                                        if args_raw[j] == "\\":
                                            j += 2
                                            continue
                                        if args_raw[j] == '"':
                                            break
                                        j += 1
                                    fval_raw = args_raw[fval_start:j]
                                fval_clean = (
                                    fval_raw
                                    .replace("\\\\", "\\\\\\\\")
                                    .replace("\n", "\\n")
                                    .replace("\r", "\\r")
                                    .replace("\t", "\\t")
                                    .replace('"', '\\"')
                                )
                                try:
                                    extracted[fkey] = msgjson.decode(f'"{fval_clean}"'.encode())
                                except Exception:
                                    extracted[fkey] = fval_raw
                            if extracted:
                                args_dict = extracted
                        else:
                            # Single field: backward scan recovers full value
                            key = kv_match.group(1)
                            val_start = kv_match.end() - 1
                            val_end = len(args_raw) - 1
                            while val_end > val_start and args_raw[val_end] != '"':
                                val_end -= 1
                            if val_end > val_start:
                                val_raw = args_raw[val_start + 1 : val_end]
                                val_clean = (
                                    val_raw
                                    .replace("\\", "\\\\")
                                    .replace("\n", "\\n")
                                    .replace("\r", "\\r")
                                    .replace("\t", "\\t")
                                    .replace('"', '\\"')
                                )
                                try:
                                    rebuilt = '{' + f'"{key}": "{val_clean}"' + '}'
                                    args_dict = msgjson.decode(rebuilt.encode())
                                except Exception:
                                    # Give up on parsing args — pass raw string
                                    args_dict = {key: val_raw}

            if args_dict is not None and isinstance(args_dict, dict):
                calls.append({"name": tool_name, "arguments": args_dict})

    # Prefer complete calls over truncated ones
    final_calls = calls or truncated_calls
    if final_calls:
        log.info(
            "json_regex_fallback_extracted",
            calls=len(final_calls),
            raw_len=len(raw),
            truncated=bool(truncated_calls and not calls),
        )
        # Record whether calls came from truncated recovery or normal regex fallback
        if truncated_calls and not calls:
            inc_parse_outcome("truncated_recovery", len(truncated_calls))
        else:
            inc_parse_outcome("regex_fallback", len(final_calls))
        return {"tool_calls": final_calls}

    return None


def _decode_json_escapes(s: str) -> str:
    """Decode JSON escape sequences in a raw string value.

    Converts: \\n → newline, \\t → tab, \\r → CR, \\\\ → \\, \\" → "
    This is needed when extracting values from truncated JSON where we
    can't use a proper JSON parser.
    """
    _JSON_ESCAPES = {
        "n": "\n",
        "t": "\t",
        "r": "\r",
        "\\": "\\",
        '"': '"',
        "/": "/",
    }
    result: list[str] = []
    i = 0
    while i < len(s):
        if s[i] == "\\" and i + 1 < len(s):
            nxt = s[i + 1]
            if nxt in _JSON_ESCAPES:
                result.append(_JSON_ESCAPES[nxt])
                i += 2
                continue
            elif nxt == "u" and i + 5 < len(s):
                # Unicode escape: \uXXXX
                hex_str = s[i + 2 : i + 6]
                try:
                    result.append(chr(int(hex_str, 16)))
                    i += 6
                    continue
                except ValueError:
                    pass
            # Unknown escape — keep as-is
            result.append(s[i])
            i += 1
        else:
            result.append(s[i])
            i += 1
    return "".join(result)


def _extract_truncated_args(args_raw: str) -> dict | None:
    """Extract argument key-value pairs from truncated JSON.

    When the stream is cut off, the arguments JSON never closes:
        {"result": "Here is the flow...\\n\\n## Step 1...
    (no closing "} at the end)

    Handles both single-field and multi-field (e.g. Write with file_path +
    content) truncated payloads.  For multi-field, non-last fields use a
    forward scan bounded by the next key; the last field uses a backward scan.
    """
    # Find ALL key positions: "key": "
    key_matches = list(_FIELD_RE.finditer(args_raw))
    if not key_matches:
        return None

    extracted: dict = {}

    for idx, km in enumerate(key_matches):
        fkey = km.group(1)
        fval_start = km.end()
        is_last = idx == len(key_matches) - 1

        if is_last:
            # Backward scan from end of string — truncated value ends at last
            # meaningful character (strip trailing JSON noise)
            val_raw = args_raw[fval_start:]
            val_raw = val_raw.rstrip()
            while val_raw and val_raw[-1] in '"}]},\n\r\t ':
                val_raw = val_raw[:-1]
            fval_raw = val_raw
        else:
            # Forward scan bounded by next key's start
            next_key_start = key_matches[idx + 1].start()
            j = fval_start
            while j < next_key_start:
                if args_raw[j] == "\\":
                    j += 2
                    continue
                if args_raw[j] == '"':
                    break
                j += 1
            fval_raw = args_raw[fval_start:j]

        if not fval_raw and is_last:
            continue

        val_decoded = _decode_json_escapes(fval_raw)
        extracted[fkey] = val_decoded

    if not extracted:
        return None

    log.debug(
        "truncated_json_args_recovered",
        key=list(extracted.keys())[0],
        val_len=len(list(extracted.values())[0]) if extracted else 0,
    )
    return extracted


def extract_json_candidates(text: str) -> list[str]:
    """Extract JSON-like substrings from text.

    Handles:
    - Fenced ```json ... ``` code blocks
    - Bare JSON objects/arrays using bracket-matching
    """
    t = (text or "").strip()
    if not t:
        return []

    candidates: list[str] = []

    # Code-fenced blocks
    for m in _JSON_FENCE_RE.finditer(t):
        block = m.group(1).strip()
        if block:
            candidates.append(block)

    # Bracket-matched JSON segments
    stack: list[str] = []
    start: int | None = None
    in_str = False
    esc = False

    for i, ch in enumerate(t):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
            esc = False
            continue
        if ch in "[{":
            if start is None:
                start = i
            stack.append(ch)
        elif ch in "]}":
            if not stack:
                continue
            top = stack[-1]
            if (top == "[" and ch == "]") or (top == "{" and ch == "}"):
                stack.pop()
                if not stack and start is not None:
                    seg = t[start : i + 1].strip()
                    if seg:
                        candidates.append(seg)
                    start = None
            else:
                stack.clear()
                start = None

    # Deduplicate preserving order
    seen: set[str] = set()
    out: list[str] = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def log_tool_calls(
    calls: list[dict],
    context: str = "parsed",
    request_id: str | None = None,
) -> None:
    """Emit a structured log entry for each tool call.

    Args:
        calls:      Normalized tool call list (OpenAI format with id/type/function).
        context:    Label for where in the pipeline this log was emitted
                    (e.g. "parsed", "streaming", "retry").
        request_id: Optional request identifier for correlation.
    """
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
    if conf < 0.3:
        log.debug("tool_parse_low_confidence_dropped", score=conf)
        inc_parse_outcome("low_confidence_dropped")
        return None

    inc_parse_outcome("success", len(out))
    return out
