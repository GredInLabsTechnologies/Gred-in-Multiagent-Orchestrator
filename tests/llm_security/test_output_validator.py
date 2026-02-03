from tools.llm_security.output_validator import OutputValidator


def test_forbidden_patterns_api_keys():
    validator = OutputValidator()
    # OpenAI API Key
    bad_output = "Here is my key: sk-1234567890abcdef1234567890abcdef"
    result = validator.validate(bad_output)
    assert result["is_valid"] is False
    assert "openai_api_key" in result["violations"][0]
    assert result["action"] == "DENY"


def test_forbidden_patterns_aws_keys():
    validator = OutputValidator()
    # AWS Key
    bad_output = "Secret: AKIA1234567890ABCDEF"
    result = validator.validate(bad_output)
    assert result["is_valid"] is False
    assert "aws_key" in result["violations"][0]


def test_forbidden_patterns_private_keys():
    validator = OutputValidator()
    # Private Key (test pattern, not real) # noqa: S105
    bad_output = (  # nosec B105 - test data only
        "-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA75...\n-----END RSA PRIVATE KEY-----"
    )
    result = validator.validate(bad_output)
    assert result["is_valid"] is False
    assert "private_key" in result["violations"][0]


def test_forbidden_patterns_pii():
    validator = OutputValidator()
    # SSN
    bad_output = "My SSN is 123-45-6789"
    result = validator.validate(bad_output)
    assert result["is_valid"] is False
    assert "ssn" in result["violations"][0]

    # Credit Card
    bad_output = "Card: 1234-5678-9012-3456"
    result = validator.validate(bad_output)
    assert result["is_valid"] is False
    assert "credit_card" in result["violations"][0]


def test_structure_validation():
    validator = OutputValidator()

    # Valid structure
    good_output = "## Summary\nAll good.\n## Issues Found\nNone.\n## Conclusion\nSafe."
    result = validator.validate(good_output)
    assert result["is_valid"] is True
    assert result["action"] == "ALLOW"

    # Missing Summary
    bad_output = "## Issues Found\nNone.\n## Conclusion\nSafe."
    result = validator.validate(bad_output)
    assert result["is_valid"] is False
    assert "## Summary" in result["violations"][0]


def test_length_validation():
    validator = OutputValidator()
    long_output = "## Summary\n" + ("x" * 10001) + "\n## Issues Found\nNone\n## Conclusion\nEnd"
    result = validator.validate(long_output)
    assert result["is_valid"] is False
    assert "length" in result["violations"][0].lower()


def test_security_violation_marker():
    validator = OutputValidator()
    bad_output = "## Summary\nSomething\nSECURITY_VIOLATION_DETECTED\n## Issues Found\nNone\n## Conclusion\nDone"
    result = validator.validate(bad_output)
    assert result["is_valid"] is False
    assert "security violation" in result["violations"][0].lower()


def test_emergency_sanitization():
    validator = OutputValidator()
    output = "Key sk-1234567890abcdef1234567890abcdef and SSN 123-45-6789"
    sanitized = validator.sanitize_if_needed(output)
    assert "sk-" not in sanitized
    assert "123-45-6789" not in sanitized
    assert "[REDACTED_OPENAI_API_KEY]" in sanitized
    assert "[REDACTED_SSN]" in sanitized


def test_empty_output():
    validator = OutputValidator()
    result = validator.validate("")
    assert result["is_valid"] is False
    assert result["action"] == "DENY"
