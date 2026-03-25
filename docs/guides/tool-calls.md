# Tool Calls Guide

Shin Proxy fully supports tool calls (function calling) in both OpenAI and Anthropic formats.

---

## How it works

The-editor (Cursor's backend) does not natively support OpenAI/Anthropic function calling. The proxy implements this by:

1. Converting tool schemas into a plain-text instruction block in the system prompt
2. Asking the model to emit tool calls in `[assistant_tool_calls]` marker format
3. Parsing the tool call JSON from the text stream using a 4-strategy fallback parser
4. Repairing malformed tool calls (fuzzy name matching, type coercion)
5. Re-formatting as standard OpenAI or Anthropic tool call responses

---

## OpenAI format

### Request

```bash
curl http://localhost:4001/v1/chat/completions \
  -H "Authorization: Bearer $KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "anthropic/claude-sonnet-4.6",
    "messages": [{"role": "user", "content": "Read /workspace/foo.py"}],
    "tools": [{
      "type": "function",
      "function": {
        "name": "Read",
        "description": "Read a file from the filesystem",
        "parameters": {
          "type": "object",
          "properties": {
            "file_path": {"type": "string", "description": "Absolute path to file"}
          },
          "required": ["file_path"]
        }
      }
    }],
    "tool_choice": "auto",
    "stream": true
  }'
```

### Tool call response

```json
{
  "id": "chatcmpl-abc123",
  "object": "chat.completion.chunk",
  "choices": [{
    "index": 0,
    "delta": {
      "tool_calls": [{
        "index": 0,
        "id": "call_abc123",
        "type": "function",
        "function": {
          "name": "Read",
          "arguments": "{\"file_path\": \"/workspace/foo.py\"}"
        }
      }]
    }
  }]
}
```

### Tool result (next turn)

```json
{
  "messages": [
    {"role": "user", "content": "Read /workspace/foo.py"},
    {
      "role": "assistant",
      "content": null,
      "tool_calls": [{
        "id": "call_abc123",
        "type": "function",
        "function": {"name": "Read", "arguments": "{\"file_path\": \"/workspace/foo.py\"}"}
      }]
    },
    {
      "role": "tool",
      "tool_call_id": "call_abc123",
      "content": "def hello():\n    return 'world'"
    }
  ]
}
```

---

## Anthropic format

### Request

```bash
curl http://localhost:4001/v1/messages \
  -H "Authorization: Bearer $KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "anthropic/claude-sonnet-4.6",
    "max_tokens": 4096,
    "messages": [{"role": "user", "content": "Read /workspace/foo.py"}],
    "tools": [{
      "name": "Read",
      "description": "Read a file",
      "input_schema": {
        "type": "object",
        "properties": {
          "file_path": {"type": "string"}
        },
        "required": ["file_path"]
      }
    }]
  }'
```

### Tool call response

```json
{
  "type": "message",
  "content": [{
    "type": "tool_use",
    "id": "toolu_abc123",
    "name": "Read",
    "input": {"file_path": "/workspace/foo.py"}
  }]
}
```

---

## tool_choice options

| Value | Behaviour |
|---|---|
| `"auto"` | Model decides whether to call a tool |
| `"required"` / `"any"` | Model must call at least one tool. Proxy retries if no tool call returned. |
| `"none"` | Model must not call tools |
| `{"type": "function", "function": {"name": "X"}}` | Force a specific tool (hint to model — not structurally enforced) |

---

## Parallel tool calls

Multiple tool calls can be returned in a single response:

```json
"tool_calls": [
  {"id": "call_1", "function": {"name": "Read", "arguments": "{\"file_path\": \"/foo.py\"}"}},
  {"id": "call_2", "function": {"name": "Read", "arguments": "{\"file_path\": \"/bar.py\"}"}}
]
```

To restrict to one tool call per response, set `parallel_tool_calls: false` in the request or `SHINWAY_DISABLE_PARALLEL_TOOLS=true` globally.

---

## Tool call limits

- Max tools per request: `64` (configurable via `SHINWAY_MAX_TOOLS`)
- Each tool must have `type: "function"` and a non-empty `name`
- Requests exceeding the limit return `400 Bad Request`

---

## Tool call repair

The proxy automatically repairs malformed tool calls before returning them to clients:

- **Name repair** — fuzzy-matches wrong tool names (Levenshtein ≤ 2, substring, shared prefix)
- **Parameter repair** — maps wrong parameter names to correct ones using alias table + fuzzy matching
- **Type coercion** — converts `"true"` → `true`, `"42"` → `42`, etc.
- **Missing params** — fills missing required non-string parameters with typed fallbacks

Repair is logged at `DEBUG` level. Unrepairable calls are dropped with a `WARNING` log.

---

## Streaming tool calls

Tool call arguments are streamed incrementally:

```
data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_abc","type":"function","function":{"name":"Write","arguments":""}}]}}]}
data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"{\"file"}}]}}]}
data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"_path\":\""}}]}}]}
...
```

The `StreamingToolCallParser` detects the `[assistant_tool_calls]` marker and emits argument chunks once the tool call JSON is complete (O(n) total, not per-chunk).
