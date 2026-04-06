# GIMO Forensic Audit — Phase 2: Root-Cause Analysis (Round 12)

**Date**: 2026-04-06
**Auditor**: Claude Opus 4.6 (4 parallel investigation agents)
**Input**: `E2E_AUDIT_LOG_20260406_R12.md`
**Issues traced**: 13 (5 BLOCKER, 2 CRITICAL, 3 GAP, 2 INCONSISTENCY, 1 FRICTION)

---

## Issue Map

| ID | Category | Root Cause Location | Confidence |
|----|----------|---------------------|------------|
| R12-#1 | Manifest lifecycle | `scripts/generate_manifest.py` destroys hand-crafted names | HIGH |
| R12-#2 | Manifest path | `manifest.py` → `/ops/providers` (plural) vs `/ops/provider` (singular) | HIGH |
| R12-#3 | Stale bytecache | `.pyc` cache serving pre-R11 import paths | HIGH (90%) |
| R12-#4 | Manifest type + name | `auto_run` type correct in new manifest, but tool name destroyed | HIGH |
| R12-#5 | `should_run` gate | `run_router.py:153-157` requires `AUTO_RUN_ELIGIBLE` + silent exception swallow | HIGH (98%) |
| R12-#6 | Shallow validation | `connector_service.py:402-413` checks binary, not credentials | HIGH (95%) |
| R12-#7 | GICS binary missing | `gics_service.py:87-89` `start_daemon()` silently returns if CLI not found | HIGH (95%) |
| R12-#8 | Schema fidelity | `generate_manifest.py:59` drops `items` schema; latent `anyOf` bug in body params | HIGH |
| R12-#9 | Non-issue | `--no-confirm` already exists at `run.py:28`; missing `--yes` alias only | HIGH (99%) |
| R12-#10 | Dual data source | `api.py:222` injects `X-Gimo-Workspace` header; MCP/HTTP don't | HIGH (98%) |
| R12-#11 | Presentation mismatch | `sagp_gateway.py:217` hardcoded `0.85` fallback vs empty truth in trust store | HIGH (98%) |
| R12-#12 | Stale bytecache | `json.JSONDecodeError` catch IS present on disk; stale server | HIGH (95%) |
| R12-#13 | No credential validation | `_enrich_with_vault_key` checks existence, not validity | HIGH (97%) |

---

## Detailed Traces

### R12-#1: 7 of 11 R11 fixes do not persist

**Reported symptom**: After server restart, 7 R11 fixes are broken despite being "resolved" with 1377 tests passing.

**Entry point**: MCP tool calls via Claude App

**Trace**:
```
scripts/generate_manifest.py:12   → app.openapi() generates spec
scripts/generate_manifest.py:23   → uses operationId as tool name
                                     (e.g., "approve_draft_ops_drafts__draft_id__approve_post")
scripts/generate_manifest.py:81-88 → writes to tools/gimo_server/mcp_bridge/manifest.py
                                     !! OVERWRITES hand-crafted manifest with gimo_* names
tools/gimo_server/mcp_bridge/manifest.py → now has auto-generated ugly names
tools/gimo_server/mcp_bridge/server.py:76 → _register_dynamic() loads new manifest
tools/gimo_server/mcp_bridge/registrar.py:17-92 → registers tools with NEW names
                                     WHERE IT BREAKS: all gimo_* names are gone
```

**Root cause**: `generate_manifest.py` is a **destructive full-regenerator** that replaces the entire manifest with OpenAPI-derived names. The old manifest was hand-crafted with semantic `gimo_*` names. R11 ran the generator, producing verbose auto-names (e.g., `list_ui_providers_ui_providers_get`). There is NO CI step, NO pre-commit hook, NO automated sync mechanism. The `.pre-commit-config.yaml` and `.github/workflows/ci.yml` have zero manifest-related steps.

**BUT**: The tests pass because they exercise HTTP endpoints directly via `TestClient`, **never** through the MCP bridge. The MCP→HTTP proxy chain (`tool_call → registrar → proxy_to_api → HTTP`) is completely untested.

**Blast radius**: Every dynamically registered MCP tool name changed. All MCP clients caching old tool lists get tool-not-found for ALL ~60 dynamic tools. Native tools (`native_tools.py`) are unaffected.

**Fix options**:

