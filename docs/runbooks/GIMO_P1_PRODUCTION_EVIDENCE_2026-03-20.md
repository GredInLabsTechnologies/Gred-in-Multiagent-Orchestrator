# GIMO P1 Production Evidence - 2026-03-20

## Scope closed

### CLI

- `gimo init`
- `gimo plan`
- `gimo run`
- `gimo chat`
- `gimo status`
- `gimo diff`
- `gimo rollback`
- `gimo config`
- `gimo audit`
- `gimo watch`

Notes:

- Local state persists under `.gimo/`.
- Non-interactive commands expose `--json` for script integration.
- `run` polls live status until terminal state.
- `status` includes latest draft/approved/run plus backend health and realtime metrics.
- `rollback` wraps safe git rollback flows.
- `watch` consumes `/ops/stream` SSE events.

### MCP/API hardening covered here

- `plan_create`, `plan_execute`, and `cost_estimate` MCP aliases are registered.
- `/health/deep` is exposed and tested.
- Generic provider auth status/logout routes exist for `codex` and `claude`.
- Legacy compatibility routes exist for `/me` and `/ui/hardware`.

### Frontend/backend contract

- `tools/orchestrator_ui/src` fetch paths are scanned against mounted backend routes.
- The contract is enforced by automated test.

## Executed evidence

### P1 suite

Command:

```powershell
python -m pytest tests\unit\test_gimo_cli.py tests\unit\test_phase1_hardening.py tests\unit\test_phase1_skills.py tests\unit\test_phase1_mcp_aliases.py tests\unit\test_phase1_frontend_backend_contract.py tests\unit\test_codex_auth_routes.py tests\unit\test_routes.py::test_get_health_deep tests\unit\test_routes.py::test_get_ui_hardware tests\unit\test_routes.py::test_get_me_uses_cookie_session -q
```

Result:

```text
30 passed, 4 warnings in 62.07s
```

### P0 regression guard

Command:

```powershell
python -m pytest tests\integration\test_p0_ops_lifecycle.py tests\unit\test_phase7_merge_gate.py tests\unit\test_merge_gate_sandbox.py tests\integration\test_unified_engine.py -q
```

Result:

```text
27 passed, 3 warnings in 64.69s
```

## Files changed for this closure

- `gimo.py`
- `requirements.txt`
- `tests/unit/test_gimo_cli.py`
- `tools/gimo_server/routes.py`
- `tests/unit/test_routes.py`
- `tools/gimo_server/services/gics_service.py`
- `tools/gimo_server/services/skills_service.py`
- `tests/unit/test_phase1_skills.py`
- `tools/gimo_server/routers/ops/provider_auth_router.py`
- `tests/unit/test_codex_auth_routes.py`
- `tools/gimo_server/mcp_bridge/registrar.py`
- `tests/unit/test_phase1_mcp_aliases.py`
- `tests/unit/test_phase1_frontend_backend_contract.py`

## Operational conclusion

P1 is production-ready for the shipped platform surface above.
Remaining roadmap items outside this evidence are expansion work, not blockers for the validated CLI + MCP/API + UI contract surface.
