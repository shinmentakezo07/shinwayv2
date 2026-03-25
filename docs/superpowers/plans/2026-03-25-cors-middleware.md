# CORS Middleware Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add configurable CORS support to Shinway so browser-based clients (web UIs, admin dashboards) can hit the proxy directly without being blocked by same-origin policy. When `SHINWAY_CORS_ENABLED=true`, Starlette's built-in `CORSMiddleware` is registered with allowed origins parsed from `SHINWAY_CORS_ORIGINS`. When disabled (the default), no CORS headers are emitted and no `OPTIONS` routes are registered — zero overhead for the common headless/server-to-server case.

**Architecture:** `CORSMiddleware` from `starlette.middleware.cors` (already available as a transitive dependency of FastAPI — zero new installs) is added in `app.py` alongside `GZipMiddleware`. Two new fields are added to `config.py` following the existing `Field(default=..., alias="SHINWAY_...")` pattern. `cors_origins` is a raw comma-separated string in config; the `[str]` list required by `CORSMiddleware` is produced with a one-liner at wire-up time in `app.py`. No separate `middleware/cors.py` file is needed — the wiring is four lines, consistent with how `GZipMiddleware` is handled.

**Tech Stack:** Python 3.12, FastAPI, Starlette (`starlette.middleware.cors.CORSMiddleware`), pydantic-settings. No new dependencies.

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `config.py` | MODIFY | Add `cors_enabled: bool` and `cors_origins: str` fields |
| `app.py` | MODIFY | Register `CORSMiddleware` when `settings.cors_enabled` is `True` |
| `tests/test_cors.py` | CREATE | Unit + integration-style tests covering enabled/disabled/preflight/multi-origin |

---

## Chunk 1: Tests (RED)

### Task 1: Write failing tests for CORS middleware

