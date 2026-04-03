# GIMO Forensic Audit — Phase 2: Root-Cause Analysis (Round 3)

**Date**: 2026-04-03 20:00 UTC
**Auditor**: Claude Opus 4.6
**Input**: `E2E_AUDIT_LOG_20260403_2000.md` (17 active issues)
**Method**: Full source code traversal via parallel subagents

---

## Traced issues: 11/17 (all blockers, gaps, and high-severity items)
## New issues discovered: 3

---

## Issue Map

| ID | Category | Root cause location | Confidence |
|----|----------|-------------------|------------|
| N1 | BLOCKER | agent_catalog_service.py:88 + execution_policy_service.py:73 + executor.py:557 | HIGH |
| N2 | BLOCKER | gimo_cli/__init__.py:14 (Console without encoding) | HIGH |
| N5 | BLOCKER | plan_router.py:525-531 (missing execution_decision) | HIGH |
| N3 | GAP | providers/service_impl.py:398 (no key validation) | HIGH |
| N4 | GAP | No `repos create` endpoint exists | HIGH |
| N9 | SILENT_FAILURE | agentic_loop_service.py:1032 (hardcoded success message) | HIGH |
| N8 | INCONSISTENCY | providers test uses reachability, not auth check | MEDIUM |
| N10 | COGNITIVE_LOAD | service_impl.py:606 (header > config > provider) | MEDIUM |
| Thread title | STILL_PRESENT | conversation_router.py:69 (Pydantic default collision) | HIGH |
| Audit 500/403 | STILL_PRESENT | dependencies_router.py:20 + legacy_ui_router.py:90 | MEDIUM |
| Bond broken | STILL_PRESENT | Not traced (auth subsystem, lower priority) | LOW |

---

## Detailed Traces

### [N1] BLOCKER — Agentic chat tools denied by `propose_only` policy

**Reported symptom**: write_file denied, propose_plan fails validation, response claims success

**CLI entry point**: `gimo_cli/commands/chat_cmd.py:69` → `POST /ops/threads` (no policy param)

**API endpoint**: `POST /ops/threads/{id}/chat` → `conversation_router.py:56-70`

**Thread creation**: `conversation_service.py:100` → defaults to `plan_orchestrator` preset

**Preset definition**: `agent_catalog_service.py:88`:
```python
"plan_orchestrator": AgentPresetProfile("plan_orchestrator", "orchestrator",
    "collaborative", "propose_only", "planning")
```

**Policy definition**: `execution_policy_service.py:73-81`:
- `propose_only` allowed_tools: `read_file`, `list_files`, `search_text`, `ask_user`, `propose_plan`, `request_context`, `web_search`
- `write_file` is NOT in allowed list → blocked

**Policy enforcement**: `agentic_loop_service.py:890`:
```python
if policy.allowed_tools and tool_name not in policy.allowed_tools:
    raise PermissionError(...)
```

**propose_plan validation**: `executor.py:557-562`:
- Requires per-task: `id`, `title`, `description`, `agent_rationale`
- LLM doesn't consistently provide `agent_rationale`
- Schema at `chat_tools_schema.py:298` lists `agent_rationale` as required — schema matches validation

**False success response**: `agentic_loop_service.py:1032`:
- Hardcoded: `final_response = "Plan proposed. Please review and approve to continue."`
- Set WITHOUT checking if propose_plan actually succeeded
- The LLM's text response is used as top-level response, ignoring tool execution failures

**No CLI/API way to change policy**: `conversation_router.py:56-70` does NOT accept execution_policy parameter. The only path is via thread metadata, but `workspace_policy_service.py:60-68` does NOT include execution_policy in default metadata.

**Root cause**: Hardcoded default preset → hardcoded policy → no override mechanism from CLI.

**Collateral findings**:
- 6 execution policies exist: `read_only`, `docs_research`, `propose_only`, `workspace_safe`, `workspace_experiment`, `security_audit`
- `workspace_safe` (line 83) allows all file tools — this is what CLI should use
- The policy system is designed for web UI approval workflows, not CLI direct usage

---

### [N2] BLOCKER — Windows cp1252 encoding crash

**Reported symptom**: UnicodeEncodeError on emoji/Unicode in any Rich output

**Console creation**: `gimo_cli/__init__.py:14`:
```python
console = Console()  # No encoding, no force_unicode
```

**Renderer fallback**: `gimo_cli_renderer.py:20-21`:
```python
self.console = console or Console()  # Same problem
```

**Hardcoded Unicode throughout**:
- `gimo_cli_renderer.py:69`: `\u2713` (checkmark)
- `gimo_cli_renderer.py:71`: `\u2717` (cross)
- `gimo_cli_renderer.py:76`: `\u25b8` (triangle)
- `gimo_cli_renderer.py:193-200`: emoji icons
- `gimo_cli_renderer.py:370-390`: clipboard, magnifier, gear emoji
- `gimo_cli/commands/threads.py:90`: `\u25b8`
- `gimo_cli/chat.py:420-422`: `\u2713`, `\u2717`

