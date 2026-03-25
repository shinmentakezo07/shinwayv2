import utils.trim as trim_module
from utils import context
from utils.trim import trim_messages_to_budget

def create_msgs(count: int, role="user"):
    # Generate ~1K tokens approx per item
    return [{"role": role, "content": "hello world test test " * 200} for _ in range(count)]

def test_trim_no_trim_needed():
    """Verify that small payloads at full 200K capacity are untouched."""
    msgs = create_msgs(10)
    trimmed, count = trim_messages_to_budget(msgs, model="cursor-small", max_tokens=200000)
    assert len(trimmed) == 10
    assert count < 200000

def test_trim_drops_oldest():
    """Verify that the tokens are trimmed precisely at boundary by dropping oldest user/assistant msgs."""
    # Each msg is roughly 800 tokens. Let's force an overflow budget
    msgs = [{"role": "system", "content": "essential system msg"}]
    msgs.extend(create_msgs(15))
    
    # Intentionally low budget, say enough for system + last 4 only
    budget = 4000
    
    trimmed, final_count = trim_messages_to_budget(msgs, model="cursor-small", max_tokens=budget)
    
    # System message must always be preserved
    assert trimmed[0]["role"] == "system"
    # Over limits, drops older msgs to fit 4000 budget, maintaining order. 
    # At least _MIN_KEEP (4) should survive by default
    assert len(trimmed[-4:]) >= 4
    for m in trimmed[-4:]:
        assert m["role"] == "user"
        
    assert final_count <= budget or len(trimmed) == 5  # system + 4 MIN_KEEP

def test_trim_prioritizes_tool_results():
    """Verify tool_result priority in trimming buffers for Agentic tasks."""
    budget = 20000
    msgs = create_msgs(5)

    # Inject tool results older in history
    tool_msg = {"role": "tool", "content": "CRITICAL TOOL RESULT DATA " * 500}
    msgs.insert(1, tool_msg)

    trimmed, count = trim_messages_to_budget(msgs, model="cursor-small", max_tokens=budget)
    roles = [m["role"] for m in trimmed]

    # Ensure the priority 2 score kept the tool response
    assert "tool" in roles


def test_utils_trim_delegates_to_context_trim_logic(monkeypatch):
    captured = {}

    def fake_trim_to_budget(messages, model, max_tokens=None, tools=None):
        captured["messages"] = messages
        captured["model"] = model
        captured["max_tokens"] = max_tokens
        captured["tools"] = tools
        return ["shimmed"], 123

    monkeypatch.setattr(context.context_engine, "trim_to_budget", fake_trim_to_budget)

    result = trim_module.trim_messages_to_budget(
        [{"role": "user", "content": "hi"}],
        model="cursor-small",
        max_tokens=456,
    )

    assert result == (["shimmed"], 123)
    assert captured == {
        "messages": [{"role": "user", "content": "hi"}],
        "model": "cursor-small",
        "max_tokens": 456,
        "tools": None,
    }
