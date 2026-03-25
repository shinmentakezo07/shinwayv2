import json
import pytest
from runtime_config import RuntimeConfig, OverrideError


@pytest.fixture
def cfg(tmp_path):
    return RuntimeConfig(persist_path=tmp_path / "runtime.json")


def test_get_falls_back_to_settings(cfg):
    from config import settings
    assert cfg.get("cache_ttl_seconds") == settings.cache_ttl_seconds


def test_set_and_get_override(cfg):
    cfg.set("cache_ttl_seconds", 999)
    assert cfg.get("cache_ttl_seconds") == 999


def test_reset_removes_override(cfg):
    from config import settings
    cfg.set("cache_ttl_seconds", 999)
    cfg.reset("cache_ttl_seconds")
    assert cfg.get("cache_ttl_seconds") == settings.cache_ttl_seconds


def test_set_unknown_key_raises(cfg):
    with pytest.raises(OverrideError, match="not overridable"):
        cfg.set("nonexistent_key", "value")


def test_set_wrong_type_raises(cfg):
    with pytest.raises(OverrideError, match="expected int"):
        cfg.set("cache_ttl_seconds", "not-an-int")


def test_all_returns_overlay_and_defaults(cfg):
    cfg.set("cache_ttl_seconds", 777)
    snapshot = cfg.all()
    assert snapshot["cache_ttl_seconds"]["value"] == 777
    assert snapshot["cache_ttl_seconds"]["overridden"] is True
    assert snapshot["rate_limit_rps"]["overridden"] is False


def test_persists_to_file(tmp_path):
    path = tmp_path / "runtime.json"
    cfg1 = RuntimeConfig(persist_path=path)
    cfg1.set("cache_ttl_seconds", 1234)
    cfg2 = RuntimeConfig(persist_path=path)
    assert cfg2.get("cache_ttl_seconds") == 1234


def test_corrupt_persist_file_is_ignored(tmp_path):
    path = tmp_path / "runtime.json"
    path.write_text("not json")
    cfg = RuntimeConfig(persist_path=path)
    from config import settings
    assert cfg.get("cache_ttl_seconds") == settings.cache_ttl_seconds