**LLM response path**: `gimo_cli/commands/chat_cmd.py:78`:
```python
console.print(content)  # LLM response direct to console, no sanitization
```

**Irony**: File I/O uses `encoding="utf-8"` correctly (chat.py:309, config.py:155, stream.py:72), but console output does not.

**Root cause**: `Console()` without `force_unicode=True` or explicit encoding on Windows defaults to cp1252 via Rich's legacy Windows renderer.

**Confidence**: HIGH — verified by cross-referencing Rich source: `rich/_windows_renderer.py:19` calls `term.write_text(text)` which hits `cp1252.py:19`.

---

### [N5] BLOCKER — Run never starts (missing execution_decision)

**Reported symptom**: `"run": null` after approval

**CLI entry**: `gimo_cli/commands/run.py:42-45`:
```python
query = {"auto_run": "true" if auto else "false"}
# POST /ops/drafts/{plan_id}/approve?auto_run=true
```

**Decision logic**: `run_router.py:120-129`:
```python
should_run = (
    (auto_run if auto_run is not None else config.default_auto_run)
    and execution_decision == "AUTO_RUN_ELIGIBLE"  # EXACT MATCH REQUIRED
    and not auto_run_blocked_by_intent
)
```

**Where execution_decision is read**: `run_router.py:102`:
```python
execution_decision = str(context.get("execution_decision") or "")
```

**THREE plan generation paths, only ONE sets it correctly**:

| Path | Endpoint | execution_decision | Result |
|------|----------|-------------------|--------|
| Intent classification | `/ops/drafts` | From IntentClassificationService | Variable |
| **Structured plan** | `/ops/generate-plan` | `"AUTO_RUN_ELIGIBLE"` (hardcoded, line 326) | **Works** |
| **Streaming plan** | `/ops/generate-plan-stream` | **MISSING** (lines 525-531) | **Never runs** |

**The CLI uses the streaming endpoint** (`plan_router.py:358-584`). Lines 525-534 create the draft WITHOUT `execution_decision` in the context dict:
```python
draft = OpsService.create_draft(
    prompt,
    content=...,
    context={
        "structured": True,
        "custom_plan_id": custom_plan.id,
        # execution_decision: MISSING!
    },
    ...
)
```

Compare with non-streaming at line 320-330:
```python
context={
    "structured": True,
    "custom_plan_id": custom_plan.id,
    "execution_decision": "AUTO_RUN_ELIGIBLE",  # PRESENT
}
```

**Root cause**: Copy-paste omission — streaming plan endpoint forgot to include `execution_decision` in draft context.

**Confidence**: HIGH — verified by diffing both code paths line by line.

---

### [N3] GAP — providers login accepts invalid API keys

**CLI entry**: `gimo_cli/commands/providers.py:188-264` — `providers_login` function

**Server storage**: `providers/service_impl.py:398-399`:
```python
if api_key:
    updates["api_key"] = api_key  # Stored as-is, no validation
```

**Auth sanitization**: `providers/auth_service.py:53-89` — stores to environment variable without format check

**Root cause**: No validation step — no format check (Anthropic: `sk-ant-*`, OpenAI: `sk-*`), no test API call to verify the key works.

---

### [N9] SILENT_FAILURE — Chat claims "Plan proposed" on failure

**Root cause**: Same as N1 analysis. `agentic_loop_service.py:1032` sets success message without checking tool execution result. The LLM generates optimistic text ("Plan proposed") which becomes the response, while `tool_calls[].status` shows `"error"`.

**The fix requires**: Checking if ANY tool with `result_status == "plan_proposed"` actually succeeded before using the hardcoded success message. If all propose_plan calls failed, the response should reflect that.

---

### [Thread title] Thread creation ignores user-provided title

**Router**: `conversation_router.py:69`:
```python
resolved_title = body.title if body.title != "New Conversation" else (title or body.title)
```

**Model default**: `CreateThreadRequest.title` defaults to `"New Conversation"`

**Bug**: When client sends `{"title": "My Title"}`, it works. But the condition is fragile — if a user literally wants their thread called "New Conversation", the logic breaks. More importantly, the title comparison depends on Pydantic default behavior.

**Root cause**: The resolver checks for the default string value instead of checking whether the field was explicitly provided.

---

### [Audit 500/403] Dependencies 500, Tail 403

**Dependencies 500**: `dependencies_router.py:20` calls `ProviderService.list_cli_dependencies()` which likely throws an exception (missing or broken implementation).

**Tail 403**: `legacy_ui_router.py:90` uses `require_read_only_access` which checks operator role against allowed paths. The `/ui/audit` path should be in `OPERATOR_EMERGENCY_PATHS` but the auth check may be failing due to token role mismatch.

