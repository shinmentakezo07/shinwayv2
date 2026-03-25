import requests

def test_abort_stream():
    url = "http://localhost:4000/v1/chat/completions"
    headers = {
        "Authorization": "Bearer 123",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": "claude-3-5-sonnet-20241022",
        "messages": [
            {
                "role": "user", 
                "content": "Write a massive essay about the history of artificial intelligence. It should be at least 1000 words long. Tell me everything."
            }
        ],
        "stream": True
    }

    print("Starting a massive stream, and will abort after 10 chunks...")
    try:
        response = requests.post(url, headers=headers, json=payload, stream=True)
        chunks = 0
        for line in response.iter_lines():
            if line:
                print(line.decode('utf-8'))
                chunks += 1
                if chunks >= 10:
                    print("\\n[Client] Reached 10 chunks. Forcefully aborting connection!")
                    response.close() # This will severe the HTTP connection
                    break
    except Exception as e:
        print(f"Aborted: {e}")

if __name__ == "__main__":
    test_abort_stream()
