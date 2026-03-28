# tests/test_config.py
from config import settings


def test_max_tool_args_bytes_default() -> None:
    assert settings.max_tool_args_bytes == 524288


def test_max_tool_payload_bytes_default() -> None:
    assert settings.max_tool_payload_bytes == 2097152
