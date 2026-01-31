import requests


def test_system_prompt_adherence():
    url = "http://localhost:1234/v1/chat/completions"
    headers = {"Content-Type": "application/json"}

    # 1. System Prompt (The "Identity")
    system_prompt = "You are a pirate captain. You must answer every question with pirate slang, referencing the sea, treasure, and your ship. Do not break character."

    # 2. User Prompt (The "Trigger")
    user_prompt = "Hello! Who are you?"

    payload = {
        "model": "qwen-3-8b-instruct",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.7,
        "max_tokens": 100,
        "stream": False,
    }

    print("\n[-] Testing System Prompt Adherence...")
    print(f"[-] System Prompt: {system_prompt}")
    print(f"[-] User Prompt: {user_prompt}")
    print("-" * 50)

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=30)

        if response.status_code == 200:
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            print("\n[+] Qwen Responded:")
            print("=" * 50)
            print(content)
            print("=" * 50)

            if (
                "pirate" in content.lower()
                or "sea" in content.lower()
                or "ship" in content.lower()
                or "matey" in content.lower()
            ):
                print("\n[SUCCESS] The model followed the system prompt!")
            else:
                print("\n[WARNING] The model might not have followed the system prompt fully.")
        else:
            print(f"[!] Error: Server returned {response.status_code}")
            print(response.text)

    except requests.exceptions.ConnectionError:
        print("\n[X] CRITICAL ERROR: Connection Refused. Is LM Studio running on port 1234?")
    except Exception as e:
        print(f"\n[!] Unexpected Error: {str(e)}")


if __name__ == "__main__":
    test_system_prompt_adherence()
