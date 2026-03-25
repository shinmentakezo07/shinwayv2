# tests/test_from_cursor_openai.py
from __future__ import annotations
import json


def test_now_ts_is_int():
    from converters.from_cursor_openai import now_ts
    assert isinstance(now_ts(), int)


def test_openai_sse_format():
    from converters.from_cursor_openai import openai_sse
    result = openai_sse({"foo": "bar"})
    assert result.startswith("data: ")
    assert result.endswith("\n\n")
    assert json.loads(result[6:]) == {"foo": "bar"}


def test_openai_done():
    from converters.from_cursor_openai import openai_done
    assert openai_done() == "data: [DONE]\n\n"


def test_openai_chunk_shape():
    from converters.from_cursor_openai import openai_chunk
    chunk = openai_chunk("cid", "model", delta={"content": "hi"})
    assert chunk["object"] == "chat.completion.chunk"
    assert chunk["choices"][0]["delta"] == {"content": "hi"}


def test_openai_non_streaming_response_shape():
    from converters.from_cursor_openai import openai_non_streaming_response
    msg = {"role": "assistant", "content": "hello"}
    resp = openai_non_streaming_response("cid", "the-editor-small", msg)
    assert resp["object"] == "chat.completion"
    assert resp["choices"][0]["message"] == msg
    assert "usage" in resp


def test_openai_usage_chunk_shape():
    from converters.from_cursor_openai import openai_usage_chunk
    result = openai_usage_chunk("cid", "the-editor-small", 100, 50)
    data = json.loads(result[6:])
    assert data["usage"]["prompt_tokens"] == 100
    assert data["usage"]["completion_tokens"] == 50
