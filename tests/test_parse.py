from tools.parse import _lenient_json_loads, parse_tool_calls_from_text

# Removed buggy structlog config

def test_lenient_json_loads_strict():
    """Test strict JSON parsing."""
    raw = '{"key": "value"}'
    assert _lenient_json_loads(raw) == {"key": "value"}

def test_lenient_json_loads_repair_control_chars():
    """Test JSON parsing with literal newlines and unescaped quotes."""
    # Literal newline inside the string
    raw = '{"key": "line1\nline2"}'
    assert _lenient_json_loads(raw) == {"key": "line1\nline2"}

def test_lenient_json_loads_regex_extract():
    """Test regex extraction for unescaped content inside arguments."""
    # Invalid JSON because of unescaped quotes inside value string
    raw = '{"tool_calls": [{"name": "attempt_completion", "arguments": {"result": "Here is some "code" that breaks json"}}]}'
    res = _lenient_json_loads(raw)
    assert res is not None
    assert "tool_calls" in res
    assert len(res["tool_calls"]) == 1
    assert res["tool_calls"][0]["name"] == "attempt_completion"
    # It should have escaped the inner quotes or extracted literal string value successfully
    assert res["tool_calls"][0]["arguments"]["result"] == 'Here is some "code" that breaks json'

def test_extract_truncated_args_fallback():
    """Test parsing truncated JSON responses (simulating cut-off tool output mid-chunk)."""
    raw = '{"tool_calls": [{"name": "write_to_file", "arguments": {"content": "This is a very long string that suddenly gets cut off...'
    res = _lenient_json_loads(raw)
    assert res is not None
    assert res["tool_calls"][0]["name"] == "write_to_file"
    assert res["tool_calls"][0]["arguments"]["content"] == "This is a very long string that suddenly gets cut off..."

def test_parse_tool_calls_from_text_large_payload():
    """Test parsing a comprehensive block representing an attempt_completion on a 200K+ token limit stream."""
    # Create massive pseudo-generated text body
    huge_result = "A" * 150000
    text = f'[assistant_tool_calls]\n{{"tool_calls": [{{"name": "attempt_completion", "arguments": {{"result": "{huge_result}"}}}}]}}'

    tools = [{
        "type": "function",
        "function": {
            "name": "attempt_completion",
            "parameters": {
                "type": "object",
                "properties": {"result": {"type": "string"}},
                "required": ["result"]
            }
        }
    }]

    parsed = parse_tool_calls_from_text(text, tools, streaming=False)
    assert parsed is not None
    assert len(parsed) == 1
    assert parsed[0]["function"]["name"] == "attempt_completion"

    # Assert fidelity mapping of massive payload
    arguments = parsed[0]["function"]["arguments"]
    assert len(huge_result) <= len(arguments)  # Appropriate bounds match checks payload survived
    assert '"result":"A' in arguments.replace(' ', '')


def test_write_with_literal_newlines_and_unescaped_quotes_in_content():
    """Write tool call with literal newlines and unescaped quotes in content:
    file_path must be exactly the path, content must be non-empty.

    Regression test for Strategy 3 last-resort kv extraction: the backward scan
    was folding the content field into the file_path value when content contained
    unescaped double-quotes. Fixed with forward scanning for multi-field args.
    """
    import json
    content = '# Plan\n\nCode:\n\n```python\ndef foo():\n    return "bar"\n```\n'
    raw = (
        '{"name": "Write", "arguments": {'
        '"file_path": "/workspace/project/PLAN.md", '
        '"content": "' + content + '"}}'
    )
    payload = '{"tool_calls": [' + raw + ']}'
    text = '[assistant_tool_calls]\n' + payload
    tools = [{
        'function': {
            'name': 'Write',
            'description': 'Writes a file.',
            'parameters': {
                'type': 'object',
                'properties': {
                    'file_path': {'type': 'string'},
                    'content': {'type': 'string'},
                },
                'required': ['file_path', 'content'],
            },
        }
    }]
    result = parse_tool_calls_from_text(text, tools)
    assert result is not None
    args = json.loads(result[0]['function']['arguments'])
    assert args['file_path'] == '/workspace/project/PLAN.md', (
        f'file_path corrupted: {args["file_path"]!r}'
    )
    assert len(args.get('content', '')) > 0, 'content should not be empty'


