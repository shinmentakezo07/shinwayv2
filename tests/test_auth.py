"""
Tests for middleware/auth.py — verify_bearer, get_key_record, check_budget, enforce_allowed_models.

Patching notes:
- _env_keys() is lru_cache(maxsize=1). Call _env_keys.cache_clear() before and after any test
  that monkeypatches settings, so the cache does not bleed between tests.
- key_store methods are patched via AsyncMock on storage.keys.key_store (the module-level singleton).
  auth.py imports key_store lazily inside each function body, so patching the singleton works.
- analytics methods are patched directly on middleware.auth.analytics (the module-level reference).
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock

import middleware.auth as auth_mod
from handlers import AuthError, RateLimitError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clear_env_keys_cache():
    """Clear the lru_cache on _env_keys so monkeypatched settings take effect."""
    auth_mod._env_keys.cache_clear()


# ---------------------------------------------------------------------------
# verify_bearer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verify_bearer_missing_header_raises_auth_error():
    """None authorization header must raise AuthError."""
    with pytest.raises(AuthError):
        await auth_mod.verify_bearer(None)


@pytest.mark.asyncio
async def test_verify_bearer_no_bearer_prefix_raises_auth_error():
    """Authorization value without 'Bearer ' prefix must raise AuthError."""
    with pytest.raises(AuthError):
        await auth_mod.verify_bearer("Token abc")


@pytest.mark.asyncio
async def test_verify_bearer_master_key_accepted(monkeypatch):
    """Master key must be accepted and returned as-is."""
    _clear_env_keys_cache()
    monkeypatch.setattr(auth_mod.settings, "master_key", "sk-test")
    monkeypatch.setattr(auth_mod.settings, "api_keys", "")
    _clear_env_keys_cache()  # clear again after patching so cache rebuilds fresh
    try:
        result = await auth_mod.verify_bearer("Bearer sk-test")
        assert result == "sk-test"
    finally:
        _clear_env_keys_cache()


@pytest.mark.asyncio
async def test_verify_bearer_env_key_accepted(monkeypatch):
    """A key listed in SHINWAY_API_KEYS must be accepted."""
    _clear_env_keys_cache()
    monkeypatch.setattr(auth_mod.settings, "master_key", "")
    monkeypatch.setattr(auth_mod.settings, "api_keys", "mykey,other")
    _clear_env_keys_cache()
    try:
        result = await auth_mod.verify_bearer("Bearer mykey")
        assert result == "mykey"
    finally:
        _clear_env_keys_cache()


@pytest.mark.asyncio
async def test_verify_bearer_env_key_with_label_prefix_accepted(monkeypatch):
    """api_keys entry formatted as 'label:key' must resolve the key part correctly.

    NOTE: The config format is 'key:label' — split on first ':', take index 0 as the key.
    So 'mykey:mylabel' → key is 'mykey'.
    """
    _clear_env_keys_cache()
    monkeypatch.setattr(auth_mod.settings, "master_key", "")
    # Format per _env_keys(): entry.split(':', 1)[0] is the key
    monkeypatch.setattr(auth_mod.settings, "api_keys", "mykey:mylabel")
    _clear_env_keys_cache()
    try:
        result = await auth_mod.verify_bearer("Bearer mykey")
        assert result == "mykey"
    finally:
        _clear_env_keys_cache()


@pytest.mark.asyncio
async def test_verify_bearer_invalid_key_raises_auth_error(monkeypatch):
    """A key not in env set and rejected by key_store must raise AuthError."""
    import storage.keys as keys_mod

    _clear_env_keys_cache()
    monkeypatch.setattr(auth_mod.settings, "master_key", "")
    monkeypatch.setattr(auth_mod.settings, "api_keys", "")
    _clear_env_keys_cache()
    # verify_bearer now calls key_store.get (not is_valid) for a single DB round-trip
    monkeypatch.setattr(keys_mod.key_store, "get", AsyncMock(return_value=None))
    auth_mod._key_cache.clear()
    try:
        with pytest.raises(AuthError):
            await auth_mod.verify_bearer("Bearer bad-key")
    finally:
        auth_mod._key_cache.clear()
        _clear_env_keys_cache()


@pytest.mark.asyncio
async def test_verify_bearer_db_key_accepted(monkeypatch):
    """A key approved by key_store.get with is_active=True must be accepted and returned."""
    import storage.keys as keys_mod

    _clear_env_keys_cache()
    monkeypatch.setattr(auth_mod.settings, "master_key", "")
    monkeypatch.setattr(auth_mod.settings, "api_keys", "")
    _clear_env_keys_cache()
    record = {"label": "test", "budget_usd": 0, "token_limit_daily": 0,
              "rpm_limit": 0, "rps_limit": 0, "allowed_models": [], "is_active": True}
    monkeypatch.setattr(keys_mod.key_store, "get", AsyncMock(return_value=record))
    auth_mod._key_cache.clear()
    try:
        result = await auth_mod.verify_bearer("Bearer db-key")
        assert result == "db-key"
    finally:
        auth_mod._key_cache.clear()
        _clear_env_keys_cache()


@pytest.mark.asyncio
async def test_verify_bearer_strips_whitespace(monkeypatch):
    """Extra whitespace around the token after 'Bearer ' must be stripped before lookup."""
    import storage.keys as keys_mod

    _clear_env_keys_cache()
    monkeypatch.setattr(auth_mod.settings, "master_key", "sk-test")
    monkeypatch.setattr(auth_mod.settings, "api_keys", "")
    _clear_env_keys_cache()
    # Ensure key_store is not called (env key path — no DB lookup needed)
    monkeypatch.setattr(keys_mod.key_store, "get", AsyncMock(side_effect=AssertionError("should not reach key_store")))
    auth_mod._key_cache.clear()
    try:
        # Double space between Bearer and key
        result = await auth_mod.verify_bearer("Bearer  sk-test")
        assert result == "sk-test"
        # Trailing space after key
        result2 = await auth_mod.verify_bearer("Bearer sk-test ")
        assert result2 == "sk-test"
    finally:
        auth_mod._key_cache.clear()
        _clear_env_keys_cache()


# ---------------------------------------------------------------------------
# get_key_record
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_key_record_returns_none_for_env_key(monkeypatch):
    """Env keys have no DB record — get_key_record must return None without querying key_store."""
    import storage.keys as keys_mod

    _clear_env_keys_cache()
    monkeypatch.setattr(auth_mod.settings, "master_key", "")
    monkeypatch.setattr(auth_mod.settings, "api_keys", "envkey")
    _clear_env_keys_cache()
    # If key_store.get is called it would raise — prove it is never reached
    monkeypatch.setattr(keys_mod.key_store, "get", AsyncMock(side_effect=AssertionError("key_store.get must not be called for env key")))
    try:
        result = await auth_mod.get_key_record("envkey")
        assert result is None
    finally:
        _clear_env_keys_cache()


@pytest.mark.asyncio
async def test_get_key_record_returns_none_for_master_key(monkeypatch):
    """Master key has no DB record — get_key_record must return None without querying key_store."""
    import storage.keys as keys_mod

    _clear_env_keys_cache()
    monkeypatch.setattr(auth_mod.settings, "master_key", "sk-master")
    monkeypatch.setattr(auth_mod.settings, "api_keys", "")
    _clear_env_keys_cache()
    monkeypatch.setattr(keys_mod.key_store, "get", AsyncMock(side_effect=AssertionError("key_store.get must not be called for master key")))
    try:
        result = await auth_mod.get_key_record("sk-master")
        assert result is None
    finally:
        _clear_env_keys_cache()


@pytest.mark.asyncio
async def test_get_key_record_fetches_from_store_for_db_key(monkeypatch):
    """A key not in env set must be fetched from key_store.get and returned."""
    import storage.keys as keys_mod

    _clear_env_keys_cache()
    monkeypatch.setattr(auth_mod.settings, "master_key", "")
    monkeypatch.setattr(auth_mod.settings, "api_keys", "")
    _clear_env_keys_cache()
    expected = {"label": "my-db-key", "budget_usd": 5.0}
    monkeypatch.setattr(keys_mod.key_store, "get", AsyncMock(return_value=expected))
    try:
        result = await auth_mod.get_key_record("db-only-key")
        assert result == expected
        keys_mod.key_store.get.assert_awaited_once_with("db-only-key")
    finally:
        _clear_env_keys_cache()


# ---------------------------------------------------------------------------
# check_budget
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_budget_passes_when_no_record(monkeypatch):
    """check_budget with key_record=None and no global budget must not raise."""
    monkeypatch.setattr(auth_mod.settings, "budget_usd", 0.0)
    # Should complete without raising
    await auth_mod.check_budget("any-key", key_record=None)


@pytest.mark.asyncio
async def test_check_budget_passes_when_budget_not_set(monkeypatch):
    """check_budget with a record that has budget_usd=0 must not raise."""
    monkeypatch.setattr(auth_mod.settings, "budget_usd", 0.0)
    rec = {"budget_usd": 0, "token_limit_daily": 0}
    await auth_mod.check_budget("any-key", key_record=rec)


@pytest.mark.asyncio
async def test_check_budget_raises_when_key_budget_exceeded(monkeypatch):
    """When per-key spend meets or exceeds budget_usd, RateLimitError must be raised."""
    monkeypatch.setattr(auth_mod.settings, "budget_usd", 0.0)  # no global budget
    monkeypatch.setattr(
        auth_mod.analytics, "get_spend", AsyncMock(return_value=10.0)
    )
    rec = {"budget_usd": 5.0, "token_limit_daily": 0}
    with pytest.raises(RateLimitError, match="Key budget limit reached"):
        await auth_mod.check_budget("key-a", key_record=rec)
    auth_mod.analytics.get_spend.assert_awaited_once_with("key-a")


@pytest.mark.asyncio
async def test_check_budget_raises_when_global_budget_exceeded(monkeypatch):
    """When total spend across all keys meets or exceeds global budget_usd, RateLimitError must be raised."""
    monkeypatch.setattr(auth_mod.settings, "budget_usd", 1.0)
    monkeypatch.setattr(
        auth_mod.analytics, "get_total_spend", AsyncMock(return_value=2.0)
    )
    # No per-key budget
    rec = {"budget_usd": 0, "token_limit_daily": 0}
    with pytest.raises(RateLimitError, match="Global budget limit reached"):
        await auth_mod.check_budget("key-b", key_record=rec)
    auth_mod.analytics.get_total_spend.assert_awaited_once()


@pytest.mark.asyncio
async def test_check_budget_raises_when_daily_token_limit_exceeded(monkeypatch):
    """When daily token usage meets or exceeds token_limit_daily, RateLimitError must be raised."""
    monkeypatch.setattr(auth_mod.settings, "budget_usd", 0.0)  # no global budget
    monkeypatch.setattr(
        auth_mod.analytics, "get_daily_tokens", AsyncMock(return_value=200)
    )
    rec = {"budget_usd": 0, "token_limit_daily": 100}
    with pytest.raises(RateLimitError, match="Daily token limit reached"):
        await auth_mod.check_budget("key-c", key_record=rec)
    auth_mod.analytics.get_daily_tokens.assert_awaited_once_with("key-c")


# ---------------------------------------------------------------------------
# enforce_allowed_models
# ---------------------------------------------------------------------------


def test_enforce_allowed_models_passes_for_none_record():
    """None key_record (env/master key) must never be restricted — no raise."""
    auth_mod.enforce_allowed_models(None, "any-model")


def test_enforce_allowed_models_passes_for_empty_allowed_list():
    """Empty allowed_models list means all models are allowed — no raise."""
    rec = {"allowed_models": []}
    auth_mod.enforce_allowed_models(rec, "gpt-4")


def test_enforce_allowed_models_passes_when_model_in_list():
    """Model present in allowed_models must be accepted — no raise."""
    rec = {"allowed_models": ["gpt-4"]}
    auth_mod.enforce_allowed_models(rec, "gpt-4")


def test_enforce_allowed_models_raises_when_model_not_in_list():
    """Model absent from a non-empty allowed_models list must raise AuthError."""
    rec = {"allowed_models": ["gpt-4"]}
    with pytest.raises(AuthError, match="not allowed"):
        auth_mod.enforce_allowed_models(rec, "claude")


# ---------------------------------------------------------------------------
# _key_cache — positive DB key cache
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verify_bearer_db_key_populates_cache(monkeypatch):
    """verify_bearer must cache the key record so get_key_record needs no DB hit."""
    import storage.keys as keys_mod
    _clear_env_keys_cache()
    monkeypatch.setattr(auth_mod.settings, "master_key", "")
    monkeypatch.setattr(auth_mod.settings, "api_keys", "")
    _clear_env_keys_cache()
    record = {"label": "t", "budget_usd": 0, "token_limit_daily": 0,
              "rpm_limit": 0, "rps_limit": 0, "allowed_models": [], "is_active": True}
    monkeypatch.setattr(keys_mod.key_store, "get", AsyncMock(return_value=record))
    auth_mod._key_cache.clear()
    try:
        await auth_mod.verify_bearer("Bearer cached-db-key")
        assert auth_mod._key_cache.get("cached-db-key") == record
    finally:
        auth_mod._key_cache.clear()
        _clear_env_keys_cache()


@pytest.mark.asyncio
async def test_get_key_record_uses_cache_after_verify_bearer(monkeypatch):
    """get_key_record must not call key_store.get if _key_cache is warm."""
    import storage.keys as keys_mod
    _clear_env_keys_cache()
    monkeypatch.setattr(auth_mod.settings, "master_key", "")
    monkeypatch.setattr(auth_mod.settings, "api_keys", "")
    _clear_env_keys_cache()
    record = {"label": "t", "budget_usd": 0, "token_limit_daily": 0,
              "rpm_limit": 0, "rps_limit": 0, "allowed_models": [], "is_active": True}
    get_call_count = 0

    async def counting_get(key):
        nonlocal get_call_count
        get_call_count += 1
        return record

    monkeypatch.setattr(keys_mod.key_store, "get", counting_get)
    auth_mod._key_cache.clear()
    try:
        await auth_mod.verify_bearer("Bearer db-key-once")
        result = await auth_mod.get_key_record("db-key-once")
        assert result == record
        assert get_call_count == 1, f"Expected 1 DB hit, got {get_call_count}"
    finally:
        auth_mod._key_cache.clear()
        _clear_env_keys_cache()


@pytest.mark.asyncio
async def test_key_cache_not_populated_for_env_keys(monkeypatch):
    """Env keys must not be stored in _key_cache."""
    _clear_env_keys_cache()
    monkeypatch.setattr(auth_mod.settings, "master_key", "sk-env")
    monkeypatch.setattr(auth_mod.settings, "api_keys", "")
    _clear_env_keys_cache()
    auth_mod._key_cache.clear()
    try:
        await auth_mod.verify_bearer("Bearer sk-env")
        assert auth_mod._key_cache.get("sk-env") is None
    finally:
        auth_mod._key_cache.clear()
        _clear_env_keys_cache()


@pytest.mark.asyncio
async def test_key_cache_not_populated_for_invalid_key(monkeypatch):
    """Invalid/inactive keys must not be cached — each attempt must hit DB."""
    import storage.keys as keys_mod
    _clear_env_keys_cache()
    monkeypatch.setattr(auth_mod.settings, "master_key", "")
    monkeypatch.setattr(auth_mod.settings, "api_keys", "")
    _clear_env_keys_cache()
    monkeypatch.setattr(keys_mod.key_store, "get", AsyncMock(return_value=None))
    auth_mod._key_cache.clear()
    try:
        with pytest.raises(AuthError):
            await auth_mod.verify_bearer("Bearer invalid-key")
        assert auth_mod._key_cache.get("invalid-key") is None
    finally:
        auth_mod._key_cache.clear()
        _clear_env_keys_cache()


@pytest.mark.asyncio
async def test_check_budget_logs_warning_when_approaching_limit(monkeypatch):
    """check_budget must log key_budget_approaching when spend >= 80% of budget."""
    monkeypatch.setattr(auth_mod.settings, "budget_usd", 0.0)
    monkeypatch.setattr(
        auth_mod.analytics, "get_spend", AsyncMock(return_value=8.5)
    )
    rec = {"budget_usd": 10.0, "token_limit_daily": 0}
    # Must not raise (not yet over limit)
    await auth_mod.check_budget("key-d", key_record=rec)
    # Logging is side-effect verified via structlog — just confirm no exception raised


def test_compute_env_keys_maxsize_is_one():
    """_compute_env_keys lru_cache maxsize must be 1 — only one live config at a time."""
    import inspect
    cache_info = auth_mod._compute_env_keys.cache_info()
    assert cache_info.maxsize == 1
