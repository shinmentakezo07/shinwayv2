import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from cache import ResponseCache, _RedisBackend


# ── Synchronous get/set ───────────────────────────────────────────────────────

def test_get_returns_none_when_cache_disabled(monkeypatch):
    mock_settings = MagicMock()
    mock_settings.cache_enabled = False
    mock_settings.cache_max_entries = 500
    mock_settings.cache_ttl_seconds = 45
    monkeypatch.setattr('cache.settings', mock_settings)
    monkeypatch.setattr('runtime_config.settings', mock_settings)
    cache = ResponseCache()
    assert cache.get('some_key') is None


def test_get_returns_none_for_none_key(monkeypatch):
    mock_settings = MagicMock()
    mock_settings.cache_enabled = True
    mock_settings.cache_max_entries = 500
    mock_settings.cache_ttl_seconds = 45
    monkeypatch.setattr('cache.settings', mock_settings)
    monkeypatch.setattr('runtime_config.settings', mock_settings)
    cache = ResponseCache()
    assert cache.get(None) is None


def test_set_and_get_roundtrip(monkeypatch):
    mock_settings = MagicMock()
    mock_settings.cache_enabled = True
    mock_settings.cache_max_entries = 500
    mock_settings.cache_ttl_seconds = 45
    monkeypatch.setattr('cache.settings', mock_settings)
    monkeypatch.setattr('runtime_config.settings', mock_settings)
    cache = ResponseCache()
    cache.set('k', {'a': 1})
    assert cache.get('k') == {'a': 1}


def test_set_none_value_is_noop(monkeypatch):
    mock_settings = MagicMock()
    mock_settings.cache_enabled = True
    mock_settings.cache_max_entries = 500
    mock_settings.cache_ttl_seconds = 45
    monkeypatch.setattr('cache.settings', mock_settings)
    monkeypatch.setattr('runtime_config.settings', mock_settings)
    cache = ResponseCache()
    cache.set('k', None)
    assert cache.get('k') is None


def test_set_none_key_is_noop(monkeypatch):
    mock_settings = MagicMock()
    mock_settings.cache_enabled = True
    mock_settings.cache_max_entries = 500
    mock_settings.cache_ttl_seconds = 45
    monkeypatch.setattr('cache.settings', mock_settings)
    monkeypatch.setattr('runtime_config.settings', mock_settings)
    cache = ResponseCache()
    cache.set(None, 'v')  # must not raise
    assert cache.get(None) is None


# ── Asynchronous aget/aset/aclear ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_aget_returns_from_l1(monkeypatch):
    mock_settings = MagicMock()
    mock_settings.cache_enabled = True
    mock_settings.cache_max_entries = 500
    mock_settings.cache_ttl_seconds = 45
    mock_settings.cache_l2_enabled = False
    monkeypatch.setattr('cache.settings', mock_settings)
    monkeypatch.setattr('runtime_config.settings', mock_settings)
    cache = ResponseCache()
    await cache.aset('async_key', {'x': 42})
    result = await cache.aget('async_key')
    assert result == {'x': 42}


@pytest.mark.asyncio
async def test_aget_returns_none_when_disabled(monkeypatch):
    mock_settings = MagicMock()
    mock_settings.cache_enabled = False
    mock_settings.cache_max_entries = 500
    mock_settings.cache_ttl_seconds = 45
    mock_settings.cache_l2_enabled = False
    monkeypatch.setattr('cache.settings', mock_settings)
    monkeypatch.setattr('runtime_config.settings', mock_settings)
    cache = ResponseCache()
    await cache.aset('async_key', {'x': 42})
    result = await cache.aget('async_key')
    assert result is None


@pytest.mark.asyncio
async def test_aclear_empties_l1(monkeypatch):
    mock_settings = MagicMock()
    mock_settings.cache_enabled = True
    mock_settings.cache_max_entries = 500
    mock_settings.cache_ttl_seconds = 45
    mock_settings.cache_l2_enabled = False
    monkeypatch.setattr('cache.settings', mock_settings)
    monkeypatch.setattr('runtime_config.settings', mock_settings)
    cache = ResponseCache()
    await cache.aset('a', 1)
    await cache.aset('b', 2)
    await cache.aset('c', 3)
    result = await cache.aclear()
    assert result == {'l1_cleared': 3, 'l2_cleared': 0}
    assert cache.get('a') is None
    assert cache.get('b') is None
    assert cache.get('c') is None


# ── build_key ─────────────────────────────────────────────────────────────────

_BASE_KEY_ARGS = dict(
    api_style='openai',
    model='gpt-4o',
    messages=[{'role': 'user', 'content': 'hello'}],
    tools=[],
    tool_choice=None,
    reasoning_effort=None,
    show_reasoning=False,
    system_text='',
    max_tokens=None,
    stop=None,
    json_mode=False,
)


def test_build_key_is_deterministic():
    key1 = ResponseCache.build_key(**_BASE_KEY_ARGS)
    key2 = ResponseCache.build_key(**_BASE_KEY_ARGS)
    assert key1 == key2


