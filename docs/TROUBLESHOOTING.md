# Troubleshooting

**Status**: NEEDS_REVIEW
**Last verified**: N/A

This document lists verified, reproducible issues and their resolution steps.

## 401 Token missing / Invalid token

Symptoms:

- API returns `401` with `Token missing` or `Invalid token`.

Fix:

1) Ensure you have a token:
   - set `ORCH_TOKEN` in your shell, or
   - read it from `tools/gimo_server/.orch_token` (auto-generated).
2) Call endpoints with the header:

```cmd
curl -H "Authorization: Bearer %ORCH_TOKEN%" http://127.0.0.1:9325/status
```

## 503 System in LOCKDOWN (Panic Mode)

Symptoms:

- API returns `503` and message mentions LOCKDOWN.

Cause:

- Panic mode was activated due to repeated invalid tokens or unhandled exceptions.

Fix:

Clear panic mode (requires valid token):

```cmd
curl -X POST -H "Authorization: Bearer %ORCH_TOKEN%" "http://127.0.0.1:9325/ui/security/resolve?action=clear_panic"
```

## Port already in use (9325)

Symptoms:

- Startup fails because port `9325` is already listening.

Fix:

- Windows: `scripts/ops/start_orch.cmd` attempts to kill any process listening on 9325.
- Otherwise, manually find and stop the process.

## UI cannot connect to API

Symptoms:

- UI loads but shows errors / empty status.

Fix:

1) Ensure backend is running on `http://localhost:9325`.
2) Configure UI:
   - set `VITE_API_URL=http://localhost:9325` in `tools/orchestrator_ui/.env.local`.

Known issue:

- UI fallback uses port `9325` if `VITE_API_URL` is not set.

## Allowlist appears empty

Symptoms:

- `/ui/status` reports `allowlist_count: 0`.

Notes:

- There is a known format mismatch between `allowed_paths.json` and the parser in `get_allowed_paths()`.
- Before 1.0, the allowlist format + enforcement must be made consistent.
