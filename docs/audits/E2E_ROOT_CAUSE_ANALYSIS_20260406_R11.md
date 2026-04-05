# GIMO Forensic Audit — Phase 2: Root-Cause Analysis (Round 11)

**Date**: 2026-04-06
**Auditor**: Claude Opus 4.6 (4 parallel investigation agents)
**Input**: `docs/audits/E2E_AUDIT_LOG_20260406_R11.md`

---

## Issue Map

| ID | Category | Root Cause Location | Confidence |
|----|----------|-------------------|------------|
| R11-#1 | MCP manifest drift | `mcp_bridge/manifest.py:91` | HIGH |
| R11-#2 | Wrong import path | `services/sagp_gateway.py:180,269` | HIGH |
| R11-#3 | MCP manifest type | `mcp_bridge/manifest.py:191` | HIGH |
| R11-#4 | Auto-run gate logic | `routers/ops/run_router.py:147-157` | HIGH |
| R11-#5 | MCP manifest drift | `mcp_bridge/manifest.py:103,106` | HIGH |
| R11-#6 | Wrong attribute name | `services/sagp_gateway.py:256-259` | HIGH |
| R11-#7 | Missing CLI commands | `gimo_cli/` (absent) | HIGH |
| R11-#8 | Method mismatch | `routers/ops/trust_router.py:14` | HIGH |
| R11-#9 | Missing GICS instance | `mcp_bridge/governance_tools.py:97-98` + `services/sagp_gateway.py:208` | HIGH |
| R11-#10 | Cookie-only design | `routers/auth_router.py:326-352` | HIGH |
| R11-#11 | Hardcoded allowlist | `services/conversation_service.py:31` | HIGH |
| R11-#12 | Bare except handler | `mcp_bridge/governance_tools.py:50-52` | HIGH |
| R11-#13 | Windows subprocess no shell | `providers/cli_account.py:178-184` | HIGH |

---

## Detailed Traces

### R11-#1: `gimo_providers_list` MCP returns 404

**Reported symptom**: MCP tool returns `{"detail": "Not Found"}` (404)
**Entry point**: MCP tool `gimo_providers_list`

**Trace**:
  → `mcp_bridge/manifest.py:87-91` — Manifest defines `method: 'GET'`, `path: '/ops/providers'`
  → `mcp_bridge/registrar.py:80` — `proxy_to_api('GET', '/ops/providers')` called
  → `mcp_bridge/bridge.py:53` — URL becomes `http://127.0.0.1:9325/ops/providers`
  → **NO ROUTE EXISTS** at `/ops/providers` (plural)
  → `routers/ops/config_router.py:14` — Actual endpoint is `@router.get("/provider")` → `/ops/provider` (SINGULAR)

**Root cause**: Manifest path uses plural `/ops/providers` but FastAPI route is singular `/ops/provider`. Route was renamed during P1 migration; manifest was not updated.

**Blast radius**: 4 manifest entries share the wrong base path:
| Tool | Manifest path (wrong) | Correct path |
|------|----------------------|--------------|
| `gimo_providers_list` | `GET /ops/providers` | `GET /ops/provider` |
| `gimo_providers_add` | `POST /ops/providers` | No `/ops/` equivalent |
| `gimo_providers_remove` | `DELETE /ops/providers/{id}` | No `/ops/` equivalent |
| `gimo_providers_test` | `POST /ops/providers/{id}/test` | See R11-#5 |

**Fix options**:
| Option | Location | Change | Risk |
|--------|----------|--------|------|
| A (recommended) | `manifest.py:91` | Change path to `/ops/provider` | NONE |
| B (full) | `manifest.py:91,96,101,106` | Fix all 4 entries or remove tools with no `/ops/` equivalent | LOW |

**Confidence**: HIGH

---

### R11-#2: `verify_proof_chain` import error

**Reported symptom**: `No module named 'tools.gimo_server.services.storage.storage_service'`
**Entry point**: MCP tool `gimo_verify_proof_chain`

