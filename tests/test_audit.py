"""Tests for tools/audit.py — ToolCallAudit ring buffer."""
from __future__ import annotations

import json
from tools.audit import ToolCallAudit


def _call(name: str, args: dict | None = None) -> dict:
    return {
        "id": f"c_{name}",
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args or {})},
    }


def test_record_and_recent() -> None:
    buf = ToolCallAudit(maxsize=10)
    buf.record([_call("Bash", {"command": "ls"})], raw="[assistant_tool_calls]\n{}", outcome="success")
    entries = buf.recent()
    assert len(entries) == 1
    assert entries[0]["calls"][0]["function"]["name"] == "Bash"
    assert entries[0]["outcome"] == "success"
    assert entries[0]["call_count"] == 1


def test_ring_evicts_oldest() -> None:
    buf = ToolCallAudit(maxsize=3)
    for i in range(5):
        buf.record([_call(f"Tool{i}")], raw="x", outcome="success")
    entries = buf.recent()
    assert len(entries) == 3
    names = [e["calls"][0]["function"]["name"] for e in entries]
    assert "Tool0" not in names
    assert "Tool4" in names


def test_recent_limit() -> None:
    buf = ToolCallAudit(maxsize=20)
    for i in range(15):
        buf.record([_call(f"T{i}")], raw="x", outcome="success")
    assert len(buf.recent(limit=5)) == 5


def test_empty_buffer() -> None:
    buf = ToolCallAudit(maxsize=10)
    assert buf.recent() == []


def test_deepcopy_prevents_mutation() -> None:
    buf = ToolCallAudit(maxsize=10)
    call = _call("Bash", {"command": "ls"})
    buf.record([call], raw="x", outcome="success")
    call["function"]["name"] = "MUTATED"
    entries = buf.recent()
    assert entries[0]["calls"][0]["function"]["name"] == "Bash"


def test_raw_snippet_capped_at_500() -> None:
    buf = ToolCallAudit(maxsize=10)
    buf.record([], raw="x" * 1000, outcome="success")
    assert len(buf.recent()[0]["raw_snippet"]) == 500
