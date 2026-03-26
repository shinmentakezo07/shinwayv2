"""
Shin Proxy — Fine-tuning API stubs.

Fine-tuning is not supported by the Cursor upstream.
Stubs complete the OpenAI API surface so clients that enumerate
capabilities don't receive connection errors.
"""
from __future__ import annotations

import structlog
from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse

from middleware.auth import verify_bearer

router = APIRouter()
log = structlog.get_logger()

_NOT_SUPPORTED = {
    "error": {
        "message": (
            "Fine-tuning is not supported by this proxy. "
            "Use the OpenAI API directly for fine-tuning."
        ),
        "type": "not_implemented_error",
        "code": "fine_tuning_not_supported",
    }
}


@router.post("/v1/fine_tuning/jobs")
async def create_fine_tuning_job(
    request: Request,
    authorization: str | None = Header(default=None),
):
    """Create fine-tuning job — not supported."""
    await verify_bearer(authorization)
    return JSONResponse(status_code=501, content=_NOT_SUPPORTED)


@router.get("/v1/fine_tuning/jobs")
async def list_fine_tuning_jobs(
    request: Request,
    authorization: str | None = Header(default=None),
):
    """List fine-tuning jobs — not supported."""
    await verify_bearer(authorization)
    return JSONResponse(status_code=501, content=_NOT_SUPPORTED)


@router.get("/v1/fine_tuning/jobs/{job_id}")
async def get_fine_tuning_job(
    job_id: str,
    request: Request,
    authorization: str | None = Header(default=None),
):
    """Get fine-tuning job status — not supported."""
    await verify_bearer(authorization)
    return JSONResponse(status_code=501, content=_NOT_SUPPORTED)


@router.post("/v1/fine_tuning/jobs/{job_id}/cancel")
async def cancel_fine_tuning_job(
    job_id: str,
    request: Request,
    authorization: str | None = Header(default=None),
):
    """Cancel fine-tuning job — not supported."""
    await verify_bearer(authorization)
    return JSONResponse(status_code=501, content=_NOT_SUPPORTED)
