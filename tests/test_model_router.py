"""Tests for routers/model_router.py — resolve_model, model_info, all_models."""
from __future__ import annotations

import json

import pytest

import routers.model_router as mr
from routers.model_router import (
    _CATALOGUE,
    _DEFAULT_META,
    all_models,
    model_info,
    resolve_model,
)


@pytest.fixture(autouse=True)
def reset_alias_map():
    """Reset the module-level alias cache before every test."""
    mr._alias_map = None
    yield
    mr._alias_map = None


# ── resolve_model ────────────────────────────────────────────────────────────

def test_resolve_model_returns_default_when_none():
    """resolve_model(None) returns the first catalogue entry as default."""
    result = resolve_model(None)
    assert result  # non-empty
    assert result == next(iter(_CATALOGUE))


def test_resolve_model_returns_requested_when_no_alias():
    """Unknown model names pass through unchanged."""
    result = resolve_model("some-unknown-model")
    assert result == "some-unknown-model"


def test_resolve_model_uses_alias_map(monkeypatch):
    """When model_map contains an alias, resolve_model returns the mapped value."""
    monkeypatch.setattr("routers.model_router.settings", _settings_with_map('{"gpt-4": "claude-3"}'))
    result = resolve_model("gpt-4")
    assert result == "claude-3"


def test_resolve_model_alias_map_invalid_json_falls_back(monkeypatch):
    """Malformed JSON in model_map is silently ignored — model passes through."""
    monkeypatch.setattr("routers.model_router.settings", _settings_with_map("not-json"))
    result = resolve_model("x")
    assert result == "x"


def test_resolve_model_alias_map_non_dict_falls_back(monkeypatch):
    """Valid JSON that is not an object is silently ignored — model passes through."""
    monkeypatch.setattr("routers.model_router.settings", _settings_with_map("[1, 2, 3]"))
    result = resolve_model("x")
    assert result == "x"


# ── model_info ───────────────────────────────────────────────────────────────

def test_model_info_known_model_returns_metadata():
    """model_info returns catalogue metadata for a known model id."""
    meta = model_info("anthropic/claude-sonnet-4.6")
    assert isinstance(meta, dict)
    assert "context" in meta
    assert meta["context"] > 0


def test_model_info_unknown_model_returns_default():
    """model_info falls back to _DEFAULT_META for unknown model ids."""
    meta = model_info("nonexistent")
    assert isinstance(meta, dict)
    assert "context" in meta
    assert meta == _DEFAULT_META


# ── all_models ───────────────────────────────────────────────────────────────

def test_all_models_returns_list_with_id():
    """all_models() returns a list and every entry has an 'id' key."""
    models = all_models()
    assert isinstance(models, list)
    for entry in models:
        assert "id" in entry


def test_all_models_contains_catalogue_entries():
    """all_models() exposes all catalogue entries — at least 5."""
    models = all_models()
    assert len(models) >= 5
    ids = {m["id"] for m in models}
    assert ids == set(_CATALOGUE.keys())


def test_composer2_in_catalogue():
    """composer-2 is in the catalogue with a 200k context window."""
    assert "composer-2" in _CATALOGUE
    assert _CATALOGUE["composer-2"]["context"] == 200_000


def test_composer2_model_info():
    """model_info returns 200k context for composer-2."""
    meta = model_info("composer-2")
    assert meta["context"] == 200_000


def test_composer2_alias_resolves(monkeypatch):
    """composer and cursor-composer aliases resolve to composer-2."""
    # Default model_map in settings includes these aliases — use the real settings
    for alias in ("composer", "cursor-composer"):
        mr._alias_map = None  # reset between iterations
        result = resolve_model(alias)
        assert result == "composer-2", f"{alias!r} should resolve to 'composer-2', got {result!r}"


# ── helpers ───────────────────────────────────────────────────────────────────

class _settings_with_map:  # noqa: N801 — intentionally lowercase to match SimpleNamespace style
    """Minimal settings stub that exposes only the model_map attribute."""

    def __init__(self, raw: str) -> None:
        self.model_map = raw
