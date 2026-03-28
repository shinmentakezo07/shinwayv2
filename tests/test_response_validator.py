# tests/test_response_validator.py
import json
from pipeline.response_validator import validate_openai_response, validate_anthropic_response
from pipeline.params import PipelineParams


def _params(tools=None):
    return PipelineParams(
        api_style="openai", model="m", messages=[], cursor_messages=[],
        tools=tools or [],
    )


def _call(name="Bash", args=None, tc_id="call_abc"):
    return {"id": tc_id, "type": "function",
            "function": {"name": name, "arguments": json.dumps(args or {"command": "ls"})}}


def test_valid_openai_stop_response_no_issues():
    resp = {"id": "c1", "choices": [{"finish_reason": "stop",
            "message": {"role": "assistant", "content": "hello"}}]}
    issues = validate_openai_response(resp, _params())
    assert issues == []


def test_valid_openai_tool_calls_no_issues():
    resp = {"id": "c1", "choices": [{"finish_reason": "tool_calls",
            "message": {"role": "assistant", "content": None,
                         "tool_calls": [_call()]}}]}
    issues = validate_openai_response(resp, _params())
    assert issues == []


def test_wrong_finish_reason_for_tool_calls():
    resp = {"id": "c1", "choices": [{"finish_reason": "stop",
            "message": {"role": "assistant", "content": None,
                         "tool_calls": [_call()]}}]}
    issues = validate_openai_response(resp, _params())
    assert any("finish_reason" in i for i in issues)


def test_arguments_as_dict_flagged():
    bad_call = {"id": "c1", "type": "function",
                "function": {"name": "Bash", "arguments": {"command": "ls"}}}
    resp = {"id": "c2", "choices": [{"finish_reason": "tool_calls",
            "message": {"role": "assistant", "content": None,
                         "tool_calls": [bad_call]}}]}
    issues = validate_openai_response(resp, _params())
    assert any("arguments" in i for i in issues)


def test_the_editor_leak_flagged():
    resp = {"id": "c1", "choices": [{"finish_reason": "stop",
            "message": {"role": "assistant",
                         "content": "the-editor is great"}}]}
    issues = validate_openai_response(resp, _params())
    assert any("the-editor" in i for i in issues)


def test_missing_id_flagged():
    resp = {"choices": [{"finish_reason": "stop",
            "message": {"role": "assistant", "content": "hi"}}]}
    issues = validate_openai_response(resp, _params())
    assert any("id" in i for i in issues)


def test_valid_anthropic_no_issues():
    resp = {"id": "msg_1", "type": "message", "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "hello"}]}
    issues = validate_anthropic_response(resp, _params())
    assert issues == []


def test_anthropic_tool_use_input_not_dict_flagged():
    resp = {"id": "msg_1", "type": "message", "stop_reason": "tool_use",
            "content": [{"type": "tool_use", "id": "tu_1", "name": "Bash",
                          "input": "not a dict"}]}
    issues = validate_anthropic_response(resp, _params())
    assert any("input" in i for i in issues)
