"""
Shin Proxy — Request-scoped tool registry.

Built once per request from the client's tool list. Immutable after init.
Replaces per-call rebuilding of allowed_exact / schema_map in parse.py.
"""
from __future__ import annotations

import re
from copy import deepcopy

from tools.coerce import _fuzzy_match_param


def _normalize_name(name: str) -> str:
    return re.sub(r"[-_\s]", "", (name or "").lower())


_CURSOR_BACKEND_TOOLS: dict[str, set[str]] = {
    "read_file": {"filePath"},
    "read_dir": {"dirPath"},
}


class ToolRegistry:
    """Immutable request-scoped registry of canonical tool names and schemas.

    Build once per request via ToolRegistry(tools). All state is frozen
    at construction; no mutation after __init__.
    """

    def __init__(
        self,
        tools: list[dict],
        backend_tools: dict[str, set[str]] | None = None,
    ) -> None:
        # Deep-copy so mutations to the input list cannot affect this registry.
        _tools = deepcopy(tools or [])
        _extra = dict(backend_tools or _CURSOR_BACKEND_TOOLS)

        _ae: dict[str, str] = {}       # normalized_name -> canonical_name
        _sm: dict[str, set[str]] = {}  # canonical_name -> param names
        _schemas: dict[str, dict] = {} # canonical_name -> parameters dict

        for t in _tools:
            if not isinstance(t, dict):
                continue
            fn = t.get("function", {})
            name = fn.get("name", "")
            if not name:
                continue
            norm = _normalize_name(name)
            _ae[norm] = name
            params = fn.get("parameters", {})
            _sm[name] = set(params.get("properties", {}).keys())
            _schemas[name] = params

        for bt_name, bt_params in _extra.items():
            norm = _normalize_name(bt_name)
            _ae[norm] = bt_name
            _sm[bt_name] = bt_params
            _schemas[bt_name] = {"type": "object", "properties": {p: {} for p in bt_params}}

        # Name-mangled to prevent external mutation
        self.__allowed_exact: dict[str, str] = _ae
        self.__schema_map: dict[str, set[str]] = _sm
        self.__schemas: dict[str, dict] = _schemas

    def canonical_name(self, raw_name: str) -> str | None:
        """Return the canonical tool name for raw_name, or None if unknown."""
        norm = _normalize_name(raw_name)
        exact = self.__allowed_exact.get(norm)
        if exact:
            return exact
        known = set(self.__allowed_exact.values())
        return _fuzzy_match_param(raw_name, known)

    def schema(self, canonical_name: str) -> dict | None:
        """Return the 'parameters' schema dict for a canonical tool name."""
        return self.__schemas.get(canonical_name)

    def known_params(self, canonical_name: str) -> set[str]:
        """Return the set of known parameter names for a canonical tool name."""
        return self.__schema_map.get(canonical_name, set())

    def allowed_exact(self) -> dict[str, str]:
        """Return normalized_name -> canonical_name mapping."""
        return self.__allowed_exact

    def schema_map(self) -> dict[str, set[str]]:
        """Return canonical_name -> param set mapping."""
        return self.__schema_map
