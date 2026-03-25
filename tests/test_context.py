from config import settings
from utils.context import context_engine


def test_context_budget_estimates_tool_schema_tokens_once(monkeypatch):
    calls = {"count": 0}

    def fake_estimate(tools, model):
        calls["count"] += 1
        return 10

    monkeypatch.setattr("utils.context.count_message_tokens", lambda messages, model: 5)
    monkeypatch.setattr(context_engine, "estimate_tool_schema_tokens", fake_estimate)

    result = context_engine.check_preflight(
        [{"role": "user", "content": "hi"}],
        [{"type": "function", "function": {"name": "x"}}],
        "cursor-small",
        [],
    )

    assert result.token_count == 15
    assert calls["count"] == 1


def test_trim_to_budget_keeps_tool_call_result_pairs_together(monkeypatch):
    monkeypatch.setattr(
        "utils.context.count_message_tokens",
        lambda messages, model: len(messages),
    )

    messages = [
        {"role": "user", "content": "older context"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "function": {"name": "lookup", "arguments": "{}"},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "ok"},
        {"role": "user", "content": "recent 1"},
        {"role": "assistant", "content": "recent 2"},
        {"role": "user", "content": "recent 3"},
        {"role": "assistant", "content": "recent 4"},
    ]

    trimmed, _tokens = context_engine.trim_to_budget(
        messages,
        "cursor-small",
        max_tokens=5,
        tools=[],
    )

    trimmed_tool_result_ids = {
        m.get("tool_call_id")
        for m in trimmed
        if isinstance(m, dict) and m.get("role") == "tool"
    }
    assistant_tool_call_ids = {
        tool_call.get("id")
        for m in trimmed
        if isinstance(m, dict)
        for tool_call in (m.get("tool_calls") or [])
        if isinstance(tool_call, dict)
    }

    assert trimmed_tool_result_ids == assistant_tool_call_ids
    assert trimmed_tool_result_ids in (set(), {"call_1"})


def test_trim_to_budget_drops_expanded_recent_tool_pair_when_pair_exceeds_budget(monkeypatch):
    monkeypatch.setattr(
        "utils.context.count_message_tokens",
        lambda messages, model: len(messages),
    )

    messages = [
        {"role": "user", "content": "older context"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "function": {"name": "lookup", "arguments": "{}"},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "ok"},
        {"role": "user", "content": "recent 1"},
        {"role": "assistant", "content": "recent 2"},
        {"role": "user", "content": "recent 3"},
    ]

    trimmed, token_count = context_engine.trim_to_budget(
        messages,
        "cursor-small",
        max_tokens=4,
        tools=[],
    )

    trimmed_tool_result_ids = {
        m.get("tool_call_id")
        for m in trimmed
        if isinstance(m, dict) and m.get("role") == "tool"
    }
    assistant_tool_call_ids = {
        tool_call.get("id")
        for m in trimmed
        if isinstance(m, dict)
        for tool_call in (m.get("tool_calls") or [])
        if isinstance(tool_call, dict)
    }

    assert token_count <= 4
    assert trimmed_tool_result_ids == assistant_tool_call_ids == set()


def test_minimum_keep_value_comes_from_single_source_of_truth():
    from utils import context, trim

    assert context.MIN_KEEP == settings.trim_min_keep_messages
    assert trim.MIN_KEEP == settings.trim_min_keep_messages
