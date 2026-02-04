# Exhaustive adversarial prompts for LLM-guided security testing
# Designed for Qwen 3 8B or similar models

SYSTEM_ADVERSARIAL_MASTER = """
You are a world-class penetration tester with expertise in:
- OWASP Top 10 vulnerabilities
- Path traversal and LFI/RFI attacks
- Authentication bypass techniques
- Injection attacks (SQL, Command, LDAP, XPath)
- Security misconfiguration exploitation
- Cryptographic failures

Target System:
- FastAPI backend (Python 3.12)
- Windows 11 host environment
- Bearer token authentication
- File read API with path validation
- Rate limiting (60 req/min)
- Panic mode (fail-closed after 5 invalid auth attempts)

Your task: Generate creative, technical attack payloads.

Response Format:
{
    "thought_process": "Brief analysis of attack strategy",
    "payloads": ["payload1", "payload2", ...],
    "attack_category": "path_traversal|auth_bypass|injection|etc",
    "severity_estimate": "critical|high|medium|low"
}

Rules:
1. NO conversational text outside JSON
2. NO code expressions inside strings (use literal values)
3. Payloads must be raw values, not wrapped in header syntax
4. Be creative with encodings and edge cases
"""

ATTACK_VECTORS = {
    # ═══════════════════════════════════════════════════════════════
    # PATH TRAVERSAL ATTACKS (30+ variations)
    # ═══════════════════════════════════════════════════════════════
    "path_traversal_basic": """
    Generate 15 basic path traversal payloads for GET /file?path=
    Include:
    - Unix style: ../, ....//
    - Windows style: ..\\, ....\\\\
    - Mixed: ../..\\
    - Root escapes: /../../../etc/passwd
    """,
    "path_traversal_encoded": """
    Generate 15 URL-encoded path traversal payloads:
    - Single encoding: %2e%2e%2f
    - Double encoding: %252e%252e%252f
    - Mixed encoding: ..%2f, %2e%2e/
    - Unicode encoding: %c0%ae%c0%ae/
    - Overlong UTF-8: %c0%2e%c0%2e/
    """,
    "path_traversal_null_byte": """
    Generate 10 null byte injection payloads:
    - Classic: ../../../etc/passwd%00.txt
    - Encoded null: ../../../etc/passwd%2500.png
    - Double null: ../etc/passwd%00%00
    - Truncation: ....//....//etc/passwd%00.jpg
    """,
    "path_traversal_windows": """
    Generate 15 Windows-specific path traversal payloads:
    - Drive letters: C:/Windows/System32/config/SAM
    - UNC paths: \\\\127.0.0.1\\c$\\Windows\\win.ini
    - Short names: C:/PROGRA~1/
    - Device names: CON, PRN, AUX, NUL, COM1, LPT1
    - ADS: file.txt::$DATA
    - Long paths: \\\\?\\C:\\...
    """,
    "path_traversal_filter_bypass": """
    Generate 15 filter bypass payloads:
    - Double dots: ....//....//
    - Triple dots: ...//...//.../
    - Nested: ..././..././
    - Case variation: ..\\..\\..\\
    - Whitespace: .. /, ..%20/, ..%09/
    - Comments: ..;/, ..#/
    """,
    "path_traversal_combo": """
    Generate 20 hybrid path traversal payloads that combine:
    - Double encoding + Windows UNC
    - NTFS ADS + traversal
    - Mixed separators + overlong UTF-8
    - Long path prefix (\\\\?\\) with traversal
    - Environment variables (e.g. %WINDIR%) if applicable
    """,
    # ═══════════════════════════════════════════════════════════════
    # AUTHENTICATION BYPASS (25+ variations)
    # ═══════════════════════════════════════════════════════════════
    "auth_empty_variations": """
    Generate 10 empty/null token variations:
    - Empty string
    - Whitespace only: spaces, tabs, newlines
    - Null character: \\x00
    - Unicode null: \\u0000
    - Zero-width chars: \\u200b, \\ufeff
    """,
    "auth_length_boundary": """
    Generate 10 length boundary test tokens:
    - Min length -1: 15 chars
    - Exact minimum: 16 chars
    - Very long: 10000+ chars
    - Max int: 2147483647 repeated
    - Binary padding
    """,
    "auth_format_attacks": """
    Generate 10 format string attack tokens:
    - Printf: %s%s%s%s%s%s%s%s%s%s
    - Python format: {0}{1}{2}
    - Template injection: {{config}}
    - SQL fragments: ' OR '1'='1
    - NoSQL: {"$gt": ""}
    """,
    "auth_encoding_attacks": """
    Generate 10 encoding-based tokens:
    - Base64 of valid pattern
    - Hex encoded
    - URL encoded special chars
    - Unicode normalization attacks
    - UTF-7 encoding
    - Punycode
    """,
    "auth_timing_attacks": """
    Generate 5 tokens designed for timing attacks:
    - Tokens that might cause slow comparison
    - Tokens matching prefix of valid token
    - Tokens with special regex chars: .*+?^$
    """,
    "auth_parser_smuggling": """
    Generate 10 payloads that attempt to confuse Bearer token parsing:
    - Multiple spaces, tabs, mixed unicode whitespace
    - Embedded nulls and control chars
    - Duplicate prefixes: "Bearer Bearer <token>"
    - Mixed-case bearer schemes
    """,
    # ═══════════════════════════════════════════════════════════════
    # INJECTION ATTACKS (20+ variations)
    # ═══════════════════════════════════════════════════════════════
    "injection_command": """
    Generate 10 command injection payloads for path parameter:
    - Semicolon: ; whoami
    - Pipe: | dir
    - Backticks: `id`
    - $() substitution: $(whoami)
    - Newline: \\nwhoami
    - Windows: & dir, && dir
    """,
    "injection_sql": """
    Generate 10 SQL injection probes for path parameter:
    - Classic: ' OR 1=1--
    - Union: ' UNION SELECT NULL--
    - Time-based: ' AND SLEEP(5)--
    - Boolean: ' AND 1=1--, ' AND 1=2--
    - Stacked: '; DROP TABLE--
    """,
    "injection_ldap": """
    Generate 5 LDAP injection payloads:
    - Wildcard: *
    - Filter bypass: )(cn=*
    - Null injection: \\00
    """,
    "injection_xpath": """
    Generate 5 XPath injection payloads:
    - Boolean: ' or '1'='1
    - Union: '] | //user/*[1
    """,
    "injection_ssti": """
    Generate 10 Server-Side Template Injection payloads:
    - Jinja2: {{7*7}}, {{config}}
    - Mako: ${7*7}
    - Tornado: {{import os}}
    - Generic: ${7*7}, #{7*7}, @(7*7)
    """,
    "injection_windows_shell": """
    Generate 10 Windows shell injection payloads:
    - PowerShell: powershell -c "Get-ChildItem"
    - CMD metacharacters: & | && ||
    - Delayed expansion tricks
    - Unicode-escaped cmd separators
    """,
    # ═══════════════════════════════════════════════════════════════
    # RATE LIMIT BYPASS (10+ techniques)
    # ═══════════════════════════════════════════════════════════════
    "ratelimit_header_spoofing": """
    Generate 10 header spoofing techniques to bypass IP-based rate limiting:
    - X-Forwarded-For variations
    - X-Real-IP
    - X-Originating-IP
    - X-Client-IP
    - True-Client-IP
    - CF-Connecting-IP
    - IPv6 variations of same host
    """,
    "ratelimit_timing": """
    Generate 5 timing-based bypass patterns:
    - Burst then pause
    - Slow drip (1 req/sec)
    - Distributed timing
    - Just under threshold
    """,
    # ═══════════════════════════════════════════════════════════════
    # PANIC MODE EVASION (10+ techniques)
    # ═══════════════════════════════════════════════════════════════
    "panic_evasion": """
    Generate 10 techniques to potentially evade panic mode:
    - Token rotation between attempts
    - IP rotation simulation
    - Timing between attempts
    - Valid token interspersed with invalid
    - Targeting different endpoints
    """,
    # ═══════════════════════════════════════════════════════════════
    # SPECIAL CHARACTER ATTACKS (15+ variations)
    # ═══════════════════════════════════════════════════════════════
    "special_unicode": """
    Generate 15 Unicode-based attack payloads:
    - RTL override: \\u202e
    - Zero-width: \\u200b, \\u200c, \\u200d
    - Homoglyphs: Cyrillic а vs Latin a
    - Combining chars: e + ́ = é
    - Full-width: ．．／ (U+FF0E, U+FF0F)
    - Emoji in paths
    """,
    "special_control_chars": """
    Generate 10 control character payloads:
    - Bell: \\x07
    - Backspace: \\x08
    - Tab: \\x09
    - Form feed: \\x0c
    - Carriage return: \\x0d
    - Escape: \\x1b
    - Delete: \\x7f
    """,
    "special_path_weirdness": """
    Generate 15 payloads with path edge cases:
    - Trailing dots/spaces
    - Alternate separators and reserved names
    - Mixed UTF-8 normalization
    - Percent-encoded backslashes and colons
    """,
}

ADAPTIVE_SYSTEM_PROMPT = """
You are an adaptive penetration testing AI. You learn from failures.

Current Attack Context:
- Previous payload: {previous_payload}
- Server response: {response_code} - {response_body}
- Security events triggered: {security_events}
- Attempts remaining: {attempts_remaining}

Analysis required:
1. Why did the previous attack fail?
2. What security mechanism blocked it?
3. How can we bypass that specific mechanism?

Generate a NEW payload that:
- Uses a different encoding than before
- Targets the same vulnerability from a new angle
- Avoids the specific filter that blocked us

Response format:
{
    "analysis": "Why previous failed",
    "bypass_strategy": "New approach",
    "new_payload": "the actual payload string",
    "confidence": 0.0-1.0
}
"""

MUTATION_STRATEGIES = [
    "double_encode",  # %2e -> %252e
    "unicode_normalize",  # .. -> ．．
    "case_swap",  # ../ -> ../
    "null_inject",  # add %00
    "whitespace_pad",  # add spaces/tabs
    "comment_inject",  # add ; or #
    "path_fragment",  # split across params
    "nested_encode",  # mix encodings
]
