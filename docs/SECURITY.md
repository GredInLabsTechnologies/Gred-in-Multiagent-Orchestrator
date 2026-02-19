# Security

**Status**: NEEDS_REVIEW
**Last verified**: N/A

This document describes the security model implemented in the current codebase.

## Security goals

1) Prevent repository exfiltration outside allowed boundaries
2) Prevent token / secret leakage in responses and logs
3) Fail closed under attack patterns
4) Provide forensic traceability (audit + snapshots)

## Controls implemented

### Authentication

- All API endpoints require `Authorization: Bearer <TOKEN>`.
- Two token roles exist:
  - **admin**: full access
  - **actions** (read-only): blocked from non-read-only endpoints by `require_read_only_access`.

Code:

- `tools/gimo_server/security/auth.py`
- `tools/gimo_server/routes.py`

### Rate limiting

- Window-based limiter (default 100 requests / 60s).
- Returns `429` when exceeded.

Code: `tools/gimo_server/security/rate_limit.py`.

### Path traversal shield

- `validate_path()` normalizes a path and enforces that the resolved target is within the active base directory.
- Null-byte rejection.
- Windows reserved device names rejection.

Code: `tools/gimo_server/security/validation.py`.

### Redaction

- Regex-based redaction for common secret formats (OpenAI, GitHub PAT, AWS keys, generic API keys, long tokens).
- Applied to file outputs and git diff outputs.
- Audit logging redacts long actor tokens.

Code: `tools/gimo_server/security/audit.py`.

### Panic mode (LOCKDOWN)

- Threshold-based trigger on repeated invalid token attempts.
- Threshold-based trigger on unhandled exceptions.
- Blocks unauthenticated access while in lockdown.

Code:

- `tools/gimo_server/middlewares.py`
- `tools/gimo_server/security/auth.py`

### License gate (startup + periodic)

- Service startup enforces license validation before serving requests.
- License is validated online against GIMO WEB and falls back to offline cache only when cryptographically valid.
- Offline cache is AES-GCM encrypted and machine-bound (fingerprint-derived key).
- JWT offline validation requires valid Ed25519 signature and clock sanity checks.
- Periodic recheck interval and grace period are configurable via env:
  - `ORCH_LICENSE_GRACE_DAYS`
  - `ORCH_LICENSE_RECHECK_HOURS`

Security defaults:

- Missing `ORCH_LICENSE_KEY` fails closed.
- DEBUG mode does **not** bypass license gate by default.
- Optional local-lab bypass requires explicit opt-in:
  - `ORCH_LICENSE_ALLOW_DEBUG_BYPASS=true`

Required env for production license setup:

- `ORCH_LICENSE_KEY`
- `ORCH_LICENSE_URL`
- `ORCH_LICENSE_PUBLIC_KEY`

## Allowlist (known gap)

There is an allowlist mechanism intended to constrain enumeration.

Known mismatch to resolve before 1.0:

- `tools/gimo_server/allowed_paths.json` currently contains objects with `{path, expires_at}`.
- `get_allowed_paths()` currently expects a JSON with `timestamp` and a `paths` list of strings.

This can result in an empty allowlist at runtime and breaks the intended guardrail.

## Verification approach
1) Run all **non-LLM** security suites and quality gates first.
2) Run LLM-driven adversarial suites last (requires LM Studio + Qwen).

Recommended evidence commands:

```cmd
python scripts\\ci\\quality_gates.py
python scripts\quality_gates.py
bandit -c pyproject.toml -r tools scripts
pip-audit -r requirements.txt
```
