"""
Shin Proxy — Per-key sliding window token quota middleware.

Two public functions:
  check_quota(api_key, token_limit_daily)
      Reads 24-hour usage from QuotaStore. Raises RateLimitError when usage
      meets or exceeds token_limit_daily. Called from check_budget before
      the request is dispatched upstream.

  record_quota_usage(api_key, tokens)
      Writes token count to QuotaStore after a response is complete.
      tokens=0 is a silent no-op — no DB write issued.

Both functions are only called when settings.quota_enabled is True and
the key's token_limit_daily > 0. That guard lives in check_budget; these
functions assume the caller has already checked the preconditions.
"""
from __future__ import annotations

import structlog

from handlers import RateLimitError
from storage.quota import quota_store

log = structlog.get_logger()


async def check_quota(api_key: str, token_limit_daily: int) -> None:
    """Raise RateLimitError if this key has reached its 24-hour token quota.

    Does not mutate any state — read-only check.
    Callers must ensure quota_store is initialised before calling this.
    """
    used = await quota_store.get_usage_24h(api_key)
    if used >= token_limit_daily:
        log.warning(
            "quota_exceeded",
            api_key=api_key[:16],
            used=used,
            limit=token_limit_daily,
        )
        raise RateLimitError("Daily token quota reached. Contact the administrator.")
    # Log approach at 80% threshold for observability
    if used >= token_limit_daily * 0.8:
        log.warning(
            "quota_approaching",
            api_key=api_key[:16],
            used=used,
            limit=token_limit_daily,
            pct=round(used / token_limit_daily * 100, 1),
        )


async def record_quota_usage(api_key: str, tokens: int) -> None:
    """Write token usage to the quota store after a response completes.

    tokens=0 is silently ignored — no DB write, no log.
    SQLite failures are caught and logged without propagating — the response
    has already been sent to the client, so a storage failure here must not
    surface as a 500.
    """
    if tokens <= 0:
        return
    try:
        await quota_store.record(api_key, tokens)
    except Exception:
        log.warning("quota_record_failed", api_key=api_key[:16], tokens=tokens, exc_info=True)
