"""
Shin Proxy — Async Cursor API client.

Wraps httpx.AsyncClient to communicate with Cursor's /api/chat endpoint.
Handles request building, SSE streaming, and error classification.
"""

from __future__ import annotations

import asyncio
from typing import AsyncIterator

import httpx
import msgspec.json as _msgjson
import structlog

from config import settings
from cursor.credentials import CredentialInfo, CredentialPool, credential_pool
from runtime_config import runtime_config  # compatibility export for existing tests/patches
from cursor.events import log_retry_scheduled, log_validation_result
from cursor.metrics import cursor_metrics
from cursor.payloads import build_payload
from cursor.request_headers import build_headers
from cursor.retry import retry_exception_delay
from cursor.sse import iter_deltas
from cursor.telemetry import send_telemetry
from handlers import (
    BackendError,
    CredentialError,
    EmptyResponseError,
    RateLimitError,
    TimeoutError,
)

log = structlog.get_logger()

# Background task references — prevents GC of pending tasks in Python 3.12+
_background_tasks: set[asyncio.Task] = set()


def _build_headers(
    cred: CredentialInfo | None = None,
    pool: CredentialPool | None = None,
) -> dict[str, str]:
    """Compatibility wrapper for request header construction."""
    return build_headers(cred, pool)


def _build_payload(
    cursor_messages: list[dict],
    model: str,
    anthropic_tools: list[dict] | None = None,
) -> dict:
    """Compatibility wrapper for upstream payload construction."""
    return build_payload(cursor_messages, model, anthropic_tools)


def classify_cursor_error(
    status: int,
    body: str,
    headers: "httpx.Headers | None" = None,
) -> BackendError | CredentialError | RateLimitError:
    """Map a Cursor HTTP error to a typed ProxyError."""
    headers_map = headers if headers is not None else {}
    match status:
        case 401:
            return CredentialError("Cursor credential rejected — cookie may be expired")
        case 403:
            return CredentialError("Cursor access forbidden — account may be banned")
        case 429:
            _ra_raw = headers_map.get("Retry-After", "60")
            try:
                retry_after = float(_ra_raw)
            except (ValueError, TypeError):
                retry_after = 60.0
            return RateLimitError("Cursor rate limit hit", retry_after=retry_after)
        case 413:
            return BackendError(
                "Cursor rejected request — payload too large. "
                "Reduce context window or enable SHINWAY_TRIM_CONTEXT.",
                upstream_status=413,
            )
        case 500 | 502 | 503:
            return BackendError(
                f"Cursor backend error {status}", upstream_status=status
            )
        case _:
            return BackendError(
                f"Unexpected Cursor response {status}: {body[:200]}"
            )