# ── False-positive marker detection regression ──────────────────────────────

def test_find_marker_pos_matches_reinforcer_echoed_at_line_start():
    """RED: if the model echoes the reinforcer verbatim at line-start, the marker fires.

    This test documents the CURRENT vulnerable behaviour — the reinforcer string
    starts with 'For reference:' so the marker is NOT at line-start.
    After Option A rephrasing, the marker must remain mid-sentence and this
    scenario must return -1.
    """
    from tools.parse import _find_marker_pos
    # Simulate model echoing the NEW (safe) reinforcer text at line-start of response
    # After Option A fix, the new text starts with 'For reference:' not '[assistant'
    new_reinforcer = (
        "For reference: tools must be invoked using the [assistant_tool_calls] "
        "JSON format described in the session configuration."
    )
    pos = _find_marker_pos(new_reinforcer)
    assert pos == -1, (
        f"New reinforcer text should not trigger marker detection, got pos={pos}"
    )


def test_find_marker_pos_does_not_match_mid_sentence_marker():
    """[assistant_tool_calls] mid-sentence (not at line-start) must NOT be matched."""
    from tools.parse import _find_marker_pos
    # This is the reinforcer message text injected as a Cursor user-turn
    text = (
        "For reference: tools must be invoked using the [assistant_tool_calls] "
        "JSON format described in the session configuration."
    )
    pos = _find_marker_pos(text)
    assert pos == -1, (
        f"Mid-sentence marker was incorrectly matched at pos {pos}."
    )


def test_find_marker_pos_does_not_match_marker_after_words_on_same_line():
    """[assistant_tool_calls] preceded by words on the same line must NOT be matched."""
    from tools.parse import _find_marker_pos
    text = "Please respond with [assistant_tool_calls] JSON using one of the session tools."
    pos = _find_marker_pos(text)
    assert pos == -1, (
        f"Marker after words on same line was incorrectly matched at pos {pos}."
    )


def test_find_marker_pos_ignores_marker_inside_code_fence():
    """[assistant_tool_calls] inside a ``` fence must NOT be treated as a real marker."""
    from tools.parse import _find_marker_pos
    # This is exactly what build_tool_instruction emits in the Tool Response Format block
    text = (
        "When using a tool, respond with this format:\n\n"
        "```\n"
        "[assistant_tool_calls]\n"
        '{"tool_calls":[{"name":"Bash","arguments":{"command":"echo hello"}}]}\n'
        "```\n"
    )
    pos = _find_marker_pos(text)
    assert pos == -1, (
        f"Marker inside code fence was incorrectly matched at pos {pos}. "
        "This would cause false-positive tool_parse_marker_found_no_json log spam."
    )


def test_parse_tool_calls_echoed_instruction_block_returns_none():
    """When the model echoes the tool instruction block verbatim, no tool calls must be parsed.

    Regression for: tool_parse_marker_found_no_json log spam when model reflects
    its own session configuration back in a text response.
    """
    tools = [{
        "type": "function",
        "function": {
            "name": "Bash",
            "description": "Run a shell command.",
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
        }
    }]
    # Simulate the model echoing back the tool instruction block exactly as emitted
    echoed = (
        "The session is configured with the following tools:\n\n"
        "## Tool Response Format\n\n"
        "When using a tool, respond with this format:\n\n"
        "```\n"
        "[assistant_tool_calls]\n"
        '{"tool_calls":[{"name":"Bash","arguments":{"command":"echo hello"}}]}\n'
        "```\n\n"
        "Guidelines:\n"
        "- Use exact parameter names.\n"
    )
    result = parse_tool_calls_from_text(echoed, tools, streaming=False)
    assert result is None, (
        f"Echoed instruction block was wrongly parsed as tool calls: {result}"
    )


