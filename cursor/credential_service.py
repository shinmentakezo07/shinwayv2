"""Service layer for admin-safe credential operations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from cursor.credential_pool import CredentialPool, credential_pool
from cursor.events import log_validation_result
from cursor.metrics import cursor_metrics
from runtime_config import runtime_config

if TYPE_CHECKING:
    from cursor.client import CursorClient


class CredentialService:
    """Public service wrapper around credential pool operations."""

    def __init__(self, pool: CredentialPool | None = None) -> None:
        self._pool = pool or credential_pool

    def readiness_status(self) -> dict:
        if self._pool.size == 0:
            return {"ready": False, "credentials": 0}
        return {"ready": True, "credentials": self._pool.size}

    def list_status(self) -> dict:
        return {
            "pool_size": self._pool.size,
            "selection_strategy": self._pool.current_selection_strategy(),
            "credentials": self._pool.snapshot(),
        }

    def metrics_status(self) -> dict:
        return {
            "selection_strategy": str(
                runtime_config.get("cursor_selection_strategy") or "round_robin"
            ),
            "pool_size": self._pool.size,
            "metrics": cursor_metrics.snapshot(),
        }

    def reset_all(self) -> dict:
        self._pool.reset_all()
        cursor_metrics.incr("credential_reset_all")
        return {"ok": True, "message": f"Reset {self._pool.size} credentials"}

    async def validate_all(self, client: "CursorClient") -> dict:
        results: list[dict] = []
        for cred in self._pool.list_credentials():
            try:
                data = await client.auth_me(cred)
                cursor_metrics.incr("credential_validation", valid=True)
                log_validation_result(cred.index, True)
                results.append(
                    {
                        "index": cred.index,
                        "credential_id": cred.index,
                        "valid": True,
                        "account": data,
                    }
                )
            except Exception as exc:
                cursor_metrics.incr("credential_validation", valid=False)
                log_validation_result(cred.index, False)
                results.append(
                    {
                        "index": cred.index,
                        "credential_id": cred.index,
                        "valid": False,
                        "error": str(exc),
                    }
                )
        return {"credentials": results}

    def add_cookie(self, cookie: str) -> tuple[bool, dict]:
        normalized = cookie.strip()
        if not normalized or "WorkosCursorSessionToken" not in normalized:
            return False, {"error": "cookie must contain WorkosCursorSessionToken"}
        added = self._pool.add(normalized)
        if not added:
            return False, {"error": "cookie already in pool or pool at maximum (15)"}
        cursor_metrics.incr("credential_added")
        return True, {"ok": True, "added": True, "pool_size": self._pool.size}


credential_service = CredentialService()
