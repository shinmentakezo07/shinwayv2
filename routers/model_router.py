"""
Shin Proxy — Model routing / alias resolution.

Maps requested model names to Cursor-compatible model strings.
Configured via SHINWAY_MODEL_MAP env var (JSON object).
"""

from __future__ import annotations

import json

import structlog

from config import settings

log = structlog.get_logger()

# ── Model metadata catalogue ─────────────────────────────────────────────────

_CATALOGUE: dict[str, dict] = {
    "anthropic/claude-sonnet-4.6":  {"context": 1_000_000, "owner": "anthropic"},
    "anthropic/claude-opus-4.6":    {"context": 1_000_000, "owner": "anthropic"},
    "openai/gpt-5.4":               {"context": 1_000_000, "owner": "openai"},
    "google/gemini-3.1-pro-preview": {"context": 1_000_000, "owner": "google"},
    "google/gemini-3-flash-preview":  {"context": 1_000_000, "owner": "google"},
    "openai/gpt-5.1-codex-mini":      {"context": 400_000, "owner": "openai"},
    "composer-2":                     {"context": 200_000,  "owner": "cursor"},
}

# ── Built-in aliases ─────────────────────────────────────────────────────────
# Common shorthand names that map to canonical model IDs.
_BUILTIN_ALIASES: dict[str, str] = {}

_DEFAULT_META = {"context": 1_000_000, "owner": "cursor"}

# Lazy-loaded alias map from settings.
# L3 note: _alias_map = None is the sentinel for "not yet loaded". In CPython
# the GIL makes the double-initialise benign (worst case: double JSON parse on
# the very first concurrent request pair). Tests reset this to None between runs.
_alias_map: dict[str, str] | None = None


def _load_alias_map() -> dict[str, str]:
    global _alias_map
    if _alias_map is None:
        try:
            parsed = json.loads(settings.model_map) if settings.model_map else {}
            env_map = parsed if isinstance(parsed, dict) else {}
            if not isinstance(parsed, dict) and parsed:
                log.warning("model_map_not_a_dict", raw=settings.model_map[:120])
        except Exception:
            log.warning("model_map_parse_error", raw=settings.model_map[:120])
            env_map = {}
        # Merge: built-in aliases as base, env overrides take precedence
        _alias_map = {**_BUILTIN_ALIASES, **env_map}
    return _alias_map


def resolve_model(requested: str | None) -> str:
    """Resolve a requested model name through the alias map.

    - If an alias exists, return the mapped value.
    - Unknown models are passed through as-is (Cursor may handle them).
    - If no model provided, returns the first model in the catalogue as default.

    IMPORTANT: Always returns the EXACT same model ID to Cursor — no silent
    substitution. The model the client requested is the model Cursor receives.
    """
    if not requested:
        default = next(iter(_CATALOGUE))
        log.warning("model_not_specified", using_default=default)
        return default
    alias = _load_alias_map()
    resolved = alias.get(requested, requested)
    if resolved != requested:
        log.info("model_alias_resolved", requested=requested, resolved=resolved)
    return resolved


def model_info(model_id: str) -> dict:
    """Return metadata for a model id (falls back to defaults for unknown models)."""
    return _CATALOGUE.get(model_id, _DEFAULT_META)


def all_models() -> list[dict]:
    """Return the full model catalogue list (built-in + runtime additions)."""
    return [
        {"id": mid, **meta}
        for mid, meta in {**_CATALOGUE, **_runtime_catalogue}.items()
    ]


# ── Runtime catalogue — models added/removed without restart ──────────────────
# Keyed by model_id, same shape as _CATALOGUE values.
_runtime_catalogue: dict[str, dict] = {}


def add_model(model_id: str, context: int, owner: str) -> dict:
    """Add a model to the runtime catalogue. Takes effect immediately."""
    entry = {"context": context, "owner": owner}
    _runtime_catalogue[model_id] = entry
    log.info("model_added", model_id=model_id, owner=owner)
    return {"id": model_id, **entry}


def remove_model(model_id: str) -> bool:
    """Remove a model from the runtime catalogue.

    Built-in _CATALOGUE entries cannot be removed — only runtime additions.
    Returns True if removed, False if not found in runtime catalogue.
    """
    if model_id in _runtime_catalogue:
        del _runtime_catalogue[model_id]
        log.info("model_removed", model_id=model_id)
        return True
    return False
