import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Dict, List, Optional

import requests

_LOG_DIR = Path(__file__).resolve().parent.parent.parent / "logs"

logger = logging.getLogger("lm_studio_client")


class LMStudioClient:
    def __init__(self, host: str = "http://localhost:1234/v1", model: str = "qwen/qwen3-8b"):
        self.host = host
        # Allow overriding the model from env for CI (ollama, etc.)
        self.model = os.environ.get("LM_STUDIO_MODEL", model)

    @staticmethod
    def _is_response_format_unsupported(resp: requests.Response) -> bool:
        # Many OpenAI-compatible servers don't support response_format=json_schema.
        # Treat 400/404/422 as likely unsupported.
        return resp.status_code in {400, 404, 422}

    def _post_chat(self, payload: dict, timeout_s: int) -> requests.Response:
        return requests.post(f"{self.host}/chat/completions", json=payload, timeout=timeout_s)

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

            # Common LLM artifact: UTF-8 BOM / zero-width chars that can break HTTP header encoding.
            s = s.replace("\ufeff", "").replace("\u200b", "").replace("\u200c", "").replace("\u200d", "")

            for prefix in prefixes:
                if s.startswith(prefix):
                    s = s[len(prefix) :]
            if s.endswith(" HTTP/1.1"):
                s = s[: -len(" HTTP/1.1")]
            cleaned.append(s.strip())
        return cleaned

    def _sanitize_json_escapes(self, text: str) -> str:
        r"""Fix invalid JSON escape sequences like \? or bare backslashes."""
        return re.sub(r"\\(?![\\/\"bfnrtu])", r"\\\\", text)

    def _extract_payloads_from_object(self, text: str) -> List[str]:
        """Extract payloads field even if JSON has invalid escapes."""
        marker = '"payloads"'
        if marker not in text:
            return []
        try:
            start = text.index("[", text.index(marker))
        except ValueError:
            return []
        depth = 0
        end = None
        for idx in range(start, len(text)):
            if text[idx] == "[":
                depth += 1
            elif text[idx] == "]":
                depth -= 1
                if depth == 0:
                    end = idx + 1
                    break
        if end is None:
            return []
        array_text = text[start:end]
        array_text = self._sanitize_json_escapes(array_text)
        try:
            data = json.loads(array_text)
            if isinstance(data, list):
                return self._clean_payloads(data)
        except Exception:
            return []
        return []

    def _extract_payloads_regex(self, text: str) -> List[str]:
        """Regex fallback when JSON parsing fails completely."""
        marker = '"payloads"'
        if marker not in text:
            return []
        try:
            start = text.index("[", text.index(marker))
        except ValueError:
            return []
        raw = text[start:]
        matches = re.findall(r'"((?:\\.|[^"\\])*)"', raw)
        payloads = [m.encode("utf-8").decode("unicode_escape") for m in matches]
        return self._clean_payloads(payloads) if payloads else []

    def _extract_json_object(self, text: str) -> List[str]:
        """Extract a JSON object and return payloads if present."""
        start = text.find("{")
        end = text.rfind("}") + 1
        if start == -1 or end <= start:
            return []
        candidate = text[start:end]
        candidate = self._sanitize_json_escapes(candidate)
        try:
            data = json.loads(candidate)
            if isinstance(data, dict) and "payloads" in data:
                return self._clean_payloads(list(data.get("payloads", [])))
        except Exception:
            return []
        return []

    def _extract_truncated_payloads(self, text: str) -> List[str]:
        """Extract payload strings even if the JSON array is truncated."""
        marker = '"payloads"'
        if marker not in text:
            return []
        try:
            start = text.index("[", text.index(marker))
        except ValueError:
            return []
        raw = text[start:]
        payloads: List[str] = []
        buffer: List[str] = []
        in_string = False
        escape = False
        for ch in raw:
            if escape:
                buffer.append(ch)
                escape = False
                continue
            if ch == "\\":
                if in_string:
                    escape = True
                continue
            if ch == '"':
                if in_string:
                    payloads.append("".join(buffer))
                    buffer = []
                    in_string = False
                else:
                    in_string = True
                continue
            if in_string:
                buffer.append(ch)
        if in_string and buffer:
            payloads.append("".join(buffer))
        if not payloads:
            return []
        cleaned = [p.encode("utf-8").decode("unicode_escape") for p in payloads]
        return self._clean_payloads(cleaned)

    def generate_payloads(self, system_prompt: str, user_prompt: str) -> List[str]:
        """
        Generates security payloads via LM Studio (OpenAI API format).
        Expects a JSON array of strings in the response.
        """
        timeout_s = int(os.environ.get("LM_STUDIO_TIMEOUT_SECONDS", "60"))
        retries = int(os.environ.get("LM_STUDIO_RETRIES", "0"))

        payload_strict = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.1,
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

        # Fallback payload without response_format for OpenAI-compatible servers that don't support json_schema.
        payload_loose = dict(payload_strict)
        payload_loose.pop("response_format", None)

        for attempt in range(retries + 1):
            try:
                response = self._post_chat(payload_strict, timeout_s)
                if (not response.ok) and self._is_response_format_unsupported(response):
                    # Retry once without response_format.
                    response = self._post_chat(payload_loose, timeout_s)
                response.raise_for_status()

                data = response.json()
                content = data["choices"][0]["message"]["content"]

                # DEBUG
                _LOG_DIR.mkdir(parents=True, exist_ok=True)
                with open(_LOG_DIR / "llm_debug.log", "a", encoding="utf-8") as f:
                    f.write(f"--- PROMPT: {user_prompt[:50]}... ---\n")
                    f.write(f"--- CONTENT ---\n{content}\n--- END ---\n")

                # Primary parse path (structured JSON)
                try:
                    structured = json.loads(content)
                    if isinstance(structured, dict) and "payloads" in structured:
                        return self._clean_payloads(list(structured["payloads"]))
                except json.JSONDecodeError:
                    # Try sanitization for invalid escapes
                    try:
                        sanitized = self._sanitize_json_escapes(content)
                        structured = json.loads(sanitized)
                        if isinstance(structured, dict) and "payloads" in structured:
                            return self._clean_payloads(list(structured["payloads"]))
                    except Exception:
                        pass

                    # Trailing junk fix
                    if "}" in content:
                        try:
                            fixed_content = content[: content.rfind("}") + 1]
                            fixed_content = self._sanitize_json_escapes(fixed_content)
                            structured = json.loads(fixed_content)
                            if isinstance(structured, dict) and "payloads" in structured:
                                return self._clean_payloads(list(structured["payloads"]))
                        except Exception:
                            pass

                # Fallback extractors
                payloads = self._extract_json_object(content)
                if payloads:
                    return payloads

                payloads = self._extract_json_array(content)
                if payloads:
                    return payloads

                payloads = self._extract_payloads_from_object(content)
                if payloads:
                    return payloads

                payloads = self._extract_payloads_regex(content)
                if payloads:
                    return payloads

                payloads = self._extract_truncated_payloads(content)
                if payloads:
                    return payloads

                logger.warning("Failed to parse JSON from LLM: %s", content)
                return self._fallback_payloads(user_prompt)

            except Exception as e:
                logger.error(f"LM Studio error: {str(e)}")
                if attempt < retries:
                    time.sleep(1.0)
                    continue
                # Deterministic fallback keeps the security suite runnable even when
                # an external LLM service is misconfigured/offline/incompatible.
                return self._fallback_payloads(user_prompt)

    def _fallback_payloads(self, user_prompt: str) -> List[str]:
        """Deterministic payloads used when LM Studio is unavailable/incompatible.

        This is intentionally conservative: tests only require non-empty payloads
        to validate the orchestrator's defenses.
        """

        p = (user_prompt or "").lower()

        # Auth / token bypass prompts
        if "auth" in p or "token" in p or "authorization" in p:
            return self._clean_payloads(
                [
                    "invalid-token-1234567890",
                    "Bearer invalid-token-1234567890",
                    "A" * 32,
                    "test-token-00000000000000000000000000000000",
                ]
            )

        # Path traversal prompts
        if "travers" in p or "../" in p or "..\\" in p or "passwd" in p or "system32" in p:
            return self._clean_payloads(
                [
                    "../etc/passwd",
                    "..\\..\\windows\\system32\\config\\sam",
                    "....//....//etc/passwd",
                    "%2e%2e/%2e%2e/etc/passwd",
                    "..%2f..%2fwindows%2fsystem32%2fdrivers%2fetc%2fhosts",
                ]
            )

        # Special chars / unicode prompts
        if "unicode" in p or "control" in p or "special" in p:
            return self._clean_payloads(
                [
                    "..／..／etc／passwd",  # fullwidth slash
                    "..\\..\\Windows\\System32",
                    "\ufeff../etc/passwd",  # BOM prefix
                    "..\u200b/..\u200b/etc/passwd",  # zero-width
                ]
            )

        # Generic fallback
        return self._clean_payloads(
            [
                "../etc/passwd",
                "..\\..\\windows\\system32\\config\\sam",
                "A" * 32,
            ]
        )

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
        if response.status_code != 200:
            return False

        # Minimal completions probe to catch cases where /models works but /chat/completions stalls.
        probe_timeout_s = int(os.environ.get("LM_STUDIO_PROBE_TIMEOUT_SECONDS", "5"))
        # Important: mirror the stricter request format used by generate_payloads.
        # Some LM Studio / OpenAI-compat servers accept /models but reject response_format=json_schema.
        probe = {
            "model": os.environ.get("LM_STUDIO_MODEL", "qwen/qwen3-8b"),
            "messages": [
                {"role": "system", "content": "Return a JSON object with a payloads list."},
                {
                    "role": "user",
                    "content": "Return exactly: {\"payloads\":[\"ok\"],\"status\":\"SUCCESS\",\"thought_process\":\"x\"}",
                },
            ],
            "temperature": 0,
            "max_tokens": 64,
            "stream": False,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "availability_probe",
                    "schema": {
                        "type": "object",
                        "properties": {
                            "thought_process": {"type": "string"},
                            "payloads": {"type": "array", "items": {"type": "string"}},
                            "status": {"type": "string"},
                        },
                        "required": ["thought_process", "payloads", "status"],
                    },
                },
            },
        }
        probe_resp = requests.post(f"{host}/chat/completions", json=probe, timeout=probe_timeout_s)
        if probe_resp.status_code == 200:
            return True

        # Retry without response_format for servers that don't support json_schema.
        if probe_resp.status_code in {400, 404, 422}:
            probe.pop("response_format", None)
            probe_resp2 = requests.post(
                f"{host}/chat/completions", json=probe, timeout=probe_timeout_s
            )
            return probe_resp2.status_code == 200

        return False
    except Exception:
        return False
