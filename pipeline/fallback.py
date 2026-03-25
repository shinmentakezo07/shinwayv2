"""Model fallback chain — selects next model when primary upstream is exhausted."""
from __future__ import annotations

import json

from handlers import BackendError, RateLimitError, TimeoutError


# Errors that qualify a request for fallback — transient upstream failures only.
_FALLBACK_ELIGIBLE = (RateLimitError, BackendError, TimeoutError)


class FallbackChain:
    """Resolves fallback models from SHINWAY_FALLBACK_CHAIN config.

    Args:
        chain_json: Raw JSON string from settings.fallback_chain.
                    Must be a JSON object: {"model": ["fallback1", "fallback2"]}.

    Raises:
        ValueError: If chain_json is not valid JSON or not a JSON object.
    """

    def __init__(self, chain_json: str) -> None:
        try:
            parsed = json.loads(chain_json)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"SHINWAY_FALLBACK_CHAIN is not valid JSON: {exc}"
            ) from exc
        if not isinstance(parsed, dict):
            raise ValueError(
                "SHINWAY_FALLBACK_CHAIN must be a JSON object mapping model "
                f"names to lists of fallback model names, got: {type(parsed).__name__}"
            )
        self._chain: dict[str, list[str]] = parsed

    def get_fallbacks(self, model: str) -> list[str]:
        """Return the ordered fallback list for model, or [] if none configured."""
        return list(self._chain.get(model, []))

    def should_fallback(self, exc: BaseException) -> bool:
        """Return True if exc is a transient upstream error that warrants a fallback attempt."""
        return isinstance(exc, _FALLBACK_ELIGIBLE)
