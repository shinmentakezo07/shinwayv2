"""
Shin Proxy — Bearer token auth middleware.

Key resolution order:
  1. LITELLM_MASTER_KEY — always valid
  2. SHINWAY_API_KEYS env list — legacy env keys
  3. KeyStore DB — dynamically managed keys

DB key cache (_key_cache):
  verify_bearer fetches the full key record and caches it on first DB lookup.
  get_key_record reads from the same cache — no second DB hit per request.
  TTL: 60 seconds. Key revocation takes effect within one TTL window.
  Only valid, active keys are cached. Invalid/inactive keys are not cached —
  each invalid attempt hits the DB to confirm invalidity, preserving security.

Model name convention for enforce_allowed_models:
  allowed_models entries must use the POST-RESOLUTION model name — the upstream
  model ID after resolve_model() has run (e.g. 'anthropic/claude-sonnet-4.6',
  'cursor-small'). The check runs after resolve_model() in the router, so
  client-facing aliases like 'claude-3-5-sonnet' will not match unless the
  model map resolves them to that exact string.

is_active contract:
  check_budget does not re-check is_active. It relies on verify_bearer having
  already rejected inactive keys via the DB lookup + is_active check.
  Callers must always call verify_bearer before check_budget.
"""
from __future__ import annotations

import functools
from typing import Any

from cachetools import TTLCache

from analytics import analytics
from config import settings
from handlers import AuthError, RateLimitError

import structlog

log = structlog.get_logger()


# ── Env key cache ─────────────────────────────────────────────────────────────

# maxsize=1: only one (master_key, api_keys) combination is live at a time.
# Keyed on actual secret values so any rotation produces a cache miss and
# _compute_env_keys re-runs with the new values.
@functools.lru_cache(maxsize=1)
def _compute_env_keys(master_key: str, api_keys_raw: str) -> frozenset[str]:
    """Pure computation: build frozenset from key material strings. Cached by value."""
    keys = {master_key}
    for entry in api_keys_raw.split(","):
        k = entry.strip().split(":", 1)[0].strip()
        if k:
            keys.add(k)
    return frozenset(keys)


class _EnvKeyAccessor:
    """Thin wrapper so callers can do _env_keys() and _env_keys.cache_clear()."""

    def __call__(self) -> frozenset[str]:
        return _compute_env_keys(settings.master_key, settings.api_keys)

    def cache_clear(self) -> None:  # noqa: D102 — mirrors lru_cache interface
        _compute_env_keys.cache_clear()


_env_keys = _EnvKeyAccessor()


# ── DB key record cache ───────────────────────────────────────────────────────

# Positive cache: full key record keyed by bearer token.
# Shared between verify_bearer and get_key_record so both calls on the same
# request share a single DB lookup. Revocation is effective within 60s.
_KEY_CACHE_TTL = 60   # seconds
_KEY_CACHE_MAX = 1_000  # max distinct active DB keys tracked in-process
_key_cache: TTLCache = TTLCache(maxsize=_KEY_CACHE_MAX, ttl=_KEY_CACHE_TTL)


# ── Auth functions ────────────────────────────────────────────────────────────

async def verify_bearer(authorization: str | None) -> str:
    """Validate Bearer token. Returns the key or raises AuthError.

    For DB keys: fetches the full record in one DB call and caches it so
    the subsequent get_key_record call on the same request is cache-served.
    Only valid, active keys are cached — invalid keys are never cached.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise AuthError("Authentication Error, No api key passed in.")
    token = authorization.split(" ", 1)[1].strip()
    if token in _env_keys():
        return token
    # Warm cache hit — no DB query
    if token in _key_cache:
        return token
    # Cold path — single DB call fetches full record (replaces separate is_valid)
    from storage.keys import key_store
    record = await key_store.get(token)
    if record and record.get("is_active"):
        _key_cache[token] = record
        return token
    raise AuthError("Authentication Error, Invalid api key.")


async def get_key_record(api_key: str) -> dict[str, Any] | None:
    """Fetch the full key record for a DB-managed key.

    Returns None for env keys and master key — they have no DB record.

    On warm requests: served from _key_cache populated by verify_bearer
    (zero additional DB queries). On cold calls (e.g. internal tooling that
    skips verify_bearer): falls back to a DB query and warms the cache.

    See module docstring for the model name convention used by allowed_models.
    """
    if api_key in _env_keys():
        return None
    cached = _key_cache.get(api_key)
    if cached is not None:
        return cached
    # Cold path
    from storage.keys import key_store
    record = await key_store.get(api_key)
    if record and record.get("is_active"):
        _key_cache[api_key] = record
    return record


_NO_RECORD = object()  # sentinel — caller did not provide a pre-fetched record


async def check_budget(api_key: str, key_record: object = _NO_RECORD) -> None:
    """Raise RateLimitError if per-key or global budget/token limit exceeded.

    key_record: pass a pre-fetched key record to avoid a redundant DB lookup.
    Pass None explicitly for env/master keys (no DB record).
    Omit to have check_budget fetch it itself (backwards-compatible).

    is_active contract: this function does NOT re-check is_active.
    It assumes verify_bearer has already validated the key is active.
    Always call verify_bearer before check_budget.

    Error messages intentionally omit exact budget figures to avoid leaking
    billing configuration to API consumers.
    """
    if key_record is _NO_RECORD:
        from storage.keys import key_store
        rec = await key_store.get(api_key)
    else:
        rec = key_record  # type: ignore[assignment]

    # Fetch spend once — used for both per-key check and approach logging
    spend: float | None = None

    if rec and rec["budget_usd"] > 0:
        spend = await analytics.get_spend(api_key)
        if spend >= rec["budget_usd"]:
            raise RateLimitError("Key budget limit reached. Contact the administrator.")
        # Log approach to limit for observability (at 80% threshold)
        if spend >= rec["budget_usd"] * 0.8:
            log.warning(
                "key_budget_approaching",
                api_key=api_key[:16],
                spend_usd=round(spend, 4),
                limit_usd=rec["budget_usd"],
                pct=round(spend / rec["budget_usd"] * 100, 1),
            )

    if settings.budget_usd > 0:
        total_spend = await analytics.get_total_spend()
        if total_spend >= settings.budget_usd:
            raise RateLimitError("Global budget limit reached. Contact the administrator.")

    # Per-key daily token limit (in-process counter, resets on restart)
    if rec and rec.get("token_limit_daily", 0) > 0:
        daily_tokens = await analytics.get_daily_tokens(api_key)
        if daily_tokens >= rec["token_limit_daily"]:
            raise RateLimitError("Daily token limit reached. Contact the administrator.")


def enforce_allowed_models(key_record: dict | None, model: str) -> None:
    """Raise AuthError if this key is restricted to specific models and the requested model is not allowed.

    key_record: pre-fetched key record (None for env/master keys — no restriction).
    model: the RESOLVED model name from resolve_model() — post-alias-expansion.

    Convention: allowed_models entries in the DB must use the post-resolution model
    ID (e.g. 'anthropic/claude-sonnet-4.6', not 'claude-3-5-sonnet'). See module
    docstring for full explanation.
    """
    if key_record is None:
        return  # env key / master key — unrestricted
    allowed = key_record.get("allowed_models", [])
    if not allowed:
        return  # empty list = all models allowed
    if model not in allowed:
        raise AuthError(
            f"Model '{model}' is not allowed for this key. "
            f"Allowed: {', '.join(allowed)}"
        )
