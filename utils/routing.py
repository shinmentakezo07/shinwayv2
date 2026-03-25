"""
Shin Proxy — Model routing utilities.

resolve_model() maps any incoming model name to a Cursor model string
via the SHINWAY_MODEL_MAP env var.
"""

from __future__ import annotations

import json
import functools

import structlog

log = structlog.get_logger()


@functools.lru_cache(maxsize=1)
def _load_model_map() -> dict[str, str]:
    """Load and parse SHINWAY_MODEL_MAP from settings (cached)."""
    from config import settings

    raw = settings.model_map
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return {str(k): str(v) for k, v in parsed.items()}
    except Exception as exc:
        log.warning("model_map_parse_error", error=str(exc), raw=raw[:200])
    return {}


def resolve_model(requested: str | None) -> str:
    """Map any model name to a Cursor model string via SHINWAY_MODEL_MAP.

    Falls back to the requested model itself if no mapping found.
    Falls back to the default Cursor model if requested is empty/None.
    """
    from routers.model_router import resolve_model as _legacy_resolve

    if not requested:
        # Use legacy resolver which has its own fallback catalogue
        return _legacy_resolve(None)

    model_map = _load_model_map()
    if requested in model_map:
        resolved = model_map[requested]
        log.debug("model_resolved_via_map", from_model=requested, to_model=resolved)
        return resolved

    # Fall through to legacy resolver (handles aliases + catalogue)
    return _legacy_resolve(requested)
