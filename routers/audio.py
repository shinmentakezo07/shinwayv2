"""
Shin Proxy — Audio API stubs.

Audio (speech synthesis, transcription, translation) is not supported
by the Cursor upstream. Returns clean 501 responses so clients that
enumerate capabilities don't receive connection errors.
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
            "Audio endpoints are not supported by this proxy. "
            "Use the OpenAI API directly for speech and transcription."
        ),
        "type": "not_implemented_error",
        "code": "audio_not_supported",
    }
}


@router.post("/v1/audio/transcriptions")
async def audio_transcriptions(
    request: Request,
    authorization: str | None = Header(default=None),
):
    """Audio transcription — not supported."""
    await verify_bearer(authorization)
    log.info("audio_transcriptions_stub_called")
    return JSONResponse(status_code=501, content=_NOT_SUPPORTED)


@router.post("/v1/audio/speech")
async def audio_speech(
    request: Request,
    authorization: str | None = Header(default=None),
):
    """Text-to-speech — not supported."""
    await verify_bearer(authorization)
    log.info("audio_speech_stub_called")
    return JSONResponse(status_code=501, content=_NOT_SUPPORTED)


@router.post("/v1/audio/translations")
async def audio_translations(
    request: Request,
    authorization: str | None = Header(default=None),
):
    """Audio translation — not supported."""
    await verify_bearer(authorization)
    return JSONResponse(status_code=501, content=_NOT_SUPPORTED)
