"""Tests for usage reporting router."""
from __future__ import annotations
import os
import pytest
os.environ.setdefault("LITELLM_MASTER_KEY", "sk-test")
os.environ.setdefault("CURSOR_COOKIE", "WorkosCursorSessionToken=test")

import config
import middleware.auth as _auth
from fastapi.testclient import TestClient

_TEST_KEY = "sk-test-usage"


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(config.settings, "master_key", _TEST_KEY)
    _auth._env_keys.cache_clear()
    from app import create_app
    with TestClient(create_app()) as c:
        yield c
    _auth._env_keys.cache_clear()
