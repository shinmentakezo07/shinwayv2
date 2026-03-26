"""
Shin Proxy — Full JSON Schema validation for tool call arguments.

Checks required fields, types, enum membership, string length,
number bounds, and array item count. Pure function — no side effects.
"""
from __future__ import annotations

_TYPE_CHECKS: dict[str, type | tuple[type, ...]] = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "array": list,
    "object": dict,
}


def validate_schema(
    args: dict,
    schema: dict,
    tool_name: str = "",
) -> tuple[bool, list[str]]:
    """Validate args against a JSON Schema 'parameters' object.

    Returns (is_valid, errors). errors is empty when valid.

    Args:
        args: The tool call arguments to validate.
        schema: A JSON Schema 'parameters' object with 'properties' and 'required'.
        tool_name: Optional tool name used as prefix in error messages.

    Returns:
        A tuple of (is_valid, errors) where errors is an empty list when valid.

    Example:
        >>> ok, errs = validate_schema({"cmd": "ls"}, {"type": "object", "properties": {"cmd": {"type": "string"}}, "required": ["cmd"]})
        >>> ok
        True
    """
    errors: list[str] = []
    prefix = f"{tool_name}: " if tool_name else ""
    properties: dict = schema.get("properties", {})
    required: list[str] = schema.get("required", [])

    for req in required:
        if req not in args:
            errors.append(f"{prefix}missing required param '{req}'")

    for key, value in args.items():
        prop = properties.get(key)
        if prop is None:
            continue

        expected_type = prop.get("type")
        type_ok = True
        if expected_type and expected_type in _TYPE_CHECKS:
            expected_python = _TYPE_CHECKS[expected_type]
            if expected_type == "integer" and isinstance(value, bool):
                errors.append(f"{prefix}param '{key}': expected integer, got bool")
                type_ok = False
            elif expected_type == "number" and isinstance(value, bool):
                errors.append(f"{prefix}param '{key}': expected number, got bool")
                type_ok = False
            elif not isinstance(value, expected_python):
                errors.append(
                    f"{prefix}param '{key}': expected {expected_type}, got {type(value).__name__}"
                )
                type_ok = False

        if not type_ok:
            continue

        enum_vals = prop.get("enum")
        if enum_vals is not None and value not in enum_vals:
            errors.append(f"{prefix}param '{key}': value {value!r} not in enum {enum_vals}")

        if expected_type == "string" and isinstance(value, str):
            min_len = prop.get("minLength")
            max_len = prop.get("maxLength")
            if min_len is not None and len(value) < min_len:
                errors.append(f"{prefix}param '{key}': length {len(value)} < minLength {min_len}")
            if max_len is not None and len(value) > max_len:
                errors.append(f"{prefix}param '{key}': length {len(value)} > maxLength {max_len}")

        if expected_type in ("number", "integer") and isinstance(value, (int, float)) and not isinstance(value, bool):
            minimum = prop.get("minimum")
            maximum = prop.get("maximum")
            if minimum is not None and value < minimum:
                errors.append(f"{prefix}param '{key}': value {value} < minimum {minimum}")
            if maximum is not None and value > maximum:
                errors.append(f"{prefix}param '{key}': value {value} > maximum {maximum}")

        if expected_type == "array" and isinstance(value, list):
            min_items = prop.get("minItems")
            max_items = prop.get("maxItems")
            if min_items is not None and len(value) < min_items:
                errors.append(f"{prefix}param '{key}': {len(value)} items < minItems {min_items}")
            if max_items is not None and len(value) > max_items:
                errors.append(f"{prefix}param '{key}': {len(value)} items > maxItems {max_items}")

    return len(errors) == 0, errors
