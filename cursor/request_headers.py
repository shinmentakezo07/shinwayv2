"""Static request-header builders for Cursor upstream calls."""

from __future__ import annotations

from config import settings
from cursor.credential_models import CredentialInfo
from cursor.credential_pool import CredentialPool, credential_pool


def build_headers(
    cred: CredentialInfo | None = None,
    pool: CredentialPool | None = None,
) -> dict[str, str]:
    """Build request headers for Cursor's /api/chat endpoint."""
    resolved_pool = pool or credential_pool
    headers: dict[str, str] = {
        "Content-Type": "application/json",
        "Accept": "*/*",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Accept-Language": "en-US,en;q=0.8",
        "User-Agent": settings.user_agent
        or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
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
    headers.update(resolved_pool.build_request_headers(cred))
    return headers