def test_write_large_file_with_multiple_unescaped_quotes():
    """Write tool with many unescaped quotes throughout content must
    preserve full content and keep file_path intact.

    Regression for Strategy 3 forward scan: it used to stop at the first
    unescaped quote inside content, truncating everything after it.
    Fix: use backward scan for the last field so full content is captured.
    """
    import json
    content = (
        'def greet(name):\n'
        '    print("Hello, " + name)\n'
        '    return f"Welcome {name}!"\n'
        '    # many "quoted" strings "here"\n'
    ) * 50  # ~4k chars with dozens of unescaped quotes
    file_path = '/workspace/project/mod.py'
    raw = (
        '{"name": "Write", "arguments": {'
        '"file_path": "' + file_path + '", '
        '"content": "' + content + '"}}'
    )
    text = '[assistant_tool_calls]\n{"tool_calls": [' + raw + ']}'
    tools = [{
        'function': {
            'name': 'Write',
            'parameters': {
                'type': 'object',
                'properties': {
                    'file_path': {'type': 'string'},
                    'content': {'type': 'string'},
                },
                'required': ['file_path', 'content'],
            },
        }
    }]
    result = parse_tool_calls_from_text(text, tools)
    assert result is not None
    args = json.loads(result[0]['function']['arguments'])
    assert args['file_path'] == file_path, f'file_path corrupted: {args["file_path"]!r}'
    assert len(args.get('content', '')) > 3000, (
        f'content truncated: len={len(args.get("content", ""))}'
    )
    assert 'Hello' in args['content']
    assert 'Welcome' in args['content']


def test_edit_three_fields_unescaped_quotes_in_new_string():
    """Edit tool with unescaped quotes in new_string must preserve full
    new_string and keep file_path + old_string intact."""
    import json
    new_str = 'def bar():\n    return "yes"\n    # more "stuff" here'
    raw = (
        '{"name": "Edit", "arguments": {'
        '"file_path": "/x.py", '
        '"old_string": "def foo():", '
        '"new_string": "' + new_str + '"}}'
    )
    text = '[assistant_tool_calls]\n{"tool_calls": [' + raw + ']}'
    tools = [{
        'function': {
            'name': 'Edit',
            'parameters': {
                'type': 'object',
                'properties': {
                    'file_path': {'type': 'string'},
                    'old_string': {'type': 'string'},
                    'new_string': {'type': 'string'},
                },
                'required': ['file_path', 'old_string', 'new_string'],
            },
        }
    }]
    result = parse_tool_calls_from_text(text, tools)
    assert result is not None
    args = json.loads(result[0]['function']['arguments'])
    assert args['file_path'] == '/x.py'
    assert args['old_string'] == 'def foo():'
    assert 'yes' in args['new_string']
    assert 'stuff' in args['new_string'], f'new_string truncated: {args["new_string"]!r}'


def test_truncated_write_stream_recovers_both_fields():
    """Truncated stream (no closing }) on a Write call must recover
    both file_path and content, not fold content into file_path.

    Regression for _extract_truncated_args single-key assumption: it matched
    only the first key and returned its value as everything to end-of-string,
    so file_path got the content appended to it.
    """
    import json
    raw = (
        '{"tool_calls": [{"name": "Write", "arguments": '
        '{"file_path": "/workspace/project/mod.py", '
        '"content": "def hello():\\n    print(\'world\')\\n    # truncated here"'
        # deliberately no closing }}
    )
    text = '[assistant_tool_calls]\n' + raw
    tools = [{
        'function': {
            'name': 'Write',
            'parameters': {
                'type': 'object',
                'properties': {
                    'file_path': {'type': 'string'},
                    'content': {'type': 'string'},
                },
                'required': ['file_path', 'content'],
            },
        }
    }]
    result = parse_tool_calls_from_text(text, tools)
    assert result is not None, 'result is None'
    args = json.loads(result[0]['function']['arguments'])
    assert args['file_path'] == '/workspace/project/mod.py', (
        f'file_path corrupted: {args["file_path"]!r}'
    )
    assert 'hello' in args.get('content', ''), (
        f'content missing or empty: {args.get("content")!r}'
    )


