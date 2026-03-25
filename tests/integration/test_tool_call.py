import json
import pytest
from fastapi.testclient import TestClient
from app import create_app


@pytest.fixture(scope="module")
def client():
    return TestClient(create_app())


def test_tool_call(client):
    headers = {
        "Authorization": "Bearer 123",
        "Content-Type": "application/json"
    }

    payload = {
        "model": "claude-3-5-sonnet-20241022",
        "messages": [
            {"role": "user", "content": "Run the command 'echo hello' in my terminal."}
        ],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "execute_command",
                    "description": "Execute a terminal command",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "command": {
                                "type": "string",
                                "description": "The command to execute"
                            }
                        },
                        "required": ["command"]
                    }
                }
            }
        ],
        "stream": False
    }

    response = client.post("/v1/chat/completions", headers=headers, json=payload)
    print("Status Code:", response.status_code)
    try:
        print("Response JSON:", json.dumps(response.json(), indent=2))
    except Exception:
        print("Response Text:", response.text)


if __name__ == "__main__":
    test_tool_call(TestClient(create_app()))