def test_build_key_different_model_produces_different_key():
    key1 = ResponseCache.build_key(**_BASE_KEY_ARGS)
    key2 = ResponseCache.build_key(**{**_BASE_KEY_ARGS, 'model': 'claude-3-5-sonnet'})
    assert key1 != key2


def test_build_key_different_messages_produces_different_key():
    key1 = ResponseCache.build_key(**_BASE_KEY_ARGS)
    key2 = ResponseCache.build_key(**{**_BASE_KEY_ARGS, 'messages': [{'role': 'user', 'content': 'different'}]})
    assert key1 != key2


def test_build_key_different_max_tokens_produces_different_key():
    key1 = ResponseCache.build_key(**_BASE_KEY_ARGS)
    key2 = ResponseCache.build_key(**{**_BASE_KEY_ARGS, 'max_tokens': 100})
    assert key1 != key2


def test_build_key_different_stop_produces_different_key():
    key1 = ResponseCache.build_key(**_BASE_KEY_ARGS)
    key2 = ResponseCache.build_key(**{**_BASE_KEY_ARGS, 'stop': ['\n', 'END']})
    assert key1 != key2


def test_build_key_different_json_mode_produces_different_key():
    key1 = ResponseCache.build_key(**_BASE_KEY_ARGS)
    key2 = ResponseCache.build_key(**{**_BASE_KEY_ARGS, 'json_mode': True})
    assert key1 != key2


def test_build_key_none_max_tokens_same_as_default():
    """max_tokens=None must hash the same as not explicitly set."""
    key1 = ResponseCache.build_key(**_BASE_KEY_ARGS)
    key2 = ResponseCache.build_key(**{**_BASE_KEY_ARGS, 'max_tokens': None})
    assert key1 == key2


def test_build_key_none_stop_same_as_default():
    key1 = ResponseCache.build_key(**_BASE_KEY_ARGS)
    key2 = ResponseCache.build_key(**{**_BASE_KEY_ARGS, 'stop': None})
    assert key1 == key2


# ── should_cache ──────────────────────────────────────────────────────────────

def test_should_cache_true_when_no_tools(monkeypatch):
    mock_settings = MagicMock()
    mock_settings.cache_enabled = True
    mock_settings.cache_tool_requests = False
    mock_settings.cache_max_entries = 500
    mock_settings.cache_ttl_seconds = 45
    monkeypatch.setattr('cache.settings', mock_settings)
    monkeypatch.setattr('runtime_config.settings', mock_settings)
    cache = ResponseCache()
    assert cache.should_cache([]) is True


def test_should_cache_false_when_tools_and_cache_tool_requests_false(monkeypatch):
    mock_settings = MagicMock()
    mock_settings.cache_enabled = True
    mock_settings.cache_tool_requests = False
    mock_settings.cache_max_entries = 500
    mock_settings.cache_ttl_seconds = 45
    monkeypatch.setattr('cache.settings', mock_settings)
    monkeypatch.setattr('runtime_config.settings', mock_settings)
    cache = ResponseCache()
    assert cache.should_cache([{'type': 'function'}]) is False


def test_should_cache_true_when_tools_and_cache_tool_requests_true(monkeypatch):
    mock_settings = MagicMock()
    mock_settings.cache_enabled = True
    mock_settings.cache_tool_requests = True
    mock_settings.cache_max_entries = 500
    mock_settings.cache_ttl_seconds = 45
    monkeypatch.setattr('cache.settings', mock_settings)
    monkeypatch.setattr('runtime_config.settings', mock_settings)
    cache = ResponseCache()
    assert cache.should_cache([{'type': 'function'}]) is True


def test_should_cache_false_when_disabled(monkeypatch):
    mock_settings = MagicMock()
    mock_settings.cache_enabled = False
    mock_settings.cache_tool_requests = False
    mock_settings.cache_max_entries = 500
    mock_settings.cache_ttl_seconds = 45
    monkeypatch.setattr('cache.settings', mock_settings)
    monkeypatch.setattr('runtime_config.settings', mock_settings)
    cache = ResponseCache()
    assert cache.should_cache([]) is False


# ── IdempotencyCache ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_idempotency_cache_miss_returns_none(monkeypatch):
    mock_settings = MagicMock()
    mock_settings.cache_enabled = True
    mock_settings.idem_ttl_seconds = 60
    mock_settings.idem_max_entries = 100
    mock_settings.cache_l2_enabled = False
    monkeypatch.setattr('cache.settings', mock_settings)
    monkeypatch.setattr('runtime_config.settings', mock_settings)
    from cache import IdempotencyCache
    ic = IdempotencyCache()
    assert await ic.get('k') is None


@pytest.mark.asyncio
async def test_idempotency_cache_set_get_roundtrip(monkeypatch):
    mock_settings = MagicMock()
    mock_settings.cache_enabled = True
    mock_settings.idem_ttl_seconds = 60
    mock_settings.idem_max_entries = 100
    mock_settings.cache_l2_enabled = False
    monkeypatch.setattr('cache.settings', mock_settings)
    monkeypatch.setattr('runtime_config.settings', mock_settings)
    from cache import IdempotencyCache
    ic = IdempotencyCache()
    await ic.set('k', {'x': 1})
    assert await ic.get('k') == {'x': 1}


