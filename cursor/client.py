"""
Shin Proxy — Async Cursor API client.

Wraps httpx.AsyncClient to communicate with Cursor's /api/chat endpoint.
Handles request building, SSE streaming, and error classification.
"""

from __future__ import annotations

import asyncio
import random
import uuid
from typing import AsyncIterator

import httpx
import msgspec.json as _msgjson
import structlog

from config import settings
from runtime_config import runtime_config
from cursor.credentials import CredentialPool, CredentialInfo, credential_pool
from cursor.sse import iter_deltas
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
    """Build request headers for Cursor's /api/chat endpoint."""
    _pool = pool or credential_pool
    headers: dict[str, str] = {
        "Content-Type": "application/json",
        "Accept": "*/*",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Accept-Language": "en-US,en;q=0.8",
        "User-Agent": settings.user_agent or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
        "Origin": settings.cursor_base_url,
        "Referer": f"{settings.cursor_base_url}/dashboard",
        "sec-ch-ua": '"Chromium";v="146", "Not-A.Brand";v="24", "Brave";v="146"',
        "sec-ch-ua-arch": '"x86"',
        "sec-ch-ua-bitness": '"64"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-ch-ua-platform-version": '"19.0.0"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "sec-gpc": "1",
        "Connection": "keep-alive",
        "DNT": "1",
        "priority": "u=1, i",
        "http-referer": "https://cursor.com/learn",
        "x-title": "Learn",
    }
    # Fingerprint: Cookie + Datadog tracing headers — all credential-aware, one call.
    headers.update(_pool.build_request_headers(cred))
    return headers


def _build_payload(
    cursor_messages: list[dict],
    model: str,
    anthropic_tools: list[dict] | None = None,
) -> dict:
    """Build the Cursor API request body.

    IMPORTANT: `model` is the EXACT model ID to send upstream.
    It must already be resolved by the router — no fallback here.
    When tools are present, spoof context path to /workspace/project to avoid
    Cursor activating its /docs path-scoping behaviour.
    """
    if not model:
        raise ValueError("model must be specified — no fallback allowed")
    log.info("upstream_model", model=model)
    # Layer 6 — Context path spoofer: tools present → local workspace path
    context_path = (
        "/workspace/project"
        if anthropic_tools
        else settings.cursor_context_file_path
    )
    payload: dict = {
        "context": [
            {
                "type": "file",
                "content": "",
                "filePath": context_path,
            }
        ],
        "model": model,
        "id": uuid.uuid4().hex[:16],
        "trigger": "submit-message",
        "messages": cursor_messages,
    }
    if anthropic_tools:
        payload["tools"] = anthropic_tools
    return payload



