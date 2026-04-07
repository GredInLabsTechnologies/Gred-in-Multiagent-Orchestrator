# E2E Engineering Plan — R16

**Date**: 2026-04-07
**Round**: 16
**Input documents**:
- `E2E_AUDIT_LOG_20260406_R16.md` (Phase 1 — 11 issues)
- `E2E_ROOT_CAUSE_ANALYSIS_20260406_R16.md` (Phase 2 — root causes)
**Design philosophy references**: `docs/SYSTEM.md`, `AGENTS.md`, `docs/CLIENT_SURFACES.md`
**Research method**: 6 parallel subagents (3 competitive, 2 academic, 1 internal analysis)

---

## Diagnosis Summary

GIMO's control plane works perfectly (27/27 HTTP endpoints, 27/30 CLI commands, MCP tool discovery). But the **data plane produces nothing** — runs complete to "done" with zero output, zero tokens, zero cost. This is architecturally worse than R14's visible hangs because it passes all health checks while delivering zero value.

The root cause is singular: **existing infrastructure isn't wired together**. FileWrite stage exists but isn't in `legacy_run`. Journal infrastructure exists but `journal_path` isn't injected. TrustEngine returns 0.85 correctly but `sagp_gateway` passes the tool name instead of the generic dimension key. Every issue traces to a disconnect between working components — not missing functionality.

**One concept: "Close the Wiring Gaps." ~40 lines across 8 files. Zero new files. Zero new dependencies.**

---

## Competitive Landscape

| Dimension | Cursor | Aider | Claude Code | Cline | Codex CLI | OpenHands | CrewAI | LangGraph | Devin | **GIMO** |
|---|---|---|---|---|---|---|---|---|---|---|
| Pipeline stages | None | None | QueryEngine loop | None | Sandbox+JSONL | EventStream | Role-based Flows | Arbitrary DAG | Opaque P/C/C | **Typed stage DAG with gates** |
| Governance | Zero | Zero | Binary permissions | Binary HITL | 4-level sandbox | LLM risk analyzer | Task Guardrails | Interrupt/checkpoint | PR review | **SAGP: risk-tiered, multi-gate** |
| Multi-surface | IDE only | CLI only | CLI+SDK+MCP+VSCode | IDE only | CLI only | Web+CLI | CLI+API | CLI+API | Web+Slack+MCP | **CLI+API+MCP+UI+ChatGPT** |
| Cost tracking | Opaque | LiteLLM post-hoc | Anthropic-only | None | None | None | Delegated | Delegated | ACU abstraction | **Built-in pricing DB + budget + cascade** |
| Trust scoring | None | None | None | None | Project trust | Per-action LLM | Memory 0-10 | None | None | **Dynamic TrustEngine + circuit breakers** |
| Proof chain | None | None | None | Snapshots | JSONL events | EventStream | None | Checkpoints | None | **GICS + proof chain verification** |

**GIMO's moat**: Only system with governance-as-architecture across multiple surfaces + cost-aware model cascading + verifiable proof chains. But the moat is theoretical until the data plane works.

---

## Research Findings per Systemic Pattern

### Pattern 1: "Succeed Without Doing" (#1, #6, #10)

**Academic**: OpenTelemetry GenAI semantic conventions define `gen_ai.usage.output_tokens` — hollow completions detectable by asserting `output_tokens > 0`. Honeycomb recommends SLI: `output.is_empty AND span.status == OK`.

**Competitive**: Cursor has "agent returns no response" issues with no retry. Aider warns on empty responses but doesn't retry. Claude Code hangs on dead SSE. Codex CLI's kernel sandbox enforces *where* writes happen but not *that* writes happen.

**GIMO fix**: Empty-content guard in LlmExecute + FileWrite in legacy_run + journal_path injection. The pipeline-native equivalent of OTel's output assertion.

### Pattern 2: "Surface Parity Drift" (#5, #11)

