import re
from typing import Any, Dict


class OutputValidator:
    """
    Layer 5: Validate and sanitize LLM output.
    Ensures no sensitive data leaks and the output follows the expected structure.
    """

    # Patterns that should NEVER appear in output
    FORBIDDEN_PATTERNS = {
        "openai_api_key": r"sk-[a-zA-Z0-9]{32,}",
        "aws_key": r"AKIA[0-9A-Z]{16}",
        "private_key": r"-----BEGIN (?:RSA |EC )?PRIVATE KEY-----",
        "bearer_token": r"Bearer [a-zA-Z0-9_\-\.]{20,}",
        "ssn": r"\d{3}-\d{2}-\d{4}",
        "credit_card": r"\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}",
    }

    # Expected format markers
    EXPECTED_STRUCTURE = [
        r"## Summary",
        r"## Issues Found",
        r"## Conclusion",
    ]

    # Maximum response length (~2500 tokens * 4 chars/token)
    MAX_OUTPUT_LENGTH = 10000

    @classmethod
    def validate(cls, output: str) -> Dict[str, Any]:
        """
        Validate LLM output against security policies.

        Returns:
            Dict: {
                'is_valid': bool,
                'sanitized_output': str | None,
                'violations': List[str],
                'action': 'ALLOW' | 'DENY',
                'reason': str
            }
        """
        if not output:
            return {
                "is_valid": False,
                "sanitized_output": None,
                "violations": ["Empty output"],
                "action": "DENY",
                "reason": "Output is empty",
            }

        violations = []

        # Check for forbidden patterns
        for category, pattern in cls.FORBIDDEN_PATTERNS.items():
            if re.search(pattern, output):
                violations.append(f"Forbidden pattern detected: {category}")

        # Check for security violation marker (if LLM itself detects it)
        if "SECURITY_VIOLATION_DETECTED" in output:
            violations.append("LLM-triggered security violation")

        # Check format structure
        missing_markers = []
        for marker in cls.EXPECTED_STRUCTURE:
            if not re.search(marker, output):
                missing_markers.append(marker)

        if missing_markers:
            violations.append(f'Missing structure markers: {", ".join(missing_markers)}')

        # Check length
        if len(output) > cls.MAX_OUTPUT_LENGTH:
            violations.append(f"Output length {len(output)} exceeds limit {cls.MAX_OUTPUT_LENGTH}")

        # Final decision
        is_valid = len(violations) == 0

        return {
            "is_valid": is_valid,
            "sanitized_output": output if is_valid else None,
            "violations": violations,
            "action": "ALLOW" if is_valid else "DENY",
            "reason": "Validation passed" if is_valid else "Security policy violations detected",
        }

    @classmethod
    def sanitize_if_needed(cls, output: str) -> str:
        """
        Apply emergency sanitization to output by redacting forbidden patterns.
        Used for logging or when a partially safe output is acceptable.
        """
        if not output:
            return ""

        sanitized = output
        for category, pattern in cls.FORBIDDEN_PATTERNS.items():
            sanitized = re.sub(pattern, f"[REDACTED_{category.upper()}]", sanitized)

        return sanitized


if __name__ == "__main__":
    # Example usage for reference
    """
    validator = OutputValidator()
    result = validator.validate("## Summary\nFine\n## Issues Found\nNone\n## Conclusion\nDone")
    print(result['is_valid'])
    """
    pass