def test_parse_tool_calls_uses_shared_tool_result_builder(monkeypatch):
    """Test main parsing path delegates result building to the shared helper."""
    called = {"count": 0}

    def fake_builder(*, merged, allowed_exact, schema_map, streaming):
        called["count"] += 1
        return [{
            "id": "call_test",
            "type": "function",
            "function": {"name": "attempt_completion", "arguments": "{}"},
        }]

    monkeypatch.setitem(
        parse_tool_calls_from_text.__globals__,
        "_build_tool_call_results",
        fake_builder,
    )

    text = (
        '[assistant_tool_calls]\n'
        '{"tool_calls": [{"name": "attempt_completion", "arguments": {"result": "done"}}]}'
    )
    tools = [{
        "type": "function",
        "function": {
            "name": "attempt_completion",
            "parameters": {
                "type": "object",
                "properties": {"result": {"type": "string"}},
                "required": ["result"],
            },
        },
    }]

    parsed = parse_tool_calls_from_text(text, tools, streaming=False)

    assert called["count"] == 1
    assert parsed == [{
        "id": "call_test",
        "type": "function",
        "function": {"name": "attempt_completion", "arguments": "{}"},
    }]


def test_cursor_backend_read_file_not_dropped():
    """read_file from the-editor's injected backend tools is parsed even when
    the client's tool list does not declare it."""
    import json
    text = (
        '[assistant_tool_calls]\n'
        '{"tool_calls": [{"name": "read_file", "arguments": {"filePath": "/help/troubleshooting/error-writing"}}]}'
    )
    client_tools = [
        {
            "type": "function",
            "function": {
                "name": "Read",
                "description": "Reads a file from the local filesystem.",
                "parameters": {
                    "type": "object",
                    "properties": {"file_path": {"type": "string"}},
                    "required": ["file_path"],
                },
            },
        }
    ]
    result = parse_tool_calls_from_text(text, client_tools)
    assert result is not None, "read_file call was dropped"
    assert result[0]["function"]["name"] == "read_file"
    args = json.loads(result[0]["function"]["arguments"])
    assert args["filePath"] == "/help/troubleshooting/error-writing"


def test_cursor_backend_read_dir_not_dropped():
    """read_dir from the-editor's injected backend tools is parsed even when
    the client's tool list does not declare it."""
    import json
    text = (
        '[assistant_tool_calls]\n'
        '{"tool_calls": [{"name": "read_dir", "arguments": {"dirPath": "/docs"}}]}'
    )
    client_tools = [
        {
            "type": "function",
            "function": {
                "name": "Read",
                "description": "Reads a file from the local filesystem.",
                "parameters": {
                    "type": "object",
                    "properties": {"file_path": {"type": "string"}},
                    "required": ["file_path"],
                },
            },
        }
    ]
    result = parse_tool_calls_from_text(text, client_tools)
    assert result is not None, "read_dir call was dropped"
    assert result[0]["function"]["name"] == "read_dir"
    args = json.loads(result[0]["function"]["arguments"])
    assert args["dirPath"] == "/docs"


def test_streaming_parser_basic():
    from tools.parse import StreamingToolCallParser
    tools = [{'function': {'name': 'bash', 'parameters': {
        'properties': {'command': {'type': 'string'}}, 'required': ['command']}}}]
    parser = StreamingToolCallParser(tools)
    chunks = [
        "Some text\n",
        "[assistant_tool_calls]\n",
        '{"tool_calls":[{"name":"bash","arguments":{"command":"ls"}}]}',
    ]
    results = [parser.feed(c) for c in chunks]
    non_none = [r for r in results if r]
    assert len(non_none) == 1
    assert non_none[0][0]['function']['name'] == 'bash'


def test_streaming_parser_none_before_marker():
    from tools.parse import StreamingToolCallParser
    tools = [{'function': {'name': 'bash', 'parameters': {
        'properties': {'command': {'type': 'string'}}, 'required': ['command']}}}]
    parser = StreamingToolCallParser(tools)
    assert parser.feed("Hello world") is None
    assert parser.feed(" still nothing") is None


def test_streaming_parser_finalize():
    from tools.parse import StreamingToolCallParser
    tools = [{'function': {'name': 'bash', 'parameters': {
        'properties': {'command': {'type': 'string'}}, 'required': ['command']}}}]
    parser = StreamingToolCallParser(tools)
    parser.feed('[assistant_tool_calls]\n{"tool_calls":[{"name":"bash","arguments":{"command":"pwd"}}]}')
    result = parser.finalize()
    assert result is not None