| Option | Location | Change | Risk |
|--------|----------|--------|------|
| A (recommended) | `generate_manifest.py` | Add name mapping convention: OpenAPI operationId → `gimo_` prefix with snake_case derivation | MEDIUM |
| B | `manifest.py` | Revert to pre-R11 hand-crafted manifest, then fix specific path/type bugs | LOW but drift recurs |
| C | CI pipeline | Add `generate_manifest.py` as CI step + diff check to prevent drift | LOW |

**Confidence**: HIGH

---

### R12-#2: `gimo_providers_list` MCP returns 404

**Reported symptom**: `gimo_providers_list` → `{"detail": "Not Found"}` (404)

**Entry point**: MCP tool `gimo_providers_list`

**Trace**:
```
OLD manifest (pre-R11):
  manifest.py:89    → name: 'gimo_providers_list', path: '/ops/providers' (PLURAL — WRONG)
  registrar.py:80   → proxy_to_api("GET", "/ops/providers")
  FastAPI routing   → NO MATCH → 404
                      WHERE IT BREAKS: endpoint is /ops/provider (SINGULAR)

Actual endpoint:
  config_router.py:14  → @router.get("/provider")  (singular)
  ops_routes.py:16-23  → prefix="/ops" → final: GET /ops/provider

CURRENT manifest (post-R11):
  manifest.py:45    → name: 'list_ui_providers_ui_providers_get', path: '/ui/providers'
                      Tool name destroyed AND path points to legacy UI route

OpenAPI spec (openapi.yaml:1049):
  Correctly declares /ops/provider (singular) — the manifest never matched
```

**Root cause**: Two compounding bugs:
1. Hand-crafted manifest had wrong path `/ops/providers` (plural). Actual is `/ops/provider` (singular) at `config_router.py:14`.
2. R11 regeneration destroyed the `gimo_providers_list` name and replaced it with `list_ui_providers_ui_providers_get` pointing to the legacy UI route.

**Blast radius**: `gimo_providers_list`, `gimo_providers_add`, `gimo_providers_remove`, `gimo_providers_test` all have wrong paths or destroyed names.

**Fix options**:

| Option | Location | Change | Risk |
|--------|----------|--------|------|
| A (recommended) | `manifest.py` | Restore `gimo_providers_list`, fix path to `/ops/provider` (singular) | LOW |
| B | `config_router.py` | Add `@router.get("/providers")` plural alias | LOW — route sprawl |

**Confidence**: HIGH

---

### R12-#3: `verify_proof_chain` import error

**Reported symptom**: `No module named 'tools.gimo_server.services.storage.storage_service'`

**Entry point**: MCP tool `gimo_verify_proof_chain`

**Trace**:
```
governance_tools.py:162  → gimo_verify_proof_chain()
governance_tools.py:163  → from tools.gimo_server.services.sagp_gateway import SagpGateway
sagp_gateway.py:183      → from .storage_service import StorageService [CORRECT on disk]

BUT error says: 'tools.gimo_server.services.storage.storage_service'
                                                    ^^^^^^^ extra segment

Current file on disk:
  sagp_gateway.py: uses "from .storage_service import StorageService" (relative, CORRECT)
  governance_tools.py:98: uses "from tools.gimo_server.services.storage_service import StorageService" (absolute, CORRECT)
```

**Root cause**: The R11 import fix IS present on disk. The error `storage.storage_service` (with extra `storage` segment) comes from a **stale `.pyc` bytecache** compiled from the pre-R11 code where the import was `from tools.gimo_server.services.storage.storage_service`. The running server loaded the cached bytecode instead of recompiling from the fixed `.py` file.

**Blast radius**: `gimo_verify_proof_chain` and `gimo_get_trust_profile` both affected. Any governance tool with lazy imports could be hit by stale cache.

**Fix options**:

| Option | Location | Change | Risk |
|--------|----------|--------|------|
| A (recommended) | `GIMO_LAUNCHER.cmd` + startup | Delete `__pycache__` dirs before server start | LOW |
| B | Environment | Set `PYTHONDONTWRITEBYTECODE=1` in dev | LOW |
| C | CI | Add `find . -name __pycache__ -exec rm -rf {} +` to CI pre-step | LOW |

**Confidence**: 90%

---

### R12-#4: `gimo_drafts_approve` MCP type mismatch

