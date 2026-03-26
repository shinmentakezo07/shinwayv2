"""
Shin Proxy — Embeddings stub.

Embeddings are not supported by the Cursor upstream.
Returns a clean 501 so clients that probe capabilities don't hang.
"""
from __future__ import annotations

import structlog
from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse

from middleware.auth import verify_bearer
from middleware.rate_limit import enforce_rate_limit

router = APIRouter()
log = structlog.get_logger()

_NOT_SUPPORTED = {
    "error": {
        "message": (
            "Embeddings are not supported by this proxy. "
            "Use a dedicated embeddings provider (OpenAI, Cohere, etc.)."
        ),
        "type": "not_implemented_error",
        "code": "embeddings_not_supported",
    }
}


@router.post("/v1/embeddings")
async def embeddings(
    request: Request,
    authorization: str | None = Header(default=None),
):
    """Embeddings — not supported by this proxy."""
    api_key = await verify_bearer(authorization)
    enforce_rate_limit(api_key, request=request)
    log.info("embeddings_stub_called")
    return JSONResponse(status_code=501, content=_NOT_SUPPORTED)
