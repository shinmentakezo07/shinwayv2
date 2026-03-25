"""
Tests for analytics.AnalyticsStore and analytics.estimate_cost.

Each test uses a fresh AnalyticsStore() instance — never the module singleton.
All async methods are tested with pytest-asyncio.
"""

import pytest

from analytics import AnalyticsStore, RequestLog, estimate_cost


def _make_log(
    api_key: str = "sk-test",
    provider: str = "anthropic",
    input_tokens: int = 100,
    output_tokens: int = 50,
    cost_usd: float = 0.002,
    latency_ms: float = 200.0,
    fallback: bool = False,
    cache_hit: bool = False,
    ttft_ms: int | None = None,
    output_tps: float | None = None,
) -> RequestLog:
    return RequestLog(
        api_key=api_key,
        provider=provider,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost_usd,
        latency_ms=latency_ms,
        fallback=fallback,
        cache_hit=cache_hit,
        ttft_ms=ttft_ms,
        output_tps=output_tps,
    )


@pytest.mark.asyncio
async def test_record_increments_request_count():
    store = AnalyticsStore()
    await store.record(_make_log(api_key="sk-a"))
    assert store._by_key["sk-a"]["requests"] == 1


@pytest.mark.asyncio
async def test_record_tracks_cache_hits():
    store = AnalyticsStore()
    await store.record(_make_log(api_key="sk-a", cache_hit=False))
    await store.record(_make_log(api_key="sk-a", cache_hit=True))
    assert store._by_key["sk-a"]["cache_hits"] == 1


@pytest.mark.asyncio
async def test_record_tracks_fallbacks():
    store = AnalyticsStore()
    await store.record(_make_log(api_key="sk-a", fallback=True))
    assert store._by_key["sk-a"]["fallbacks"] == 1


@pytest.mark.asyncio
async def test_record_accumulates_tokens_and_cost():
    store = AnalyticsStore()
    await store.record(_make_log(api_key="sk-a", input_tokens=100, output_tokens=50, cost_usd=0.002))
    await store.record(_make_log(api_key="sk-a", input_tokens=200, output_tokens=80, cost_usd=0.004))
    rec = store._by_key["sk-a"]
    assert rec["estimated_input_tokens"] == 300
    assert rec["estimated_output_tokens"] == 130
    assert abs(rec["estimated_cost_usd"] - 0.006) < 1e-9


@pytest.mark.asyncio
async def test_record_tracks_provider_breakdown():
    store = AnalyticsStore()
    await store.record(_make_log(api_key="sk-a", provider="anthropic"))
    await store.record(_make_log(api_key="sk-a", provider="openai"))
    providers = store._by_key["sk-a"]["providers"]
    assert providers.get("anthropic") == 1
    assert providers.get("openai") == 1


@pytest.mark.asyncio
async def test_record_adds_to_rolling_log():
    store = AnalyticsStore()
    await store.record(_make_log(api_key="first"))
    await store.record(_make_log(api_key="second"))
    await store.record(_make_log(api_key="third"))
    entries = await store.snapshot_log(limit=10)
    assert len(entries) == 3
    # newest first (appendleft)
    assert entries[0]["api_key"] == "third"
    assert entries[1]["api_key"] == "second"
    assert entries[2]["api_key"] == "first"


@pytest.mark.asyncio
async def test_rolling_log_max_200():
    store = AnalyticsStore()
    for i in range(201):
        await store.record(_make_log(api_key=f"sk-{i}"))
    entries = await store.snapshot_log(limit=201)
    assert len(entries) == 200


@pytest.mark.asyncio
async def test_snapshot_returns_all_keys():
    store = AnalyticsStore()
    await store.record(_make_log(api_key="sk-alpha"))
    await store.record(_make_log(api_key="sk-beta"))
    snap = await store.snapshot()
    assert "sk-alpha" in snap["keys"]
    assert "sk-beta" in snap["keys"]


@pytest.mark.asyncio
async def test_get_spend_returns_zero_for_unknown_key():
    store = AnalyticsStore()
    result = await store.get_spend("nonexistent")
    assert result == 0.0


@pytest.mark.asyncio
async def test_get_spend_returns_accumulated_cost():
    store = AnalyticsStore()
    await store.record(_make_log(api_key="sk-a", cost_usd=0.003))
    await store.record(_make_log(api_key="sk-a", cost_usd=0.007))
    result = await store.get_spend("sk-a")
    assert abs(result - 0.010) < 1e-9


@pytest.mark.asyncio
async def test_get_total_spend_sums_all_keys():
    store = AnalyticsStore()
    await store.record(_make_log(api_key="sk-a", cost_usd=0.005))
    await store.record(_make_log(api_key="sk-b", cost_usd=0.003))
    total = await store.get_total_spend()
    assert abs(total - 0.008) < 1e-9


@pytest.mark.asyncio
async def test_get_daily_tokens_sums_input_and_output():
    store = AnalyticsStore()
    await store.record(_make_log(api_key="sk-a", input_tokens=10, output_tokens=5))
    result = await store.get_daily_tokens("sk-a")
    assert result == 15


@pytest.mark.asyncio
async def test_anonymous_key_normalised():
    store = AnalyticsStore()
    await store.record(_make_log(api_key=""))
    assert "anonymous" in store._by_key
    assert "" not in store._by_key


@pytest.mark.asyncio
async def test_snapshot_log_limit():
    store = AnalyticsStore()
    for i in range(10):
        await store.record(_make_log(api_key=f"sk-{i}"))
    entries = await store.snapshot_log(limit=3)
    assert len(entries) == 3


def test_estimate_cost_anthropic():
    result = estimate_cost("anthropic", 1000, 1000)
    assert isinstance(result, float)
    assert result > 0.0


def test_estimate_cost_openai():
    result = estimate_cost("openai", 1000, 1000)
    assert isinstance(result, float)
    assert result > 0.0


def test_estimate_cost_unknown_provider_falls_back_to_anthropic():
    unknown = estimate_cost("unknown", 1000, 0)
    anthropic = estimate_cost("anthropic", 1000, 0)
    assert unknown == anthropic
""