**Trace**:
  → `mcp_bridge/governance_tools.py:152-161` — Calls `SagpGateway.verify_proof_chain(thread_id)`
  → `services/sagp_gateway.py:176-199` — Implementation of `verify_proof_chain`
  → `services/sagp_gateway.py:180` — **`from ..services.storage.storage_service import StorageService`** ← BREAKS
  → `services/storage/` directory contains: `config_storage.py`, `cost_storage.py`, `eval_storage.py`, `trust_storage.py`, `workflow_storage.py` — NO `storage_service.py`
  → `services/storage_service.py` — `StorageService` lives HERE (one level up, not inside `storage/` subdirectory)

**Root cause**: Wrong import path. The import `from ..services.storage.storage_service` resolves to `services/storage/storage_service.py` which doesn't exist. Correct import is `from .storage_service import StorageService` (relative to `services/` package). Every other file in `services/` uses this correct pattern.

**Blast radius**: 2 occurrences of the same bad import:
- Line 180: `verify_proof_chain()` — BROKEN (returns `valid: false`)
- Line 269: `_get_proof_chain_length()` — BROKEN (silently returns 0)
- `evaluate_action()` calls `_get_proof_chain_length()`, so **every governance evaluation gets `proof_chain_length: 0`** regardless of actual state

**Fix options**:
| Option | Location | Change | Risk |
|--------|----------|--------|------|
| A (recommended) | `sagp_gateway.py:180,269` | Change to `from .storage_service import StorageService` | NONE |

**Confidence**: HIGH

---

### R11-#3: `gimo_drafts_approve` MCP type mismatch

**Reported symptom**: `Input should be a valid string [type=string_type, input_value=True, input_type=bool]`
**Entry point**: MCP tool `gimo_drafts_approve`

**Trace**:
  → `mcp_bridge/manifest.py:189-192` — Declares `auto_run` with `'type': 'string'`
  → `mcp_bridge/registrar.py:32-33` — Maps `string` → Python `str`, generating `auto_run: str | None = None`
  → LLM sends `auto_run: true` (JSON boolean) → FastMCP's Pydantic rejects `bool` for `str` field
  → `routers/ops/run_router.py:120` — Actual endpoint declares `auto_run: Annotated[Optional[bool], Query(...)]` — expects **bool**

**Root cause**: Manifest declares `auto_run` as `type: 'string'` when it should be `type: 'boolean'`. Evidence of correct pattern: `gimo_config_set` at `manifest.py:476-478` correctly declares `default_auto_run` as `type: 'boolean'`.

**Blast radius**: Only `gimo_drafts_approve` affected. Combined with R11-#4, this completely blocks the MCP draft lifecycle (can't approve + can't auto-run).

**Fix options**:
| Option | Location | Change | Risk |
|--------|----------|--------|------|
| A (recommended) | `manifest.py:191` | Change `'type': 'string'` to `'type': 'boolean'` | NONE |

**Confidence**: HIGH

---

### R11-#4: `auto_run=true` HTTP approve does not create a run

**Reported symptom**: `POST /ops/drafts/{id}/approve?auto_run=true` returns `"run": null`
**Entry point**: HTTP endpoint `POST /ops/drafts/{id}/approve`

**Trace**:
  → `routers/ops/run_router.py:110-199` — Approve endpoint handler
  → Line 130: `execution_decision = draft.context.get("execution_decision", "")`
  → Lines 147-157 — Three-way AND gate:
  ```python
  should_run = (
      (auto_run if auto_run is not None else config.default_auto_run)  # ✓ True
      and execution_decision == "AUTO_RUN_ELIGIBLE"                    # ✗ "" != "AUTO_RUN_ELIGIBLE"
      and not auto_run_blocked_by_intent                               # ✓ not blocked
  )
  ```
  → Drafts created via `POST /ops/drafts` or MCP `gimo_create_draft` never set `execution_decision`
  → Default is empty string `""`, fails the `== "AUTO_RUN_ELIGIBLE"` check
  → `should_run` is always `False` for these drafts

**Root cause**: The `execution_decision` gate blocks all drafts not created through the full engine pipeline (risk_gate, intent_classification, plan_router). Direct API/MCP drafts never receive `AUTO_RUN_ELIGIBLE` status.

