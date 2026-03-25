import pytest
from fastapi.testclient import TestClient


def test_body_size_limit_returns_413(monkeypatch):
    """Requests with Content-Length exceeding the limit must return 413."""
    import config as cfg
    # Patch settings before app creation so the middleware reads the patched value
    original = cfg.settings.max_request_body_bytes
    cfg.settings.max_request_body_bytes = 50
    try:
        from app import create_app
        client = TestClient(create_app(), raise_server_exceptions=False)
        big = '{"messages": [{"role": "user", "content": "' + 'x' * 200 + '"}]}'
        r = client.post(
            '/v1/chat/completions',
            headers={'Authorization': 'Bearer test-key', 'Content-Type': 'application/json'},
            content=big.encode(),
        )
        assert r.status_code == 413
        assert 'error' in r.json()
    finally:
        cfg.settings.max_request_body_bytes = original


def _make_authed_client():
    """Create a TestClient with auth cache cleared and master_key forced to a known value."""
    import config
    import middleware.auth as _auth
    import storage.keys as _keys
    from app import create_app

    _test_key = "sk-local-dev"
    config.settings.master_key = _test_key
    config.settings.debug = True  # suppress sk-local-dev guard
    _auth._env_keys.cache_clear()
    # Patch key_store.get so it doesn't require DB initialisation
    _keys.key_store.get = lambda key: _async_none()
    _keys.key_store.is_valid = lambda key: _async_false()
    client = TestClient(create_app(), raise_server_exceptions=False)
    _auth._env_keys.cache_clear()
    return client, _test_key


async def _async_none():
    return None


async def _async_false():
    return False


def test_malformed_json_returns_400(monkeypatch):
    """Malformed JSON body must return 400 with our error envelope, not 422."""
    client, key = _make_authed_client()
    r = client.post(
        '/v1/chat/completions',
        headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'},
        content=b'{not valid json',
    )
    assert r.status_code == 400
    body = r.json()
    assert 'error' in body
    assert body['error']['type'] == 'invalid_request_error'


def test_non_json_content_type_returns_400(monkeypatch):
    """Non-JSON content type must return 400 with our error envelope."""
    client, key = _make_authed_client()
    r = client.post(
        '/v1/chat/completions',
        headers={'Authorization': f'Bearer {key}', 'Content-Type': 'text/plain'},
        content=b'hello world',
    )
    assert r.status_code == 400
    body = r.json()
    assert 'error' in body


@pytest.mark.asyncio
async def test_check_budget_global_uses_total_spend(monkeypatch):
    """Global budget must check total spend across all keys, not per-key spend."""
    from analytics import AnalyticsStore
    from handlers import RateLimitError
    import middleware.auth as auth_mod

    store = AnalyticsStore()
    def _rec(cost):
        return {"estimated_cost_usd": cost, "estimated_input_tokens": 0,
                "estimated_output_tokens": 0, "requests": 1, "cache_hits": 0,
                "fallbacks": 0, "latency_ms_total": 0.0, "last_request_ts": 0, "providers": {}}
    store._by_key["key_a"] = _rec(0.60)
    store._by_key["key_b"] = _rec(0.60)
    monkeypatch.setattr(auth_mod, "analytics", store)
    monkeypatch.setattr(auth_mod.settings, "budget_usd", 1.0)

    with pytest.raises(RateLimitError, match="Global budget limit reached"):
        await auth_mod.check_budget("key_a", key_record=None)


@pytest.mark.asyncio
async def test_verify_bearer_strips_whitespace(monkeypatch):
    """Bearer token with extra whitespace must still authenticate."""
    import middleware.auth as auth_mod
    auth_mod._env_keys.cache_clear()
    monkeypatch.setattr(auth_mod, "_env_keys", lambda: frozenset({"sk-test"}))
    result = await auth_mod.verify_bearer("Bearer  sk-test")  # double space
    assert result == "sk-test"
    result2 = await auth_mod.verify_bearer("Bearer sk-test ")  # trailing space
    assert result2 == "sk-test"
    # monkeypatch restores _env_keys automatically; no manual cache_clear needed here


def test_env_keys_uses_first_colon_as_label_separator(monkeypatch):
    """API key entries with label must parse key correctly using first colon as separator."""
    import middleware.auth as auth_mod
    auth_mod._env_keys.cache_clear()
    monkeypatch.setattr(auth_mod.settings, "master_key", "")
    monkeypatch.setattr(auth_mod.settings, "api_keys", "sk-one:label,sk-two:scope:extra")
    keys = auth_mod._env_keys()
    auth_mod._env_keys.cache_clear()
    assert "sk-one" in keys
    assert "sk-two" in keys
    assert "scope" not in keys
    assert "extra" not in keys


@pytest.mark.asyncio
async def test_idempotency_keys_scoped_per_api_key():
    """Different API keys must not share idempotency cache entries."""
    from middleware.idempotency import get_or_lock, complete

    # Key A stores a response
    hit_a, _ = await get_or_lock("idem-req-1", api_key="key_alpha")
    assert not hit_a
    await complete("idem-req-1", {"result": "from_key_alpha"}, api_key="key_alpha")

    # Key B with same idempotency key must NOT get Key A's response
    hit_b, resp_b = await get_or_lock("idem-req-1", api_key="key_beta")
    assert not hit_b, "Different API key must not receive another key's cached response"
    assert resp_b is None

    # Key A with same key SHOULD get the cached response
    hit_a2, resp_a2 = await get_or_lock("idem-req-1", api_key="key_alpha")
    assert hit_a2, "Same API key must receive its own cached response"
    assert resp_a2 == {"result": "from_key_alpha"}
