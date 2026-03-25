import pytest
from unittest.mock import MagicMock

from cache import IdempotencyCache
from middleware.idempotency import (
    _cache_key,
    _is_sentinel,
    _SENTINEL,
    complete,
    get_or_lock,
    release,
    validate_idem_key,
)


def _make_settings():
    s = MagicMock()
    s.cache_enabled = True
    s.idem_ttl_seconds = 60
    s.idem_max_entries = 100
    s.cache_l2_enabled = False
    return s


# ── _cache_key ────────────────────────────────────────────────────────────────

def test_cache_key_format():
    assert _cache_key('mykey', 'user1') == 'idem:user1:mykey'


def test_cache_key_empty_api_key():
    assert _cache_key('mykey') == 'idem::mykey'


# ── validate_idem_key ─────────────────────────────────────────────────────────

def test_validate_idem_key_accepts_uuid_format():
    validate_idem_key('550e8400-e29b-41d4-a716-446655440000')  # must not raise


def test_validate_idem_key_accepts_alphanumeric_with_underscores():
    validate_idem_key('req_abc123XYZ')  # must not raise


def test_validate_idem_key_rejects_empty():
    with pytest.raises(ValueError, match='empty'):
        validate_idem_key('')


def test_validate_idem_key_rejects_too_long():
    with pytest.raises(ValueError, match='256'):
        validate_idem_key('x' * 257)


def test_validate_idem_key_rejects_spaces():
    with pytest.raises(ValueError, match='characters'):
        validate_idem_key('key with spaces')


def test_validate_idem_key_rejects_colon():
    with pytest.raises(ValueError, match='characters'):
        validate_idem_key('key:with:colons')


def test_validate_idem_key_rejects_at_sign():
    with pytest.raises(ValueError, match='characters'):
        validate_idem_key('key@domain')


def test_validate_idem_key_accepts_max_length():
    validate_idem_key('a' * 256)  # exactly 256 — must not raise


# ── _is_sentinel ──────────────────────────────────────────────────────────────

def test_is_sentinel_true_for_sentinel():
    assert _is_sentinel(_SENTINEL) is True


def test_is_sentinel_false_for_real_response():
    assert _is_sentinel({'id': 'chatcmpl-abc', 'choices': []}) is False


def test_is_sentinel_false_for_none():
    assert _is_sentinel(None) is False


# ── get_or_lock / complete / release ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_or_lock_returns_false_none_for_new_key(monkeypatch):
    monkeypatch.setattr('cache.settings', _make_settings())
    ic = IdempotencyCache()
    import cache as cache_mod
    monkeypatch.setattr(cache_mod, 'idempotency_cache', ic)
    found, result = await get_or_lock('newkey', 'user1')
    assert found is False
    assert result is None


@pytest.mark.asyncio
async def test_get_or_lock_writes_sentinel_on_first_call(monkeypatch):
    monkeypatch.setattr('cache.settings', _make_settings())
    ic = IdempotencyCache()
    import cache as cache_mod
    monkeypatch.setattr(cache_mod, 'idempotency_cache', ic)
    await get_or_lock('sentkey', 'user1')
    # Second call must see sentinel
    found, result = await get_or_lock('sentkey', 'user1')
    assert found is True
    assert result is None  # sentinel → in-progress signal


@pytest.mark.asyncio
async def test_complete_replaces_sentinel_with_response(monkeypatch):
    monkeypatch.setattr('cache.settings', _make_settings())
    ic = IdempotencyCache()
    import cache as cache_mod
    monkeypatch.setattr(cache_mod, 'idempotency_cache', ic)
    await get_or_lock('k1', 'user1')  # writes sentinel
    await complete('k1', {'data': 'ok'}, 'user1')
    found, result = await get_or_lock('k1', 'user1')
    assert found is True
    assert result == {'data': 'ok'}


@pytest.mark.asyncio
async def test_release_removes_sentinel_allowing_retry(monkeypatch):
    monkeypatch.setattr('cache.settings', _make_settings())
    ic = IdempotencyCache()
    import cache as cache_mod
    monkeypatch.setattr(cache_mod, 'idempotency_cache', ic)
    await get_or_lock('k2', 'user1')  # writes sentinel
    await release('k2', 'user1')  # removes sentinel
    found, result = await get_or_lock('k2', 'user1')  # fresh — should proceed
    assert found is False
    assert result is None


@pytest.mark.asyncio
async def test_different_api_keys_are_isolated(monkeypatch):
    monkeypatch.setattr('cache.settings', _make_settings())
    ic = IdempotencyCache()
    import cache as cache_mod
    monkeypatch.setattr(cache_mod, 'idempotency_cache', ic)
    await get_or_lock('k', 'key_a')  # key_a gets sentinel
    await complete('k', {'secret': True}, 'key_a')
    # key_b must not see key_a's response
    found, result = await get_or_lock('k', 'key_b')
    assert found is False
    assert result is None


@pytest.mark.asyncio
async def test_concurrent_duplicate_sees_in_progress(monkeypatch):
    """Second concurrent request with same key must see in-progress sentinel."""
    monkeypatch.setattr('cache.settings', _make_settings())
    ic = IdempotencyCache()
    import cache as cache_mod
    monkeypatch.setattr(cache_mod, 'idempotency_cache', ic)
    found1, _ = await get_or_lock('concurrent_key', 'user1')  # first — proceeds
    assert found1 is False
    found2, result2 = await get_or_lock('concurrent_key', 'user1')  # second — blocked
    assert found2 is True
    assert result2 is None  # sentinel → caller returns 409
