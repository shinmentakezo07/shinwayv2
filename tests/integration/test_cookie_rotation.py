import requests
import time

def test_multiple_requests():
    import os
    port = os.environ.get("PORT", "4002")
    url = f"http://localhost:{port}/v1/chat/completions"
    headers = {
        "Authorization": "Bearer 123",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": "claude-3-5-sonnet-20241022",
        "messages": [
            {
                "role": "user", 
                "content": "Reply with a single word: 'Ping'"
            }
        ],
        "stream": False
    }

    print("Sending 4 requests to trigger cookie rotation (3 requests per cookie)...")
    for i in range(1, 5):
        print(f"\\n--- Request {i} ---")
        response = requests.post(url, headers=headers, json=payload)
        print(f"Status Code: {response.status_code}")
        if response.status_code != 200:
            print("Error Response:", response.text)
        else:
            print("Response:", response.json().get("choices", [{}])[0].get("message", {}).get("content"))
        time.sleep(1)

if __name__ == "__main__":
    test_multiple_requests()
