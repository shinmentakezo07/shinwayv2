"""Payload builders for Cursor upstream requests."""

from __future__ import annotations

import uuid

import structlog

from config import settings

log = structlog.get_logger()


def build_payload(
    cursor_messages: list[dict],
    model: str,
    anthropic_tools: list[dict] | None = None,
) -> dict:
    """Build the Cursor API request body."""
    if not model:
        raise ValueError("model must be specified — no fallback allowed")
    log.info("upstream_model", model=model)
    context_path = "/workspace/project" if anthropic_tools else settings.cursor_context_file_path
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