**Which paths set `AUTO_RUN_ELIGIBLE`**:
| Creation path | `execution_decision` | Auto-run? |
|---------------|---------------------|-----------|
| `engine/stages/risk_gate.py:27` (low risk) | `AUTO_RUN_ELIGIBLE` | YES |
| `services/intent_classification_service.py:184` (read-only) | `AUTO_RUN_ELIGIBLE` | YES |
| `routers/ops/plan_router.py:326,531` (plan execute) | `AUTO_RUN_ELIGIBLE` | YES |
| Direct API `POST /ops/drafts` | `""` (empty) | **NO** |
| MCP `gimo_create_draft` | `""` (empty) | **NO** |
| `services/intent_classification_service.py:164` (code change) | `HUMAN_APPROVAL_REQUIRED` | NO |

**Blast radius**: Any draft created via API or MCP and approved with `auto_run=true` will silently not run. The `auto_run` parameter is misleading — it appears to be an override but is actually gated by internal classification.

**Fix options**:
| Option | Location | Change | Risk |
|--------|----------|--------|------|
| A (transparency) | `run_router.py:157` | Add `"auto_run_skipped_reason"` to response when `should_run=False` | NONE |
| B (recommended) | `run_router.py:153-156` | When `auto_run` is explicitly `True` (user override), skip the `execution_decision` gate but still respect `RISK_SCORE_TOO_HIGH` | LOW |
| C (defensive) | `run_router.py:130` | Default `execution_decision` to `AUTO_RUN_ELIGIBLE` when empty/missing for operator-created drafts | MEDIUM |

**Confidence**: HIGH

---

### R11-#5: `gimo_providers_test` MCP returns 405

**Reported symptom**: `{"detail": "Method Not Allowed"}` (405)
**Entry point**: MCP tool `gimo_providers_test`

**Trace**:
  → `mcp_bridge/manifest.py:102-106` — Declares `method: 'POST'`, `path: '/ops/providers/{provider_id}/test'`
  → CLI equivalent: `gimo_cli/commands/providers.py:151` — Uses `api_request(config, "GET", f"/ops/connectors/{provider_id}/health")`
  → `routers/ops/config_router.py:99` — Actual endpoint: `@router.get("/connectors/{connector_id}/health")` → `GET /ops/connectors/{id}/health`

**Root cause**: TWO mismatches — wrong HTTP method (`POST` vs `GET`) AND wrong path (`/ops/providers/{id}/test` vs `/ops/connectors/{id}/health`).

