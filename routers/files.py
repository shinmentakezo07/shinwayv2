"""
Shin Proxy — OpenAI-compatible Files API.

Files are stored in-memory (metadata only — no actual file content is kept
between requests). This satisfies clients that call /v1/files before
submitting batch jobs. File IDs are stable within a single server process
lifetime.

Endpoints:
    POST   /v1/files
    GET    /v1/files
    GET    /v1/files/{file_id}
    DELETE /v1/files/{file_id}
"""
from __future__ import annotations

import time
import uuid
from typing import Any

import structlog
from fastapi import APIRouter, Form, Header, Query, Request, UploadFile
from fastapi.responses import JSONResponse

from middleware.auth import verify_bearer
from middleware.rate_limit import enforce_rate_limit

router = APIRouter()
log = structlog.get_logger()

# In-memory store: file_id -> {metadata, content bytes}
# Scoped to process lifetime — no persistence required for this use case.
_files: dict[str, dict[str, Any]] = {}
_file_content: dict[str, bytes] = {}  # file_id -> raw bytes for /content endpoint


def _file_object(file_id: str, filename: str, purpose: str, size: int) -> dict[str, Any]:
    return {
        "id": file_id,
        "object": "file",
        "bytes": size,
        "created_at": int(time.time()),
        "filename": filename,
        "purpose": purpose,
        "status": "processed",
        "status_details": None,
    }


@router.post("/v1/files")
async def upload_file(
    request: Request,
    file: UploadFile,
    purpose: str = Form(...),
    authorization: str | None = Header(default=None),
):
    """Upload a file — stores metadata and content in-memory."""
    api_key = await verify_bearer(authorization)
    enforce_rate_limit(api_key, request=request)
    content = await file.read()
    file_id = f"file-{uuid.uuid4().hex[:24]}"
    obj = _file_object(file_id, file.filename or "upload", purpose, len(content))
    _files[file_id] = obj
    _file_content[file_id] = content
    log.info("file_uploaded", file_id=file_id, purpose=purpose, size=len(content))
    return JSONResponse(obj)


@router.get("/v1/files")
async def list_files(
    request: Request,
    purpose: str | None = Query(default=None),
    authorization: str | None = Header(default=None),
):
    """List uploaded files. Optional `purpose` filter (e.g. 'batch', 'assistants')."""
    api_key = await verify_bearer(authorization)
    enforce_rate_limit(api_key, request=request)
    files = list(_files.values())
    if purpose is not None:
        files = [f for f in files if f.get("purpose") == purpose]
    return JSONResponse({
        "object": "list",
        "data": files,
    })


@router.get("/v1/files/{file_id}")
async def get_file(
    file_id: str,
    request: Request,
    authorization: str | None = Header(default=None),
):
    """Retrieve file metadata by ID."""
    api_key = await verify_bearer(authorization)
    enforce_rate_limit(api_key, request=request)
    obj = _files.get(file_id)
    if obj is None:
        return JSONResponse(
            status_code=404,
            content={"error": {"message": f"File '{file_id}' not found", "type": "not_found_error", "code": "404"}},
        )
    return JSONResponse(obj)


@router.get("/v1/files/{file_id}/content")
async def get_file_content(
    file_id: str,
    request: Request,
    authorization: str | None = Header(default=None),
):
    """Return the raw bytes of an uploaded file."""
    from fastapi.responses import Response
    api_key = await verify_bearer(authorization)
    enforce_rate_limit(api_key, request=request)
    if file_id not in _files:
        return JSONResponse(
            status_code=404,
            content={"error": {"message": f"File '{file_id}' not found", "type": "not_found_error", "code": "404"}},
        )
    content = _file_content.get(file_id, b"")
    filename = _files[file_id].get("filename", "file")
    return Response(
        content=content,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete("/v1/files/{file_id}")
async def delete_file(
    file_id: str,
    request: Request,
    authorization: str | None = Header(default=None),
):
    """Delete a file record and its stored content."""
    api_key = await verify_bearer(authorization)
    enforce_rate_limit(api_key, request=request)
    if file_id not in _files:
        return JSONResponse(
            status_code=404,
            content={"error": {"message": f"File '{file_id}' not found", "type": "not_found_error", "code": "404"}},
        )
    del _files[file_id]
    _file_content.pop(file_id, None)
    log.info("file_deleted", file_id=file_id)
    return JSONResponse({"id": file_id, "object": "file", "deleted": True})