def classify_cursor_error(
    status: int,
    body: str,
    headers: "httpx.Headers | None" = None,
) -> BackendError | CredentialError | RateLimitError:
    """Map a Cursor HTTP error to a typed ProxyError."""
    match status:
        case 401:
            return CredentialError("Cursor credential rejected — cookie may be expired")
        case 403:
            return CredentialError("Cursor access forbidden — account may be banned")
        case 429:
            # M1 fix: Retry-After may be an integer string OR an HTTP-date string
            # (RFC 7231 allows both). float() raises ValueError on dates — guard it.
            _ra_raw = (headers or {}).get("Retry-After", "60")
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

    async def _send_telemetry(self, cred: CredentialInfo) -> None:
        """Send a background Vercel insights event to mimic the browser and prevent rate-limiting."""
        try:
            url = f"{settings.cursor_base_url}/_vercel/insights/event"
            headers = _build_headers(cred, self._pool)
            # Fix #4: telemetry uses no-cors + text/plain, matching real browser beacon behaviour
            headers["Content-Type"] = "text/plain; charset=utf-8"
            headers["sec-fetch-mode"] = "no-cors"
            headers["priority"] = "u=4, i"
            payload = "{}"
            await self._http.post(url, headers=headers, content=payload)
        except Exception as e:
            log.debug("telemetry_failed", error=str(e))

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
        """Stream text deltas from Cursor /api/chat.

        Yields plain strings — never tool call JSON.
        The caller (pipeline) is responsible for tool-call detection.
        """
        payload = _build_payload(cursor_messages, model, anthropic_tools)
        # Bug 4 — offload JSON serialization to thread pool (non-blocking for large contexts)
        loop = asyncio.get_running_loop()
        payload_bytes = await loop.run_in_executor(
            None, lambda: _msgjson.encode(payload)
        )
        
        last_exc: Exception | None = None

        # Retry loop for connection phase ONLY
        for attempt in range(runtime_config.get("retry_attempts")):
            _cred = cred or self._pool.next()
            headers = _build_headers(_cred, self._pool)
            
            try:
                # Fire and forget Vercel telemetry
                if _cred:
                    _t = asyncio.create_task(self._send_telemetry(_cred))
                    _background_tasks.add(_t)
                    _t.add_done_callback(_background_tasks.discard)

                # Use a custom generator inside to handle yielding
                # We do this because yielding inside `async with` and catching errors there
                # is tricky if the chunk extraction itself crashes.
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
                        raise classify_cursor_error(response.status_code, body_text, response.headers)

                    async for delta in iter_deltas(response, anthropic_tools):
                        yield delta

                    if _cred:
                        self._pool.mark_success(_cred)
                    
                    # If we finish parsing normally, don't execute the generic exception block
                    return

            except (httpx.ReadTimeout, httpx.ConnectTimeout) as exc:
                if _cred:
                    self._pool.mark_error(_cred)
                cred = None  # H1 fix: rotate credential on next attempt
                last_exc = TimeoutError(f"Cursor timeout: {exc}")
                if attempt + 1 < runtime_config.get("retry_attempts"):
                    base = runtime_config.get("retry_backoff_seconds") * (2 ** attempt)
                    jitter = random.uniform(0, base * 0.3)  # nosec B311 — jitter for backoff, not crypto
                    await asyncio.sleep(min(base + jitter, 30.0))
                continue
            except httpx.ConnectError as exc:
                if _cred:
                    self._pool.mark_error(_cred)
                cred = None  # H1 fix: rotate credential on next attempt
                last_exc = BackendError(f"Cursor connection error: {exc}")
                if attempt + 1 < runtime_config.get("retry_attempts"):
                    base = runtime_config.get("retry_backoff_seconds") * (2 ** attempt)
                    jitter = random.uniform(0, base * 0.3)  # nosec B311 — jitter for backoff, not crypto
                    await asyncio.sleep(min(base + jitter, 30.0))
                continue
            except (CredentialError, RateLimitError) as exc:
                last_exc = exc
                if isinstance(exc, CredentialError):
                    cred = None  # allow pool rotation on next attempt
                if attempt + 1 < runtime_config.get("retry_attempts"):
                    wait = getattr(exc, 'retry_after', runtime_config.get("retry_backoff_seconds") * (2 ** attempt))
                    jitter = random.uniform(0, min(wait * 0.1, 5.0))  # nosec B311 — jitter for backoff, not crypto
                    await asyncio.sleep(min(wait + jitter, 120.0))
                continue
            except EmptyResponseError as exc:
                if _cred:
                    self._pool.mark_error(_cred)
                cred = None  # H1 fix: rotate credential on next attempt
                last_exc = BackendError(f"Empty upstream response (attempt {attempt + 1}): {exc}")
                if attempt + 1 < runtime_config.get("retry_attempts"):
                    base = runtime_config.get("retry_backoff_seconds") * (2 ** attempt)
                    jitter = random.uniform(0, base * 0.3)  # nosec B311 — jitter, not crypto
                    await asyncio.sleep(min(base + jitter, 30.0))
                continue
            except Exception as exc:
                # Non-retryable unknown error — bubble immediately
                if _cred:
                    self._pool.mark_error(_cred)
                raise exc

        # If the retry loop exhausted
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
        _cred = cred or self._pool.next()
        headers = {
            "Accept": "application/json",
            "User-Agent": settings.user_agent,
            "Origin": settings.cursor_base_url,
            "Referer": f"{settings.cursor_base_url}/",
        }
        headers.update(self._pool.get_auth_headers(_cred))

        url = f"{settings.cursor_base_url}/api/auth/me"
        response = await self._http.get(url, headers=headers)

        if response.status_code == 401:
            raise CredentialError("Cursor credential rejected — cookie may be expired")
        if response.status_code == 403:
            raise CredentialError("Cursor access forbidden — account may be banned")
        if response.status_code != 200:
            raise BackendError(
                f"Unexpected /api/auth/me response {response.status_code}",
                upstream_status=response.status_code,
            )

        return response.json()
