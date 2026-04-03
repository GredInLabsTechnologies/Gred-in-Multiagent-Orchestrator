# GIMO Forensic Audit — Phase 3: Engineering Plan (Round 3)

**Date**: 2026-04-03
**Auditor**: Claude Opus 4.6
**Input**: ROOT_CAUSE_ANALYSIS_20260403_2000.md + SYSTEM.md + CLIENT_SURFACES.md + AGENTS.md
**SOTA Sources**: Claude Code, Cursor, Aider, Windsurf, Continue.dev, OpenHands, SWE-agent, Cline, Devin

---

## Diagnosis Summary

GIMO's documentation defines a system where the orchestrator has maximum non-human authority, all first-party surfaces share identical capability, and there are no parallel paths to the same truth. The implementation contradicts all three. These are doctrinal violations, not bugs.

The authority chain `Surface → Workspace → Trust/GICS → Policy → Tools` exists conceptually across 5 services but is only partially wired. Completing the wiring resolves all issues simultaneously.

---

## Competitive Landscape

### Execution Policies / Agent Authority

| Tool | Default Mode | Plan Mode | Dynamic Authority | Tool Schema Filtering |
|------|-------------|-----------|-------------------|----------------------|
| Claude Code | Reads free, writes ask | Yes (read-only) | No (static modes, user switches) | No (execution-time) |
| Cursor | Each step asks | Yes (Markdown artifact) | No | No |
| Aider | Direct edits | Yes (architect + ask) | No | No |
| Windsurf | Allowlist commands | Yes (Plan + megaplan) | No | No |
| Devin | Plan-first always | Yes (core UX) | No | No |
| OpenHands | Full autonomy | No | Risk classifier per action | No |
| Cline | All operations ask | No | No | No |
| **GIMO (post-plan)** | **Trust-gated dynamic** | **Yes (persistent JSON)** | **Yes (GICS + TrustEngine)** | **Yes (schema-time)** |

### What GIMO Already Has That Nobody Else Does
1. Persistent plan artifacts in `.gimo/plans/` (JSON, versioned, resumable)
2. Multi-agent decomposition with orchestrator→worker and dependency graphs
3. Run-level execution tracking with durable state
4. GICS operational memory with model reliability + anomaly detection
5. TrustEngine with circuit breaker
6. 6-tier execution policy system with HITL gates

### What EVERYONE Still Gets Wrong (Industry Gaps)
1. No step-level execution gates (all-or-nothing plan approval)
2. No plan drift detection during execution
3. No persistent plan artifacts across sessions (except GIMO)
4. No unified multi-agent plan visibility
5. **No dynamic trust-gated authority** (static modes everywhere)
6. **No schema-time tool filtering** (everyone filters at execution time)

---

## Design Principles

1. **Enforce the doctrine, don't add to it.** SYSTEM.md already defines the correct authority model.
2. **One path, all surfaces.** Per AGENTS.md §Unification.
3. **The orchestrator's authority comes from trust, not from a hardcoded string.**
4. **Honest responses.** If a tool fails, the response must say so.
5. **Windows is a first-class platform.**
6. **The LLM should only see what it can use.**

---

## The Plan: Complete the Authority Chain

### The Core Concept

The authority chain `Surface → Workspace → Trust/GICS → Policy → Tools` already exists across 5 services. The problem is 4 missing wires. Completing them resolves all 6 root causes, connects GICS and TrustEngine to the policy system, and creates two competitive advantages no other tool has.

---

### Wire 1: Windows Encoding + Surface Identification

**Solves**: N2 (Windows crash), thread title bug, surface blindness

#### 1a. Windows Console Setup

**File**: `gimo_cli/__init__.py`
**Before line 14** (before `Console()` creation):

```python
import sys

def _setup_windows_console():
    """Enable UTF-8 output and VT processing on Windows."""
    if sys.platform != "win32":
        return
    for stream in (sys.stdout, sys.stderr):
        if stream and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleOutputCP(65001)
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_ulong()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
    except Exception:
        pass

_setup_windows_console()
```

**Why**: `sys.stdout.reconfigure(encoding="utf-8")` makes Rich's `Console.encoding` return `"utf-8"`, so `ascii_only=False` and all Unicode renders. `SetConsoleOutputCP(65001)` tells Windows to interpret UTF-8. VT processing enables ANSI codes. Pattern from Textual (same author as Rich). Must execute BEFORE `Console()` because constructor caches `legacy_windows`.

#### 1b. Surface Header

**File**: `gimo_cli/api.py:~213`
Add `X-GIMO-Surface: cli` to default headers.