**Reported symptom**: `Input should be a valid string [type=string_type, input_value=True, input_type=bool]`

**Entry point**: MCP tool `gimo_drafts_approve`

**Trace**:
```
OLD manifest: auto_run type 'string' — MCP sends string "true" → FastAPI parses → works
NEW manifest: auto_run type 'boolean' — matches OpenAPI spec (CORRECT)
                                       httpx serializes True as "True" → FastAPI parses → works

ACTUAL problem: the tool name 'gimo_drafts_approve' no longer exists (R12-#1)
                the Claude allow list references it → MCP says tool not found
```

Wait — the Phase 1 error was a Pydantic validation error, not a 404. This means the tool IS being found through some path. Investigating further:

The `gimo_drafts_approve` tool is defined as a **native tool** in `native_tools.py:369`:
```
native_tools.py:369   → async def gimo_approve_draft(draft_id: str, auto_run: bool = True)
native_tools.py:379   → __query={"auto_run": str(auto_run).lower()}
```

BUT the tool also existed in the OLD manifest as `gimo_drafts_approve`, which was a **dynamic proxy tool**. The Pydantic error comes from the proxy path where the registrar passes the raw boolean to httpx query params, and the FastAPI endpoint's Pydantic model for query params expects a specific type.

**Root cause**: The tool `gimo_drafts_approve` is registered from the **old manifest** (pre-R11 hand-crafted) which declared `auto_run` as type `string`. When MCP sends `true` (boolean), the registrar at `registrar.py:67-69` puts it directly as a query param. The Pydantic model on the endpoint sees a boolean where it expects a string. The native tool `gimo_approve_draft` at `native_tools.py:379` correctly converts to `str(auto_run).lower()`.

**Fix options**:

| Option | Location | Change | Risk |
|--------|----------|--------|------|
| A (recommended) | `manifest.py` | Fix `auto_run` type to `'boolean'` in the `gimo_drafts_approve` entry | LOW |
| B | `registrar.py:67-69` | Add bool→string coercion for query params: `str(v).lower() if isinstance(v, bool) else v` | LOW — defensive |

**Confidence**: HIGH

---

### R12-#5: No surface can execute a run

**Reported symptom**: MCP (type mismatch), CLI (no --yes flag), HTTP (run: null) — all paths blocked.

**Entry point**: `POST /ops/drafts/{id}/approve?auto_run=true`

**Trace (HTTP path — THE CRITICAL ONE)**:
```
run_router.py:120   → auto_run: Optional[bool] = None → True ✓
run_router.py:129-130 → context = dict(draft.context or {})
                         execution_decision = str(context.get("execution_decision") or "")
run_router.py:147-157 → THE should_run GATE:

  should_run = (
      (auto_run if auto_run is not None else config.default_auto_run)  # ① True ✓
      and execution_decision == "AUTO_RUN_ELIGIBLE"                      # ② FAILS
      and not auto_run_blocked_by_intent                                 # ③ True ✓
  )

run_router.py:167-197 → if should_run: create_run() → BUT should_run is False
run_router.py:196-197 → except Exception: pass ← SILENT SWALLOW of any error
run_router.py:199     → return OpsApproveResponse(approved=approved, run=None)
```

**WHY condition ② fails**: Drafts created via `POST /ops/drafts` go through `IntentClassificationService.evaluate()` which returns `AUTO_RUN_ELIGIBLE` ONLY for low-risk intents (`DOC_UPDATE`, `TEST_ADD`, `SAFE_REFACTOR`) with risk score ≤ 30. Everything else → `HUMAN_APPROVAL_REQUIRED`. The draft created in Phase 1 got `"execution_decision": "HUMAN_APPROVAL_REQUIRED"` with `"decision_reason": "fallback_to_most_restrictive_human_review"`.

**The semantic contradiction**: The user explicitly passes `auto_run=true` (human approval IS given), but the system ignores this explicit override because the intent classification gate is upstream and immutable.

**Secondary bug**: `run_router.py:196-197` swallows ALL exceptions with `except Exception: pass`. If `create_run()` fails (repo unresolvable, lock conflict), the error is silently lost and `run` returns `null` with no explanation.

**CLI path — NOT BROKEN**: `gimo run` already has `--confirm/--no-confirm` at `run.py:28`. Running `gimo run <id> --no-confirm` works. The Phase 1 test used stdin pipe which triggered the `sys.stdin.isatty()` guard at `run.py:58`.

