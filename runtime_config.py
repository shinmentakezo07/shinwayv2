"""
Shin Proxy — Runtime configuration overlay.

Provides a thin dict-based overlay over the pydantic `settings` singleton.
Values set via the Admin UI override the startup-loaded .env values and take
effect immediately for all new requests. Overlay is persisted to runtime.json
so overrides survive process restarts.

Usage:
    from runtime_config import runtime_config
    ttl = runtime_config.get("cache_ttl_seconds")  # int
    runtime_config.set("cache_ttl_seconds", 120)
    runtime_config.reset("cache_ttl_seconds")
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

import structlog

from config import settings

log = structlog.get_logger()


class OverrideError(ValueError):
    """Raised when a set() call is invalid (unknown key or wrong type)."""


OVERRIDABLE_KEYS: dict[str, type] = {
    "cache_enabled": bool,
    "cache_ttl_seconds": int,
    "cache_max_entries": int,
    "cache_tool_requests": bool,
    "rate_limit_rps": float,
    "rate_limit_rpm": float,
    "rate_limit_burst": int,
    "rate_limit_rpm_burst": int,
    "retry_attempts": int,
    "retry_backoff_seconds": float,
    "first_token_timeout": float,
    "idle_chunk_timeout": float,
    "stream_heartbeat_s": float,
    "max_context_tokens": int,
    "hard_context_limit": int,
    "context_headroom": int,
    "trim_context": bool,
    "trim_preserve_tool_results": bool,
    "trim_min_keep_messages": int,
    "price_anthropic_per_1k": float,
    "price_openai_per_1k": float,
    "disable_parallel_tools": bool,
    "tool_call_retry_on_miss": bool,
    "budget_usd": float,
    "log_request_bodies": bool,
    "metrics_enabled": bool,
    "cursor_selection_strategy": str,
    "max_tools": int,
    "idem_ttl_seconds": int,
    "idem_max_entries": int,
    "prompt_logging_enabled": bool,
    "prompt_logging_max_response_chars": int,
}

_DEFAULT_PERSIST_PATH = Path("runtime.json")


def _coerce(key: str, value: Any) -> Any:
    """Coerce value to the expected type for key, or raise OverrideError."""
    expected = OVERRIDABLE_KEYS[key]
    if isinstance(value, expected):
        return value
    if expected is float and isinstance(value, int):
        return float(value)
    if expected is bool and isinstance(value, str):
        if value.lower() in ("true", "1", "yes"):
            return True
        if value.lower() in ("false", "0", "no"):
            return False
    if expected is int and isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            pass
    if expected is float and isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            pass
    raise OverrideError(
        f"key '{key}': expected {expected.__name__}, got {type(value).__name__} ({value!r})"
    )


class RuntimeConfig:
    """Thread-safe runtime overlay over the settings singleton."""

    def __init__(self, persist_path: Path | str = _DEFAULT_PERSIST_PATH) -> None:
        self._lock = threading.Lock()
        self._overlay: dict[str, Any] = {}
        self._persist_path = Path(persist_path)
        self._load_persisted()

    def _load_persisted(self) -> None:
        if not self._persist_path.exists():
            return
        try:
            raw = json.loads(self._persist_path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                return
            for k, v in raw.items():
                try:
                    if k in OVERRIDABLE_KEYS:
                        self._overlay[k] = _coerce(k, v)
                except OverrideError:
                    log.warning("runtime_config_skip_bad_persisted_value", key=k, value=v)
        except (json.JSONDecodeError, OSError):
            log.warning("runtime_config_corrupt_persist_file", path=str(self._persist_path))

    def _save_persisted(self) -> None:
        try:
            self._persist_path.write_text(
                json.dumps(self._overlay, indent=2), encoding="utf-8"
            )
        except OSError as exc:
            log.warning("runtime_config_persist_failed", error=str(exc))

    def get(self, key: str) -> Any:
        with self._lock:
            if key in self._overlay:
                return self._overlay[key]
        return getattr(settings, key)

    def set(self, key: str, value: Any) -> Any:
        if key not in OVERRIDABLE_KEYS:
            raise OverrideError(f"'{key}' is not overridable at runtime")
        coerced = _coerce(key, value)
        with self._lock:
            self._overlay[key] = coerced
            self._save_persisted()
        log.info("runtime_config_set", key=key, value=coerced)
        return coerced

    def reset(self, key: str) -> None:
        with self._lock:
            self._overlay.pop(key, None)
            self._save_persisted()
        log.info("runtime_config_reset", key=key)

    def all(self) -> dict[str, dict]:
        with self._lock:
            overlay = dict(self._overlay)
        result: dict[str, dict] = {}
        for key, typ in OVERRIDABLE_KEYS.items():
            overridden = key in overlay
            result[key] = {
                "value": overlay[key] if overridden else getattr(settings, key),
                "default": getattr(settings, key),
                "type": typ.__name__,
                "overridden": overridden,
            }
        return result


runtime_config = RuntimeConfig()