**Confidence**: MEDIUM — would need runtime debugging to confirm exact failure.

---

### [N8] providers test vs auth-status inconsistency

**`providers test`**: Checks HTTP reachability to provider endpoint only. Returns "Auth status: unknown" always.

**`providers auth-status`**: Queries the auth subsystem which stores the key-based auth state.

**Root cause**: Two completely separate code paths. `test` was designed as a connectivity check, not an auth check, but the UX makes them seem equivalent.

---

### [N10] config preferred_model vs providers model

**Precedence chain** (from `service_impl.py:606` and `model_router_service.py:524`):
1. `X-Preferred-Model` HTTP header (highest)
2. `context["model"]` or `context["preferred_model"]` from config
3. Active provider's default model (lowest)

**CLI's `config --model`** writes to `.gimo/config.yaml` `preferred_model`. This is read by the backend but only when routed through specific code paths.

**Root cause**: Not a bug per se, but undocumented precedence. The CLI has no way to know which model will actually be used.

---

## New Issues Discovered During Tracing

### [NEW-1] Streaming vs non-streaming plan endpoint divergence

Beyond the `execution_decision` bug, the streaming endpoint (`/ops/generate-plan-stream`) and non-streaming endpoint (`/ops/generate-plan`) have diverged in subtle ways. The streaming endpoint has ~250 more lines of code and handles edge cases differently. This is a maintenance risk — any fix applied to one must be manually applied to the other.

### [NEW-2] `workspace_safe` policy exists but is unreachable from CLI

`execution_policy_service.py:83` defines `workspace_safe` which allows all file tools. This is exactly what CLI users need. But there's no CLI flag, API parameter, or configuration option to select it. The entire policy system is locked behind hardcoded presets.

### [NEW-3] propose_plan schema requires `agent_rationale` but LLMs consistently fail to provide it

The `agent_rationale` field is `required` in the JSON schema (chat_tools_schema.py:298) and validated in executor.py:559. But in practice, LLMs (both Claude and ollama) often omit it or provide it inconsistently. The schema describes it as "explain WHY you chose this profile" but the LLM has no context about what profiles exist or why one would be chosen over another. The field is architecturally unreasonable to require from an LLM.

---

## Systemic Patterns

### Pattern 1: "Designed for web, broken for CLI" (5 of 11 issues)

Issues N1, N5, N2, NEW-2, and N10 all share the same root: GIMO's backend was designed for a web UI approval workflow where a human reviews plans before execution. The CLI was bolted on later without adjusting the defaults:
- Default policy is `propose_only` (web-appropriate, CLI-hostile)
- execution_decision missing from streaming path (web uses non-streaming)
- No policy override from CLI (web could use metadata)
- Windows encoding not considered (web doesn't need terminal rendering)

### Pattern 2: "Parallel code paths that drift" (3 of 11 issues)

Issues N5, NEW-1, and the audit 500/403 share the pattern of duplicate code paths that were updated independently:
- Streaming vs non-streaming plan generation
- `providers test` vs `providers auth-status`
- Multiple audit endpoints with different auth requirements

### Pattern 3: "Optimistic responses that lie" (2 of 11 issues)

Issues N1/N9 and N3 share the pattern of reporting success before verifying it:
- Chat says "Plan proposed" when no plan was created
- Login says "authenticated" when key was never validated

---

## Dependency Graph of Issues

```
execution_decision missing (N5) ─────────────────── fixes → run never starts
                                                              │
propose_only default (N1) ──┬── fixes → tool denial          │
                            │                                  │
no policy override (NEW-2) ─┘                                  │
                                                              │
false success response (N9) ── fixes → honest error messages  │
                                                              │
agent_rationale required (NEW-3) ── fixes → propose_plan works│
                                                              │
                            ALL ABOVE ── fixes → calculator can be built

Console encoding (N2) ──────── fixes → Windows CLI usable (independent)

API key validation (N3) ────── fixes → auth reliability (independent)

Thread title (B) ──────────���─ fixes → thread UX (independent)
```

**Key insight**: Fixing N5 (one line: add `execution_decision`) + N1/NEW-2 (change default preset or add CLI flag) would unblock the entire plan→run→execute pipeline. N2 is independent but equally critical for Windows users.

---

## Residual Risks

1. **Bond system**: Not fully traced. The Fernet encryption/machine-key derivation path was not explored. Marked as low priority since Legacy Bond works.
2. **Run execution engine**: Even if `should_run` becomes True, the actual `EngineService.execute_run()` has not been stress-tested. It may have its own bugs.
3. **Tool execution in workspace**: Even if policy allows `write_file`, the file path resolution for the `gimo_prueba` workspace may be incorrect — the tool may write to the wrong directory.
4. **Streaming plan quality**: The streaming endpoint may produce lower-quality plans than non-streaming due to different prompt handling.
