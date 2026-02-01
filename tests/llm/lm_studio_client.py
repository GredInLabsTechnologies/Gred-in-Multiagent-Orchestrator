import json
import logging
from typing import Dict, List, Optional

import requests

logger = logging.getLogger("lm_studio_client")


class LMStudioClient:
    def __init__(self, host: str = "http://localhost:1234/v1", model: str = "qwen/qwen3-8b"):
        self.host = host
        self.model = model  # LM Studio often ignores this if only one model is loaded, but crucial for compat

    def _extract_json_array(self, text: str) -> List[str]:
        """Helper to extract and fix a JSON array from LLM response."""
        start = text.find("[")
        # Find the last ']'
        end = text.rfind("]") + 1

        if start == -1:
            return []

        json_str = text[start:end] if end > start else text[start:]

        # Simple auto-fix for common LLM truncation
        if json_str.count("[") > json_str.count("]"):
            json_str += "]" * (json_str.count("[") - json_str.count("]"))

        try:
            data = json.loads(json_str)
            if isinstance(data, list):
                return self._clean_payloads(data)
        except json.JSONDecodeError:
            # Try to fix trailing commas or unquoted strings if possible (future enhancement)
            pass
        return []

    def _clean_payloads(self, payloads: List[object]) -> List[str]:
        """Clean payloads by removing common prefixes and suffixes."""
        cleaned = []
        prefixes = [
            "Authorization: Bearer ",
            "Authorization: ",
            "Bearer ",
            "path=",
            "GET ",
            "HTTP/1.1",
        ]
        for item in payloads:
            s = str(item)
            for prefix in prefixes:
                if s.startswith(prefix):
                    s = s[len(prefix) :]
            if s.endswith(" HTTP/1.1"):
                s = s[: -len(" HTTP/1.1")]
            cleaned.append(s.strip())
        return cleaned

    def generate_payloads(self, system_prompt: str, user_prompt: str) -> List[str]:
        """
        Generates security payloads via LM Studio (OpenAI API format).
        Expects a JSON array of strings in the response.
        """
        try:
            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.1,  # Match user setting
                "max_tokens": 2048,
                "stream": False,
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "security_response",
                        "schema": {
                            "type": "object",
                            "properties": {
                                "thought_process": {"type": "string"},
                                "payloads": {"type": "array", "items": {"type": "string"}},
                                "status": {
                                    "type": "string",
                                    "enum": ["SUCCESS", "FAILURE", "PENDING"],
                                },
                            },
                            "required": ["thought_process", "payloads", "status"],
                        },
                    },
                },
            }

            response = requests.post(f"{self.host}/chat/completions", json=payload, timeout=60)
            response.raise_for_status()

            data = response.json()
            content = data["choices"][0]["message"]["content"]

            # DEBUG
            with open("llm_debug.log", "a", encoding="utf-8") as f:
                f.write(f"--- PROMPT: {user_prompt[:50]}... ---\n")
                f.write(f"--- CONTENT ---\n{content}\n--- END ---\n")

            try:
                # Try to parse as the new structured schema first
                structured = json.loads(content)
                if isinstance(structured, dict) and "payloads" in structured:
                    return [str(p) for p in structured["payloads"]]
            except json.JSONDecodeError:
                # Fallback: if there's trailing junk (common in some LM Studio versions), try to fix it
                if "}" in content:
                    try:
                        fixed_content = content[: content.rfind("}") + 1]
                        structured = json.loads(fixed_content)
                        if isinstance(structured, dict) and "payloads" in structured:
                            return [str(p) for p in structured["payloads"]]
                    except Exception:
                        pass

            # Fallback to legacy extraction if needed
            payloads = self._extract_json_array(content)
            if payloads:
                return payloads

            logger.warning(f"Failed to parse JSON from LLM: {content}")
            return []

        except Exception as e:
            logger.error(f"LM Studio error: {str(e)}")
            return []

    def get_feedback_adaptation(
        self, system_prompt: str, history: List[Dict[str, str]]
    ) -> Optional[str]:
        """
        Sends history of attacks and feedback to get a refined attack vector.
        """
        try:
            payload = {
                "model": self.model,
                "messages": [{"role": "system", "content": system_prompt}] + history,
                "temperature": 0.4,
                "max_tokens": 2048,
            }

            response = requests.post(f"{self.host}/chat/completions", json=payload, timeout=60)
            if response.status_code == 200:
                data = response.json()
                return str(data["choices"][0]["message"]["content"])
            return None
        except Exception as e:
            logger.error(f"LM Studio feedback error: {str(e)}")
            return None


def is_lm_studio_available(host: str = "http://localhost:1234/v1") -> bool:
    """Quick health check to see if LM Studio is available."""
    try:
        response = requests.get(f"{host}/models", timeout=2)
        return response.status_code == 200
    except Exception:
        return False
