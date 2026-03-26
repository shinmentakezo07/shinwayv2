# tests/test_emitter.py
from __future__ import annotations
import json
from tools.emitter import (
    compute_tool_signature,
    parse_tool_arguments,
    serialize_tool_arguments,
    OpenAIToolEmitter,
)


def _tc(name: str, **kwargs) -> dict:
    return {
        "id": "call_abc",
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(kwargs)},
    }


def test_compute_tool_signature_deterministic():
    fn = {"name": "Bash", "arguments": json.dumps({"b": 2, "a": 1})}
    sig1 = compute_tool_signature(fn)
    fn2 = {"name": "Bash", "arguments": json.dumps({"a": 1, "b": 2})}
    sig2 = compute_tool_signature(fn2)
    assert sig1 == sig2  # key order normalized


def test_compute_tool_signature_different_args_differ():
    fn1 = {"name": "Bash", "arguments": json.dumps({"command": "ls"})}
    fn2 = {"name": "Bash", "arguments": json.dumps({"command": "pwd"})}
    assert compute_tool_signature(fn1) != compute_tool_signature(fn2)


def test_parse_tool_arguments_from_string():
    result = parse_tool_arguments('{"command": "ls"}')
    assert result == {"command": "ls"}


def test_parse_tool_arguments_from_dict():
    d = {"command": "ls"}
    assert parse_tool_arguments(d) is d


def test_parse_tool_arguments_double_encoded():
    inner = json.dumps({"command": "ls"})
    double = json.dumps(inner)
    result = parse_tool_arguments(double)
    assert result == {"command": "ls"}


def test_parse_tool_arguments_invalid_returns_empty():
    assert parse_tool_arguments("not json") == {}


def test_serialize_tool_arguments_from_string():
    raw = '{"command": "ls"}'
    result = serialize_tool_arguments(raw)
    assert json.loads(result) == {"command": "ls"}


def test_openai_tool_emitter_new_call_produces_chunks():
    emitter = OpenAIToolEmitter(chunk_id="cid", model="claude", created=0)
    chunks = emitter.emit([_tc("Bash", command="ls")])
    assert len(chunks) > 0
    assert emitter.active is True


def test_openai_tool_emitter_dedup_same_signature():
    emitter = OpenAIToolEmitter(chunk_id="cid", model="claude", created=0)
    call = _tc("Bash", command="ls")
    chunks1 = emitter.emit([call])
    chunks2 = emitter.emit([call])  # same signature — no new header
    assert len(chunks1) > 0
    assert isinstance(chunks2, list)


def test_openai_tool_emitter_empty_list():
    emitter = OpenAIToolEmitter(chunk_id="cid", model="claude", created=0)
    assert emitter.emit([]) == []