def test_read_file_files_alias_renamed_to_filepath():
    """Model sends 'files' but read_file schema requires 'filePath' — must be renamed, not dropped."""
    import json
    inner = json.dumps({"files": "/some/path.py"})
    text = '[assistant_tool_calls]\n' + json.dumps({"tool_calls": [{"name": "read_file", "arguments": inner}]})
    # Backend tool — not in client tools list; registered via _CURSOR_BACKEND_TOOLS
    client_tools = [{"function": {"name": "Bash", "parameters": {"properties": {"command": {"type": "string"}}, "required": ["command"]}}}]
    result = parse_tool_calls_from_text(text, client_tools)
    assert result is not None, "read_file call was dropped"
    args = json.loads(result[0]["function"]["arguments"])
    assert args.get("filePath") == "/some/path.py", f"Expected filePath to be renamed, got: {args}"
    assert "files" not in args


def test_strategy3_brace_inside_string_value():
    """Strategy 3 bracket walk must not terminate at a brace inside a string value.

    Regression: the old depth counter counted raw { / } characters without
    tracking string delimiters, so an argument value like 'if x: {return y}'
    would cause the walk to stop at the } inside the string rather than at
    the real closing brace of the arguments object.
    """
    from tools.parse import _lenient_json_loads

    # Inject a literal (unescaped) newline so Strategy 1 and 2 fail and
    # Strategy 3's regex + brace walk is exercised.
    raw = (
        '{"name": "Write", "arguments": '
        '{"file_path": "/f.py", "content": "def f():\n    return {a: b}"}}'
    )
    # Wrap in the tool_calls envelope Strategy 3 expects
    payload = '{"tool_calls": [' + raw + ']}'
    result = _lenient_json_loads(payload)
    # Must parse without crashing
    assert result is not None, "_lenient_json_loads returned None for brace-inside-string input"
    calls = result.get("tool_calls", [])
    assert len(calls) == 1, f"Expected 1 tool call, got {calls}"
    args = calls[0].get("arguments", {})
    # The brace characters inside the string must not truncate the content value
    content = args.get("content", "")
    assert "{" in content, f"Brace was eaten from content: {content!r}"
    assert args.get("file_path") == "/f.py", f"file_path corrupted: {args.get('file_path')!r}"


def test_read_dir_dir_alias_renamed_to_dirpath():
    """Model sends 'dir' but read_dir schema requires 'dirPath' — must be renamed, not dropped."""
    import json
    inner = json.dumps({"dir": "/docs"})
    text = '[assistant_tool_calls]\n' + json.dumps({"tool_calls": [{"name": "read_dir", "arguments": inner}]})
    client_tools = [{"function": {"name": "Bash", "parameters": {"properties": {"command": {"type": "string"}}, "required": ["command"]}}}]
    result = parse_tool_calls_from_text(text, client_tools)
    assert result is not None, "read_dir call was dropped"
    args = json.loads(result[0]["function"]["arguments"])
    assert args.get("dirPath") == "/docs"