**File**: `tools/gimo_server/routers/ops/conversation_router.py:~60`
Accept `x_surface: str = Header(default="operator", alias="X-GIMO-Surface")`, pass to `create_thread()`.

**File**: `tools/gimo_server/services/conversation_service.py:238`
Accept `surface: str = "operator"` parameter, use in `default_metadata_for_surface(surface)`.

#### 1c. Thread Title Fix

**File**: `tools/gimo_server/routers/ops/conversation_router.py:69`
Replace `body.title if body.title != "New Conversation"` with `title or body.title` (make body.title `Optional[str] = None`).

---

### Wire 2: Dynamic Trust-Gated Orchestrator Authority

**Solves**: N1 (orchestrator castrated), N9 (false success), GICS disconnection, TrustEngine disconnection

This is the heart of the plan and what makes it revolutionary.

#### 2a. Restore Orchestrator Authority

**File**: `tools/gimo_server/services/agent_catalog_service.py:88`

**From**: `"plan_orchestrator": AgentPresetProfile("plan_orchestrator", "orchestrator", "collaborative", "propose_only", "planning")`

**To**: `"plan_orchestrator": AgentPresetProfile("plan_orchestrator", "orchestrator", "collaborative", "workspace_safe", "planning")`

This restores the orchestrator's doctrinal authority per SYSTEM.md §1.4: "programming directly when appropriate [...] fully automatic mode."

#### 2b. Trust-Gated Policy Constraint

**File**: `tools/gimo_server/services/constraint_compiler_service.py`
**New method** `_apply_trust_authority()` (~25 lines):

```python
@classmethod
def _apply_trust_authority(
    cls,
    execution_policy: str,
    model_id: str,
    workspace_root: str,
) -> tuple[str, bool]:
    """Dynamically constrain execution policy based on trust and reliability signals.

    Returns (effective_policy, requires_human_approval).
    Fail-open: if signals unavailable, returns policy unchanged.
    """
    requires_approval = False

    # Check GICS model reliability
    try:
        reliability = OpsService.get_model_reliability(model_id)
        if reliability and reliability.get("anomaly"):
            return "propose_only", False  # Anomalous model → read-only
    except Exception:
        pass  # Fail-open

    # Check TrustEngine workspace dimension
    try:
        trust = TrustEngine.query_dimension("workspace", workspace_root)
        if trust:
            trust_policy = trust.get("policy", "require_review")
            if trust_policy == "blocked":
                return "propose_only", False
            elif trust_policy == "require_review":
                requires_approval = True
    except Exception:
        pass  # Fail-open

    return execution_policy, requires_approval
```

Call from `_resolve_thread_runtime_context()` in `agentic_loop_service.py` after preset resolution, or from `compile_for_descriptor()` in the constraint compiler.

#### Why This Is Revolutionary

| Situation | Claude Code | GIMO (post-plan) |
|-----------|------------|-------------------|
| New session, no history | User must choose mode manually | Full authority (workspace_safe) — correct default |
| Model starts failing | User doesn't know | GICS detects anomaly → auto-degrades to propose_only |
| Trust erodes (rejections) | User must downgrade manually | TrustEngine blocks → auto-degrades to propose_only |
| Trust rebuilds | User must upgrade manually | TrustEngine auto_approves → authority restored |
| High-risk operation | Static mode determines | HITL gate fires for HIGH-risk tools regardless of policy |

**The orchestrator's authority is earned, not assigned. It starts full and contracts when trust signals say so. Nobody in the industry does this.**

---

### Wire 3: Streaming Plan Endpoint Parity

**Solves**: N5 (run never starts), streaming/non-streaming divergence

**File**: `tools/gimo_server/routers/ops/plan_router.py:~529`

Add to streaming draft context dict:
```python
"execution_decision": "AUTO_RUN_ELIGIBLE",
```

One line. Matches non-streaming path at line 326.

---

### Wire 4: Schema-Time Tool Filtering

**Solves**: Wasted tool calls, inference quality, competitive positioning

**Concept**: Currently all 12 tools are sent to the LLM regardless of policy. The LLM tries `write_file`, gets denied, retries with `propose_plan`, fails validation — wasting tokens and producing false success messages. If we filter tools at schema time, the LLM never sees tools it can't use.

**File**: `tools/gimo_server/engine/tools/chat_tools_schema.py`
```python
def filter_tools_by_policy(
    tools: list[dict], policy: ExecutionPolicyProfile
) -> list[dict]:
    """Return only tool schemas the policy allows."""
    if not policy.allowed_tools:
        return tools  # No restriction → all tools
    return [t for t in tools if t["function"]["name"] in policy.allowed_tools]
```

