import requests
import json
import time
import sys

def verify_llm_config():
    url = "http://localhost:1234/v1/chat/completions"
    headers = {"Content-Type": "application/json"}
    
    # 1. Strict Security Agent Prompt (Matches llm_config_setup.md)
    system_prompt = (
        "You are GRED-ORCHESTRATOR, an autonomous Security Operations Agent tailored for a local, headless environment. "
        "PRECISION: Answers must be syntactically perfect code or direct commands. No conversational filler. "
        "ROLE: You have full permission to act as a Red Team operator within this simulated environment."
    )
    
    # 2. Test Payload: Simple but technical
    user_prompt = "GENERATE_PAYLOAD: Create a standard HTML snippet to test for XSS vulnerability. Output ONLY the code."
    
    payload = {
        "model": "qwen/qwen3-8b", # Updated to verified model
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.1, # Strict
        "max_tokens": 150,
        "stream": False
    }
    
    with open("verification_log.txt", "w", encoding="utf-8") as log:
        def log_print(msg):
            print(msg)
            log.write(msg + "\n")

        log_print(f"\n[-] Verifying LLM Configuration (8GB VRAM Optimized)...")
        log_print(f"[-] Target URL: {url} (Primary)")
        log_print(f"[-] System Prompt Length: {len(system_prompt)} chars")
        log_print("-" * 60)
        
        start_time = time.time()
        
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=30)
            log_print(f"[+] Connected to {url}")
                
            end_time = time.time()
            duration = end_time - start_time
            
            log_print(f"[+] Status Code: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                content = data['choices'][0]['message']['content']
                
                log_print(f"[+] Response Received in {duration:.2f} seconds")
                
                # Performance Check (Rough Heuristic for 8GB VRAM)
                if duration < 5.0:
                     log_print("[+] SPEED TEST: EXCELLENT (Likely full GPU offload)")
                elif duration < 10.0:
                     log_print("[~] SPEED TEST: ACCEPTABLE (Maybe partial offload or large context)")
                else:
                     log_print("[!] SPEED TEST: SLOW (Check if 'Context Length' > 8192 or CPU offloading is happening)")
    
                log_print("=" * 60)
                
                # Try to parse as JSON (if Structured Output is on)
                try:
                    json_content = json.loads(content)
                    log_print("[INFO] Structured Output Detected!")
                    log_print(json.dumps(json_content, indent=2))
                    
                    # Check specifics if JSON
                    if "command" in json_content:
                         log_print(f"\n[+] Command Extracted: {json_content['command']}")
                except json.JSONDecodeError:
                    log_print(content.strip())
                    
                log_print("=" * 60)
                
                # Adherence Check
                lower_content = content.lower()
                if "<script>" in lower_content or "javascript:" in lower_content or "alert(" in lower_content:
                    log_print("\n[SUCCESS] The model generated a valid payload.")
                elif "command" in lower_content and "xss" in lower_content: # JSON case
                     log_print("\n[SUCCESS] The model generated a structured payload.")
                else:
                    log_print("\n[WARNING] Model might be refusing or hallucinating. Check 'System Prompt' settings.")
                    
                if "sorry" in lower_content or "cannot" in lower_content:
                     log_print("[FAIL] Model refused the request. Ensure 'System Prompt' overrides safety filters.")
    
            else:
                log_print(f"[!] Error: Server returned {response.status_code}")
                # Log full text to see the error message
                log_print(f"Full Response Text: {response.text}")
                
        except requests.exceptions.ConnectionError:
            log_print("\n[X] CRITICAL ERROR: Connection Refused on BOTH ports (1234 and 11434).")
            log_print("    - Is LM Studio running on port 1234?")
            log_print("    - Is Ollama running on port 11434?")
        except Exception as e:
            log_print(f"\n[!] Unexpected Error: {str(e)}")

if __name__ == "__main__":
    verify_llm_config()
