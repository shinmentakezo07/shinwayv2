"""Parsing helpers for Cursor credential cookies."""

from __future__ import annotations

import base64
import json
import uuid

import structlog

log = structlog.get_logger()


def extract_workos_id(cookie: str) -> str:
    """Extract the WorkOS user ID from a Cursor session cookie."""
    try:
        token_part = ""
        for part in cookie.split(";"):
            stripped = part.strip()
            if stripped.startswith("WorkosCursorSessionToken="):
                token_part = stripped[len("WorkosCursorSessionToken=") :]
                break
        if not token_part:
            return ""

        token_part = token_part.replace("%3A%3A", "::").replace("%3a%3a", "::")
        if "::" not in token_part:
            return ""

        user_id, jwt = token_part.split("::", 1)
        if user_id.startswith("user_"):
            return user_id

        parts = jwt.split(".")
        if len(parts) < 2:
            return ""
        payload = parts[1]
        payload += "=" * (-len(payload) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(payload))
        sub = decoded.get("sub", "")
        if "|" in sub:
            return sub.split("|")[-1]
        return sub
    except Exception:
        log.debug("workos_id_extraction_failed")
        return ""


def stable_uuid(seed: str) -> str:
    """Generate a stable UUID5 from a seed string."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, seed))


def merge_cookie(base: str, extras: list[str]) -> str:
    """Append extra cookie pairs to base, skipping keys already present."""
    existing = {part.split("=")[0].strip() for part in base.split(";")}
    additions = "; ".join(
        item for item in extras if item.split("=")[0].strip() not in existing
    )
    return f"{base}; {additions}" if additions else base


def parse_cookies(raw: str) -> list[str]:
    """Parse one or more credential cookies from env-configured text."""
    if not raw or not raw.strip():
        return []

    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    if len(lines) > 1:
        return lines

    parts = [part.strip() for part in raw.split(",") if part.strip()]
    if len(parts) <= 1:
        return [raw]

    cookie_parts = [part for part in parts if "=" in part]
    if len(cookie_parts) != len(parts):
        return [raw]

    if not all("WorkosCursorSessionToken" in part or "=" in part for part in parts):
        return [raw]

    if any(len(part) > 100 for part in parts):
        return parts
    return [raw]