**Blast radius**: Only `gimo_providers_test` affected. Other provider manifest entries share the path issue (R11-#1).

**Fix options**:
| Option | Location | Change | Risk |
|--------|----------|--------|------|
| A (recommended) | `manifest.py:103,106` | Change to `method: 'GET'`, `path: '/ops/connectors/{provider_id}/health'` | NONE |

**Confidence**: HIGH

---

### R11-#6: GICS daemon not alive

**Reported symptom**: `gics_health.daemon_alive: false` in governance snapshot
**Entry point**: `gimo_get_governance_snapshot`

**Trace**:
  → `services/sagp_gateway.py:256` — `_get_gics_health()` creates fresh `GicsService()` instance
  → `services/sagp_gateway.py:257` — Checks `hasattr(gics, "_daemon") and gics._daemon is not None`
  → `services/gics_service.py:63` — **`GicsService` stores supervisor in `self._supervisor`**, NOT `self._daemon`
  → `hasattr(gics, "_daemon")` always returns `False` → `daemon_alive: false`

**Root cause**: TWO bugs:
1. Attribute name mismatch: checks `_daemon` but `GicsService` uses `_supervisor`
2. Creates a fresh `GicsService()` instead of using the shared instance from `app.state.gics`

**Blast radius**: Every governance snapshot reports `daemon_alive: false` and `entry_count: 0`, regardless of actual GICS state. Dashboard and MCP consumers always see dead GICS.

**Fix options**:
| Option | Location | Change | Risk |
|--------|----------|--------|------|
| A (recommended) | `sagp_gateway.py:256-259` | Use shared `StorageService._shared_gics` + check `_supervisor` instead of `_daemon` | LOW |

**Confidence**: HIGH

---

### R11-#7: CLI `graph` and `capabilities` commands missing

**Reported symptom**: "No such command 'graph'" / "No such command 'capabilities'"
**Entry point**: `python gimo.py graph` / `python gimo.py capabilities`

**Trace**:
  → `gimo_cli/__init__.py:43-58` — All CLI commands registered via imports
  → No `@app.command("graph")` or `@app.command("capabilities")` exists in any `gimo_cli/commands/*.py` file
  → `routers/ops/graph_router.py:65` — API `GET /ops/graph` exists and works
  → `ops_routes.py:158` — API `GET /ops/capabilities` exists and works
  → `gimo_cli/api.py:111` — `fetch_capabilities()` exists for internal use (bond, timeouts) but not exposed as CLI command

**Root cause**: Accidental omission during CLI development. API endpoints exist, MCP tools exist, but no CLI commands were ever created.

**Blast radius**: Low. Both features accessible via API and MCP. Only CLI users lack these.

**Fix options**:
| Option | Location | Change | Risk |
|--------|----------|--------|------|
| A (recommended) | `gimo_cli/commands/ops.py` | Add `@app.command("graph")` and `@app.command("capabilities")` following existing patterns | NONE |

**Confidence**: HIGH

---

### R11-#8: `/ops/trust/query` returns 404

**Reported symptom**: `GET /ops/trust/query` → 404
**Entry point**: HTTP GET request

**Trace**:
  → `routers/ops/trust_router.py:14` — Endpoint defined as `@router.post("/trust/query")`
  → `GET /ops/trust/query` returns 404 because no GET handler exists (FastAPI doesn't return 405 for method mismatches on nonexistent GET routes)
  → MCP manifest at `manifest.py:298-301` correctly declares `method: 'POST'`

**Root cause**: Endpoint is POST-only. The Phase 1 audit tested with GET.

**Blast radius**: Low. MCP callers use POST correctly. Only manual API testing with GET is affected.

**Fix options**:
| Option | Location | Change | Risk |
|--------|----------|--------|------|
| A | Documentation | Document that `/ops/trust/query` requires POST | NONE |
| B | `trust_router.py:14` | Add GET handler with `dimension_key` as query param | LOW |

**Confidence**: HIGH

---

### R11-#9: Trust profile empty vs snapshot divergence

**Reported symptom**: `gimo_get_trust_profile` → `[]` but `gimo_get_governance_snapshot` → `{provider: 0.85, model: 0.85, tool: 0.85}`
**Entry point**: Both MCP tools

**Trace (snapshot path)**:
  → `services/sagp_gateway.py:137-139` — Calls `_get_trust_score("provider")`, etc.
  → `sagp_gateway.py:204` — Creates `TrustStorage()` **without** `gics_service` arg
  → `TrustStorage.list_trust_events()` returns `[]` (no GICS → no data)
  → `TrustEngine.query_dimension()` returns `score: 0.0`
  → `sagp_gateway.py:214` — **Fallback: `return score if score > 0.0 else 0.85`** ← Synthetic value

**Trace (trust profile path)**:
  → `mcp_bridge/governance_tools.py:97-98` — Creates `TrustStorage()` **without** `gics_service`
  → `TrustEngine.dashboard(limit=20)` → `list_trust_events()` → `[]`
  → Returns `[]` faithfully (no fallback)

**Root cause**: Both paths create `TrustStorage()` without passing the shared GICS instance, so all data queries return empty. The divergence comes from the snapshot having a hardcoded `0.85` fallback while the trust profile returns raw empty results.

**Blast radius**: HIGH — Trust scores in governance snapshots are **synthetic** (always 0.85). Trust-based governance decisions operate on fake data. The trust profile is always empty, rendering the trust dashboard useless.

**Fix options**:
| Option | Location | Change | Risk |
|--------|----------|--------|------|
| A (recommended) | `governance_tools.py:97` + `sagp_gateway.py:204` | Pass `StorageService._shared_gics` to `TrustStorage()` | LOW |
| B | `sagp_gateway.py:214` | Remove 0.85 fallback, return actual 0.0 | LOW (but may break UI expectations) |

**Confidence**: HIGH

---

### R11-#10: `/auth/check` returns false for Bearer token

**Reported symptom**: `GET /auth/check` with valid Bearer token → `{authenticated: false}`
**Entry point**: HTTP GET with Bearer header

**Trace**:
  → `routers/auth_router.py:326-352` — `check_session()` reads `request.cookies.get(SESSION_COOKIE_NAME)`
  → No check for `Authorization` header
  → Docstring: "Check if the current session cookie is valid"
  → By design: dual auth system — Bearer (API/CLI) vs cookie (UI)

**Root cause**: `/auth/check` is intentionally cookie-only. Bearer tokens are validated by `verify_token` dependency on `/ops/` endpoints, not by `/auth/check`.

**Blast radius**: Low. API/CLI callers get misleading `authenticated: false` but all actual API calls work. Confusing, not broken.

**Fix options**:
| Option | Location | Change | Risk |
|--------|----------|--------|------|
| A (recommended) | `auth_router.py:326-352` | Add Bearer token check as fallback after cookie check | NONE |
| B | Documentation | Document that `/auth/check` is cookie-only | NONE |

**Confidence**: HIGH

---

### R11-#11: `add_turn` agent_id restrictive

**Reported symptom**: `Unsupported thread agent_id 'claude-operator'. Allowed values: User, orchestrator, system, user`
**Entry point**: MCP tool `gimo_threads_add_turn`

**Trace**:
  → `services/conversation_service.py:31` — `_ALLOWED_TURN_AGENT_IDS = frozenset({"user", "User", "system", "orchestrator"})`
  → `conversation_service.py:258-267` — `_validate_turn_agent_id()` checks `normalized not in cls._ALLOWED_TURN_AGENT_IDS`
  → `claude-operator` not in frozenset → raises `ValueError`
  → `routers/ops/conversation_router.py:111` — `ValueError` → `HTTPException(400)`

**Root cause**: Hardcoded frozenset was designed for internal use only. SAGP migration introduced surface-aware identifiers but the validation was never updated. Also note case inconsistency: both `"user"` and `"User"` exist.

**Blast radius**: Medium. Any MCP/external client sending surface-specific agent_ids gets 400. Internal code unaffected (all use `"user"`, `"orchestrator"`, `"system"`).

**Fix options**:
| Option | Location | Change | Risk |
|--------|----------|--------|------|
| A | `conversation_service.py:31` | Expand frozenset with known surface IDs | LOW |
| B (recommended) | `conversation_service.py:258-267` | Use pattern validation (regex `^[a-zA-Z][a-zA-Z0-9_-]{0,63}$`) instead of hardcoded set | LOW |
| C | `conversation_service.py:258` | Normalize surface IDs to canonical roles (e.g., `claude-operator` → `orchestrator`) | LOW |

**Confidence**: HIGH

---

### R11-#12: Malformed `evaluate_action` returns unstructured error

**Reported symptom**: `{"error": "Expecting value: line 1 column 1 (char 0)"}`
**Entry point**: MCP tool `gimo_evaluate_action`

**Trace**:
  → `mcp_bridge/governance_tools.py:37` — `tool_args = json.loads(tool_args_json)` throws `json.JSONDecodeError`
  → `governance_tools.py:50-52` — `except Exception as e: return json.dumps({"error": str(e)})`
  → Raw Python exception message propagated without GIMO error envelope

**Root cause**: Bare `except Exception` handler in governance tools returns unstructured `{"error": str(e)}` instead of a proper error envelope with `code`, `type`, `detail`, `surface` fields.

**Blast radius**: All 8 governance MCP tools in `governance_tools.py` use the same pattern. Any exception in any of them produces unstructured errors.

**Fix options**:
| Option | Location | Change | Risk |
|--------|----------|--------|------|
| A (recommended) | `governance_tools.py` | Add `json.JSONDecodeError` catch before general except; use structured envelope | NONE |
| B (thorough) | `governance_tools.py` | Create shared `_mcp_error(code, detail)` helper for all 8 tools | NONE |

**Confidence**: HIGH

---

### R11-#13: `CliAccountAdapter` fails on Windows — `[WinError 2]`

**Reported symptom**: `[WinError 2] El sistema no puede encontrar el archivo especificado` when using codex-account provider
**Entry point**: `gimo chat -m "..." -w <path>` or `gimo plan "..." -w <path>` with codex-account active

**Trace**:
  → `providers/cli_account.py:155` — `shutil.which(self.binary)` finds `codex` (returns `codex.cmd` path) ✓
  → `providers/cli_account.py:164` — `cmd = self._build_cmd(...)` builds command list `["codex", "exec", ...]`
  → `providers/cli_account.py:178-184` — Windows path: `_subprocess.run(cmd, ...)` **without `shell=True`**
  → Windows `CreateProcess` cannot execute `.cmd` files directly → `[WinError 2]`

**Correct pattern already exists**: `codex_auth_service.py:27-29`:
```python
if sys.platform == "win32":
    return subprocess.Popen(" ".join(args), shell=True, **kwargs)
```

**Root cause**: The Windows subprocess invocation in `CliAccountAdapter.generate()` uses `subprocess.run(cmd, ...)` (list form, no shell) which cannot execute `.cmd` shims from npm. The same file's `_create_process` helper at line 36-39 also has the correct Windows handling with `create_subprocess_shell`, but `generate()` doesn't use it — it has its own inline subprocess code.

**Blast radius**: ALL Codex CLI operations on Windows are broken: chat, plan, run, any LLM generation via codex-account provider. Auth works because `CodexAuthService` has its own correct `_popen` wrapper.

**Fix options**:
| Option | Location | Change | Risk |
|--------|----------|--------|------|
| A (recommended) | `cli_account.py:178-184` | Add `shell=True` and join cmd to string on Windows: `_subprocess.run(" ".join(cmd), shell=True, ...)` | LOW — matches `codex_auth_service.py` pattern |
| B (thorough) | `cli_account.py:178-195` | Use the existing `_create_process` helper instead of inline subprocess code | LOW — reduces duplication |

**Confidence**: HIGH

---

## Probe B Deep Dive: Cross-Provider Governance & Execution

### Governance Parity Verification

All 9 governance paths were traced at the code level for both Claude and OpenAI/Codex providers:

| Governance Path | Parity Status | Evidence |
|----------------|---------------|----------|
| Draft creation | IDENTICAL | `services/ops/_draft.py:58-87` — no provider-conditional logic |
| Policy gate | IDENTICAL | `engine/stages/policy_gate.py:11-49` — zero provider references |
| Risk gate | IDENTICAL | `engine/stages/risk_gate.py:14-43` — intent-based, not provider-based |
| LLM execute | IDENTICAL | `engine/stages/llm_execute.py:13-77` — delegates via adapter polymorphism |
| Cost tracking | IDENTICAL | `services/economy/cost_service.py` — model-name-based, both adapters normalize to same usage shape |
| GICS recording | IDENTICAL | `services/gics_service.py:356-408` — `record_model_outcome()` called for all providers via `service_impl.py:717-727` |
| Trust engine | IDENTICAL | `services/trust_engine.py:29-248` — dimension-keyed, zero provider awareness |
| Proof chain | IDENTICAL | `agentic_loop_service.py:555-572` — thread-keyed, no provider field |
| SSE events | IDENTICAL | `iteration_cost`/`cumulative_cost` derived from provider-agnostic `CostService` |
| Cascade | IDENTICAL | `services/economy/cascade_service.py:15-157` — tier-based from unified inventory |
| Model router | IDENTICAL | `services/model_router_service.py:71-806` — multi-objective scoring, no provider bias |

**Conclusion**: GIMO's governance is genuinely provider-agnostic. No governance bypass or special-casing exists for any provider. The only provider-specific code is in the adapter layer (connection/auth), not in the governance stack.

### CliAccountAdapter Deep Analysis

**File**: `tools/gimo_server/providers/cli_account.py`

3 subprocess call sites analyzed:

| Method | Subprocess mechanism | Windows `.cmd` handling |
|--------|---------------------|------------------------|
| `_create_process()` (line 35-39) | `asyncio.create_subprocess_shell` on win32 | CORRECT |
| `generate()` (line 167-198) | `subprocess.run(cmd, ...)` via `asyncio.to_thread` | **BROKEN** — no `shell=True` |
| `health_check()` (line 318) | Uses `_create_process()` | CORRECT (inherits fix) |

**Why `generate()` doesn't use `_create_process()`**: The Windows path in `generate()` was written separately to support stdin piping via temp files (bypass 8191-char cmd limit). The developer built custom subprocess code but forgot `shell=True`.

**`shell=True` safety**: The command at this point is `["codex", "exec", "-", "--json"]` — all hardcoded strings. The user prompt goes through stdin (file handle), never touching the shell's argument parser. No injection risk.

**Alternative path**: `OpenAICompatAdapter` (`openai_compat.py`) makes direct HTTP calls to OpenAI API. Could bypass CLI entirely if user has an API key, but `CliAccountAdapter` exists for users who want OAuth/browser auth without managing API keys.

**`_is_codex` / `_is_claude` edge case**: Both flags use substring matching (`"codex" in self.binary.lower()`). A binary named `"claude-codex"` would set both to `True`, with Claude behavior winning (checked first at line 129).

### Auto-Run Gate: Additional Findings (R11-#4 extension)

**Critical discovery: Two `approve` tools with different governance enforcement**

| Tool | Location | Gates enforced | Creates run? |
|------|----------|----------------|-------------|
| `gimo_drafts_approve` (manifest) | `manifest.py:189` → HTTP endpoint | All 3 gates (auto_run + execution_decision + intent) | Only if all gates pass |
| `gimo_approve_draft` (native) | `native_tools.py:346-353` | **NONE** | **ALWAYS** |
| `gimo_run_task` (native) | `native_tools.py:309-325` | **NONE** | **ALWAYS** (auto-approve + auto-run) |
| `POST /ops/runs` (HTTP) | `run_router.py:227-277` | **NONE** (only needs valid `approved_id`) | ALWAYS |

The native MCP `gimo_approve_draft` at `native_tools.py:346` is a **governance escape hatch**:
```python
def gimo_approve_draft(draft_id: str) -> str:
    approved = OpsService.approve_draft(draft_id, approved_by="human")
    run = OpsService.create_run(approved.id)  # Always creates run, no gates
    return f"Approved. Run: {run.id}"
```

**Additional finding**: `app_router.py:153` uses `"MANUAL_REVIEW_REQUIRED"` which is not a valid `ExecutionDecisionCode` (the Literal type defines `"HUMAN_APPROVAL_REQUIRED"`). Same blocking effect but type-incorrect.

**`fallback_to_most_restrictive_human_review`**: This is correct defensive behavior at `intent_classification_service.py:187-193`. When a draft has no intent classification data, the system correctly defaults to requiring human review rather than auto-running unknown work.

---

## Systemic Patterns

### Pattern 1: MCP Manifest Drift (R11-#1, #3, #5)

**3 of 12 issues** stem from `mcp_bridge/manifest.py` being out of sync with actual FastAPI routes. The manifest is a hand-maintained JSON-like structure that maps MCP tool names to HTTP endpoints. When routes are renamed, moved, or their signatures change during refactoring, the manifest is not automatically updated.

**Future failure modes**: Every new route migration or parameter change risks introducing new manifest drift. Currently 4 of ~40 manifest entries have wrong paths — the drift rate is ~10%.

**What would make this impossible**: Auto-generate the manifest from FastAPI route introspection (OpenAPI schema), or validate manifest against live routes at startup.

### Pattern 2: Missing Shared GICS Instance (R11-#6, #9)

**2 issues** stem from services creating fresh `GicsService()` or `TrustStorage()` instances instead of using the shared instance from `app.state.gics` or `StorageService._shared_gics`. Fresh instances have no data connection, no event history, and no daemon.

**Future failure modes**: Any new service that needs GICS data will face the same trap — it's too easy to `GicsService()` when you should use the shared singleton.

**What would make this impossible**: Remove the `GicsService()` default constructor or make it raise an error when called without explicit binding. Force all access through `StorageService._shared_gics`.

### Pattern 3: Dual Approve Tools with Governance Gap (R11-#4)

The same logical operation ("approve a draft and run it") has **two implementations** with completely different governance enforcement. The manifest-based `gimo_drafts_approve` respects all 3 auto-run gates. The native `gimo_approve_draft` bypasses all gates and always creates a run. This means the governance enforcement of auto-run depends on WHICH tool the operator happens to call — an architecture-level invariant violation.

**Future failure modes**: An operator (or a prompt-injected LLM) could call `gimo_approve_draft` instead of `gimo_drafts_approve` to bypass governance. The `gimo_run_task` native tool is even more permissive — it auto-approves AND auto-runs with zero checks.

**What would make this impossible**: Funnel all approve operations through a single `OpsService.approve_and_maybe_run()` method that enforces governance uniformly, regardless of entry point (HTTP, MCP manifest, MCP native).

### Pattern 4: Import Path Confusion (R11-#2)

The `services/` directory has a `storage/` subdirectory containing domain-specific storage modules AND a `storage_service.py` at the `services/` level. The naming overlap (`storage` package vs `storage_service` module) is a trap.

**Future failure modes**: Any new code importing `StorageService` might accidentally use the wrong path.

**What would make this impossible**: Rename `storage_service.py` to avoid ambiguity, or add `StorageService` to `services/storage/__init__.py`.

---

## Dependency Graph

```
Pattern 1: Manifest Drift
  └── R11-#1 (providers_list 404)
  └── R11-#3 (drafts_approve type)
  └── R11-#5 (providers_test 405)

Pattern 2: Missing Shared GICS
  └── R11-#6 (GICS daemon false)
  └── R11-#9 (trust profile empty)

Pattern 3: Import Confusion
  └── R11-#2 (proof chain import error)

Independent:
  └── R11-#4 (auto_run gate) — execution pipeline design
  └── R11-#7 (CLI missing commands) — omission
  └── R11-#8 (trust/query 404) — method mismatch
  └── R11-#10 (auth/check Bearer) — design choice
  └── R11-#11 (add_turn agent_id) — hardcoded allowlist
  └── R11-#12 (error envelope) — error handling pattern
```

---

## Preventive Findings

1. **Manifest validation at startup**: If the MCP bridge validated every manifest entry against the live OpenAPI schema at startup, R11-#1, #3, and #5 would have been caught immediately as import-time errors rather than runtime 404/405s.

2. **Singleton enforcement for GICS**: If `GicsService()` raised `RuntimeError("Use StorageService._shared_gics")` when called without arguments, R11-#6 and #9 would have been caught at first execution.

3. **Type-safe MCP parameter declarations**: If manifest parameter types were validated against their corresponding FastAPI endpoint signatures (from OpenAPI), R11-#3 would be impossible.

4. **`auto_run` contract clarity**: The `auto_run=true` parameter creates a false expectation. Either it should be an actual override (Option B in R11-#4) or the response should explain why it was ignored.

---

## Recommended Fix Priority

| Priority | Issues | Rationale |
|----------|--------|-----------|
| 1 (highest) | R11-#1, #3, #5, #13 | Manifest fixes + Windows subprocess — unblocks MCP provider management, draft lifecycle, and Codex execution |
| 2 | R11-#2 | Import fix — 2 lines, unblocks proof chain verification |
| 3 | R11-#4 | Auto-run gate — core functionality, unblocks draft→run pipeline via API/MCP |
| 4 | R11-#6, #9 | Shared GICS — 2 changes, fixes trust and GICS health reporting |
| 5 | R11-#12 | Error envelope — structural improvement for all 8 governance tools |
| 6 | R11-#11 | Agent ID validation — expand or liberalize the allowlist |
| 7 | R11-#7 | CLI commands — low severity, nice-to-have |
| 8 (lowest) | R11-#8, #10 | Documentation/design — minimal impact |
