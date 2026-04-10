# E2E Engineering Plan — Constraint Compiler Reconnection

**Date**: 2026-04-10
**Round**: R22
**Phase**: 3 — Engineering plan
**Input**: `E2E_ROOT_CAUSE_ANALYSIS_20260410_R22.md`
**Scope**: Reconnect disconnected GICS intelligence to constraint compiler; fix hard-block violation of GICS philosophy

---

## Diagnosis Summary

The ConstraintCompilerService's `apply_trust_authority()` hard-clamps execution policy to `propose_only` when GICS detects a model anomaly. This contradicts the GICS design philosophy (degrade and announce, never prohibit) and creates a vicious failure cycle: failure → anomaly → propose_only → stripped tools → retry → timeout → more failures.

**Root problem**: Refactors disconnected the constraint compiler from the capability intelligence system. The pieces exist:

| Component | Status | Location |
|-----------|--------|----------|
| `CapabilityProfileService` | ✅ Exists, connected to pipeline/routing | `services/capability_profile_service.py` |
| `recommend_model_for_task()` | ✅ Exists, connected to capability_router | `services/capability_profile_service.py:213` |
| `get_full_profile()` (strengths/weaknesses) | ✅ Exists | `services/capability_profile_service.py:175` |
| `BenchmarkEnrichmentService.get_best_model_for_task()` | ✅ Exists | `services/benchmark_enrichment_service.py:545` |
| `TaskDescriptorService` (task_type classification) | ✅ Exists | `services/task_descriptor_service.py` |
| `ModelRouterService._gics_success_adjustment()` | ✅ Uses CapabilityProfileService | `services/model_router_service.py:233` |
| Constraint compiler → CapabilityProfileService | ❌ **Not connected** | — |
| Constraint compiler → task_type context | ❌ **Not received** | — |
| Constraint compiler → DEBUG mode bypass | ❌ **Missing** | — |
| `apply_trust_authority` return type | ❌ **No metadata channel** | Returns `tuple[str, bool]` only |

This is a reconnection task, not a design task. The architecture was designed; refactors broke the wiring.

---

## Design Principles

1. **GICS is a counselor, not a cop** — anomaly signals become metadata annotations, never policy overrides
2. **One backend truth** — trust metadata flows from backend to all surfaces equally (MCP, CLI, Web, Apps)
3. **Reconnect, don't reinvent** — use CapabilityProfileService and BenchmarkEnrichmentService as-is
4. **Fail-open** — if GICS or capability data is unavailable, the policy passes through unchanged
5. **Minimal diff** — change the fewest lines needed to close the gap

---

## Change List

### Change 1: New return type for `apply_trust_authority`

- **Solves**: RC-1, RC-6
- **What**: Replace `tuple[str, bool]` return with a `TrustAuthorityResult` dataclass that carries trust metadata alongside the (unchanged) policy.
- **Where**: `services/constraint_compiler_service.py` (new dataclass), `models/agent_routing.py` (if typed model preferred)
- **Why this design**: The current return type has no channel for metadata. Adding a third positional element to a tuple is fragile. A named dataclass is explicit, typed, and extensible. It also aligns with `TaskConstraints` and `GovernanceVerdict` patterns already in the codebase.
- **Shape**:
  ```python
  @dataclass
  class TrustAuthorityResult:
      policy: str                         # The ORIGINAL policy, unchanged
      requires_approval: bool
      trust_warning: str | None = None    # Human-readable warning
      reliability_score: float | None = None
      anomaly_detected: bool = False
      recommended_alternative: dict | None = None  # {model_id, provider_type, success_rate, samples, reason}
      model_profile_summary: dict | None = None    # {strengths: [...], weaknesses: [...]}
  ```
- **Risk**: 3 call sites in `agentic_loop_service.py` need updating (mechanical).
- **Verification**: Existing tests that mock `apply_trust_authority` will need return type update. `pytest -k constraint_compiler`

### Change 2: Reconnect `apply_trust_authority` to CapabilityProfileService

- **Solves**: RC-1, RC-6, and the user's vision for task-type-aware recommendations
- **What**: When GICS detects anomaly, instead of hard-clamping:
  1. Keep original policy unchanged
  2. Query `CapabilityProfileService.recommend_model_for_task(task_type)` for best alternative
  3. Query `CapabilityProfileService.get_full_profile(provider, model)` for model strengths/weaknesses summary
  4. If no operational data in CapabilityProfileService, fall back to `BenchmarkEnrichmentService.get_best_model_for_task(dimension)` using task_semantic → dimension mapping
  5. Pack all signals into `TrustAuthorityResult` metadata