**Workaround exists**: `POST /ops/runs` with `{"approved_id": "..."}` bypasses the `should_run` gate entirely and immediately spawns the run.

**Blast radius**: HIGH. Every surface that uses `approve?auto_run=true` is affected. The silent exception swallow masks additional failures.

**Fix options**:

| Option | Location | Change | Risk |
|--------|----------|--------|------|
| A (recommended) | `run_router.py:153` | When `auto_run=True` is explicit query param (not from config default), treat it as override — bypass `execution_decision` check. The explicit human action IS the approval. | LOW |
| B | `run_router.py:196-197` | Replace `except Exception: pass` with `except Exception as e: run_error = str(e)` and include in response | LOW |
| C | `run_router.py:199` | Add `run_blocked_reason` field to response explaining which condition failed | LOW |

**Confidence**: 98%

---

### R12-#6: `providers test` reports healthy but API key is invalid

**Reported symptom**: `providers test claude-account` → "authenticated (api_key)" but `gimo plan` → 401 Unauthorized

**Entry point**: CLI `gimo providers test claude-account`

**Trace**:
```
providers.py:151       → GET /ops/connectors/claude-account/health
  connector_service.py:392-431 → _resolve_connector("claude-account") → ("claude_code", None)
  connector_service.py:402-413 → shutil.which("claude") → True
                                  subprocess("claude --version") → "2.1.44"
                                  → {"healthy": True}  ← BINARY EXISTS, NOT KEY VALIDATED

providers.py:158-159   → GET /ops/connectors/claude/auth-status
  provider_auth_router.py:116-126 → ClaudeAuthService.get_auth_status()
  provider_auth_router.py:15-36 → _enrich_with_vault_key("claude", data)
    → checks if ORCH_PROVIDER_CLAUDE_ACCOUNT_API_KEY EXISTS in secret_store
    → key EXISTS → {"authenticated": True, "method": "api_key"}
      WHERE IT BREAKS: existence ≠ validity

Actual API call during gimo plan:
  adapter_registry.py:28 → resolve_secret(entry) → gets expired key from vault
  anthropic_adapter.py:211-217 → POST /v1/messages → 401 Unauthorized
```

**Root cause**: Two-layer shallow validation:
1. `connector_health` checks binary installation (`shutil.which`), not API credentials.
2. `_enrich_with_vault_key` reports `authenticated=True` if key EXISTS in vault, regardless of validity.

**An unused validate endpoint EXISTS**: `catalog_router.py:97-114` — `POST /ops/connectors/{type}/validate` calls `ProviderCatalogService.validate_credentials()`. Also, `AnthropicAdapter.health_check()` at `anthropic_adapter.py:219-235` makes a real API call. Neither is used by `providers test`.

**Blast radius**: ALL users with expired/revoked keys see green health status. First failure at actual LLM call time.

**Fix options**:

| Option | Location | Change | Risk |
|--------|----------|--------|------|
| A (recommended) | `connector_service.py:402-413` | For `claude_code` type: if vault has key, call `AnthropicAdapter.health_check()` | LOW |
| B | `providers.py:158` | After auth-status, also call `POST /ops/connectors/{type}/validate` | LOW |
| C | `main.py` startup | Background task validates all stored keys on boot | LOW |

**Confidence**: 95%

---

### R12-#7: GICS `daemon_alive` always false

**Reported symptom**: `gics_health.daemon_alive: false, entry_count: 0`

**Entry point**: `gimo_get_governance_snapshot`

**Trace**:
```
sagp_gateway.py:256-267  → _get_gics_health()
sagp_gateway.py:260      → gics = StorageService._shared_gics
sagp_gateway.py:263      → alive = hasattr(gics, "_supervisor") and gics._supervisor is not None

gics_service.py:63       → self._supervisor: Optional[GICSDaemonSupervisor] = None
gics_service.py:87-89    → start_daemon():
                              if not self._cli_path:
                                  logger.error("GICS CLI not found")
                                  return  ← _supervisor stays None

main.py:276              → gics_service = GicsService()
                            gics_service.start_daemon()  ← silently fails if CLI missing
```

