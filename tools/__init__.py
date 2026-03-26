"""Shin Proxy — tools package public API."""
from tools.coerce import _PARAM_ALIASES, _levenshtein, _fuzzy_match_param, _coerce_value  # noqa: F401
from tools.score import _find_marker_pos, score_tool_call_confidence  # noqa: F401
from tools.streaming import StreamingToolCallParser  # noqa: F401
from tools.parse import (  # noqa: F401
    extract_json_candidates,
    log_tool_calls,
    parse_tool_calls_from_text,
    repair_tool_call,
    validate_tool_call,
    _escape_unescaped_quotes,
    _extract_truncated_args,
    _lenient_json_loads,
    _repair_json_control_chars,
)