- **Where**: `services/constraint_compiler_service.py::apply_trust_authority` (lines 209-224)
- **Why this design**: The data sources already exist and are already used by ModelRouterService. The constraint compiler just needs the same connections. The task_semantic → benchmark dimension mapping is a small static dict (same pattern as `_BASE_POLICIES_BY_SEMANTIC`).
- **Task semantic → benchmark dimension mapping**:
  ```python
  _SEMANTIC_TO_DIMENSION = {
      "implementation": "coding",
      "planning": "reasoning",
      "research": "general_knowledge",
      "security": "expert_knowledge",
      "review": "reasoning",
      "approval": "instruction_following",
  }
  ```
- **Risk**: If CapabilityProfileService has no data yet (cold start), falls through to benchmark data. If both empty, metadata is simply None — no degradation.
- **Verification**: Unit test with mocked GICS returning anomaly → verify policy unchanged + metadata populated.

### Change 3: Thread `task_type` to `apply_trust_authority`

- **Solves**: Enables task-type-aware recommendations
- **What**: Add optional `task_type: str | None = None` parameter to `apply_trust_authority()`. The 3 call sites in `agentic_loop_service.py` already have `task_key` available (line 1353 shows it's used for `record_model_outcome`). Pass it through.
- **Where**:
  - `services/constraint_compiler_service.py::apply_trust_authority` — add param
  - `services/agentic_loop_service.py` lines 1426, 1537, 1721 — pass `task_type=task_key` or derive from thread context
- **Why this design**: `task_key` already flows through the agentic loop and is used for outcome recording. Reusing it here is zero new plumbing.
- **Risk**: None. Optional param, fail-open if absent.
- **Verification**: Trace that `task_key` value matches what `record_model_outcome` uses.

### Change 4: Add DEBUG mode bypass to ConstraintCompilerService

- **Solves**: RC-2
- **What**: At the top of `apply_trust_authority()`, check `os.getenv("DEBUG", "").lower() in ("1", "true")`. If active, return policy unchanged with metadata indicating debug bypass. Log warning.
- **Where**: `services/constraint_compiler_service.py::apply_trust_authority` (top of method)
- **Why this design**: Every other governance service uses this exact pattern. The constraint compiler was the only one missed during the debug rollout.
- **Risk**: None. Follows established pattern.
- **Verification**: `pytest -k constraint_compiler` with `DEBUG=true` env.

### Change 5: Surface trust metadata in agentic loop response

- **Solves**: Makes trust warnings visible to all surfaces
- **What**: When `TrustAuthorityResult` contains a warning, attach it to the thread metadata and/or response. This makes it available to MCP (`gimo_chat` result), CLI (renderer), and Web UI (thread view) equally.
- **Where**: `services/agentic_loop_service.py` — after calling `apply_trust_authority`, if `result.trust_warning`, store in thread metadata via `ConversationService`.
- **Why this design**: Thread metadata is the canonical channel that all surfaces already read. No new transport needed. MCP reads thread via `gimo_get_status`. CLI reads thread for rendering. Web UI reads thread for display. One write, all surfaces see it.
- **Risk**: Low. Thread metadata is extensible dict. No schema change.
- **Verification**: Run `gimo_chat` with an anomalous model → check thread metadata contains trust warning.

### Change 6: Fix CLI adapter retry on propose_only

- **Solves**: RC-3
- **What**: In `_raw_chat_with_tools`, skip the retry loop when the effective tools list is empty or contains only read-only tools (i.e., when the effective policy is propose_only).
- **Where**: `providers/cli_account.py::_raw_chat_with_tools` (line ~302)
- **Why this design**: The retry loop exists for when the LLM should have used tools but didn't. When the policy strips write tools, the LLM correctly responds with text — retrying is wrong.
- **Risk**: Must preserve retry for legitimate cases (tools available but LLM responded with text). Check: `if not tools or len(tools) <= len(PROPOSE_ONLY_TOOLS)`.
- **Verification**: Unit test: propose_only policy → no retry → no timeout amplification.

### Change 7: Offset httpx timeout above subprocess timeout

- **Solves**: RC-5
- **What**: In `mcp_bridge/native_tools.py::_background_chat`, change `httpx.AsyncClient(timeout=300.0)` to `timeout=360.0`. The subprocess timeout (300s) fires first, the httpx timeout provides a safety net 60s later.
- **Where**: `mcp_bridge/native_tools.py` line 892
- **Why this design**: The subprocess error is more informative (includes the actual failure). The httpx error (`ReadTimeout:` with no details) should never win the race.
- **Risk**: None. 60s buffer is generous enough for cleanup.
- **Verification**: Inspect code — no runtime test needed for a constant change.

---

## Execution Order

```
C4 (DEBUG bypass) ← immediate unblock, zero risk
    ↓
C1 (TrustAuthorityResult dataclass) ← enables all metadata work
    ↓
C3 (thread task_type) ← plumbing for recommendations
    ↓
C2 (reconnect CapabilityProfileService) ← the core reconnection
    ↓
C5 (surface metadata in thread) ← makes it visible
    ↓
C6 (CLI retry fix) ← secondary, prevents timeout amplification
    ↓
C7 (httpx timeout offset) ← minor, independent
```

Changes C4, C6, C7 are independent and can be parallelized.
Changes C1→C3→C2→C5 are sequential (each builds on the previous).

---

## Unification Check

| Surface | How trust metadata reaches it | Change needed |
|---------|-------------------------------|---------------|
| MCP | Thread metadata → `gimo_get_status` / `gimo_chat` result | C5 |
| CLI | Thread metadata → `ChatRenderer` reads thread | C5 (renderer may need display logic) |
| Web UI | Thread metadata → thread API → React component | C5 (UI may need display logic) |
| API | Thread metadata → `GET /ops/threads/{id}` | C5 (already exposed) |
| Apps | Thread metadata → same API | C5 |

One write to thread metadata. All surfaces read it through existing channels. No surface-specific logic needed in the constraint compiler.

---

## Verification Strategy

| Change | Verification | Type |
|--------|-------------|------|
| C1 | `pytest -k constraint_compiler` — return type tests | Unit |
| C2 | Mock GICS anomaly → verify policy unchanged + metadata populated | Unit |
| C3 | Trace `task_key` from agentic loop → constraint compiler | Code review |
| C4 | `DEBUG=true pytest -k constraint_compiler` | Unit |
| C5 | `gimo_chat` with anomalous model → thread metadata check | Integration |
| C6 | CLI adapter unit test: propose_only → no retry | Unit |
| C7 | Code inspection | Review |
| All | `python -m pytest -x -q` — full suite green | Regression |

---

## Compliance Matrix

| Principle | Satisfied | Evidence |
|-----------|-----------|----------|
| AGENTS.md: one backend truth | ✅ | Trust metadata written once to thread, all surfaces read |
| AGENTS.md: minimal diffs | ✅ | 7 changes, ~100 LOC total, reconnection not invention |
| AGENTS.md: no silent degradation | ✅ | Anomaly signals become visible metadata, not silent blocks |
| AGENTS.md: fail-closed security | ✅ | Policy never WEAKENED. Anomaly can't upgrade policy, only annotate |
| CLIENT_SURFACES.md: all surfaces same contract | ✅ | Thread metadata is the universal channel |
| SECURITY.md: no trust weakening | ✅ | `require_review` from TrustEngine workspace dimension unchanged |
| GICS philosophy: degrade and announce | ✅ | Hard-block removed, replaced with metadata annotation |
| SYSTEM.md: GICS is operational memory | ✅ | CapabilityProfileService reconnected as intelligence source |

---

## Residual Risks

1. **Stale GICS anomaly data**: `record_model_outcome` never expires old anomaly flags. If codex/gpt-5 had 3 consecutive failures 2 weeks ago and hasn't been used since, `anomaly=True` persists forever. Separate fix needed: TTL or decay on anomaly flags.

2. **Cold start**: If CapabilityProfileService has zero data (fresh install, new model), `recommend_model_for_task()` returns None. The fallback to BenchmarkEnrichmentService provides static capability data, but no operational history. This is acceptable — the system bootstraps from benchmarks and learns from usage.

3. **Task type granularity**: Current `task_type` values from `TaskDescriptorService` are broad (execution, research, review, etc.). The user's vision includes finer types (refactor, cleanup, test_write, debug). This is a future enhancement to the task classifier — the plumbing supports it already.

4. **CLI renderer display**: Change C5 puts trust metadata in thread. The CLI renderer (`gimo_cli_renderer.py`) may need a small update to display trust warnings. This is surface-level polish, not architectural.

5. **Thread metadata size**: If many models have anomalies and profiles grow large, thread metadata could bloat. Mitigate by keeping only the top recommendation + a summary, not full profiles.

---

## Quality Gates (from AGENTS.md Plan Quality Standard)

| Gate | Answer |
|------|--------|
| **Permanence**: Does this deserve to stay? | YES — reconnects designed architecture, not a patch |
| **Completeness**: Resolves all observed gaps? | YES — all 6 RC issues addressed |
| **Foresight**: Future-proof? | YES — task_type plumbing supports finer granularity later |
| **Potency**: Creates lasting leverage? | YES — one reconnection enables task-aware routing for all surfaces |
| **Innovation**: Improves state of art? | YES — constraint compiler becomes an intelligence surface, not a blocker |
| **Elegance**: Clean design? | YES — one dataclass, one reconnection, one metadata channel |
| **Lightness**: Minimal implementation? | YES — ~100 LOC across 4 files, mostly reconnection |
| **Multiplicity**: One change solves multiple problems? | YES — C2 alone solves RC-1 + RC-6 + enables task-type routing |
| **Unification**: One canonical path for all surfaces? | YES — thread metadata is the single channel |