**Files:**
- Create: `tests/test_cors.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_cors.py
"""
Tests for CORS middleware wiring in app.py + config.py.

All tests use TestClient against the real create_app() factory with env-var
overrides via monkeypatch so they exercise the full middleware stack.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_client(monkeypatch, *, cors_enabled: str, cors_origins: str = "*") -> TestClient:
    """Return a TestClient with CORS settings overridden via env vars."""
    monkeypatch.setenv("SHINWAY_CORS_ENABLED", cors_enabled)
    monkeypatch.setenv("SHINWAY_CORS_ORIGINS", cors_origins)
    # Re-import settings and app after env override so pydantic-settings picks up new values
    import importlib
    import config as config_mod
    importlib.reload(config_mod)
    import app as app_mod
    importlib.reload(app_mod)
    application = app_mod.create_app()
    return TestClient(application, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Config field tests — no app needed
# ---------------------------------------------------------------------------

def test_cors_enabled_defaults_to_false():
    """cors_enabled is False when SHINWAY_CORS_ENABLED is not set."""
    import importlib
    import config as config_mod
    importlib.reload(config_mod)
    assert config_mod.settings.cors_enabled is False


def test_cors_origins_defaults_to_wildcard():
    """cors_origins defaults to '*' when SHINWAY_CORS_ORIGINS is not set."""
    import importlib
    import config as config_mod
    importlib.reload(config_mod)
    assert config_mod.settings.cors_origins == "*"


def test_cors_enabled_env_var_sets_true(monkeypatch):
    """SHINWAY_CORS_ENABLED=true sets cors_enabled to True."""
    monkeypatch.setenv("SHINWAY_CORS_ENABLED", "true")
    import importlib
    import config as config_mod
    importlib.reload(config_mod)
    assert config_mod.settings.cors_enabled is True


def test_cors_origins_env_var_stored_verbatim(monkeypatch):
    """SHINWAY_CORS_ORIGINS is stored as-is (parsing happens in app.py)."""
    monkeypatch.setenv("SHINWAY_CORS_ORIGINS", "https://a.com,https://b.com")
    import importlib
    import config as config_mod
    importlib.reload(config_mod)
    assert config_mod.settings.cors_origins == "https://a.com,https://b.com"


# ---------------------------------------------------------------------------
# CORS disabled (default) — no headers emitted
# ---------------------------------------------------------------------------

def test_cors_disabled_no_allow_origin_header(monkeypatch):
    """When CORS is disabled, Access-Control-Allow-Origin is absent on GET."""
    client = _make_client(monkeypatch, cors_enabled="false")
    r = client.get("/health", headers={"Origin": "https://evil.com"})
    assert "access-control-allow-origin" not in r.headers


def test_cors_disabled_options_not_intercepted(monkeypatch):
    """When CORS is disabled, OPTIONS to /health returns 405 (not handled by CORS middleware)."""
    client = _make_client(monkeypatch, cors_enabled="false")
    r = client.options("/health", headers={"Origin": "https://ui.example.com"})
    # Without CORSMiddleware, OPTIONS is not a registered method → 405
    assert r.status_code == 405


# ---------------------------------------------------------------------------
# CORS enabled with wildcard origin
# ---------------------------------------------------------------------------

def test_cors_enabled_wildcard_sets_allow_origin(monkeypatch):
    """When CORS is enabled with '*', Access-Control-Allow-Origin: * is present."""
    client = _make_client(monkeypatch, cors_enabled="true", cors_origins="*")
    r = client.get("/health", headers={"Origin": "https://ui.example.com"})
    assert r.headers.get("access-control-allow-origin") == "*"


def test_cors_enabled_wildcard_preflight_returns_200(monkeypatch):
    """OPTIONS preflight with wildcard returns 200 and correct CORS headers."""
    client = _make_client(monkeypatch, cors_enabled="true", cors_origins="*")
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
        cors_enabled="true",
        cors_origins="https://admin.example.com",
    )
    r = client.get(
        "/health",
        headers={"Origin": "https://admin.example.com"},
    )
    assert r.headers.get("access-control-allow-origin") == "https://admin.example.com"


def test_cors_enabled_single_origin_non_matching(monkeypatch):
    """Non-matching origin does not receive Access-Control-Allow-Origin header."""
    client = _make_client(
        monkeypatch,
        cors_enabled="true",
        cors_origins="https://admin.example.com",
    )
    r = client.get(
        "/health",
        headers={"Origin": "https://evil.com"},
    )
    # Starlette CORSMiddleware omits the header when origin does not match
    assert r.headers.get("access-control-allow-origin") != "https://evil.com"


# ---------------------------------------------------------------------------
# CORS enabled with multiple comma-separated origins
# ---------------------------------------------------------------------------

def test_cors_multiple_origins_parsed_correctly_first(monkeypatch):
    """First origin in comma-separated list is allowed."""
    client = _make_client(
        monkeypatch,
        cors_enabled="true",
        cors_origins="https://app.example.com,https://admin.example.com",
    )
    r = client.get(
        "/health",
        headers={"Origin": "https://app.example.com"},
    )
    assert r.headers.get("access-control-allow-origin") == "https://app.example.com"


def test_cors_multiple_origins_parsed_correctly_second(monkeypatch):
    """Second origin in comma-separated list is also allowed."""
    client = _make_client(
        monkeypatch,
        cors_enabled="true",
        cors_origins="https://app.example.com,https://admin.example.com",
    )
    r = client.get(
        "/health",
        headers={"Origin": "https://admin.example.com"},
    )
    assert r.headers.get("access-control-allow-origin") == "https://admin.example.com"


def test_cors_multiple_origins_excludes_unlisted(monkeypatch):
    """An origin not in the list is not reflected."""
    client = _make_client(
        monkeypatch,
        cors_enabled="true",
        cors_origins="https://app.example.com,https://admin.example.com",
    )
    r = client.get(
        "/health",
        headers={"Origin": "https://unlisted.example.com"},
    )
    assert r.headers.get("access-control-allow-origin") != "https://unlisted.example.com"


def test_cors_origins_whitespace_trimmed(monkeypatch):
    """Whitespace around comma-separated origins is stripped before passing to middleware."""
    client = _make_client(
        monkeypatch,
        cors_enabled="true",
        cors_origins=" https://app.example.com , https://admin.example.com ",
    )
    r = client.get(
        "/health",
        headers={"Origin": "https://app.example.com"},
    )
    assert r.headers.get("access-control-allow-origin") == "https://app.example.com"


# ---------------------------------------------------------------------------
# Preflight with explicit origins
# ---------------------------------------------------------------------------

def test_cors_preflight_explicit_origin_returns_200(monkeypatch):
    """Preflight OPTIONS for an allowed explicit origin returns 200."""
    client = _make_client(
        monkeypatch,
        cors_enabled="true",
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
```

- [ ] **Step 2: Run tests — expect ImportError or collection failure**

```bash
cd /teamspace/studios/this_studio/dikders
pytest tests/test_cors.py -v 2>&1 | tail -15
```