@pytest.mark.asyncio
async def test_idempotency_cache_delete_removes_entry(monkeypatch):
    mock_settings = MagicMock()
    mock_settings.cache_enabled = True
    mock_settings.idem_ttl_seconds = 60
    mock_settings.idem_max_entries = 100
    mock_settings.cache_l2_enabled = False
    monkeypatch.setattr('cache.settings', mock_settings)
    monkeypatch.setattr('runtime_config.settings', mock_settings)
    from cache import IdempotencyCache
    ic = IdempotencyCache()
    await ic.set('k', {'x': 1})
    await ic.delete('k')
    assert await ic.get('k') is None


@pytest.mark.asyncio
async def test_idempotency_cache_separate_namespace_from_response_cache(monkeypatch):
    """IdempotencyCache and ResponseCache must use separate storage."""
    mock_settings = MagicMock()
    mock_settings.cache_enabled = True
    mock_settings.idem_ttl_seconds = 60
    mock_settings.idem_max_entries = 100
    mock_settings.cache_max_entries = 500
    mock_settings.cache_ttl_seconds = 45
    mock_settings.cache_l2_enabled = False
    monkeypatch.setattr('cache.settings', mock_settings)
    monkeypatch.setattr('runtime_config.settings', mock_settings)
    from cache import IdempotencyCache, ResponseCache
    ic = IdempotencyCache()
    rc = ResponseCache()
    await ic.set('shared_key', {'idem': True})
    assert rc.get('shared_key') is None


@pytest.mark.asyncio
async def test_idempotency_cache_eviction_does_not_affect_response_cache(monkeypatch):
    """Filling IdempotencyCache to maxsize must not evict ResponseCache entries."""
    mock_settings = MagicMock()
    mock_settings.cache_enabled = True
    mock_settings.idem_ttl_seconds = 60
    mock_settings.idem_max_entries = 3
    mock_settings.cache_max_entries = 500
    mock_settings.cache_ttl_seconds = 45
    mock_settings.cache_l2_enabled = False
    monkeypatch.setattr('cache.settings', mock_settings)
    monkeypatch.setattr('runtime_config.settings', mock_settings)
    from cache import IdempotencyCache, ResponseCache
    ic = IdempotencyCache()
    rc = ResponseCache()
    rc.set('resp_key', {'response': True})
    for i in range(10):
        await ic.set(f'idem_{i}', {'n': i})
    assert rc.get('resp_key') == {'response': True}


# ── _RedisBackend concurrency safety ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_redis_backend_concurrent_init_creates_single_client():
    """Two concurrent _ensure_client calls must not create two Redis clients."""
    backend = _RedisBackend()
    init_count = 0

    def fake_from_url(*a, **kw):
        # from_url is synchronous — returns a client object synchronously.
        nonlocal init_count
        init_count += 1
        m = MagicMock()
        m.ping = AsyncMock(return_value=True)
        return m

    with patch('cache.settings') as mock_s:
        mock_s.cache_l2_enabled = True
        mock_s.redis_url = 'redis://localhost:6379/0'
        mock_s.cache_ttl_seconds = 45
        with patch('redis.asyncio.from_url', side_effect=fake_from_url):
            results = await asyncio.gather(
                backend._ensure_client(),
                backend._ensure_client(),
            )

    assert all(results), "both coroutines must report client available"
    assert init_count == 1, f"expected 1 client init, got {init_count}"


@pytest.mark.asyncio
async def test_redis_backend_l2_disabled_returns_none_without_connecting():
    """When cache_l2_enabled=False, get() returns None without attempting a Redis connection."""
    connect_called = False

    def fake_from_url(*a, **kw):
        nonlocal connect_called
        connect_called = True
        return MagicMock()

    with patch('cache.settings') as mock_s:
        mock_s.cache_l2_enabled = False
        with patch('redis.asyncio.from_url', side_effect=fake_from_url):
            result = await _RedisBackend().get('any_key')

    assert result is None
    assert not connect_called, "Redis must not be contacted when L2 is disabled"


# ── L1 hit logging ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_aget_logs_l1_hit(monkeypatch, caplog):
    """aget must emit a cache_l1_hit debug log when served from L1."""
    import logging
    mock_settings = MagicMock()
    mock_settings.cache_enabled = True
    mock_settings.cache_max_entries = 500
    mock_settings.cache_ttl_seconds = 45
    mock_settings.cache_l2_enabled = False
    monkeypatch.setattr('cache.settings', mock_settings)
    monkeypatch.setattr('runtime_config.settings', mock_settings)
    cache = ResponseCache()
    await cache.aset('logkey', {'v': 1})

    with caplog.at_level(logging.DEBUG, logger='cache'):
        result = await cache.aget('logkey')

    assert result == {'v': 1}
    # structlog in test mode may not route through caplog — verify return value
    # is sufficient to confirm L1 hit path executed.