def test_streaming_parser_calls_parse_once():
    """StreamingToolCallParser must call parse_tool_calls_from_text exactly once,
    not once per chunk after marker confirmed."""
    import tools.parse as _parse_mod
    call_count = 0
    original = _parse_mod.parse_tool_calls_from_text

    def counting_parse(text, tools, streaming=False, **kwargs):
        nonlocal call_count
        call_count += 1
        return original(text, tools, streaming=streaming, **kwargs)

    _parse_mod.parse_tool_calls_from_text = counting_parse
    try:
        tools_list = [{"type": "function", "function": {"name": "Write", "parameters": {"properties": {"file_path": {}, "content": {}}, "required": ["file_path"]}}}]
        parser = _parse_mod.StreamingToolCallParser(tools_list)
        # Simulate 20 chunks for a complete tool call
        full = '[assistant_tool_calls]\n{"tool_calls": [{"name": "Write", "arguments": {"file_path": "/foo.py", "content": "hello world"}}]}'
        chunk_size = max(1, len(full) // 20)
        result = None
        for i in range(0, len(full), chunk_size):
            r = parser.feed(full[i:i + chunk_size])
            if r:
                result = r
        parser.finalize()
        # feed() path: exactly 1 call (streaming=True when depth hits 0)
        # finalize() path: 1 more call (streaming=False)
        # Total must be <= 2, not 20+
        assert call_count <= 2, f"Expected <=2 calls but got {call_count}"
        assert result is not None, "Should have returned parsed calls"
        assert result[0]["function"]["name"] == "Write"
    finally:
        _parse_mod.parse_tool_calls_from_text = original


def test_edit_unescaped_quotes_in_old_string():
    """Regression: Edit call where old_string contains literal unescaped
    double-quote chars (Python dict subscript syntax). Exact pattern that
    triggered tool_parse_marker_found_no_json in production."""
    import json
    from tools.parse import parse_tool_calls_from_text
    # Build payload with literal unescaped " inside old_string value.
    # String concatenation keeps the " chars unescaped in the resulting
    # string, mimicking exactly what the upstream model emits.
    payload = (
        '[assistant_tool_calls]\n'
        '{"tool_calls": [{"name": "Edit", "arguments": {'
        '"replace_all": false, '
        '"file_path": "/tests/test_routing.py", '
        '"old_string": "    assert captured_calls[3]["tool_choice"] == \"none\"\\n", '
        '"new_string": "    assert captured_calls[3][\'tool_choice\'] == \'none\'\\n"'
        '}}]}'
    )
    tools = [{'type': 'function', 'function': {
        'name': 'Edit',
        'parameters': {'type': 'object', 'properties': {
            'file_path': {'type': 'string'},
            'old_string': {'type': 'string'},
            'new_string': {'type': 'string'},
            'replace_all': {'type': 'boolean'},
        }, 'required': ['file_path', 'old_string', 'new_string']},
    }}]
    result = parse_tool_calls_from_text(payload, tools, streaming=False)
    assert result is not None, "Edit call with unescaped quotes in old_string was dropped"
    assert result[0]['function']['name'] == 'Edit'
    args = json.loads(result[0]['function']['arguments'])
    assert args.get('file_path') == '/tests/test_routing.py'
    assert 'tool_choice' in args.get('old_string', '')


def test_escape_unescaped_quotes_helper():
    """Unit test for _escape_unescaped_quotes repair helper."""
    import json
    from tools.parse import _escape_unescaped_quotes
    raw = '{"key": "value with "inner" quotes"}'
    escaped = _escape_unescaped_quotes(raw)
    parsed = json.loads(escaped)
    assert parsed['key'] == 'value with "inner" quotes'


def test_lenient_json_unescaped_quotes_multi_field():
    """_lenient_json_loads must recover a multi-field payload where
    a non-last field value contains unescaped double-quote chars."""
    from tools.parse import _lenient_json_loads
    raw = (
        '{"tool_calls": [{"name": "Edit", "arguments": {'
        '"file_path": "/f.py", '
        '"old_string": "x["key"] = 1", '
        '"new_string": "x[key] = 1"'
        '}}]}'
    )
    result = _lenient_json_loads(raw)
    assert result is not None, "_lenient_json_loads returned None for unescaped-quote payload"
    args = result['tool_calls'][0]['arguments']
    assert 'key' in args.get('old_string', '')


def test_escape_unescaped_quotes_preserves_string_arrays():
    """_escape_unescaped_quotes must not corrupt string arrays.
    Regression: closing '"' before ']' at square_depth=0 must be
    treated as a real terminator, not an interior literal quote."""
    import json
    from tools.parse import _escape_unescaped_quotes
    # Valid JSON — must survive unchanged
    cases = [
        '{"k": ["a", "b"]}',
        '{"arr": ["x"]}',
        '{"tool_calls": [{"name": "Bash", "arguments": {"command": "ls"}}]}',
    ]
    for case in cases:
        result = _escape_unescaped_quotes(case)
        assert result == case, f"Corrupted valid JSON: {case!r} -> {result!r}"
        # Also verify it round-trips through json.loads
        assert json.loads(result) == json.loads(case)