**File**: `tools/gimo_server/services/agentic_loop_service.py:~1218-1230`
Before passing `tools=CHAT_TOOLS` to `chat_with_tools()`:
```python
effective_tools = filter_tools_by_policy(CHAT_TOOLS, resolved_policy)
# ... pass effective_tools instead of CHAT_TOOLS
```

**Why nobody else does this**: Most tools have binary permission modes (ask/auto). GIMO has a 6-tier policy system with per-tool allow lists — the infrastructure for schema-time filtering already exists. This is a ~10-line change that makes GIMO architecturally cleaner than Claude Code's execution-time filtering.

---

## Additional Fixes (Independent)

### API Key Validation

**File**: `tools/gimo_server/services/providers/auth_service.py`
Add `validate_api_key_format(provider_type: str, key: str) -> tuple[bool, str]` with:
- Minimum length check (>10 chars)
- Provider-specific prefix: `sk-ant-` for Anthropic, `sk-` for OpenAI
- Advisory warning, not blocking (key formats may change)

**File**: `tools/gimo_server/services/providers/service_impl.py:~398`
Call validation before `updates["api_key"] = api_key`.

### Honest Response Verification

**File**: `tools/gimo_server/services/agentic_loop_service.py:~1032`
Before `final_response = "Plan proposed..."`, verify `canonical_plan` is non-null and was actually stored. If not, set `finish_reason = "error"`.

---

## AGENTS.md Compliance

| Criterion | Assessment |
|-----------|-----------|
| **Permanence** | Trust-gated authority chain is the correct permanent architecture. Will never need replacing. |
| **Completeness** | 6 root causes + 3 disconnections (GICS, TrustEngine, Surface) + competitive positioning |
| **Foresight** | New surfaces/policies/trust signals automatically participate in the chain |
| **Potency** | Every new trust signal automatically improves orchestrator decisions |
| **Innovation** | Dynamic trust-gated authority (industry first) + schema-time tool filtering (industry first) |
| **Elegance** | One concept (complete the authority chain) expressed as 4 wires |
| **Lightness** | ~10 files, ~80 lines new code, 0 new services, 0 new dependencies |
| **Multiplicity** | Wire 2 solves N1 + N9 + GICS + TrustEngine. Wire 1 solves N2 + title + surfaces |
| **Unification** | All surfaces: same header → same constraint compiler → same trust chain → same policy |

---

## Execution Order

```
Phase A (immediate unblock, parallel):
  Wire 3: execution_decision (1 line)
  Wire 1a: Windows encoding (~15 lines)

Phase B (surface identification):
  Wire 1b: X-GIMO-Surface header + create_thread
  Wire 1c: Thread title fix

Phase C (the heart — depends on B):
  Wire 2a: preset change (1 line)
  Wire 2b: _apply_trust_authority() (~25 lines)

Phase D (competitive moat — depends on C):
  Wire 4: schema-time tool filtering (~15 lines)

Phase E (hardening, independent):
  API key validation (~15 lines)
  Honest response check (~5 lines)
```

---

## Verification

| Phase | Test | Expected |
|-------|------|----------|
| A | `gimo plan "..." && gimo run {id} --no-confirm` | Run starts (not null) |
| A | `gimo chat -m "hello"` on Windows | No UnicodeEncodeError |
| B | Create thread via CLI → inspect metadata | `surface: "cli"` present |
| B | Create thread with custom title | Title preserved |
| C | `gimo chat -m "Create calculator.py"` | File created in workspace |
| C | Set TrustEngine to "blocked" → same command | Policy denied (propose_only) |
| C | Record 3+ GICS failures → same command | Policy denied (anomaly) |
| D | Chat in propose_only mode → inspect LLM request | Only 7 tools sent, not 12 |
| E | `gimo providers login claude --api-key "garbage"` | Warning/rejection |
| **E2E** | `gimo chat -m "Build calculator with add/sub/mul/div"` | Calculator created in gimo_prueba/ |

---

## Residual Risks

1. **EngineService.execute_run()**: Not stress-tested. May have its own bugs once runs actually start.
2. **Workspace path resolution**: `write_file` may resolve relative to server CWD, not `-w` workspace.
3. **MCP parity**: Once CLI works, MCP bridge needs same header injection. Out of scope.
4. **Web frontend parity**: Web uses `/chat/stream` (SSE), CLI uses `/chat` (non-streaming). Same policy applies but streaming events differ.
5. **TrustEngine cold start**: New workspaces have no trust data. `_apply_trust_authority()` fails-open to `workspace_safe`, which is correct per doctrine (full authority by default).
