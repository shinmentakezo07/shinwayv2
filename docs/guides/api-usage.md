# API Usage Guide

Shin Proxy is OpenAI API-compatible. Any client that supports the OpenAI API works out of the box.

Base URL: `http://localhost:4001`
Auth header: `Authorization: Bearer <your-LITELLM_MASTER_KEY>`

---

## Chat Completions

### Non-streaming

```bash
curl -X POST http://localhost:4001/v1/chat/completions \
  -H "Authorization: Bearer sk-your-key" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-4o",
    "messages": [{"role": "user", "content": "What is 2+2?"}]
  }'
```

### Streaming

```bash
curl -X POST http://localhost:4001/v1/chat/completions \
  -H "Authorization: Bearer sk-your-key" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-4o",
    "messages": [{"role": "user", "content": "Count to 5"}],
    "stream": true
  }'
```

### With tools

```bash
curl -X POST http://localhost:4001/v1/chat/completions \
  -H "Authorization: Bearer sk-your-key" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-4o",
    "messages": [{"role": "user", "content": "What is 10 * 5? Use the calculator."}],
    "tools": [{
      "type": "function",
      "function": {
        "name": "calculator",
        "description": "Evaluate a math expression",
        "parameters": {
          "type": "object",
          "properties": {
            "expression": {"type": "string"}
          },
          "required": ["expression"]
        }
      }
    }],
    "tool_choice": "required"
  }'
```

---

## Responses API (OpenAI Responses format)

Stateful multi-turn endpoint. The server stores responses and links them via `previous_response_id`.

### Basic request

```bash
curl -X POST http://localhost:4001/v1/responses \
  -H "Authorization: Bearer sk-your-key" \
  -H "Content-Type: application/json" \
  -d '{"model": "gpt-4o", "input": "Hello!"}'
```

### Multi-turn (stateful)

```bash
# Turn 1
RESP=$(curl -s -X POST http://localhost:4001/v1/responses \
  -H "Authorization: Bearer sk-your-key" \
  -H "Content-Type: application/json" \
  -d '{"model": "gpt-4o", "input": "My name is Alice."}')

ID=$(echo $RESP | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

# Turn 2 — server remembers the conversation
curl -X POST http://localhost:4001/v1/responses \
  -H "Authorization: Bearer sk-your-key" \
  -H "Content-Type: application/json" \
  -d "{\"model\": \"gpt-4o\", \"input\": \"What is my name?\", \"previous_response_id\": \"$ID\"}"
```

### Streaming

```bash
curl -X POST http://localhost:4001/v1/responses \
  -H "Authorization: Bearer sk-your-key" \
  -H "Content-Type: application/json" \
  -d '{"model": "gpt-4o", "input": "Tell me a joke", "stream": true}'
```

### With instructions (system prompt)

```bash
curl -X POST http://localhost:4001/v1/responses \
  -H "Authorization: Bearer sk-your-key" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-4o",
    "input": "What should I eat today?",
    "instructions": "You are a nutritionist. Always recommend vegetables."
  }'
```

---

## List Models

```bash
curl http://localhost:4001/v1/models \
  -H "Authorization: Bearer sk-your-key"
```

---

## Internal Endpoints

These require the same bearer token.

### Stats

```bash
curl http://localhost:4001/v1/internal/stats \
  -H "Authorization: Bearer sk-your-key"
```

### Clear cache

```bash
curl -X POST http://localhost:4001/v1/internal/cache/clear \
  -H "Authorization: Bearer sk-your-key"
```

### Credential health

```bash
curl http://localhost:4001/v1/internal/credentials \
  -H "Authorization: Bearer sk-your-key"
```

### Validate all cookies against Cursor

```bash
curl http://localhost:4001/v1/internal/credentials/me \
  -H "Authorization: Bearer sk-your-key"
```

---

## Using with OpenAI Python SDK

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:4001/v1",
    api_key="sk-your-key",
)

response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Hello!"}],
)
print(response.choices[0].message.content)
```

## Using with any OpenAI-compatible client

Set the base URL to `http://localhost:4001/v1` and the API key to your `LITELLM_MASTER_KEY`. Everything else works identically to the OpenAI API.
