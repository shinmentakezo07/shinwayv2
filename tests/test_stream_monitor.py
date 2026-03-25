import asyncio
import pytest
from handlers import TimeoutError as ProxyTimeoutError
from utils.stream_monitor import StreamMonitor

@pytest.mark.asyncio
async def test_stream_monitor_fast_paths():
    """Test general stream timing tracking for fast connections."""
    monitor = StreamMonitor(first_token_timeout=2.0, idle_timeout=2.0, label="test-fast")
    
    async def fast_stream():
        yield "a"
        yield "b"
        yield "c"
        
    chunks = [c async for c in monitor.wrap(fast_stream())]
    
    assert chunks == ["a", "b", "c"]
    stats = monitor.stats()
    assert stats["chunks"] == 3
    assert stats["stalls"] == 0
    assert stats["bytes"] == 3

@pytest.mark.asyncio
async def test_stream_monitor_first_token_timeout():
    """Test TimeoutError exception if the first token exceeds timeout limits (simulation for overloaded models)."""
    monitor = StreamMonitor(first_token_timeout=0.1, idle_timeout=1.0, label="test-timeout")
    
    async def delayed_stream():
        await asyncio.sleep(0.3)
        yield "token"
        
    with pytest.raises(ProxyTimeoutError, match="No first token after"):
        async for _ in monitor.wrap(delayed_stream()):
            pass

@pytest.mark.asyncio
async def test_stream_monitor_idle_stall_timeout():
    """Test TimeoutError exception for intra-chunk slow delivery (e.g. dropped context processing at 180K tokens)."""
    monitor = StreamMonitor(first_token_timeout=1.0, idle_timeout=0.2, label="test-stall")
    
    async def stalling_stream():
        yield "fast"
        await asyncio.sleep(0.5)
        yield "stall"
        
    with pytest.raises(ProxyTimeoutError, match="Stream stalled for"):
        async for _ in monitor.wrap(stalling_stream()):
            pass


@pytest.mark.asyncio
async def test_stream_monitor_stats_before_start():
    """stats() before wrap() is called returns zero-state values."""
    monitor = StreamMonitor(label="test-before-start")
    stats = monitor.stats()
    # _start_time is 0.0 (falsy) so total_s is 0.0 by the implementation guard
    assert stats["total_s"] == 0.0
    assert stats["ttft_ms"] is None
    assert stats["chunks"] == 0


@pytest.mark.asyncio
async def test_stream_monitor_stats_after_stream():
    """After a 3-chunk stream stats reflect correct chunk/byte/ttft counts."""
    monitor = StreamMonitor(first_token_timeout=2.0, idle_timeout=2.0, label="test-stats-after")

    async def three_chunks():
        yield "a"
        yield "b"
        yield "c"

    async for _ in monitor.wrap(three_chunks()):
        pass

    stats = monitor.stats()
    assert stats["chunks"] == 3
    assert stats["bytes"] == 3  # one char per chunk
    assert stats["ttft_ms"] is not None
    assert stats["stalls"] == 0


@pytest.mark.asyncio
async def test_stream_monitor_client_disconnect_raises_stream_abort():
    """CancelledError from the source generator is converted to StreamAbortError."""
    from handlers import StreamAbortError

    monitor = StreamMonitor(first_token_timeout=2.0, idle_timeout=2.0, label="test-cancel")

    async def cancel_stream():
        yield "first"
        raise asyncio.CancelledError()

    with pytest.raises(StreamAbortError):
        async for _ in monitor.wrap(cancel_stream()):
            pass


@pytest.mark.asyncio
async def test_stream_monitor_avg_chunk_bytes_zero_when_no_chunks():
    """avg_chunk_bytes is 0 when no chunks have been received."""
    monitor = StreamMonitor(label="test-avg-zero")
    stats = monitor.stats()
    assert stats["avg_chunk_bytes"] == 0


@pytest.mark.asyncio
async def test_stream_monitor_counts_bytes_correctly():
    """bytes and chunks reflect actual content yielded by the source."""
    monitor = StreamMonitor(first_token_timeout=2.0, idle_timeout=2.0, label="test-bytes")

    async def two_words():
        yield "hello"
        yield "world"

    async for _ in monitor.wrap(two_words()):
        pass

    stats = monitor.stats()
    assert stats["chunks"] == 2
    assert stats["bytes"] == 10  # 5 + 5 characters
