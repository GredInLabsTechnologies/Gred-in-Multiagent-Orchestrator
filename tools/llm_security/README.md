# LLM Security Infrastructure (Phase 1)

This directory contains the core defensive security layers for LLM integration. These modules are independent and designed to satisfy rigorous security requirements.

## Modules

### 1. `audit.py`
**Class**: `LLMAuditLogger`
Provides an immutable (append-only) audit trail of all LLM interactions.
- `log_interaction`: Logs phases like sanitization, LLM calls, and validation.
- `log_alert`: Logs security-critical events with varying severity levels.
- Format: Structured JSON logs for easy parsing and monitoring.

### 2. `input_sanitizer.py`
**Classes**: `SecretsFilter`, `PIIFilter`, `PromptInjectionDetector`, `InputSanitizer`
Deep inspection and cleaning of user input/code before it reaches the LLM.
- Removes API keys, tokens, passwords, and connection strings.
- Redacts PII (Emails, SSNs, CCs, IPs, Phones).
- Detects and neutralizes prompt injection attempts (e.g., "ignore previous instructions").
- `sanitize_full`: Orchestrates all filters and makes an ALLOW/DENY decision.

### 3. `scope_limiter.py`
**Class**: `ScopeLimiter`
Enforces strict resource limits on the context provided to the LLM.
- Limits the number of files (Max 10).
- Limits total tokens (Max 8000) and bytes per file (Max 100KB).
- Filter files by allowed extensions and denies access to sensitive paths (e.g., `.env`, `node_modules`).

### 4. `prompts.py`
- `HARDENED_SYSTEM_PROMPT`: A rock-solid system prompt designed to prevent jailbreaking and output leakage.
- `build_user_prompt`: Helper to structure user requests with appropriate safety metadata.

## Security Principles
- **Fail-Safe Defaults**: Any detected violation leads to a `DENY` action.
- **Independence**: Modules have ZERO dependencies on each other to ensure robustness.
- **Redaction**: Sensitive data is replaced with markers (e.g., `[REDACTED_API_KEY]`) rather than just being deleted.
