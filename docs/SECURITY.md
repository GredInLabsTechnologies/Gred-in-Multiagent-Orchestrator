# Security

**Status**: CURRENT
**Last verified**: 2026-03-04

This document describes the security model implemented in the current codebase.

## Security goals

1) Prevent repository exfiltration outside allowed boundaries
2) Prevent token / secret leakage in responses and logs
3) Fail closed under attack patterns
4) Provide forensic traceability (audit + snapshots)

## Controls implemented

### Authentication

- All API endpoints require `Authorization: Bearer <TOKEN>`.
- Three token roles exist:
  - **actions** (read-only): lowest privilege, blocked from non-read-only endpoints.
  - **operator**: can approve, create/cancel runs, view evals/trust/observability.
  - **admin**: full control, can mutate plans/provider/config and manage drafts.

Code:

- `tools/gimo_server/security/auth.py`
- `tools/gimo_server/routers/ops/common.py` (`_require_role()`)
- `tools/gimo_server/routers/auth_router.py`

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

## Provider Authentication

### Account mode (OAuth / Device Flow)

- Supported for Codex (OpenAI) and Claude (Anthropic).
- Device flow: user approves via browser, token stored securely.
- Refresh token management with automatic renewal.
- Fallback to `api_key` mode if account auth fails.

Code:

- `tools/gimo_server/services/codex_auth_service.py`
- `tools/gimo_server/services/claude_auth_service.py`
- `tools/gimo_server/services/provider_auth_service.py`
- `tools/gimo_server/services/provider_account_service.py`

## GIMO Web Authentication

- Firebase Auth (Google Sign-In) for user-facing web app.
- JWT-based license validation between orchestrator and GIMO Web.
- Ed25519 signature verification for offline license cache.
- Internal auth via shared secret (`GIMO_INTERNAL_KEY`).

Code: `apps/web/src/lib/`

## Verification approach
1) Run all **non-LLM** security suites and quality gates first.
2) Run LLM-driven adversarial suites last (requires LM Studio + Qwen).

Recommended evidence commands:

```cmd
python scripts\ci\quality_gates.py
bandit -c pyproject.toml -r tools scripts
pip-audit -r requirements.txt
```