Expected: all tests fail — `cors_enabled` and `cors_origins` attributes do not exist on `settings` yet, and `CORSMiddleware` is not registered in `app.py`.

---

## Chunk 2: Config fields (GREEN — config layer)

### Task 2: Add `cors_enabled` and `cors_origins` to `config.py`

**Files:**
- Modify: `config.py`

- [ ] **Step 1: Add CORS fields to `config.py`**

In `config.py`, find the `# ── Prometheus metrics` section (the last block before `settings = Settings()`). Insert a new `# ── CORS` block immediately before it:

```python
    # ── CORS ─────────────────────────────────────────────────────────────────
    # Disabled by default — server-to-server usage needs no CORS headers.
    # Enable for browser clients (admin UIs, web playgrounds).
    cors_enabled: bool = Field(default=False, alias="SHINWAY_CORS_ENABLED")
    # Comma-separated allowed origins. Use "*" to allow all origins.
    # Example: "https://admin.example.com,https://app.example.com"
    cors_origins: str = Field(default="*", alias="SHINWAY_CORS_ORIGINS")
```

- [ ] **Step 2: Verify config loads with correct defaults**

```bash
cd /teamspace/studios/this_studio/dikders
python -c "
import importlib, config as m
importlib.reload(m)
print('cors_enabled:', m.settings.cors_enabled)
print('cors_origins:', m.settings.cors_origins)
assert m.settings.cors_enabled is False
assert m.settings.cors_origins == '*'
print('OK')
"
```

Expected output:
```
cors_enabled: False
cors_origins: *
OK
```

- [ ] **Step 3: Verify env var override works**

```bash
SHINWAY_CORS_ENABLED=true SHINWAY_CORS_ORIGINS="https://a.com,https://b.com" python -c "
import importlib, config as m
importlib.reload(m)
assert m.settings.cors_enabled is True
assert m.settings.cors_origins == 'https://a.com,https://b.com'
print('env override OK')
"
```

Expected: `env override OK`

- [ ] **Step 4: Run full test suite — config tests pass, CORS app tests still fail**

```bash
pytest tests/ --ignore=tests/integration -q 2>&1 | tail -10
```

Expected: existing suite passes; `test_cors.py` config-only tests (`test_cors_enabled_defaults_to_false`, `test_cors_origins_defaults_to_wildcard`, `test_cors_enabled_env_var_sets_true`, `test_cors_origins_env_var_stored_verbatim`) now PASS; middleware behaviour tests still FAIL.

- [ ] **Step 5: Commit config change**

```bash
cd /teamspace/studios/this_studio/dikders
git add config.py
git commit -m "feat(config): add SHINWAY_CORS_ENABLED and SHINWAY_CORS_ORIGINS settings"
```

---

## Chunk 3: App wiring (GREEN — middleware layer)

### Task 3: Register `CORSMiddleware` in `app.py`

**Files:**
- Modify: `app.py`

- [ ] **Step 1: Add the import and conditional middleware registration**

In `app.py`, locate the existing GZip middleware line:

```python
    # ── Middleware: gzip compression for non-streaming responses ────────
    app.add_middleware(GZipMiddleware, minimum_size=1000)
```

Replace it with:

```python
    # ── Middleware: gzip compression for non-streaming responses ────────
    app.add_middleware(GZipMiddleware, minimum_size=1000)

    # ── Middleware: CORS — only registered when explicitly enabled ───────
    # Disabled by default: server-to-server clients need no CORS headers,
    # and registering CORSMiddleware unconditionally adds latency + header
    # noise to every response. Enable via SHINWAY_CORS_ENABLED=true.
    if settings.cors_enabled:
        from starlette.middleware.cors import CORSMiddleware

        allowed_origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
        app.add_middleware(
            CORSMiddleware,
            allow_origins=allowed_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        log.info("cors_enabled", origins=allowed_origins)
```

Note: the import is intentionally deferred inside the `if` block so the import cost is zero when CORS is disabled.

- [ ] **Step 2: Verify the app imports cleanly with CORS disabled**

```bash
cd /teamspace/studios/this_studio/dikders
python -c "
import importlib, config as cfg_mod
importlib.reload(cfg_mod)
import app as app_mod
importlib.reload(app_mod)
app = app_mod.create_app()
print('routes:', len(app.routes))
print('middleware disabled OK')
"
```

Expected: prints route count, no error, no CORS middleware registered.

- [ ] **Step 3: Verify the app registers CORS middleware when enabled**