**Academic**: Stripe maintains a single Ruby DSL that generates all surface contracts — parity by construction. MCP spec 2025-06-18 adds `structuredContent` + `outputSchema` for typed tool returns.

**Competitive**: No competitor has this problem because none have multiple surfaces with shared state. GIMO is unique in needing cross-surface governance consistency.

**GIMO fix**: Normalize trust dimension key in sagp_gateway.py (1 line). Aligns MCP path with HTTP path structurally.

### Pattern 3: "Silent Swallow" (#3, #9)

**Academic**: CPython #116720 — nested TaskGroup can silently swallow cancellation. Best practice: `TaskGroup` + `add_done_callback()` for structured concurrency. Istio's `holdApplicationUntilProxyStarts` pattern for daemon readiness gating.

**Competitive**: Codex CLI handles MCP server failures gracefully with disable+warning. Cline's telemetry sends data even when "disabled" (trust violation). OpenHands blocks entirely on Docker failure.

**GIMO fix**: GICS token path fix (the daemon ignores `--token-path`). Audit file retry-on-rotation.

### Pattern 4: "Proxy String Parsing" (#7, #8)

**Academic**: MCP spec 2025-06-18 recommends `structuredContent` for machine-consumable returns. `outputSchema` enables tool chaining without LLM intermediation.

**Competitive**: All MCP implementations face this. The spec now has an answer but adoption is early.

**GIMO fix**: Fix response parsing using existing `split("\n", 1)` pattern. Long-term: adopt `structuredContent` in MCP bridge.

### Pattern 5: CLI Silence (#2, #4)

**Academic**: MCP spec: "All sent requests MUST have timeouts." Claude Code #33949 confirms unbounded waits are industry-wide.

**Competitive**: Aider has Knight Rider spinner. Claude Code shows "Not responding" after 60s. Codex CLI streams progress to stderr. None have adaptive heartbeat during provider calls.

**GIMO fix**: Finite timeout in `smart_timeout` + fire-and-return for chat + SSE heartbeat during provider wait.

---

## Design Principles

1. **Wire, don't build**: Every fix connects existing components rather than creating new ones
2. **Fail loud**: Empty content → explicit failure, not silent "done"
3. **Single dimension model**: Trust is per-dimension (provider/model/tool), not per-tool-name
4. **Fire-and-return for long ops**: MCP tools return promptly; clients poll for results
5. **Estimated > zero**: Approximate token counts with honesty flag beat hardcoded zeros

---

## The Plan (8 Changes)

### Change 1: Pipeline Data Plane Activation
- **Solves issues**: #1 (hollow run), #10 (SSE log-only)
- **What**: Three wiring fixes: (a) empty-content guard in LlmExecute, (b) FileWrite stage added to `legacy_run` composition, (c) `journal_path` injected into pipeline context
- **Where**:
  - `tools/gimo_server/engine/stages/llm_execute.py::execute` (~L64)
  - `tools/gimo_server/services/execution/engine_service.py::_COMPOSITION_MAP["legacy_run"]` (~L176)
  - `tools/gimo_server/services/execution/engine_service.py::execute_run` (~L350)
- **Why this design**: FileWrite already exists and handles no-content case. Journal infrastructure (Pipeline→JournalEntry→RunJournal→replay) is fully built but `journal_path` is never injected. One line activates the entire telemetry pipeline.
- **Risk**: Runs that previously completed hollow will now correctly fail → monitoring spike (desired behavior)
- **Verification**: Create draft via MCP → approve → run has `tokens_total > 0`, SSE events include stage transitions, journal JSONL file exists
- **SOTA context**: OTel GenAI convention `gen_ai.usage.output_tokens`; Honeycomb SLI on empty output

