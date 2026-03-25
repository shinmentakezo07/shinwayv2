"""
Tests for CORS middleware wiring in app.py + config.py.

All tests use TestClient against the real create_app() factory.
Settings are overridden via monkeypatch.setattr on the settings singleton
(the established pattern in this codebase — no importlib.reload).
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import config as config_mod
from app import create_app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_client(
    monkeypatch,
    *,
    cors_enabled: bool,
    cors_origins: str = "*",
) -> TestClient:
    """Return a TestClient with CORS settings patched on the settings singleton."""
    monkeypatch.setattr(config_mod.settings, "cors_enabled", cors_enabled)
    monkeypatch.setattr(config_mod.settings, "cors_origins", cors_origins)
    return TestClient(create_app(), raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Config field tests — verify the fields exist with correct defaults
# ---------------------------------------------------------------------------

def test_cors_enabled_defaults_to_false():
    """cors_enabled is False by default."""
    assert config_mod.settings.cors_enabled is False


def test_cors_origins_defaults_to_wildcard():
    """cors_origins defaults to '*'."""
    assert config_mod.settings.cors_origins == "*"


def test_cors_enabled_env_var_sets_true(monkeypatch):
    """monkeypatching cors_enabled to True works."""
    monkeypatch.setattr(config_mod.settings, "cors_enabled", True)
    assert config_mod.settings.cors_enabled is True


def test_cors_origins_env_var_stored_verbatim(monkeypatch):
    """cors_origins stores arbitrary string values unchanged."""
    monkeypatch.setattr(config_mod.settings, "cors_origins", "https://a.com,https://b.com")
    assert config_mod.settings.cors_origins == "https://a.com,https://b.com"


# ---------------------------------------------------------------------------
# CORS disabled (default) — no headers emitted
# ---------------------------------------------------------------------------

def test_cors_disabled_no_allow_origin_header(monkeypatch):
    """When CORS is disabled, Access-Control-Allow-Origin is absent on GET."""
    client = _make_client(monkeypatch, cors_enabled=False)
    r = client.get("/health", headers={"Origin": "https://evil.com"})
    assert "access-control-allow-origin" not in r.headers


def test_cors_disabled_options_not_intercepted(monkeypatch):
    """When CORS is disabled, OPTIONS to /health returns 405 — no CORS middleware handles it."""
    client = _make_client(monkeypatch, cors_enabled=False)
    r = client.options("/health", headers={"Origin": "https://ui.example.com"})
    # Without CORSMiddleware, OPTIONS is not a registered method → 405
    assert r.status_code == 405


# ---------------------------------------------------------------------------
# CORS enabled with wildcard origin
# ---------------------------------------------------------------------------

def test_cors_enabled_wildcard_sets_allow_origin(monkeypatch):
    """When CORS is enabled with '*', Access-Control-Allow-Origin: * is present."""
    client = _make_client(monkeypatch, cors_enabled=True, cors_origins="*")
    r = client.get("/health", headers={"Origin": "https://ui.example.com"})
    assert r.headers.get("access-control-allow-origin") == "*"


def test_cors_enabled_wildcard_preflight_returns_200(monkeypatch):
    """OPTIONS preflight with wildcard returns 200 and correct CORS headers."""
    client = _make_client(monkeypatch, cors_enabled=True, cors_origins="*")
    r = client.options(
        "/v1/chat/completions",
        headers={
            "Origin": "https://ui.example.com",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    assert r.status_code == 200
    assert "access-control-allow-origin" in r.headers
    assert "access-control-allow-methods" in r.headers


# ---------------------------------------------------------------------------
# CORS enabled with explicit single origin
# ---------------------------------------------------------------------------

def test_cors_enabled_single_origin_matching(monkeypatch):
    """Matching origin is reflected in Access-Control-Allow-Origin."""
    client = _make_client(
        monkeypatch,
        cors_enabled=True,
        cors_origins="https://admin.example.com",
    )
    r = client.get("/health", headers={"Origin": "https://admin.example.com"})
    assert r.headers.get("access-control-allow-origin") == "https://admin.example.com"


def test_cors_enabled_single_origin_non_matching(monkeypatch):
    """Non-matching origin does not receive Access-Control-Allow-Origin header."""
    client = _make_client(
        monkeypatch,
        cors_enabled=True,
        cors_origins="https://admin.example.com",
    )
    r = client.get("/health", headers={"Origin": "https://evil.com"})
    # Starlette CORSMiddleware omits the header when origin does not match
    assert r.headers.get("access-control-allow-origin") != "https://evil.com"


# ---------------------------------------------------------------------------
# CORS enabled with multiple comma-separated origins
# ---------------------------------------------------------------------------

def test_cors_multiple_origins_parsed_correctly_first(monkeypatch):
    """First origin in comma-separated list is allowed."""
    client = _make_client(
        monkeypatch,
        cors_enabled=True,
        cors_origins="https://app.example.com,https://admin.example.com",
    )
    r = client.get("/health", headers={"Origin": "https://app.example.com"})
    assert r.headers.get("access-control-allow-origin") == "https://app.example.com"


def test_cors_multiple_origins_parsed_correctly_second(monkeypatch):
    """Second origin in comma-separated list is also allowed."""
    client = _make_client(
        monkeypatch,
        cors_enabled=True,
        cors_origins="https://app.example.com,https://admin.example.com",
    )
    r = client.get("/health", headers={"Origin": "https://admin.example.com"})
    assert r.headers.get("access-control-allow-origin") == "https://admin.example.com"


def test_cors_multiple_origins_excludes_unlisted(monkeypatch):
    """An origin not in the list is not reflected."""
    client = _make_client(
        monkeypatch,
        cors_enabled=True,
        cors_origins="https://app.example.com,https://admin.example.com",
    )
    r = client.get("/health", headers={"Origin": "https://unlisted.example.com"})
    assert r.headers.get("access-control-allow-origin") != "https://unlisted.example.com"


def test_cors_origins_whitespace_trimmed(monkeypatch):
    """Whitespace around comma-separated origins is stripped before passing to middleware."""
    client = _make_client(
        monkeypatch,
        cors_enabled=True,
        cors_origins=" https://app.example.com , https://admin.example.com ",
    )
    r = client.get("/health", headers={"Origin": "https://app.example.com"})
    assert r.headers.get("access-control-allow-origin") == "https://app.example.com"


# ---------------------------------------------------------------------------
# Preflight with explicit origins
# ---------------------------------------------------------------------------

def test_cors_preflight_explicit_origin_returns_200(monkeypatch):
    """Preflight OPTIONS for an allowed explicit origin returns 200."""
    client = _make_client(
        monkeypatch,
        cors_enabled=True,
        cors_origins="https://admin.example.com",
    )
    r = client.options(
        "/v1/messages",
        headers={
            "Origin": "https://admin.example.com",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type,x-api-key",
        },
    )
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == "https://admin.example.com"
