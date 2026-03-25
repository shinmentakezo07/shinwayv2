"""
Shin Proxy — Request payload validators.

All functions raise RequestValidationError on invalid input.
Pure functions — no side effects, no I/O.
"""

from __future__ import annotations

from handlers import RequestValidationError

_VALID_OPENAI_ROLES = frozenset({"user", "assistant", "system", "tool", "function"})
_VALID_ANTHROPIC_ROLES = frozenset({"user", "assistant"})


def validate_messages(
    messages: object,
    valid_roles: frozenset[str] = _VALID_OPENAI_ROLES,
) -> None:
    """Validate messages array — non-empty list of dicts with valid roles."""
    if not isinstance(messages, list) or not messages:
        raise RequestValidationError("messages must be a non-empty array")
    for i, msg in enumerate(messages):
        if not isinstance(msg, dict):
            raise RequestValidationError(f"messages[{i}] must be an object")
        role = msg.get("role")
        if not role:
            raise RequestValidationError(f"messages[{i}] missing required field 'role'")
        if not isinstance(role, str):
            raise RequestValidationError(
                f"messages[{i}].role must be a string, got {type(role).__name__}"
            )
        if role in ("user", "system"):
            content = msg.get("content")
            if content is None:
                raise RequestValidationError(
                    f"messages[{i}].content is required for role '{role}'"
                )
        if role == "assistant":
            content = msg.get("content")
            # assistant content can be None (tool-only response) but must be str/list if present
            if content is not None and not isinstance(content, (str, list)):
                raise RequestValidationError(
                    f"messages[{i}].content must be a string or null for role 'assistant', "
                    f"got {type(content).__name__}"
                )
        if role not in valid_roles:
            raise RequestValidationError(
                f"messages[{i}].role '{role}' is not valid — "
                f"must be one of: {', '.join(sorted(valid_roles))}"
            )


def validate_model(model: object) -> None:
    """Validate model field — string or absent."""
    if model is not None and model != "" and not isinstance(model, str):
        raise RequestValidationError("model must be a string")


def validate_max_tokens(max_tokens: object) -> None:
    """Validate max_tokens — positive integer when present."""
    if max_tokens is None:
        return
    if not isinstance(max_tokens, int) or isinstance(max_tokens, bool):
        raise RequestValidationError("max_tokens must be an integer")
    if max_tokens <= 0:
        raise RequestValidationError(f"max_tokens must be positive, got {max_tokens}")


def validate_temperature(temperature: object) -> None:
    """Validate temperature — float in [0.0, 2.0] when present."""
    if temperature is None:
        return
    if not isinstance(temperature, (int, float)) or isinstance(temperature, bool):
        raise RequestValidationError("temperature must be a number")
    if not (0.0 <= float(temperature) <= 2.0):
        raise RequestValidationError(
            f"temperature must be between 0.0 and 2.0, got {temperature}"
        )


def validate_n(n: object) -> None:
    """Validate n — only 1 supported."""
    if n is None:
        return
    if not isinstance(n, int) or isinstance(n, bool):
        raise RequestValidationError("n must be an integer")
    if n <= 0:
        raise RequestValidationError(f"n must be positive, got {n}")
    if n > 1:
        raise RequestValidationError(
            "n > 1 is not supported — this proxy returns a single completion"
        )


def validate_tools(tools: object, max_tools: int | None = None) -> None:
    """Validate tools array structure.

    Checks:
    - Must be a list if present
    - Each entry must be a dict with type=="function" (or no type)
    - Each function entry must have a non-empty string name
    - Total count must not exceed max_tools (default from settings.max_tools)
    """
    if tools is None:
        return
    if max_tools is None:
        from config import settings  # local import to avoid circular dependency at module load
        max_tools = settings.max_tools
    if not isinstance(tools, list):
        raise RequestValidationError("tools must be an array")
    if len(tools) > max_tools:
        raise RequestValidationError(
            f"tools array exceeds maximum of {max_tools} entries (got {len(tools)})"
        )
    for i, tool in enumerate(tools):
        if not isinstance(tool, dict):
            raise RequestValidationError(f"tools[{i}] must be an object")
        tool_type = tool.get("type")
        if tool_type is not None and tool_type != "function":
            raise RequestValidationError(
                f"tools[{i}].type must be 'function', got {tool_type!r}"
            )
        fn = tool.get("function")
        if fn is not None:
            if not isinstance(fn, dict):
                raise RequestValidationError(f"tools[{i}].function must be an object")
            name = fn.get("name")
            if name is not None and (not isinstance(name, str) or not name.strip()):
                raise RequestValidationError(
                    f"tools[{i}].function.name must be a non-empty string"
                )


def validate_openai_payload(payload: dict) -> None:
    """Full validation of an OpenAI /v1/chat/completions payload."""
    validate_model(payload.get("model"))
    validate_messages(payload.get("messages"))
    validate_max_tokens(payload.get("max_tokens"))
    validate_temperature(payload.get("temperature"))
    validate_n(payload.get("n"))
    validate_tools(payload.get("tools"))


def validate_anthropic_payload(payload: dict) -> None:
    """Full validation of an Anthropic /v1/messages payload.

    Anthropic requires max_tokens to be explicitly provided.
    """
    validate_model(payload.get("model"))
    validate_messages(payload.get("messages"), valid_roles=_VALID_ANTHROPIC_ROLES)
    if payload.get("max_tokens") is None:
        raise RequestValidationError("max_tokens is required for Anthropic messages requests")
    validate_max_tokens(payload.get("max_tokens"))
    validate_tools(payload.get("tools"))