class CursorClient:
    """Async wrapper around Cursor's /api/chat SSE endpoint."""

    def __init__(
        self,
        http_client: httpx.AsyncClient,
        pool: CredentialPool | None = None,
    ) -> None:
        self._http = http_client
        self._pool = pool or credential_pool

    @property
    def chat_url(self) -> str:
        return f"{settings.cursor_base_url}/api/chat"

    async def stream(
        self,
        cursor_messages: list[dict],
        model: str,
        anthropic_tools: list[dict] | None = None,
        cred: CredentialInfo | None = None,
    ) -> AsyncIterator[str]:
        """Stream text deltas from Cursor /api/chat."""
        payload = _build_payload(cursor_messages, model, anthropic_tools)
        loop = asyncio.get_running_loop()
        payload_bytes = await loop.run_in_executor(None, lambda: _msgjson.encode(payload))

        retry_attempts = int(runtime_config.get("retry_attempts"))
        retry_backoff_seconds = float(runtime_config.get("retry_backoff_seconds"))
        last_exc: Exception | None = None

        for attempt in range(retry_attempts):
            attempt_started = asyncio.get_running_loop().time()
            _cred = cred or self._pool.next()
            headers = _build_headers(_cred, self._pool)
            if _cred is not None:
                cursor_metrics.incr("client_attempt_selected", index=_cred.index)

            try:
                if _cred:
                    task = asyncio.create_task(send_telemetry(self._http, _cred, self._pool))
                    _background_tasks.add(task)
                    task.add_done_callback(_background_tasks.discard)

                async with self._http.stream(
                    "POST",
                    self.chat_url,
                    headers=headers,
                    content=payload_bytes,
                ) as response:
                    if response.status_code != 200:
                        body = await response.aread()
                        body_text = body.decode("utf-8", errors="ignore")
                        if _cred:
                            self._pool.mark_error(_cred)
                        raise classify_cursor_error(
                            response.status_code,
                            body_text,
                            response.headers,
                        )

                    async for delta in iter_deltas(response, anthropic_tools):
                        yield delta

                    if _cred:
                        latency_ms = (asyncio.get_running_loop().time() - attempt_started) * 1000.0
                        self._pool.mark_success(_cred, latency_ms=latency_ms)
                        cursor_metrics.incr("client_stream_success", index=_cred.index)
                        cursor_metrics.set_gauge("client_stream_last_latency_ms", latency_ms, index=_cred.index)
                    return

            except (httpx.ReadTimeout, httpx.ConnectTimeout) as exc:
                if _cred:
                    self._pool.mark_error(_cred)
                    cursor_metrics.incr("client_stream_error", kind="timeout", index=_cred.index)
                cred = None
                last_exc = TimeoutError(f"Cursor timeout: {exc}")
                if attempt + 1 < retry_attempts:
                    log_retry_scheduled(attempt + 1, "timeout")
                    cursor_metrics.incr("client_retry_scheduled", kind="timeout")
                    await asyncio.sleep(
                        retry_exception_delay(
                            last_exc,
                            attempt,
                            retry_backoff_seconds,
                        )
                    )
                continue
            except httpx.ConnectError as exc:
                if _cred:
                    self._pool.mark_error(_cred)
                    cursor_metrics.incr("client_stream_error", kind="connect", index=_cred.index)
                cred = None
                last_exc = BackendError(f"Cursor connection error: {exc}")
                if attempt + 1 < retry_attempts:
                    log_retry_scheduled(attempt + 1, "connect")
                    cursor_metrics.incr("client_retry_scheduled", kind="connect")
                    await asyncio.sleep(
                        retry_exception_delay(
                            last_exc,
                            attempt,
                            retry_backoff_seconds,
                        )
                    )
                continue
            except (CredentialError, RateLimitError) as exc:
                last_exc = exc
                if _cred is not None:
                    error_kind = "credential" if isinstance(exc, CredentialError) else "rate_limit"
                    cursor_metrics.incr("client_stream_error", kind=error_kind, index=_cred.index)
                if isinstance(exc, CredentialError):
                    cred = None
                if attempt + 1 < retry_attempts:
                    error_kind = "credential" if isinstance(exc, CredentialError) else "rate_limit"
                    log_retry_scheduled(attempt + 1, error_kind)
                    cursor_metrics.incr("client_retry_scheduled", kind=error_kind)
                    await asyncio.sleep(
                        retry_exception_delay(
                            exc,
                            attempt,
                            retry_backoff_seconds,
                        )
                    )
                continue
            except EmptyResponseError as exc:
                if _cred:
                    self._pool.mark_error(_cred)
                    cursor_metrics.incr("client_stream_error", kind="empty_response", index=_cred.index)
                cred = None
                last_exc = BackendError(
                    f"Empty upstream response (attempt {attempt + 1}): {exc}"
                )
                if attempt + 1 < retry_attempts:
                    log_retry_scheduled(attempt + 1, "empty_response")
                    cursor_metrics.incr("client_retry_scheduled", kind="empty_response")
                    await asyncio.sleep(
                        retry_exception_delay(
                            last_exc,
                            attempt,
                            retry_backoff_seconds,
                        )
                    )
                continue
            except Exception as exc:
                if _cred:
                    self._pool.mark_error(_cred)
                    cursor_metrics.incr("client_stream_error", kind="unexpected", index=_cred.index)
                raise exc

        if last_exc:
            raise last_exc

    async def call(
        self,
        cursor_messages: list[dict],
        model: str,
        anthropic_tools: list[dict] | None = None,
        cred: CredentialInfo | None = None,
    ) -> str:
        """Non-streaming call — collects full response text."""
        chunks: list[str] = []
        async for delta in self.stream(
            cursor_messages, model, anthropic_tools, cred
        ):
            chunks.append(delta)
        return "".join(chunks)

    async def auth_me(self, cred: CredentialInfo | None = None) -> dict:
        """Call Cursor's /api/auth/me to validate a credential and fetch account info."""
        resolved_cred = cred or self._pool.next()
        headers = {
            "Accept": "application/json",
            "User-Agent": settings.user_agent,
            "Origin": settings.cursor_base_url,
            "Referer": f"{settings.cursor_base_url}/",
        }
        headers.update(self._pool.get_auth_headers(resolved_cred))

        url = f"{settings.cursor_base_url}/api/auth/me"
        response = await self._http.get(url, headers=headers)

        if response.status_code == 401:
            if resolved_cred is not None:
                cursor_metrics.incr("client_auth_me", valid=False, index=resolved_cred.index)
                log_validation_result(resolved_cred.index, False)
            raise CredentialError("Cursor credential rejected — cookie may be expired")
        if response.status_code == 403:
            if resolved_cred is not None:
                cursor_metrics.incr("client_auth_me", valid=False, index=resolved_cred.index)
                log_validation_result(resolved_cred.index, False)
            raise CredentialError("Cursor access forbidden — account may be banned")
        if response.status_code != 200:
            if resolved_cred is not None:
                cursor_metrics.incr("client_auth_me", valid=False, index=resolved_cred.index)
                log_validation_result(resolved_cred.index, False)
            raise BackendError(
                f"Unexpected /api/auth/me response {response.status_code}",
                upstream_status=response.status_code,
            )

        if resolved_cred is not None:
            cursor_metrics.incr("client_auth_me", valid=True, index=resolved_cred.index)
            log_validation_result(resolved_cred.index, True)
        return response.json()
