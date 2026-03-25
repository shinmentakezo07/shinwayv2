import requests
import time

def test_large_payload():
    url = "http://localhost:4000/v1/chat/completions"
    headers = {
        "Authorization": "Bearer 123",
        "Content-Type": "application/json"
    }
    
    # 1 token is roughly 4 characters. We want ~73,000 tokens, so ~300,000 characters.
    # Let's generate a large block of text.
    large_text_block = "This is a block of text to simulate a large codebase payload. " * 5000  # ~310,000 chars
    
    payload = {
        "model": "claude-3-5-sonnet-20241022",
        "messages": [
            {
                "role": "user", 
                "content": f"Here is my codebase: {large_text_block}\\n\\nPlease reply with exactly one word: 'Received'."
            }
        ],
        "stream": False
    }

    print(f"Sending request with ~{len(large_text_block) // 4} tokens...")
    start_time = time.time()
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=240) # 4 mins timeout on client side
        end_time = time.time()
        print(f"Status Code: {response.status_code}")
        print(f"Time taken: {end_time - start_time:.2f} seconds")
        
        if response.status_code == 200:
            print("Response:", response.json().get("choices", [{}])[0].get("message", {}).get("content"))
        else:
            print("Error Response:", response.text)
    except Exception as e:
        print(f"Request failed: {e}")

if __name__ == "__main__":
    test_large_payload()