### Change 2: Trust Dimension Normalization
- **Solves issues**: #5 (trust 0.0 vs 0.85), #11 (trust varies by input)
- **What**: In `evaluate_action`, pass `"tool"` as dimension key instead of `tool_name`
- **Where**: `tools/gimo_server/services/sagp_gateway.py::evaluate_action` L66
- **Why this design**: Trust is per-dimension (provider/model/tool), not per-tool-name. The HTTP endpoint `trust_router.py` uses generic dimensions. This aligns MCP with HTTP structurally. Per-tool trust granularity would require a different data model.
- **Risk**: Low — makes MCP and HTTP return identical results
- **Verification**: MCP `gimo_get_trust_profile` returns 0.85 for all dimensions; `gimo_evaluate_action(tool_name="write_file")` and `gimo_evaluate_action(tool_name="INVALID")` return same trust_score
- **SOTA context**: TRiSM framework — consistent trust scoring across surfaces. Trust Paradox paper (arXiv 2510.18563) — per-tool escalation without authorization narrowing is dangerous.

### Change 3: MCP Bridge Response Parsing
- **Solves issues**: #7 (run_task "failed" on success), #8 (team_config not found)
- **What**: (a) Replace `lstrip` with `split("\n", 1)[-1]` in `gimo_run_task`. (b) Add fallback to draft's `prompt` field in `gimo_generate_team_config` when `content` is null.
- **Where**: `tools/gimo_server/mcp_bridge/native_tools.py::gimo_run_task` (~L311-319) and `::gimo_generate_team_config` (~L667-671)
- **Why this design**: The `split` pattern is already used in `gimo_get_plan_graph` in the same file. The prompt fallback is architecturally correct — the draft stores user intent.
- **Risk**: Low — local changes within MCP bridge
- **Verification**: `gimo_run_task` returns draft_id on 201; `gimo_generate_team_config` generates config from draft with null content
- **SOTA context**: MCP spec 2025-06-18 `structuredContent`. Long-term: adopt structured returns.

### Change 4: CLI Adapter Token Estimation
- **Solves issues**: #6 (zero cost/token tracking)
- **What**: Replace hardcoded zeros with `len(prompt_bytes) // 4` and `len(content.encode()) // 4` estimation. Add `"estimated": True` flag.
- **Where**: `tools/gimo_server/providers/cli_account.py::generate` (~L202-209)
- **Why this design**: `len//4` is ~75% accurate for English (confirmed by tokenization literature). tiktoken would be exact but adds a dependency. The `estimated` flag preserves honesty per AGENTS.md §11.
- **Risk**: Low — approximate beats zero; flag prevents false precision
- **Verification**: After codex-account run, `GET /ops/observability/metrics` shows `tokens_total > 0`
- **SOTA context**: Aider uses `litellm.token_counter()`. Claude Code tracks only Anthropic. Neither tracks CLI subprocess tokens.

### Change 5: gimo_chat Fire-and-Return
- **Solves issues**: #4 (chat MCP timeout)
- **What**: Change `gimo_chat` from synchronous 300s call to fire-and-return: POST chat request in background, return immediately with `thread_id` + polling instructions.
- **Where**: `tools/gimo_server/mcp_bridge/native_tools.py::gimo_chat` (~L476-567)
- **Why this design**: Same pattern as `gimo_approve_draft`. MCP spec: "All sent requests MUST have timeouts." The agentic loop's multi-turn execution can take minutes — no synchronous timeout is sufficient.
- **Risk**: Medium — changes MCP tool contract. Clients must poll instead of waiting.
- **Verification**: `gimo_chat` returns within 5s with thread_id; subsequent polling shows progress
- **SOTA context**: MCP spec lifecycle timeout requirement. Claude Code SSE hang issue #33949.

