import re
from typing import Dict, List, Tuple


class SecretsFilter:
    """Layer 1: Remove secrets before sending to LLM"""

    PATTERNS = {
        "api_key": r'(?i)(api[_-]?key|apikey)\s*[:=]\s*["\']?([a-zA-Z0-9_\-]{20,})["\']?',
        "bearer_token": r"Bearer\s+([a-zA-Z0-9_\-\.]{20,})",
        "aws_key": r"AKIA[0-9A-Z]{16}",
        "private_key": r"-----BEGIN (?:RSA |EC )?PRIVATE KEY-----",
        "password": r'(?i)(password|passwd|pwd)\s*([:=]|is)\s*["\']?([^\s\'"]{8,})["\']?',
        "connection_string": r"(?i)(mongodb|postgres|mysql|redis)://[^\s]+",
        "jwt": r"eyJ[a-zA-Z0-9_-]*\.eyJ[a-zA-Z0-9_-]*\.[a-zA-Z0-9_-]*",
        "orch_token": r"ORCH_TOKEN\s*=\s*.+",
        "cloudflare_token": r"CLOUDFLARE_TUNNEL_TOKEN\s*=\s*.+",
    }

    @classmethod
    def sanitize(cls, content: str) -> Tuple[str, List[str]]:
        """
        Remove secrets from content.
        Returns: (sanitized_content, list_of_detected_secrets_types)
        """
        detected = []
        sanitized = content

        for secret_type, pattern in cls.PATTERNS.items():
            if re.search(pattern, sanitized):
                detected.append(secret_type)
                sanitized = re.sub(pattern, f"[REDACTED_{secret_type.upper()}]", sanitized)

        return sanitized, detected

    @classmethod
    def validate_clean(cls, content: str) -> bool:
        """Verify no secrets remain (safety check)"""
        for pattern in cls.PATTERNS.values():
            if re.search(pattern, content):
                return False
        return True


class PIIFilter:
    """Remove Personally Identifiable Information"""

    PATTERNS = {
        "email": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
        "ssn": r"\b\d{3}-\d{2}-\d{4}\b",
        "credit_card": r"\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b",
        "phone": r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b",
        "ip_address": r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
    }

    @classmethod
    def sanitize(cls, content: str) -> str:
        sanitized = content
        for pii_type, pattern in cls.PATTERNS.items():
            sanitized = re.sub(pattern, f"[REDACTED_{pii_type.upper()}]", sanitized)
        return sanitized


class PromptInjectionDetector:
    """Detect and neutralize prompt injection attempts"""

    SUSPICIOUS_PATTERNS = [
        r"(?i)ignore\s+.*(previous|all|above|system).*\s+instructions?",
        r"(?i)disregard\s+.*(previous|all|above|system)",
        r"(?i)forget\s+.*(everything|all|previous)",
        r"(?i)you\s+are\s+now\s+a\s+different",
        r"(?i)new\s+instructions?:",
        r"(?i)system\s+prompt:",
        r"(?i)---\s*end\s+of\s+",
        r"(?i)pretend\s+to\s+be",
        r"(?i)roleplay\s+as",
        r"(?i)act\s+as\s+if",
    ]

    @classmethod
    def detect(cls, content: str) -> Tuple[bool, List[str]]:
        """
        Returns: (is_suspicious, list_of_matched_patterns)
        """
        matches = []
        for pattern in cls.SUSPICIOUS_PATTERNS:
            if re.search(pattern, content):
                matches.append(pattern)

        return len(matches) > 0, matches

    @classmethod
    def neutralize(cls, content: str) -> str:
        """Replace injection attempts with safe markers"""
        neutralized = content
        for pattern in cls.SUSPICIOUS_PATTERNS:
            neutralized = re.sub(pattern, "[SUSPICIOUS_PATTERN_REMOVED]", neutralized)
        return neutralized


class InputSanitizer:
    """Combined Layer 1 sanitization"""

    @staticmethod
    def sanitize_full(content: str, abort_on_injection: bool = True) -> Dict:
        """
        Full sanitization pipeline for Layer 1

        Returns:
        {
            'action': 'ALLOW' | 'DENY',
            'sanitized_content': str,
            'detected_secrets': List[str],
            'detected_injections': List[str],
            'reason': str
        }
        """
        # Step 1: Secrets
        sanitized, secrets = SecretsFilter.sanitize(content)

        # Step 2: PII
        sanitized = PIIFilter.sanitize(sanitized)

        # Step 3: Injection detection
        is_injection, injection_patterns = PromptInjectionDetector.detect(sanitized)

        # Step 4: Decision
        if is_injection and abort_on_injection:
            return {
                "action": "DENY",
                "sanitized_content": None,
                "detected_secrets": secrets,
                "detected_injections": injection_patterns,
                "reason": "Prompt injection attempt detected",
            }

        # Step 5: Neutralize if not aborting
        if is_injection:
            sanitized = PromptInjectionDetector.neutralize(sanitized)

        # Step 6: Final validation
        is_clean = SecretsFilter.validate_clean(sanitized)

        return {
            "action": "ALLOW" if is_clean else "DENY",
            "sanitized_content": sanitized if is_clean else None,
            "detected_secrets": secrets,
            "detected_injections": injection_patterns,
            "reason": "Sanitization successful" if is_clean else "Secrets still present",
        }
