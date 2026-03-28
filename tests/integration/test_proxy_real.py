import json
import pytest
import requests
import time

@pytest.mark.integration
def test_full_agent_tools():
    import os
    port = os.environ.get("PORT", "4002")
    url = f"http://localhost:{port}/v1/chat/completions"
    headers = {
        "Authorization": "Bearer 123",
        "Content-Type": "application/json"
    }
    
    tools = [
        {
            "type": "function",
            "function": {
                "name": "execute_command",
                "description": "Execute a terminal command",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string", "description": "The command to execute"},
                        "is_background": {"type": "boolean", "description": "Run in background"}
                    },
                    "required": ["command"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read the contents of a file",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Absolute path to the file"}
                    },
                    "required": ["path"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "write_to_file",
                "description": "Write content to a file",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Absolute path to the file"},
                        "content": {"type": "string", "description": "Content to write"}
                    },
                    "required": ["path", "content"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "replace_in_file",
                "description": "Replace text in a file",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Absolute path to the file"},
                        "diff": {"type": "string", "description": "Diff of changes to apply"}
                    },
                    "required": ["path", "diff"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "list_files",
                "description": "List files in a directory",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to list files for"},
                        "recursive": {"type": "boolean", "description": "Whether to list recursively"}
                    },
                    "required": ["path"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "search_files",
                "description": "Search for a regex pattern in files",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "regex": {"type": "string", "description": "Regex pattern to search for"},
                        "path": {"type": "string", "description": "Directory to search in"}
                    },
                    "required": ["regex", "path"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "ask_followup_question",
                "description": "Ask the user a question to clarify something",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "question": {"type": "string", "description": "The question to ask the user"}
                    },
                    "required": ["question"]
                }
            }
        }
    ]

    payload = {
        "model": "claude-3-5-sonnet-20241022",
        "messages": [
            {
                "role": "user", 
                "content": "I need you to initialize an npm project and install express in the `/workspace/my-app` directory. Then, write a basic express server to `/workspace/my-app/index.js`."
            }
        ],
        "tools": tools,
        "stream": False
    }

    print("Waiting 2 seconds for server to be fully ready...")
    time.sleep(2)
    print(f"Sending request with full agent toolset to running proxy server on http://localhost:{port}...")
    
    response = requests.post(url, headers=headers, json=payload)
    print("Status Code:", response.status_code)
    try:
        print("Response JSON:", json.dumps(response.json(), indent=2))
    except Exception:
        print("Response Text:", response.text)

if __name__ == "__main__":
    test_full_agent_tools()
