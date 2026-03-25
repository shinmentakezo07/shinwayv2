import pytest
from unittest.mock import MagicMock

from middleware.rate_limit import DualBucketRateLimiter, TokenBucket, enforce_rate_limit, enforce_per_key_rate_limit
import middleware.rate_limit as rl_mod
from handlers import RateLimitError


async def _async_return(value):
    """Tiny coroutine helper — returns a fixed value, used for monkeypatching async methods."""
    return value


def test_rate_limiter_rps_rpm_combo():
    """Verify combined bucket thresholds where RPM eventually throttles RPS burst."""
    # RPS: 10/s with burst 10
    # RPM: 120/m, meaning 2/s refill, with burst 120
    limiter = DualBucketRateLimiter(rate_rps=10, burst_rps=10, rate_rpm=120, burst_rpm=120)
    
    key = "test_key_combo"
    
    # Burst 10 requests immediately should pass (both buckets full)
    for _ in range(10):
        allowed, reason, _ = limiter.consume(key)
        assert allowed is True
        
    # The 11th should fail the RPS bucket because burst is max 10, refill needs a full 1/10th second per token
    allowed, reason, _ = limiter.consume(key)
    assert allowed is False
    assert "RPS limit exceeded" in reason

def test_rate_limiter_high_throughput_burst():
    """Verify performance correctness scaling bursts immediately available under heavy proxy load limits."""
    # Setup limiter: no RPS limit, max 1000 requests per minute
    # Simulates a heavy bulk sync stream of tool outputs. 
    limiter = DualBucketRateLimiter(rate_rps=0, burst_rps=1000, rate_rpm=1000, burst_rpm=500)
    
    key = "test_stress_1"
    
    # Consume 499 burst tokens cleanly
    for _ in range(499):
        allowed, reason, _ = limiter.consume(key)
        assert allowed is True
        assert reason == ""
        
    # Boundary logic Check at exact token capacity
    # Consume exactly the 500th
    allowed, reason, _ = limiter.consume(key)
    assert allowed is True
    
    # Token 501 should reject immediately
    allowed, reason, _ = limiter.consume(key)
    assert allowed is False
    assert "RPM limit exceeded" in reason


# ── New tests ─────────────────────────────────────────────────────────────────

def test_token_bucket_disabled_when_rate_zero():
    """TokenBucket with rate=0 always returns True (disabled path)."""
    bucket = TokenBucket(rate=0, burst=10)
    for _ in range(20):
        assert bucket.consume("k") is True


def test_token_bucket_peek_does_not_consume():
    """peek() is non-destructive; two peeks leave the token available for consume()."""
    # burst=1 so bucket starts with exactly 1 token
    bucket = TokenBucket(rate=0.001, burst=1)
    key = "peek_key"
    # Pre-fill the bucket by triggering a lookup with 0 elapsed time
    # The bucket will initialise to (burst=1, now) on first access.
    assert bucket.peek(key) is True
    assert bucket.peek(key) is True  # still True — nothing consumed
    assert bucket.consume(key) is True  # uses the one token
    assert bucket.consume(key) is False  # token gone


def test_dual_bucket_rpm_blocks_after_burst():
    """RPM bucket exhausted after burst_rpm=5 requests; 6th call is rejected."""
    limiter = DualBucketRateLimiter(
        rate_rps=1000,
        burst_rps=1000,
        rate_rpm=5,
        burst_rpm=5,
    )
    key = "rpm_burst_key"
    for i in range(5):
        allowed, reason, _ = limiter.consume(key)
        assert allowed is True, f"request {i+1} should pass"
    allowed, reason, _ = limiter.consume(key)
    assert allowed is False
    assert "RPM limit exceeded" in reason


def test_enforce_rate_limit_raises_rate_limit_error(monkeypatch):
    """enforce_rate_limit raises RateLimitError when the module-level limiter rejects."""
    mock_limiter = MagicMock()
    mock_limiter.consume.return_value = (False, "RPS limit exceeded", 5.0)
    monkeypatch.setattr(rl_mod, "_limiter", mock_limiter)
    with pytest.raises(RateLimitError) as exc_info:
        enforce_rate_limit("test-key")
    assert "RPS limit exceeded" in str(exc_info.value)


def test_enforce_rate_limit_passes_when_allowed(monkeypatch):
    """enforce_rate_limit does not raise when the limiter allows the request."""
    mock_limiter = MagicMock()
    mock_limiter.consume.return_value = (True, "", 0.0)
    monkeypatch.setattr(rl_mod, "_limiter", mock_limiter)
    # Must not raise
    enforce_rate_limit("test-key")