```bash
SHINWAY_CORS_ENABLED=true python -c "
import importlib, config as cfg_mod
importlib.reload(cfg_mod)
import app as app_mod
importlib.reload(app_mod)
a = app_mod.create_app()
from starlette.middleware.cors import CORSMiddleware
mw_types = [type(m.cls) if hasattr(m, 'cls') else type(m) for m in a.user_middleware]
print('middleware stack:', [t.__name__ for t in mw_types])
assert any('CORS' in t.__name__ for t in mw_types), 'CORSMiddleware not found'
print('CORS registration OK')
"
```

Expected: `CORS registration OK`

- [ ] **Step 4: Run all CORS tests — expect full PASS**

```bash
cd /teamspace/studios/this_studio/dikders
pytest tests/test_cors.py -v 2>&1 | tail -30
```

Expected: all 15 tests PASS.

- [ ] **Step 5: Run full suite — no regressions**

```bash
pytest tests/ --ignore=tests/integration -q 2>&1 | tail -10
```

Expected: existing count + 15 new tests, all PASS.

- [ ] **Step 6: Commit app wiring**

```bash
cd /teamspace/studios/this_studio/dikders
git add app.py
git commit -m "feat(app): register CORSMiddleware when SHINWAY_CORS_ENABLED=true"
```

---

## Chunk 4: Final validation

### Task 4: Smoke test + UPDATES.md

**Files:** none new

- [ ] **Step 1: Import smoke test — both code paths**

```bash
cd /teamspace/studios/this_studio/dikders
python -c "
import importlib

# --- disabled path ---
import config as cfg_mod
importlib.reload(cfg_mod)
assert cfg_mod.settings.cors_enabled is False
assert cfg_mod.settings.cors_origins == '*'
print('disabled defaults: OK')

import app as app_mod
importlib.reload(app_mod)
a = app_mod.create_app()
mw_names = [getattr(m, 'cls', type(m)).__name__ for m in a.user_middleware]
assert 'CORSMiddleware' not in mw_names, f'CORSMiddleware should not be present: {mw_names}'
print('middleware absent when disabled: OK')
print('ALL OK')
"
```

Expected: `ALL OK`

- [ ] **Step 2: Full unit test run with coverage check**

```bash
cd /teamspace/studios/this_studio/dikders
pytest tests/ --ignore=tests/integration -q 2>&1 | tail -5
```

Expected: all existing tests + 15 new CORS tests PASS, 0 failures.

- [ ] **Step 3: Update UPDATES.md**

Add a new session entry at the bottom of `UPDATES.md` documenting:
- `config.py` — added `cors_enabled` / `SHINWAY_CORS_ENABLED` and `cors_origins` / `SHINWAY_CORS_ORIGINS` fields in the new `# ── CORS` block
- `app.py` — added conditional `CORSMiddleware` registration block after `GZipMiddleware`; imports `starlette.middleware.cors.CORSMiddleware` (already available, zero new deps); parses comma-separated origins list with strip
- `tests/test_cors.py` — created with 15 tests covering: config defaults, env var overrides, CORS disabled (no header, OPTIONS 405), wildcard enabled (header present, preflight 200), single explicit origin (match / non-match), multiple origins parsed correctly (first, second, unlisted excluded), whitespace trimming, preflight with explicit origin

- [ ] **Step 4: Commit and push**

```bash
cd /teamspace/studios/this_studio/dikders
git add UPDATES.md
git commit -m "docs: update UPDATES.md for CORS middleware session"
git push
```

---

## Summary

| Task | File | What changes |
|---|---|---|
| 1 | `tests/test_cors.py` | 15 tests — config defaults, disabled behaviour, wildcard, single origin, multi-origin, whitespace trim, preflight |
| 2 | `config.py` | `cors_enabled: bool` (default `False`) + `cors_origins: str` (default `"*"`) in new `# ── CORS` block |
| 3 | `app.py` | Conditional `CORSMiddleware` registration after `GZipMiddleware`; comma-split + strip origins |
| 4 | `UPDATES.md` | Session entry, commit, push |

**Env vars added:**

| Var | Type | Default | Description |
|---|---|---|---|
| `SHINWAY_CORS_ENABLED` | bool | `false` | Set `true` to enable CORS headers for browser clients |
| `SHINWAY_CORS_ORIGINS` | str | `*` | Comma-separated allowed origins. `*` = all origins |

**Zero new dependencies. Zero overhead when disabled. Preflight handled automatically by Starlette.**