**Root cause**: `start_daemon()` at `gics_service.py:87-89` has a guard: if the GICS CLI binary is not found at the expected path, it logs an error and returns silently, leaving `_supervisor = None`. The attribute check at `sagp_gateway.py:263` correctly detects this. The daemon literally IS NOT alive — this is truthful, not a bug in the health check.

The real bug is: **no GICS CLI binary exists** in this Windows dev environment (or it's at a different path). The conftest mocks `start_daemon` which hides this in tests.

**Blast radius**: All GICS-dependent features report degraded health. No trust events stored, no proof chain entries, no cost event persistence.

**Fix options**:

| Option | Location | Change | Risk |
|--------|----------|--------|------|
| A | `gics_service.py:87` | Log WARN (not just error) + add `self._daemon_available = False` flag for explicit health reporting | LOW |
| B (recommended) | `sagp_gateway.py:263` | Check `gics._client` connectivity instead of `_supervisor` object existence — true liveness probe | LOW |
| C | Startup | Emit a clear console warning: "GICS daemon not available — governance telemetry disabled" | LOW |

**Confidence**: 95%

---

### R12-#8: `gimo_drafts_create` schema missing types for complex params

**Reported symptom**: `constraints="string"` → `Input should be a valid list`

**Entry point**: MCP tool `gimo_drafts_create`

**Trace**:
```
generate_manifest.py:56-61 → for body props: prop_val.get("type", "string")
  constraints: has "type": "array" → manifest gets 'array' ✓ CORRECT
  BUT: "items": {"type": "string"} is LOST → generator ignores items schema

registrar.py:35 → 'array' → py_type = 'list'
MCP client sends list → FastAPI Pydantic validates items → WORKS
```

**Root cause**: The `constraints` type IS present as `array`. The Phase 1 error occurred when passing a STRING (`"Python only, pytest"`) rather than a list — this is correct Pydantic validation. The actual schema fidelity gap is: `items` sub-schema is dropped, so MCP clients don't know the array should contain strings.

**Latent bug**: `generate_manifest.py:56-61` does NOT resolve `anyOf` for body properties. If any body field were `Optional[List[str]]`, it would get `anyOf: [{type: array}, {type: null}]` and the generator would default to `type: "string"` (WRONG). Currently no such field exists, but it's a time bomb.

**Blast radius**: Low for `constraints`. The latent `anyOf` bug affects future `Optional[list]`/`Optional[dict]` body fields.

**Fix options**:

| Option | Location | Change | Risk |
|--------|----------|--------|------|
| A | `generate_manifest.py:56-61` | Add `anyOf` resolution for body params (mirror lines 34-38 logic) | LOW |
| B | `generate_manifest.py:59` | Include `items` key in param dict when present | LOW |

**Confidence**: HIGH

---

### R12-#9: `gimo run` lacks `--yes` flag

**Reported symptom**: `gimo run <id>` aborts without stdin

**Entry point**: CLI `gimo run`

**Trace**:
```
run.py:28  → confirm: bool = typer.Option(True, "--confirm/--no-confirm", ...)
run.py:58-62 → if confirm and sys.stdin.isatty():
                    if not typer.confirm(...): raise typer.Exit(1)
```

**Root cause**: **This issue was mischaracterized in Phase 1.** The `--no-confirm` flag EXISTS at `run.py:28`. Running `gimo run <id> --no-confirm` skips the prompt. In non-TTY environments, `sys.stdin.isatty()` returns `False`, so the prompt is also skipped. The Phase 1 test piped stdin which caused `typer.confirm` to read EOF → abort.

The only real gap is: no `--yes` / `-y` alias (user expectation mismatch).

**Blast radius**: None functional. UX discoverability only.

**Fix options**:

| Option | Location | Change | Risk |
|--------|----------|--------|------|
| A | `run.py:28` | Add `yes: bool = typer.Option(False, "--yes", "-y")` → combine with confirm | LOW |

**Confidence**: 99%

---

### R12-#10: `repos list` returns 0 via MCP/HTTP but CLI shows 1

**Reported symptom**: CLI shows `gred_in_multiagent_orchestrator`, MCP/HTTP show `repos: []`

**Entry point**: `GET /ops/repos`

**Trace**:
```
CLI path:
  repos.py:25      → api_request(config, "GET", "/ops/repos")
  api.py:222-223   → headers["X-Gimo-Workspace"] = str(project_root())
                      ← INJECTS current workspace as header

Server:
  repo_router.py:57 → registry = load_repo_registry()
    validation.py:18-19 → loads repo_registry.json → {"repos": [], "active_repo": null} ← EMPTY
  repo_router.py:76-84 → checks X-Gimo-Workspace header
                          → if header present and path valid, MERGES it into response ← DISPLAY-ONLY

MCP path:
  bridge.py:59-62 → headers only contain Authorization
                     ← NO X-Gimo-Workspace header
  repo_router.py:76-84 → no header → returns empty registry

gimo init:
  core.py:56-102 → creates .gimo/ dirs and config
                    ← NEVER calls /ops/repos/register
```

**Root cause**: Dual data source divergence:
1. Server-side registry (`repo_registry.json`) is empty — `gimo init` never registers repos.
2. CLI injects `X-Gimo-Workspace` header at `api.py:222-223`, making the workspace appear as a repo (display-only hack).
3. MCP bridge and direct HTTP clients don't inject this header.

**Blast radius**: MCP and UI surfaces always show 0 repos. Any tool relying on repo list from API fails. `gimo_repos_select`, `gimo_repos_active` return empty on non-CLI surfaces.

**Fix options**:

| Option | Location | Change | Risk |
|--------|----------|--------|------|
| A (recommended) | `core.py:56-102` | After creating `.gimo/`, call `POST /ops/repos/register?path={cwd}` | LOW |
| B | `bridge.py:59-62` | Inject `X-Gimo-Workspace` from `ORCH_REPO_ROOT` env var | LOW |
| C | `repo_router.py` | Auto-register on first request if `X-Gimo-Workspace` is valid | MEDIUM |

**Confidence**: 98%

---

### R12-#11: Trust profile empty vs governance snapshot

**Reported symptom**: `get_trust_profile` → `[]`, snapshot → `{provider: 0.85, model: 0.85, tool: 0.85}`

**Entry point**: Both governance tools

**Trace (trust profile)**:
```
governance_tools.py:89-111 → gimo_get_trust_profile()
governance_tools.py:100    → storage = TrustStorage(gics_service=StorageService._shared_gics)
governance_tools.py:101    → engine = TrustEngine(trust_store=storage)
governance_tools.py:107    → dashboard = engine.dashboard(limit=20)
  trust_engine.py:51-58    → events = self.storage.list_trust_events(limit=20)
  trust_storage.py:58-69   → scans GICS for "te:" prefix → [] (no events ever recorded)
  → _build_records([]) → {} → returns []
```

**Trace (governance snapshot)**:
```
governance_tools.py:114-135 → gimo_get_governance_snapshot()
sagp_gateway.py:136-139     → trust_profile = {"provider": cls._get_trust_score("provider"), ...}
sagp_gateway.py:206-219     → _get_trust_score(dimension_key)
sagp_gateway.py:214          → record = engine.query_dimension(dimension_key)
  trust_engine.py:44-49     → _build_records({}) → _empty_record() → score: 0.0
sagp_gateway.py:217          → return score if score > 0.0 else 0.85 ← HARDCODED FALLBACK
```

**Root cause**: Both behaviors are correct for a fresh install with no trust events. The `0.85` values are hardcoded conservative defaults at `sagp_gateway.py:217,219`. The empty `[]` from trust profile is truthful. The inconsistency is a **presentation mismatch** — the snapshot synthesizes defaults while the profile reports raw truth.

**Blast radius**: Low — confusing to operators comparing outputs, but no functional breakage.

**Fix options**:

| Option | Location | Change | Risk |
|--------|----------|--------|------|
| A | `governance_tools.py:107` | If dashboard empty, return synthetic defaults matching snapshot | LOW |
| B (recommended) | `sagp_gateway.py:217` | Mark fallback values as `"source": "default"` in snapshot | LOW |

**Confidence**: 98%

---

### R12-#12: Malformed evaluate_action still unstructured error

**Reported symptom**: `{"error": "Expecting value..."}` instead of `{"error": "INVALID_TOOL_ARGS", "detail": "..."}`

**Entry point**: MCP tool `gimo_evaluate_action`

**Trace**:
```
governance_tools.py:37    → tool_args = json.loads(tool_args_json)  ← raises JSONDecodeError
governance_tools.py:50-51 → except json.JSONDecodeError as e:
                                return json.dumps({"error": "INVALID_TOOL_ARGS", "detail": str(e)})
                              ← THIS HANDLER IS PRESENT ON DISK
```

**Root cause**: The R11 fix IS applied in the current code on disk. The `json.JSONDecodeError` catch at line 50-51 DOES return the `INVALID_TOOL_ARGS` envelope. The Phase 1 test ran against a **stale server process** that loaded pre-R11 bytecache — same root cause as R12-#3.

**Blast radius**: None if server is restarted with clean `__pycache__`.

**Fix options**: Same as R12-#3 — purge `__pycache__` + restart.

**Confidence**: 95%

---

### R12-#13: Claude API key expired, no early warning

**Reported symptom**: 401 from Anthropic with no prior detection

**Entry point**: All credential-related paths

**Trace**:
```
providers login:
  providers.py:250-254 → POST /ops/provider/select with api_key
  auth_service.py:73-109 → sanitize_entry_for_storage()
    Line 84-87: set_secret(env_name, inline_key) → encrypted vault
    ← NO VALIDATION OF KEY

providers test:
  connector_service.py:402-413 → shutil.which("claude") → binary check only
  provider_auth_router.py:15-36 → _enrich_with_vault_key() → vault existence check only
  ← NO API CALL

Unused validate endpoint:
  catalog_router.py:97-114 → POST /ops/connectors/{type}/validate
  → ProviderCatalogService.validate_credentials() → NEVER CALLED by any CLI command

Unused real health check:
  anthropic_adapter.py:219-235 → AnthropicAdapter.health_check()
  → Makes real API call → NEVER CALLED by connector_health
```

**Root cause**: No credential validation anywhere in the happy path. Three validation mechanisms exist but are disconnected: (1) vault existence check ≠ validity, (2) binary check ≠ API access, (3) real validate endpoint exists but is dead code.

**Blast radius**: Same as R12-#6.

**Fix options**: Same as R12-#6 (A+B+C).

**Confidence**: 97%

---

## Systemic Patterns

### Pattern 1: Three Competing Sources of Truth for MCP Tools

**Affected issues**: R12-#1, #2, #4, #8

The MCP tool definitions come from three sources that diverge:
1. **Hand-crafted manifest** (`manifest.py`): Human-readable `gimo_*` names, some wrong paths/types.
2. **OpenAPI spec** (`openapi.yaml`): Correct paths and types, ugly auto-generated names.
3. **Actual FastAPI routers**: The ground truth.

There is NO automated sync. The generator (`generate_manifest.py`) is destructive and produces incompatible names. The result: fixes applied to routers don't propagate to the manifest, and manifest regeneration destroys user-facing tool names.

**Future failure modes**:
- Every new endpoint will have a mismatched MCP tool name
- Every type change in a router will drift from the manifest
- Integration tests that use `TestClient` will never catch MCP-layer bugs

**What would make this impossible**: A single-source manifest derivation that preserves semantic names, runs in CI, and has a diff-check gate.

---

### Pattern 2: Existence Checks Instead of Validity Checks

**Affected issues**: R12-#6, #7, #13

The system consistently checks if something EXISTS rather than if it WORKS:
- Provider credentials: vault has key → "authenticated" (but key could be expired)
- GICS health: `_supervisor is not None` → "alive" (but daemon could have crashed)
- Binary checks: `shutil.which("claude")` → "installed" (but may not be functional)

**Future failure modes**:
- Any credential rotation will silently break with green health
- Infrastructure failures masked by stale object references
- Users lose trust in health checks → start ignoring them

**What would make this impossible**: Replace existence checks with liveness probes (real API calls, ping endpoints, subprocess health).

---

### Pattern 3: Display-Only Workarounds That Diverge Across Surfaces

**Affected issues**: R12-#10, #11

The CLI uses workarounds (header injection, fallback defaults) that make it appear to work while the API/MCP surfaces show the raw (broken) truth:
- Repos: CLI injects `X-Gimo-Workspace` header → repo appears; MCP/HTTP → empty
- Trust: Snapshot synthesizes `0.85` defaults; trust profile → empty `[]`

**Future failure modes**:
- Every new surface (mobile app, web app, third-party integration) inherits the broken API behavior
- CLI tests pass while integration tests against the API fail
- Operators develop false confidence from CLI experience

**What would make this impossible**: All display logic lives server-side. No surface-specific workarounds. If the CLI needs a repo to show, the repo must be registered in the API registry.

---

### Pattern 4: Silent Failure Gates That Swallow Context

**Affected issues**: R12-#5, #7

Critical control flow decisions fail silently with no diagnostic output:
- `should_run` gate: returns `run: null` with no explanation of which condition failed
- `start_daemon()`: returns silently if CLI binary missing
- `run_router.py:196`: `except Exception: pass` — swallows all run creation errors

**Future failure modes**:
- Debugging production run failures requires source-code reading
- Operators see "run: null" and have no actionable next step
- Silent failures cascade into confusion about system state

**What would make this impossible**: Every gate that can block an operation returns a structured reason. No bare `except: pass`.

---

### Pattern 5: Stale Bytecache Invalidating Applied Fixes

**Affected issues**: R12-#3, #12 (and likely contributing to R12-#1)

Python `.pyc` files cache compiled bytecode. When `.py` files are edited but the server is not restarted (or `__pycache__` is not purged), the old bytecode executes. This means:
- R11 fixes applied to disk but running server still uses pre-fix code
- Tests run fresh (pytest purges bytecache) → pass
- Production server → fails

**Future failure modes**:
- Every fix round will have "ghost failures" where fixes are on disk but not active
- Developers lose confidence in the fix→test→deploy cycle

**What would make this impossible**: `PYTHONDONTWRITEBYTECODE=1` in dev, or `__pycache__` purge in launcher/CI.

---

## Dependency Graph

```
R12-#1 (manifest lifecycle)
  ├── R12-#2 (providers_list 404)     — wrong path in manifest
  ├── R12-#4 (drafts_approve type)    — wrong type + destroyed name
  └── R12-#8 (drafts_create schema)   — dropped items/anyOf in generator

R12-#5 (no run execution)
  ├── R12-#4 (MCP path blocked)       — from R12-#1
  ├── R12-#9 (CLI path — NOT broken)  — mischaracterized
  └── run_router.py:153 (HTTP path)   — should_run gate + silent swallow

R12-#3 (proof chain import) ←→ R12-#12 (error envelope)
  └── Both: stale __pycache__         — Pattern 5

R12-#6 (shallow provider test) ←→ R12-#13 (no key validation)
  └── Both: existence ≠ validity      — Pattern 2

R12-#7 (GICS daemon)
  └── start_daemon() silent failure   — Pattern 4

R12-#10 (repos divergence)
  └── CLI header injection display hack — Pattern 3

R12-#11 (trust inconsistency)
  └── Hardcoded 0.85 fallback vs empty truth — Pattern 3
```

---

## Preventive Findings

| Pattern | Future Risk | Prevention |
|---------|-------------|------------|
| Manifest drift | Every new endpoint will have mismatched MCP tool | CI step: `generate_manifest.py` + diff check |
| Existence ≠ validity | Credential rotation breaks silently | Liveness probes in health checks |
| Display-only workarounds | New surfaces inherit broken API | Server-side display logic only |
| Silent failure gates | Run failures are undiagnosable | Structured rejection reasons |
| Stale bytecache | Fixes don't take effect until restart | `PYTHONDONTWRITEBYTECODE=1` |
| Test blind spot | Tests exercise HTTP, not MCP chain | MCP integration tests via subprocess |

---

## Recommended Fix Priority

| Priority | Issues | Rationale |
|----------|--------|-----------|
| **P0** | R12-#5 (should_run gate) | Unblocks ALL run execution across ALL surfaces |
| **P0** | R12-#1 + #2 + #4 (manifest) | Restores MCP surface — GIMO's primary Claude integration |
| **P1** | R12-#3 + #12 (__pycache__) | One-line env var fix, unblocks proof chain + error envelope |
| **P1** | R12-#10 (repos registration) | Unblocks MCP/HTTP repo discovery |
| **P2** | R12-#6 + #13 (credential validation) | Prevents silent auth failures |
| **P2** | R12-#7 (GICS liveness) | Better health reporting |
| **P3** | R12-#9 (--yes alias) | UX polish |
| **P3** | R12-#11 (trust presentation) | Consistency polish |
| **P3** | R12-#8 (anyOf latent bug) | Prevents future manifest type bugs |
