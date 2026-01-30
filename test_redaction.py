import re

# Test the redaction pattern
pattern = re.compile(r"ghp_[a-zA-Z0-9]{32,}")
test_content = 'github_token = "ghp_1234567890abcdefghijklmnopqrstuv"'

result = pattern.sub("[REDACTED]", test_content)
print(f"Original: {test_content}")
print(f"Redacted: {result}")
print(f"'ghp_' in result: {'ghp_' in result}")

# The actual test token length
test_token = "ghp_1234567890abcdefghijklmnopqrstuv"
print(f"\nToken length: {len(test_token)}")
print(f"Token without prefix: {len(test_token) - 4}")