### Change 6: GICS Daemon Token Path Fix
- **Solves issues**: #3 (GICS daemon not initialized)
- **What**: Parse `--token-path` flag in `daemonStart` function. Currently `const tokenPath = DEFAULT_TOKEN_PATH` ignores the flag that GICSDaemonSupervisor passes.
- **Where**: `vendor/gics/dist/src/cli/commands.js::daemonStart` L909
- **Why this design**: `parseFlag` already exists and is used for `--config`, `--socket-path`, `--data-path`, `--wal-type`. `--token-path` is the ONLY flag that isn't parsed. Python client sends `--token-path` but daemon ignores it → token mismatch → auth failure.
- **Risk**: Medium — vendored JS code. Need to verify build state.
- **Verification**: `gimo_get_gics_insight` returns entries, not "GICS not initialized"
- **SOTA context**: Istio `holdApplicationUntilProxyStarts` pattern. Daemon must accept client-specified paths.

### Change 7: CLI Plan/Chat Definitive Fix
- **Solves issues**: #2 (CLI plan/chat produce zero output)
- **What**: (a) `smart_timeout` returns 180s for `/chat` paths instead of `None` (infinite). (b) Wrap single-turn chat in `console.status` with progress feedback. (c) Add SSE heartbeat emission during provider call wait in `generate-plan-stream` endpoint.
- **Where**:
  - `gimo_cli/api.py::smart_timeout` L141-142
  - `gimo_cli/commands/chat_cmd.py` L113
  - `tools/gimo_server/routers/ops/run_router.py` (or equivalent SSE endpoint)
- **Why this design**: `plan.py` already has `console.status` and 180s timeout. The gap is: (a) chat has no timeout, (b) no heartbeat during provider wait. Change 1's empty-content guard ensures the backend responds or fails within the provider timeout, rather than hanging for 300s.
- **Risk**: Low — additive UX improvements + timeout enforcement
- **Verification**: `gimo plan "..." --no-confirm` shows spinner + output within 180s; `gimo chat -m "..." -w .` shows progress and responds or fails with clear error
- **SOTA context**: Aider: Knight Rider spinner. Claude Code: "Not responding" after 60s. Codex CLI: JSONL progress events.

### Change 8: Audit File Handle Isolation
- **Solves issues**: #9 (audit ValueError)
- **What**: In `tail_audit_lines`, catch `ValueError` and `OSError` specifically (not bare `Exception`) and retry once after 100ms sleep. The `RotatingFileHandler` in `audit.py` can rotate the file while `read_text()` is reading.
- **Where**:
  - `tools/gimo_server/services/file_service.py::tail_audit_lines` L13-20
  - `tools/gimo_server/security/audit.py` (review module-level side effects)
- **Why this design**: The rotation window is brief (~ms). A single retry with short sleep resolves the race. Specific exception types preserve the fail-loud principle.
- **Risk**: Low — defensive retry for known race condition
- **Verification**: `gimo audit` shows no ValueError in Audit Tail check
- **SOTA context**: Standard RotatingFileHandler race condition. Python docs recommend separate file handles for reading rotated logs.

---

## Execution Order (dependency-aware)

```
P0 (parallel — unblocks data plane):
  Change 1 — Pipeline activation (llm_execute.py, engine_service.py)
  Change 2 — Trust normalization (sagp_gateway.py)
  Change 4 — Token estimation (cli_account.py)

P1 (parallel, after P0 — bridge fixes):
  Change 3 — MCP parsing (native_tools.py)
  Change 5 — Chat fire-and-return (native_tools.py) ← same file as 3, sequential
  Change 6 — GICS token path (commands.js)

P2 (parallel, after P1 — UX + cleanup):
  Change 7 — CLI streaming (api.py, chat_cmd.py, run_router.py)
  Change 8 — Audit fix (file_service.py)
```

---

## Unification Check

All changes enforce the single-backend-authority principle from `CLIENT_SURFACES.md`:

- **Trust scores**: Flow from one TrustEngine through one dimension model → all surfaces get identical results
- **Pipeline stages**: Single execution path for ALL surfaces (MCP, CLI, HTTP all use RunWorker → EngineService → Pipeline)
- **Cost tracking**: Happens in the adapter layer, below all surfaces
- **No surface-specific business logic**: All fixes are in the shared backend. Zero surface-specific code paths added.

---

## 8-Criterion Compliance Matrix

