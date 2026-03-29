"""Converters — multi-modal content block routing.

Routes content blocks by type. Text blocks are extracted as plain text.
Non-text blocks (image_url, image, audio, file, etc.) are replaced with
a neutral placeholder so the model knows content existed but was omitted.

This eliminates the silent data-loss in _extract_text (which just drops
non-text blocks with a warning). Callers that previously called
_extract_text can call extract_text_with_placeholders instead when they
want explicit placeholder insertion rather than silent dropping.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog

log = structlog.get_logger()

UNSUPPORTED_BLOCK_PLACEHOLDER = "[content omitted: unsupported block type]"

_TEXT_BLOCK_TYPES: frozenset[str] = frozenset({"text", "input_text", "output_text"})
_KNOWN_NON_TEXT_TYPES: frozenset[str] = frozenset({
    "image", "image_url", "audio", "file", "document", "video",
    "image_base64", "image_file",
})


@dataclass(frozen=True)
class ContentBlock:
    """Typed representation of a single content block."""

    type: str
    text: str | None = None
    data: Any = None


def extract_text_with_placeholders(content: str | list | None) -> str:
    """Extract text from content, replacing non-text blocks with a placeholder.

    Unlike _extract_text (which silently drops non-text blocks), this function
    inserts UNSUPPORTED_BLOCK_PLACEHOLDER so the model knows something was
    present but could not be processed.

    Args:
        content: A string, list of content blocks, or None.

    Returns:
        Joined text string with placeholders where non-text blocks appeared.
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""

    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        btype = block.get("type", "")
        if btype in _TEXT_BLOCK_TYPES:
            text = block.get("text", "")
            if isinstance(text, str):
                parts.append(text)
        else:
            log.info(
                "content_block_replaced_with_placeholder",
                block_type=btype,
                known_non_text=btype in _KNOWN_NON_TEXT_TYPES,
            )
            parts.append(UNSUPPORTED_BLOCK_PLACEHOLDER)

    return "".join(parts)
