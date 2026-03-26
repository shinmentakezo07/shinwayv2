from __future__ import annotations
import pytest
from tools.registry import ToolRegistry


def _tool(name: str, **props) -> dict:
    properties = {k: {"type": t} for k, t in props.items()}
    return {
        "type": "function",
        "function": {
            "name": name,
            "parameters": {"type": "object", "properties": properties},
        },
    }


def test_canonical_name_exact():
    reg = ToolRegistry([_tool("Bash", command="string")])
    assert reg.canonical_name("Bash") == "Bash"


def test_canonical_name_fuzzy():
    reg = ToolRegistry([_tool("Bash", command="string")])
    assert reg.canonical_name("bash") == "Bash"


def test_canonical_name_unknown():
    reg = ToolRegistry([_tool("Bash", command="string")])
    assert reg.canonical_name("unknown_xyz") is None


def test_known_params():
    reg = ToolRegistry([_tool("Bash", command="string")])
    assert reg.known_params("Bash") == {"command"}


def test_known_params_unknown_tool():
    reg = ToolRegistry([_tool("Bash", command="string")])
    assert reg.known_params("NoSuch") == set()


def test_schema_returns_params_dict():
    reg = ToolRegistry([_tool("Bash", command="string")])
    schema = reg.schema("Bash")
    assert schema is not None
    assert "properties" in schema


def test_schema_unknown_tool():
    reg = ToolRegistry([_tool("Bash", command="string")])
    assert reg.schema("NoSuch") is None


def test_backend_tools_at_construction():
    reg = ToolRegistry(
        [_tool("Bash", command="string")],
        backend_tools={"read_file": {"filePath"}},
    )
    assert reg.canonical_name("read_file") == "read_file"
    assert reg.known_params("read_file") == {"filePath"}


def test_allowed_exact_returns_dict():
    reg = ToolRegistry([_tool("Bash", command="string")])
    ae = reg.allowed_exact()
    assert isinstance(ae, dict)
    assert "bash" in ae or "Bash" in ae.values()


def test_schema_map_returns_dict():
    reg = ToolRegistry([_tool("Bash", command="string")])
    sm = reg.schema_map()
    assert isinstance(sm, dict)
    assert "Bash" in sm


def test_registry_is_immutable_after_construction():
    tools = [_tool("Bash", command="string")]
    reg = ToolRegistry(tools)
    tools.append(_tool("Write", file_path="string"))
    assert reg.canonical_name("Write") is None
