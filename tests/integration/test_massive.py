import requests
import time

def test_massive_payload():
    url = "http://localhost:4000/v1/chat/completions"
    headers = {
        "Authorization": "Bearer 123",
        "Content-Type": "application/json"
    }
    
    # Target: ~150,000 tokens (close to the 200K limit, leaving headroom).
    # 1 token is roughly 4 characters -> ~600,000 characters.
    # To be safe and push the limit, let's generate ~160,000 tokens.
    large_text_block = "def example_function():\\n    # This is a block of text to simulate a massive codebase payload.\\n    pass\\n" * 9000  # ~810,000 chars, ~200,000 tokens depending on tokenizer
    
    payload = {
        "model": "claude-3-5-sonnet-20241022",
        "messages": [
            {
                "role": "system",
                "content": "You are a senior software engineer. Analyze the massive codebase provided and return a tool call to execute a command that says 'Codebase ingested successfully'."
            },
            {
                "role": "user", 
                "content": f"Here is my massive codebase:\\n\\n{large_text_block}\\n\\nPlease analyze it."
            }
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
                            "command": {"type": "string", "description": "The command to execute"}
                        },
                        "required": ["command"]
                    }
                }
            }
        ],
        "stream": True
    }

    # Roughly estimate token size (very basic estimation)
    estimated_tokens = len(large_text_block) // 4
    print(f"\\n[!] Preparing to send MASSIVE payload. Estimated tokens: ~{estimated_tokens:,}")
    print("This will test both the HTTP request size limits and the Cursor backend's 200k context limit.")
    
    start_time = time.time()
    
    try:
        # Increase timeout drastically for a 150k+ token read
        response = requests.post(url, headers=headers, json=payload, stream=True, timeout=300) 
        
        chunks_received = 0
        print("Receiving stream chunks...")
        for line in response.iter_lines():
            if line:
                chunks_received += 1
                # Print a dot for every chunk to show progress without spamming terminal
                print(".", end="", flush=True)
                
                # Check for error or done messages
                line_str = line.decode('utf-8')
                if '"error"' in line_str:
                    print(f"\\n\\n[ERROR Chunk]: {line_str}")
                elif "tool_calls" in line_str and "execute_command" in line_str:
                    print("\\n\\n[SUCCESS] Tool call detected in stream!")
                    
        end_time = time.time()
        print(f"\\n\\nStatus Code: {response.status_code}")
        print(f"Time taken: {end_time - start_time:.2f} seconds")
        print(f"Total chunks received: {chunks_received}")
        
    except Exception as e:
        print(f"\\n\\nRequest failed or timed out: {e}")

if __name__ == "__main__":
    test_massive_payload()
