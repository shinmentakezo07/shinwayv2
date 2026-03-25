"""
Shin Proxy — FastAPI application factory.

Creates the app, registers routers, middleware, exception handlers,
and lifespan hooks (httpx client init/teardown).
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

import httpx
import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError as FastAPIValidationError
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator
from starlette.middleware.gzip import GZipMiddleware

from config import settings
from handlers import ProxyError, StreamAbortError

log = structlog.get_logger()


# ── Shared httpx client (created in lifespan) ──────────────────────────────
_http_client: httpx.AsyncClient | None = None


def get_http_client() -> httpx.AsyncClient:
    """Return the shared httpx AsyncClient. Must be called after app startup."""
    if _http_client is None:
        raise RuntimeError("httpx client not initialised — call app startup before get_http_client()")
    return _http_client

@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    global _http_client
    if not settings.debug and settings.master_key == "sk-local-dev":
        raise RuntimeError(
            "LITELLM_MASTER_KEY is set to the default placeholder 'sk-local-dev'. "
            "Set a real key in .env, or set DEBUG=true to suppress this check."
        )
    _http_client = httpx.AsyncClient(
        http2=True,
        # Let StreamMonitor handle stream read timeouts to support dynamic 200K token payloads
        timeout=httpx.Timeout(connect=15.0, read=None, write=None, pool=15.0),
        limits=httpx.Limits(
            max_connections=1500,
            max_keepalive_connections=300,
            keepalive_expiry=60.0,
        ),
        follow_redirects=True,
    )
    log.info("httpx_client_started")
    # Pre-warm HTTP/2 connection to cursor upstream before serving traffic
    try:
        await _http_client.head(settings.cursor_base_url, timeout=5.0)
        log.info("upstream_connection_prewarmed", url=settings.cursor_base_url)
    except Exception as exc:
        log.warning("upstream_prewarm_failed", error=str(exc)[:100])
    # Init response store
    from storage.responses import response_store
    await response_store.init()
    log.info("response_store_started")
    from storage.keys import key_store
    await key_store.init()
    log.info("key_store_started")

    try:
        yield
    finally:
        from storage.keys import key_store
        await key_store.close()
        log.info("key_store_closed")
        await response_store.close()
        log.info("response_store_closed")
        await _http_client.aclose()
        log.info("httpx_client_closed")


# ── Helpers ─────────────────────────────────────────────────────────────────

def _is_anthropic(request: Request) -> bool:
    return request.url.path.startswith("/v1/messages")


# ── App factory ─────────────────────────────────────────────────────────────

def create_app() -> FastAPI:
    app = FastAPI(
        title="Shin Proxy",
        version="1.0.0",
        description="Clean-architecture Cursor reverse proxy",
        lifespan=_lifespan,
    )

    # ── Exception handlers ──────────────────────────────────────────────

    @app.exception_handler(ProxyError)
    async def proxy_error_handler(request: Request, exc: ProxyError) -> JSONResponse:
        from handlers import RateLimitError as _RateLimitError
        request_id = getattr(request.state, "request_id", "unknown")
        if not isinstance(exc, StreamAbortError):
            log.error(
                "proxy_error",
                type=exc.error_type,
                message=exc.message,
                path=str(request.url.path),
                request_id=request_id,
            )
        body = exc.to_anthropic() if _is_anthropic(request) else exc.to_openai()
        headers: dict[str, str] = {}
        if isinstance(exc, _RateLimitError):
            headers["Retry-After"] = str(int(exc.retry_after))
        return JSONResponse(status_code=exc.status_code, content=body, headers=headers)

    @app.exception_handler(FastAPIValidationError)
    async def validation_error_handler(
        request: Request, exc: FastAPIValidationError
    ) -> JSONResponse:
        errors = exc.errors()
        first = errors[0] if errors else {}
        loc = first.get("loc", ["unknown"])
        msg = f"Invalid request: {loc[-1]} — {first.get('msg', 'validation error')}"
        log.warning("validation_error", errors=errors, path=str(request.url.path))
        body = {
            "error": {
                "message": msg,
                "type": "invalid_request_error",
                "code": "400",
            }
        }
        return JSONResponse(status_code=400, content=body)

    import json as _json

    @app.exception_handler(_json.JSONDecodeError)
    async def json_decode_error_handler(
        request: Request, exc: _json.JSONDecodeError
    ) -> JSONResponse:
        log.warning("json_decode_error", path=str(request.url.path), error=str(exc)[:100])
        body = {
            "error": {
                "message": "Request body is not valid JSON",
                "type": "invalid_request_error",
                "code": "400",
            }
        }
        return JSONResponse(status_code=400, content=body)

    @app.exception_handler(Exception)
    async def unhandled_error_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        request_id = getattr(request.state, "request_id", "unknown")
        log.exception(
            "unhandled_error",
            path=str(request.url.path),
            request_id=request_id,
        )
        body = {
            "error": {
                "message": "Internal server error",
                "type": "server_error",
                "code": "500",
            }
        }
        return JSONResponse(status_code=500, content=body)

    # ── Middleware: gzip compression for non-streaming responses ────────
    app.add_middleware(GZipMiddleware, minimum_size=1000)

    # ── Middleware: request body size limit ─────────────────────────────
    if settings.max_request_body_bytes > 0:
        @app.middleware("http")
        async def body_size_limit(request: Request, call_next):
            content_length = request.headers.get("content-length")
            # Note: chunked requests (Transfer-Encoding: chunked) omit Content-Length
            # and bypass this check. LLM API clients always send Content-Length.
            if content_length is not None:
                try:
                    if int(content_length) > settings.max_request_body_bytes:
                        from handlers import RequestValidationError as _RVE
                        err = _RVE(
                            f"Request body too large: {content_length} bytes "
                            f"(limit {settings.max_request_body_bytes} bytes)"
                        )
                        return JSONResponse(
                            status_code=413,
                            content=err.to_anthropic() if _is_anthropic(request) else err.to_openai(),
                        )
                except (ValueError, TypeError):
                    pass
            return await call_next(request)

    # ── Middleware: RequestContext + structured lifecycle logging ────────
    from middleware.logging import request_context_middleware

    @app.middleware("http")
    async def _request_context(request: Request, call_next):
        return await request_context_middleware(request, call_next)

    # ── Register routers ────────────────────────────────────────────────
    from routers.internal import router as internal_router
    from routers.openai import router as openai_router
    from routers.anthropic import router as anthropic_router
    from routers.responses import router as responses_router

    app.include_router(internal_router)
    app.include_router(openai_router)
    app.include_router(anthropic_router)
    app.include_router(responses_router)

    # ── Prometheus metrics ──────────────────────────────────────────────
    if settings.metrics_enabled:
        Instrumentator(
            should_group_status_codes=False,
            excluded_instrumentations=[],
        ).instrument(app).expose(app, endpoint=settings.metrics_path, include_in_schema=False)
        log.info("metrics_enabled", path=settings.metrics_path)

    return app
