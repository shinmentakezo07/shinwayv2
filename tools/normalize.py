"""
Shin Proxy — Tool normalization.

Converts between OpenAI and Anthropic tool schemas, ensuring a consistent
internal representation (OpenAI format) for the Cursor API.
"""

from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

import structlog

try:
    import litellm
except Exception:  # pragma: no cover - dependency may not be installed yet
    litellm = SimpleNamespace(
        utils=SimpleNamespace(
            convert_to_openai_tool_format=None,
            convert_to_anthropic_tool_format=None,
        )
    )
else:  # pragma: no branch
    if not hasattr(litellm, "utils"):
        litellm.utils = SimpleNamespace()
    if not hasattr(litellm.utils, "convert_to_openai_tool_format"):
        litellm.utils.convert_to_openai_tool_format = None
    if not hasattr(litellm.utils, "convert_to_anthropic_tool_format"):
        litellm.utils.convert_to_anthropic_tool_format = None


log = structlog.get_logger()

_OPENAI_DEFAULT_PARAMETERS = {"type": "object", "properties": {}}
_VALID_TOOL_CHOICE_STRINGS = {"auto", "none", "required", "any"}


def _default_parameters() -> dict:
    return deepcopy(_OPENAI_DEFAULT_PARAMETERS)


def _manual_normalize_openai_tools(tools: list[dict] | None) -> list[dict]:
    out: list[dict] = []
    for t in tools or []:
        if not isinstance(t, dict) or t.get("type") != "function":
            continue
        fn = t.get("function")
        if not isinstance(fn, dict) or not isinstance(fn.get("name"), str):
            continue
        out.append(
            {
                "type": "function",
                "function": {
                    "name": fn["name"],
                    "description": fn.get("description", ""),
                    "parameters": deepcopy(fn.get("parameters", _default_parameters())),
                },
            }
        )
    return out


def _manual_normalize_anthropic_tools(tools: list[dict] | None) -> list[dict]:
    out: list[dict] = []
    for t in tools or []:
        if not isinstance(t, dict) or not isinstance(t.get("name"), str):
            continue
        out.append(
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": deepcopy(t.get("input_schema", _default_parameters())),
                },
            }
        )
    return out


def _manual_to_anthropic_tool_format(openai_tools: list[dict] | None) -> list[dict]:
    result: list[dict] = []
    for t in openai_tools or []:
        if not isinstance(t, dict) or t.get("type") != "function":
            continue
        fn = t.get("function", {})
        if not isinstance(fn.get("name"), str):
            continue
        result.append(
            {
                "name": fn["name"],
                "description": fn.get("description", ""),
                "input_schema": deepcopy(fn.get("parameters", _default_parameters())),
            }
        )
    return result


def normalize_openai_tools(tools: list[dict] | None) -> list[dict]:
    """Normalise OpenAI-format tools, discarding malformed entries."""
    return _manual_normalize_openai_tools(tools)


def normalize_anthropic_tools(tools: list[dict] | None) -> list[dict]:
    """Convert Anthropic-format tools to internal (OpenAI) format."""
    converter = getattr(getattr(litellm, "utils", None), "convert_to_openai_tool_format", None)
    if callable(converter):
        converted: list[dict] = []
        try:
            for tool in tools or []:
                if not isinstance(tool, dict):
                    continue
                converted_tool = converter(tool)
                converted.extend(normalize_openai_tools([deepcopy(converted_tool)]))
            return converted
        except Exception as exc:
            log.warning("litellm_openai_tool_normalization_failed", error=str(exc))
    return _manual_normalize_anthropic_tools(tools)


def to_anthropic_tool_format(openai_tools: list[dict] | None) -> list[dict]:
    """Convert normalised OpenAI tools to Anthropic tool_use format for Cursor."""
    converter = getattr(getattr(litellm, "utils", None), "convert_to_anthropic_tool_format", None)
    if callable(converter):
        converted: list[dict] = []
        try:
            for tool in normalize_openai_tools(openai_tools):
                converted_tool = converter(tool)
                if isinstance(converted_tool, dict) and isinstance(converted_tool.get("name"), str):
                    converted.append(
                        {
                            "name": converted_tool["name"],
                            "description": converted_tool.get("description", ""),
                            "input_schema": deepcopy(converted_tool.get("input_schema", _default_parameters())),
                        }
                    )
            return converted
        except Exception as exc:
            log.warning("litellm_anthropic_tool_normalization_failed", error=str(exc))
    return _manual_to_anthropic_tool_format(openai_tools)



def validate_tool_choice(
    tool_choice: str | dict | None,
    tools: list[dict] | None,
) -> str | dict:
    """Validate tool_choice while preserving current default behavior."""
    has_tools = bool(tools)

    if isinstance(tool_choice, dict):
        return deepcopy(tool_choice)

    if isinstance(tool_choice, str):
        if tool_choice in _VALID_TOOL_CHOICE_STRINGS:
            return tool_choice
        # Fix: log unknown values so misconfigured tool_choice doesn't fail silently
        log.warning(
            "unknown_tool_choice_coerced",
            received=tool_choice,
            coerced_to="auto" if has_tools else "none",
        )
        return "auto" if has_tools else "none"

    if tool_choice is None:
        return "auto" if has_tools else "none"

    return "auto" if has_tools else "none"
