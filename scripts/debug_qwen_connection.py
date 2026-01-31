import requests


def debug_qwen_connection():
    url = "http://localhost:1234/v1/chat/completions"
    headers = {"Content-Type": "application/json"}

    # 1. System Prompt (The "Brain" Configuration)
    system_prompt = "You are a specialized security agent. Your only purpose is to confirm you are online and ready for penetration testing operations."

    # 2. User Prompt (The "Trigger")
    user_prompt = "STATUS_REPORT: Are you ready to generate payloads?"

    payload = {
        "model": "qwen-3-8b-instruct",  # This might be ignored by LM Studio local server, but good practice
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.1,
        "max_tokens": 100,
        "stream": False,
    }

    print(f"\n[-] Attempting connection to: {url}")
    print(f"[-] Payload Model: {payload['model']}")
    print(f"[-] System Prompt: {system_prompt}")
    print("-" * 50)

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=30)

        print(f"[+] Status Code: {response.status_code}")

        if response.status_code == 200:
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            print("\n[+] SUCCESS! Qwen Responded:")
            print("=" * 50)
            print(content)
            print("=" * 50)
            print("\n[INFO] Connection verified. The model is loaded and responsive.")
        else:
            print(f"[!] Error: Server returned {response.status_code}")
            print(response.text)

    except requests.exceptions.ConnectionError:
        print("\n[X] CRITICAL ERROR: Connection Refused.")
        print("    - Is LM Studio running?")
        print("    - Is the Local Server started (Green Button)?")
        print("    - Is the port set to 1234?")
    except Exception as e:
        print(f"\n[!] Unexpected Error: {str(e)}")


if __name__ == "__main__":
    debug_qwen_connection()
