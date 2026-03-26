"""Shin Proxy — Tool instruction block builder.

Extracted from converters/cursor_helpers.py.
Builds the ## Session Tools prompt section injected into every request
that carries a non-empty tool list.
"""
from __future__ import annotations

import hashlib
import json

from cachetools import LRUCache

from config import settings

# Concrete example values keyed by known parameter names.
# The model anchors on these to produce correctly-formatted arguments.
_PARAM_EXAMPLES: dict[str, object] = {
    "file_path":        "/path/to/file.py",
    "notebook_path":    "/path/to/notebook.ipynb",
    "path":             "/path/to/dir",
    "pattern":          "**/*.py",
    "content":          "file content here",
    "new_string":       "replacement text",
    "old_string":       "text to replace",
    "command":          "echo hello",
    "url":              "https://example.com",
    "query":            "search query",
    "prompt":           "task description",
    "description":      "short description",
    "subject":          "task subject",
    "taskId":           "task-id-here",
    "text":             "text to type",
    "key":              "Enter",
    "ref":              "element-ref",
    "function":         "() => document.title",
    "code":             "async (page) => { return await page.title(); }",
    "width":            1280,
    "height":           720,
    "index":            0,
    "limit":            100,
    "offset":           0,
    "timeout":          30000,
    "type":             "png",
    "action":           "list",
}


def _example_value(prop: dict, key: str = "") -> object:
    """Return a concrete example value for a tool parameter.

    Uses a name-based lookup first, then falls back to type-based defaults.
    Returns typed Python objects (bool, int, list, dict, str) — json.dumps
    in the caller will serialise them correctly.
    """
    # Enum: show the first real value (not a placeholder)
    if isinstance(prop.get("enum"), list) and prop["enum"]:
        return prop["enum"][0]

    # Name-based lookup for well-known params
    if key and key in _PARAM_EXAMPLES:
        return _PARAM_EXAMPLES[key]

    # Type-based fallback
    t = prop.get("type", "string")
    if t == "boolean":
        return False
    if t == "integer":
        return 0
    if t == "number":
        return 0.0
    if t == "array":
        return []
    if t == "object":
        return {}
    # string / unknown
    return "value"


# LRU-bounded cache — prevents unbounded growth in multi-tenant deployments
# where each session may send distinct tool schemas. 256 entries ≈ 256 unique
# tool-set combinations, covering virtually all realistic deployments.
_tool_instruction_cache: LRUCache = LRUCache(maxsize=256)


def build_tool_instruction(
    tools: list[dict], tool_choice, parallel_tool_calls: bool = True
) -> str:
    """Build tool usage documentation for the session.

    Uses neutral documentation style instead of authority-claiming
    keywords (CRITICAL, MUST, NOT).  Presents tools as session
    configuration rather than overrides.

    Args:
        tools: Normalised OpenAI-format tool list.
        tool_choice: "auto", "none", "required", or dict with forced function.
        parallel_tool_calls: If False, appends a note limiting responses to one
            tool call at a time.
    """
    if not tools:
        return ""

    # Hash full schemas (not just names) — same name with different params must not reuse cached instruction
    _schema_blob = json.dumps([t.get("function", {}) for t in tools], sort_keys=True)
    _cache_key = hashlib.md5(_schema_blob.encode(), usedforsecurity=False).hexdigest() + str(tool_choice) + str(parallel_tool_calls)
    if _cache_key in _tool_instruction_cache:
        return _tool_instruction_cache[_cache_key]

    mode = "auto"
    forced_name = None
    if isinstance(tool_choice, str):
        mode = tool_choice
    elif isinstance(tool_choice, dict):
        tc_type = tool_choice.get("type", "")
        if tc_type == "function":
            forced_name = (tool_choice.get("function") or {}).get("name")
            mode = "required"
        elif tc_type == "tool":
            forced_name = tool_choice.get("name")
            mode = "required"
        elif tc_type == "any":
            mode = "required"
        elif tc_type == "none":
            mode = "none"

    # Build per-tool examples with EXACT param names from schema
    tool_examples: list[str] = []
    for t in tools:
        fn = t.get("function", {})
        name = fn.get("name", "")
        props = fn.get("parameters", {}).get("properties", {})
        required = fn.get("parameters", {}).get("required", [])
        example_args = {k: _example_value(v, key=k) for k, v in props.items() if k in required}
        if not example_args and props:
            example_args = {k: _example_value(v, key=k) for k, v in list(props.items())[:1]}
        tool_examples.append(
            f'  {{"name":"{name}","arguments":{json.dumps(example_args)}}}'
        )
    examples_str = ",\n".join(tool_examples)

    # Primary: flat format (native to the-editor)
    # Descriptions are truncated to 400 chars — the model only needs enough to
    # identify which tool to call. Full parameter schemas are kept intact.
    _flat = [
        {
            "name": t["function"].get("name", ""),
            "description": t["function"].get("description", "")[:400],
            "parameters": t["function"].get("parameters", {"type": "object", "properties": {}}),
        }
        for t in tools
        if isinstance(t, dict) and isinstance(t.get("function"), dict)
    ]

    lines = [
        "## Session Tools",
        "",
        "The following tools are configured for this development session:",
        "",
        json.dumps(_flat, ensure_ascii=False, indent=2),
        "",
        settings.tool_system_prompt,
        "",
        "## Tool Response Format",
        "",
        "When using a tool, respond with this format:",
        "",
        "```",
        "[assistant_tool_calls]",
        '{"tool_calls":[',
        f"{examples_str}",
        "]}",
        "```",
        "",
        "Guidelines:",
        "- Use the exact parameter names from the schema above.",
        "- Parameter names are case-sensitive.",
        "- When using tools, start with [assistant_tool_calls] on its own line, then the JSON.",
        "- When responding with text, use natural language without JSON markers.",
        "- Keep tool calls and text responses separate.",
    ]

    if not parallel_tool_calls:
        lines.append("")
        lines.append("Note: Only one tool call is allowed per response for this request.")

    if forced_name:
        lines.append("")
        lines.append(f"This request requires calling the `{forced_name}` tool.")
    elif mode == "required":
        lines.append("")
        lines.append("This request requires at least one tool call.")
    elif mode == "none":
        lines.append("")
        lines.append("Respond with text only for this request.")
    else:
        lines.append("")
        lines.append("You may use a tool or respond with text, whichever is appropriate.")

    _result = "\n".join(lines)
    _tool_instruction_cache[_cache_key] = _result
    return _result