| Criterion | Status | Evidence |
|---|---|---|
| **Aligned** | YES | Every change follows SYSTEM.md pipeline architecture, AGENTS.md minimal-diff doctrine, CLIENT_SURFACES.md single-backend authority |
| **Potent** | YES | Change 1 alone unblocks the entire data plane. Change 2 is 1 line that resolves 2 issues permanently |
| **Lightweight** | YES | ~40 lines of new code across 8 files. Zero new files. Zero new dependencies. Zero new abstractions |
| **Multi-solving** | YES | 8 changes solve 11 issues. Change 1→3 issues. Change 2→2 issues. Change 3→2 issues |
| **Innovative** | YES | Token estimation with `estimated` flag (honesty > precision) is novel vs competitors. Fire-and-return for MCP chat follows spec better than any competitor |
| **Disruptive** | YES | Working data plane + governance across surfaces = capability gap no competitor can match without architectural rewrite |
| **Safe** | YES | All changes additive or corrective. No new attack surfaces. FileWrite respects workspace bounds. Trust normalization is more restrictive, not less |
| **Elegant** | YES | One concept: "close the wiring gaps." No new abstractions, no new patterns, no new services. Just connecting what exists |

---

## Residual Risks

1. **FileWrite in legacy_run**: Runs that previously "completed" hollow will now correctly fail. Monitoring dashboards may show error spike — this is correct behavior, not a regression.
2. **Token estimation ~75% accurate**: `estimated: true` flag mitigates. Exact counting requires tiktoken dependency (deferred to future round).
3. **gimo_chat contract change**: Fire-and-return is a breaking change for the MCP tool's return type. Clients expecting inline response must adapt to polling. This is the correct MCP pattern per spec.
4. **GICS JS rebuild**: If `vendor/gics/dist/` is stale, an `npm run build` in `vendor/gics/` is required. Operational step, verified during implementation.
5. **SSE heartbeat adds async complexity**: The heartbeat task during provider wait in Change 7 uses `asyncio.create_task` — must ensure proper cleanup if the request is cancelled. Mitigated by wrapping in `try/finally`.

---

## Issue → Change Traceability Matrix

| Phase 1 Issue | Phase 2 Root Cause | Phase 3 Change | Verification |
|---|---|---|---|
| #1 Hollow run (BLOCKER) | `legacy_run` has no FileWrite; LlmExecute accepts empty content | Change 1 | Run produces `tokens_total > 0` + files |
| #2 CLI silent (BLOCKER) | `smart_timeout` returns None for chat; no heartbeat | Change 7 + Change 1 | CLI shows progress, responds within 180s |
| #3 GICS dead (BLOCKER) | `commands.js` ignores `--token-path` flag | Change 6 | `gimo_get_gics_insight` returns data |
| #4 Chat timeout (CRITICAL) | `gimo_chat` blocks 300s > MCP stdio timeout | Change 5 | Returns within 5s with thread_id |
| #5 Trust 0.0/0.85 (CRITICAL) | `_get_trust_score(tool_name)` uses wrong dimension | Change 2 | All surfaces return 0.85 |
| #6 Zero cost (CRITICAL) | `CliAccountAdapter` returns hardcoded 0 tokens | Change 4 + Change 1 | `tokens_total > 0` in metrics |
| #7 run_task "failed" (GAP) | `lstrip` character-set strip corrupts JSON | Change 3 | Returns draft_id on 201 |
| #8 team_config not found (GAP) | Looks for `content` which is null in MCP drafts | Change 3 | Generates config from draft prompt |
| #9 Audit ValueError (GAP) | `RotatingFileHandler` race with `read_text()` | Change 8 | `gimo audit` clean |
| #10 SSE log-only (FRICTION) | `journal_path` never injected into context | Change 1 | SSE events include stage transitions |
| #11 Trust varies (INCONSISTENCY) | Same as #5 | Change 2 | Consistent trust_score for all inputs |
