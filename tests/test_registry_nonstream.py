# tests/test_registry_nonstream.py
from __future__ import annotations

from pipeline.params import PipelineParams
from tools.registry import ToolRegistry

_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "Bash",
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
        },
    }
]


def test_registry_field_on_params() -> None:
    reg = ToolRegistry(_TOOL)
    p = PipelineParams(
        api_style="openai",
        model="gpt-4",
        messages=[],
        cursor_messages=[],
        tools=_TOOL,
        registry=reg,
    )
    assert p.registry is reg


def test_registry_none_by_default() -> None:
    p = PipelineParams(
        api_style="openai",
        model="gpt-4",
        messages=[],
        cursor_messages=[],
    )
    assert p.registry is None