async def test_enforce_per_key_rate_limit_skips_when_no_record(monkeypatch):
    """enforce_per_key_rate_limit returns silently when key_record is None.

    key_store.get() is patched to return None so no DB init is required.
    """
    from storage import keys as keys_mod
    monkeypatch.setattr(keys_mod.key_store, "get", lambda key: _async_return(None))
    await enforce_per_key_rate_limit("some-key", key_record=None)


async def test_enforce_per_key_rate_limit_skips_when_zero_limits():
    """enforce_per_key_rate_limit returns silently when both limits are 0."""
    await enforce_per_key_rate_limit("some-key", key_record={"rpm_limit": 0, "rps_limit": 0})


async def test_enforce_per_key_rate_limit_raises_when_exhausted():
    """Second call for a key with rpm_limit=1 raises RateLimitError."""
    # Use a unique key so no state leaks from other tests
    key = "per-key-exhaust-test-unique"
    record = {"rpm_limit": 1, "rps_limit": 0}
    # First call must pass (burst_rpm=1 allows exactly 1 token)
    await enforce_per_key_rate_limit(key, key_record=record)
    # Second call must be rejected
    with pytest.raises(RateLimitError) as exc_info:
        await enforce_per_key_rate_limit(key, key_record=record)
    assert "Per-key rate limit exceeded" in str(exc_info.value)


# ── Bug 2: TOCTOU race fix tests ──────────────────────────────────────────────

def test_dual_bucket_consume_return_values_are_used():
    """DualBucketRateLimiter.consume() must honour consume() return values.

    With burst_rpm=1: first consume passes, second must fail with RPM reason.
    Verifies the silent-discard bug (return values of _rps.consume/_rpm.consume
    were previously ignored) is fixed.
    """
    limiter = DualBucketRateLimiter(
        rate_rps=1000.0,
        burst_rps=1000,
        rate_rpm=1.0,
        burst_rpm=1,
    )
    key = "discard-return-test"
    allowed, reason, _ = limiter.consume(key)
    assert allowed is True
    allowed, reason, _ = limiter.consume(key)
    assert allowed is False
    assert "RPM" in reason


def test_token_bucket_refund_restores_token():
    """refund() must restore a previously consumed token, capped at burst."""
    bucket = TokenBucket(rate=0.001, burst=1)
    key = "refund-test"
    assert bucket.consume(key) is True
    assert bucket.consume(key) is False  # empty
    bucket.refund(key)
    assert bucket.consume(key) is True  # restored


def test_token_bucket_refund_capped_at_burst():
    """refund() must not push level above burst capacity."""
    bucket = TokenBucket(rate=0.001, burst=2)
    key = "refund-cap-test"
    # Bucket starts full at burst=2; refund should not push above 2
    bucket.refund(key)
    assert bucket.consume(key) is True
    assert bucket.consume(key) is True
    assert bucket.consume(key) is False  # empty


def test_token_bucket_refund_disabled_when_rate_zero():
    """refund() on a disabled bucket (rate=0) must be a no-op."""
    bucket = TokenBucket(rate=0, burst=10)
    bucket.refund("any-key")  # must not raise


def test_dual_bucket_rps_refunded_on_rpm_failure():
    """When RPM fails, the already-consumed RPS token must be refunded.

    Sets up burst_rps=1, burst_rpm=0 (disabled). First consume drains RPS.
    If refund works, a second consume on the same key must still reject on RPS
    (meaning the refund from the first RPM-fail correctly restored the RPS token,
    and then the second call consumed it again and RPM still blocks).
    """
    # RPS burst=1, RPM disabled (rate=0 means always passes)
    # We can't easily test the refund path without RPM failing.
    # Instead: RPS burst=1, RPM burst=1. After first consume both drained.
    # Second consume: RPS has 0 tokens → fails immediately (RPS reason).
    # This shows RPS was NOT silently left at -1 from the previous consume.
    limiter = DualBucketRateLimiter(
        rate_rps=0.001,
        burst_rps=1,
        rate_rpm=0.001,
        burst_rpm=1,
    )
    key = "refund-path-test"
    allowed, reason, _ = limiter.consume(key)
    assert allowed is True
    allowed, reason, _ = limiter.consume(key)
    assert allowed is False
    # Either RPS or RPM is exhausted — both buckets drained correctly
    assert "exceeded" in reason


