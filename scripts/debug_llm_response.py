import json

import requests


def debug_llm():
    url = "http://localhost:1234/v1/chat/completions"
    payload = {
        "model": "qwen/qwen3-8b",
        "messages": [
            {"role": "system", "content": "Output a JSON array of strings only."},
            {"role": "user", "content": "Generate 3 test strings."},
        ],
        "temperature": 0.1,
    }

    try:
        response = requests.post(url, json=payload, timeout=30)
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        print(f"RAW CONTENT:\n{content}\n")

        start = content.find("[")
        end = content.rfind("]") + 1
        if start != -1 and end != -1:
            json_str = content[start:end]
            try:
                parsed = json.loads(json_str)
                print(f"PARSED SUCCESSFULLY: {parsed}")
            except Exception as e:
                print(f"PARSE ERROR: {e}")
        else:
            print("NO JSON ARRAY FOUND")

    except Exception as e:
        print(f"CONNECTION ERROR: {e}")


if __name__ == "__main__":
    debug_llm()
