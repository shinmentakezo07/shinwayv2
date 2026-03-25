"""
Shin Proxy — Stream health monitor.

Wraps any async string generator to track TTFT, chunk rate, stalls,
and logs per-request stream stats on completion.
"""

from __future__ import annotations

import asyncio
import time
from typing import AsyncIterator

import structlog

from config import settings
from handlers import StreamAbortError, TimeoutError as ProxyTimeoutError

log = structlog.get_logger()


class StreamMonitor:
    """Wraps a streaming generator to track timing, detect stalls, and log stats.

    Usage:
        monitor = StreamMonitor(label="openai/claude-sonnet-4.6")
        async for chunk in monitor.wrap(client.stream(...)):
            yield chunk
    """

    def __init__(
        self,
        first_token_timeout: float = 60.0,
        idle_timeout: float = 30.0,
        label: str = "stream",
    ) -> None:
        self.first_token_timeout = first_token_timeout
        self.idle_timeout = idle_timeout
        self.label = label

        self._start_time: float = 0.0
        self._first_token_time: float | None = None
        self._last_chunk_time: float = 0.0
        self._chunk_count: int = 0
        self._byte_count: int = 0
        self._stall_count: int = 0

    async def wrap(self, source: AsyncIterator[str]) -> AsyncIterator[str]:
        self._start_time = time.monotonic()
        self._last_chunk_time = self._start_time
        heartbeat_s = settings.stream_heartbeat_s

        it = source.__aiter__()
        while True:
            timeout = (
                self.first_token_timeout
                if self._first_token_time is None
                else min(self.idle_timeout, heartbeat_s)
            )
            try:
                chunk = await asyncio.wait_for(it.__anext__(), timeout=timeout)
            except StopAsyncIteration:
                break
            except asyncio.TimeoutError:
                elapsed = time.monotonic() - self._last_chunk_time
                if self._first_token_time is None:
                    # Still waiting for first token — hard timeout
                    self._stall_count += 1
                    log.warning(
                        "stream_first_token_timeout",
                        label=self.label,
                        waited_s=round(elapsed, 1),
                    )
                    raise ProxyTimeoutError(
                        f"No first token after {elapsed:.0f}s — Cursor may be overloaded"
                    )
                elif elapsed < self.idle_timeout:
                    # Heartbeat interval elapsed but stream is still alive — skip
                    # Do NOT yield SSE comments here; they corrupt the text accumulator
                    # in pipeline.py. HTTP keepalive is handled at the transport layer.
                    continue
                else:
                    # True idle stall — exceeded idle_timeout
                    self._stall_count += 1
                    log.warning(
                        "stream_idle_stall",
                        label=self.label,
                        idle_s=round(elapsed, 1),
                        stalls=self._stall_count,
                    )
                    raise ProxyTimeoutError(
                        f"Stream stalled for {elapsed:.0f}s after {self._chunk_count} chunks"
                    )
            except asyncio.CancelledError:
                log.info("client_disconnected", label=self.label, chunks=self._chunk_count)
                raise StreamAbortError("Client disconnected")

            now = time.monotonic()
            if self._first_token_time is None:
                self._first_token_time = now
                log.info(
                    "stream_first_token",
                    label=self.label,
                    ttft_ms=round((now - self._start_time) * 1000),
                )

            self._last_chunk_time = now
            self._chunk_count += 1
            self._byte_count += len(chunk)  # character count — avoids re-encoding decoded string on every chunk
            yield chunk

        self._log_completion()

    def stats(self) -> dict:
        now = time.monotonic()
        total_s = now - self._start_time if self._start_time else 0.0
        ttft_ms = (
            round((self._first_token_time - self._start_time) * 1000)
            if self._first_token_time
            else None
        )
        return {
            "label": self.label,
            "total_s": round(total_s, 2),
            "ttft_ms": ttft_ms,
            "chunks": self._chunk_count,
            "bytes": self._byte_count,
            "stalls": self._stall_count,
            "avg_chunk_bytes": (
                round(self._byte_count / self._chunk_count)
                if self._chunk_count > 0
                else 0
            ),
        }

    def _log_completion(self) -> None:
        s = self.stats()
        log.info("stream_complete", **{k: v for k, v in s.items() if v is not None})
