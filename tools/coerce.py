"""
Shin Proxy — Tool parameter coercion and fuzzy name matching.

Extracted from tools/parse.py. No imports from other tools/ modules.
"""
from __future__ import annotations

import re

import msgspec.json as msgjson


# ── Common param aliases the model tends to use wrong ───────────────────────
# Maps normalized wrong name → canonical param name.
# Applied BEFORE fuzzy matching as a fast-path.
_PARAM_ALIASES: dict[str, str] = {
    # Bash
    "cmd": "command",
    "bash": "command",
    "shell": "command",
    "script": "command",
    "run": "command",
    # Read / Write / Edit
    "file": "file_path",
    "filepath": "file_path",
    "filename": "file_path",
    "path": "file_path",
    # NOTE: "src", "source", "destination", "dest" intentionally omitted —
    # they are too generic and cause the repair logic to mismap content/args
    # from other tools (e.g. treating file content as file_path).
    # Edit
    "old": "old_string",
    "oldstr": "old_string",
    "oldstring": "old_string",
    "original": "old_string",
    "search": "old_string",
    "find": "old_string",
    "new": "new_string",
    "newstr": "new_string",
    "newstring": "new_string",
    "replacement": "new_string",
    "replace": "new_string",
    # Write
    "body": "content",
    "data": "content",
    "contents": "content",
    # NOTE: "text" intentionally omitted — too ambiguous, collides with
    # many other tools that have a 'text' param meaning something else.
    # Glob
    "glob": "pattern",
    "match": "pattern",
    "filter": "pattern",
    # Grep
    "query": "pattern",
    "regex": "pattern",
    "searchpattern": "pattern",
    # WebSearch
    "searchquery": "query",
    "searchterm": "query",
    "term": "query",
    "keywords": "query",
    # WebFetch
    "link": "url",
    "uri": "url",
    "webpage": "url",
    "website": "url",
    # Agent
    "task": "prompt",
    "instruction": "prompt",
    "instructions": "prompt",
    "message": "prompt",
    "desc": "description",
    # TaskCreate / TaskUpdate
    "title": "subject",
    "name": "subject",
    "id": "taskId",
    "taskid": "taskId",
    "status": "status",
    # read_file / read_dir (backend tools injected by the-editor)
    # 'files'→'filePath' and 'dir'→'dirPath' share no substring and have
    # edit distance > 2, so no fuzzy strategy catches them.
    "files": "filePath",
    "dir": "dirPath",
}


def _levenshtein(a: str, b: str) -> int:
    """Compute Levenshtein edit distance between two strings."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        curr = [i + 1]
        for j, cb in enumerate(b):
            curr.append(min(
                prev[j + 1] + 1,   # deletion
                curr[j] + 1,        # insertion
                prev[j] + (ca != cb),  # substitution
            ))
        prev = curr
    return prev[len(b)]


def _fuzzy_match_param(supplied: str, known_keys: set[str]) -> str | None:
    """Find the best matching known param for a supplied (possibly wrong) param name.

    Strategy order (first match wins):
    1. Exact match (already checked by caller)
    2. Alias table lookup
    3. Normalized exact match (strip - _ spaces, lowercase)
    4. Levenshtein distance ≤ 2 for short keys
    5. Substring containment (one contains the other)
    6. Shared prefix ≥ 4 chars
    """
    norm = re.sub(r"[-_\s]", "", supplied.lower())

    # Strategy 2: alias table
    alias_target = _PARAM_ALIASES.get(norm)
    if alias_target and alias_target in known_keys:
        return alias_target

    # Precompute normalized known keys
    norm_known = {k: re.sub(r"[-_\s]", "", k.lower()) for k in known_keys}

    # Strategy 3: normalized exact match
    for k, nk in norm_known.items():
        if norm == nk:
            return k

    # Strategy 4: Levenshtein distance ≤ 2 (only for keys ≤ 12 chars to avoid false positives)
    if len(norm) <= 12:
        best_k: str | None = None
        best_dist = 3
        for k, nk in norm_known.items():
            if abs(len(norm) - len(nk)) > 2:
                continue
            dist = _levenshtein(norm, nk)
            if dist < best_dist:
                best_dist = dist
                best_k = k
        if best_k is not None:
            return best_k

    # Strategy 5: substring containment (only for substrings ≥ 5 chars to avoid
    # false positives like "file" matching "file_path" when content was intended)
    if len(norm) >= 5:
        for k, nk in norm_known.items():
            if norm in nk or nk in norm:
                return k

    # Strategy 6: shared prefix ≥ 5 chars (raised from 4 to reduce false positives)
    for k, nk in norm_known.items():
        prefix_len = 0
        for a, b in zip(norm, nk):
            if a == b:
                prefix_len += 1
            else:
                break
        if prefix_len >= 5:
            return k

    return None


def _coerce_value(value: object, prop_schema: dict, key: str, repairs: list[str]) -> object:
    """Coerce a value to match the type declared in the property schema.

    Handles common model mistakes:
    - Passing a string where a number/boolean/array is expected
    - Passing a number where a string is expected
    - Passing a string "true"/"false" where a boolean is expected
    - Passing a JSON string where an object/array is expected
    """
    expected = prop_schema.get("type")
    if not expected or value is None:
        return value

    # boolean coercion
    if expected == "boolean":
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            if value.lower() in ("true", "1", "yes"):
                repairs.append(f"coerced '{key}': string '{value}' \u2192 true")
                return True
            if value.lower() in ("false", "0", "no", ""):
                repairs.append(f"coerced '{key}': string '{value}' \u2192 false")
                return False
        if isinstance(value, (int, float)):
            repairs.append(f"coerced '{key}': number {value} \u2192 bool")
            return bool(value)

    # number / integer coercion
    if expected in ("number", "integer"):
        if isinstance(value, (int, float)):
            return value
        if isinstance(value, str):
            try:
                coerced = int(value) if expected == "integer" else float(value)
                repairs.append(f"coerced '{key}': string '{value}' \u2192 {expected}")
                return coerced
            except (ValueError, TypeError):
                pass

    # string coercion
    if expected == "string":
        if isinstance(value, str):
            return value
        if isinstance(value, (int, float, bool)):
            repairs.append(f"coerced '{key}': {type(value).__name__} \u2192 string")
            return str(value)
        if isinstance(value, (dict, list)):
            repairs.append(f"coerced '{key}': {type(value).__name__} \u2192 JSON string")
            return msgjson.encode(value).decode("utf-8")

    # array coercion — wrap scalar in list
    if expected == "array":
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            # Try parsing as JSON array first
            stripped = value.strip()
            if stripped.startswith("["):
                try:
                    parsed = msgjson.decode(stripped.encode())
                    if isinstance(parsed, list):
                        repairs.append(f"coerced '{key}': JSON string \u2192 array")
                        return parsed
                except Exception:  # nosec B110 — parse strategy fallthrough; next strategy follows
                    pass
            # Wrap as single-element array
            repairs.append(f"coerced '{key}': string \u2192 [string]")
            return [value]
        repairs.append(f"coerced '{key}': {type(value).__name__} \u2192 [value]")
        return [value]

    # object coercion
    if expected == "object":
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.startswith("{"):
                try:
                    parsed = msgjson.decode(stripped.encode())
                    if isinstance(parsed, dict):
                        repairs.append(f"coerced '{key}': JSON string \u2192 object")
                        return parsed
                except Exception:  # nosec B110 — parse strategy fallthrough; next strategy follows
                    pass

    return value