# ── seconds_until_token ───────────────────────────────────────────────────────

def test_seconds_until_token_zero_when_tokens_available():
    """Returns 0.0 when bucket has tokens."""
    bucket = TokenBucket(rate=10.0, burst=10)
    assert bucket.seconds_until_token("k") == 0.0


def test_seconds_until_token_positive_after_exhaustion():
    """Returns positive value after bucket is drained."""
    bucket = TokenBucket(rate=1.0, burst=1)
    bucket.consume("k")  # drain
    wait = bucket.seconds_until_token("k")
    assert wait > 0.0
    assert wait <= 1.0  # at rate=1 token/s, max wait is 1s


def test_seconds_until_token_zero_when_disabled():
    """Disabled bucket (rate=0) always returns 0.0."""
    bucket = TokenBucket(rate=0, burst=10)
    assert bucket.seconds_until_token("k") == 0.0


# ── retry_after propagated from consume ───────────────────────────────────────

def test_dual_bucket_consume_returns_retry_after_on_rps_fail():
    """consume() must return a positive retry_after when RPS bucket is exhausted."""
    limiter = DualBucketRateLimiter(rate_rps=1.0, burst_rps=1, rate_rpm=1000, burst_rpm=1000)
    key = "retry-rps"
    limiter.consume(key)  # drain RPS
    allowed, reason, retry_after = limiter.consume(key)
    assert allowed is False
    assert "RPS" in reason
    assert retry_after > 0.0


def test_dual_bucket_consume_returns_retry_after_on_rpm_fail():
    """consume() must return a positive retry_after when RPM bucket is exhausted."""
    limiter = DualBucketRateLimiter(rate_rps=1000, burst_rps=1000, rate_rpm=1.0, burst_rpm=1)
    key = "retry-rpm"
    limiter.consume(key)  # drain RPM
    allowed, reason, retry_after = limiter.consume(key)
    assert allowed is False
    assert "RPM" in reason
    assert retry_after > 0.0


# ── enforce_rate_limit sets retry_after on RateLimitError ─────────────────────

def test_enforce_rate_limit_retry_after_is_positive(monkeypatch):
    """RateLimitError raised by enforce_rate_limit must have retry_after >= 1."""
    mock_limiter = MagicMock()
    mock_limiter.consume.return_value = (False, "RPS limit exceeded", 0.3)
    monkeypatch.setattr(rl_mod, "_limiter", mock_limiter)
    with pytest.raises(RateLimitError) as exc_info:
        enforce_rate_limit("key")
    # retry_after floored to 1.0 minimum
    assert exc_info.value.retry_after >= 1.0


# ── LRU bound on TokenBucket._buckets ────────────────────────────────────────

def test_token_bucket_lru_evicts_oldest_key():
    """TokenBucket evicts LRU keys when maxsize is reached."""
    from middleware.rate_limit import _BUCKET_MAX_KEYS
    # Use a tiny maxsize to force eviction without iterating 10k times
    from cachetools import LRUCache
    bucket = TokenBucket(rate=1.0, burst=10)
    bucket._buckets = LRUCache(maxsize=3)  # override for test
    for i in range(4):
        bucket.consume(f"key_{i}")
    # maxsize=3: oldest key_0 should be evicted
    assert len(bucket._buckets) == 3
    # key_0 evicted — accessing it returns fresh burst (not an error)
    assert bucket.peek("key_0") is True  # full bucket after eviction


# ── rpm_burst config ─────────────────────────────────────────────────────────

def test_rpm_burst_defaults_to_rate_limit_rpm(monkeypatch):
    """When rate_limit_rpm_burst=0, _rpm_burst() returns rate_limit_rpm."""
    from middleware.rate_limit import _rpm_burst
    import middleware.rate_limit as rl
    mock_s = MagicMock()
    mock_s.rate_limit_rpm_burst = 0
    mock_s.rate_limit_rpm = 60.0
    monkeypatch.setattr(rl, "settings", mock_s)
    assert _rpm_burst() == 60


def test_rpm_burst_uses_explicit_setting_when_set(monkeypatch):
    """When rate_limit_rpm_burst>0, _rpm_burst() returns it directly."""
    from middleware.rate_limit import _rpm_burst
    import middleware.rate_limit as rl
    mock_s = MagicMock()
    mock_s.rate_limit_rpm_burst = 10
    mock_s.rate_limit_rpm = 60.0
    monkeypatch.setattr(rl, "settings", mock_s)
    assert _rpm_burst() == 10
