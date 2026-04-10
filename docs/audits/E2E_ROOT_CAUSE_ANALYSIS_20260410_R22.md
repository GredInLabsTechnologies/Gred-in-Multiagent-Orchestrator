# E2E Root-Cause Analysis — Codex Timeout

**Date**: 2026-04-10
**Round**: R22
**Phase**: 2 — Root-cause analysis
**Scope**: Why does `codex-account` (GPT-5) timeout on every code generation task?
**Input**: Live session evidence from calculator E2E test (threads thread_e0d222e2, thread_acabfda0)

---

## Issue Map

| ID | Title | Severity | Confidence |
|----|-------|----------|------------|
| RC-1 | GICS anomaly detection clamps codex/gpt-5 to propose_only | BLOCKER | HIGH |
| RC-2 | ConstraintCompilerService not covered by DEBUG mode bypass | BLOCKER | HIGH |
| RC-3 | CLI adapter retry loop amplifies timeout from 300s to 600s+ | CRITICAL | HIGH |
| RC-4 | Tool schema injection bloats prompt past Windows argument limit | CRITICAL | HIGH |
| RC-5 | httpx and subprocess race on identical 300s timeout | FRICTION | HIGH |
| RC-6 | GICS anomaly should degrade, not block — contradicts GICS design philosophy | INCONSISTENCY | HIGH |

---

## [RC-1] GICS anomaly detection clamps codex/gpt-5 to propose_only

**Reported symptom**: Codex subprocess returns 192 chars of text instead of expected code, then retry loop triggers and times out at 300s.

**Entry point**: `mcp_bridge/native_tools.py::gimo_chat` → POST `/ops/threads/{id}/chat`

**Trace**:
- `routers/ops/conversation_router.py::chat_message` (line 201) → `AgenticLoopService.run()`
- `services/agentic_loop_service.py::run` (line 1426) → `ConstraintCompilerService.apply_trust_authority(execution_policy, model_id="gpt-5", provider_type="codex")`
- `services/constraint_compiler_service.py::apply_trust_authority` (line 210-222):
  ```python
  reliability = gics.get_model_reliability(provider_type="codex", model_id="gpt-5")
  if reliability and reliability.get("anomaly"):
      return "propose_only", False  # ← HARD CLAMP
  ```
- `services/gics_service.py::get_model_reliability` (line 479) → GICS daemon lookup on key `ops:model_score:codex:gpt-5`
- GICS returns `{"anomaly": True}` based on prior session failures (timeouts recorded as errors)
- Back in `agentic_loop_service.py` (line 1460): `filter_tools_by_policy(CHAT_TOOLS, policy_obj.allowed_tools)` → only exposes 7 read-only tools (no write_file, patch_file, shell_exec, etc.)
- Adapter receives restricted tools → codex responds with text (not tool_calls) → 192 chars

**Root cause**: GICS recorded previous codex timeout failures as model anomalies. On next request, ConstraintCompilerService sees the anomaly flag and **hard-clamps** execution to `propose_only`, which strips write tools. Without write tools, the response is pure text. The CLI adapter then sees "no tool_calls" and enters the **retry loop**, which pushes the prompt over the 8000-byte Windows limit, triggering temp-file pipe mode, which then times out at 300s.

**Blast radius**: Every codex-account request is affected once GICS records a single failure. This is a **vicious cycle**: failure → anomaly → propose_only → retry → timeout → more failures → stronger anomaly.

**Fix options**:
1. Add DEBUG mode bypass to ConstraintCompilerService (immediate)
2. Change GICS anomaly from hard-block to soft-degrade (architectural, aligns with GICS philosophy)
3. Add `propose_only` detection in CLI adapter to skip retry loop

---

## [RC-2] ConstraintCompilerService not covered by DEBUG mode bypass

**Reported symptom**: Despite DEBUG=true env var, codex/gpt-5 is still clamped to propose_only.

**Entry point**: `services/constraint_compiler_service.py::apply_trust_authority`

**Trace**:
- `services/trust_engine.py` — has `_DEBUG_MODE` check ✅
- `services/economy/cost_service.py` — has `_DEBUG_MODE` check ✅
- `services/economy/budget_forecast_service.py` — has `_DEBUG_MODE` check ✅
- `services/agent_insight_service.py` — has `_DEBUG_MODE` scaffold ✅
- `services/model_router_service.py` — has `_DEBUG_MODE` scaffold ✅
- `services/constraint_compiler_service.py` — **NO DEBUG MODE CHECK** ❌

**Root cause**: When we implemented debug mode across the governance stack, the ConstraintCompilerService was not included. It has its own independent path to GICS (`GicsService.get_model_reliability()`) that is not gated by the TrustEngine's debug mode. The constraint compiler is architecturally upstream of the TrustEngine — it runs at compile-time before the loop starts, while TrustEngine runs during/after execution.

**Blast radius**: Debug mode is incomplete. Any GICS anomaly detection still blocks, defeating the purpose of DEBUG mode for development.

**Fix options**:
1. Add `_DEBUG_MODE` check at the top of `apply_trust_authority()` — return policy unchanged in debug mode
2. Log a warning when debug mode bypasses the clamp, so the anomaly is visible but not blocking

---

## [RC-3] CLI adapter retry loop amplifies timeout from 300s to 600s+

**Reported symptom**: Second attempt (thread_acabfda0) took >600s total before failing.

**Entry point**: `providers/cli_account.py::_raw_chat_with_tools` (line 302)

**Trace**:
- First `generate()` call: prompt_len=7870, under 8000 limit → argument mode
- Codex responds with 192 chars of text (propose_only restricted its tools)
- `_parse_tool_calls_from_text()` finds no tool_calls in the text
- Retry loop activates (line 302): `while not tool_calls and tools and retry_count < max_retries:`
- Retry builds new prompt: original (7870) + response (192) + retry hint (~200) = 8285 bytes
- 8285 > 8000 → switches to temp file pipe mode
- Second `generate()` call: subprocess.run with 300s timeout → TIMEOUT
- Total wall time: ~300s (first call, fast) + 300s (retry, timeout) = **~600s**

**Root cause**: The retry loop in `_raw_chat_with_tools` was designed for cases where the LLM should have made tool calls but didn't format them correctly. When the execution policy strips tools, the LLM correctly responds with text. The retry logic doesn't distinguish "no tools available" from "tools available but LLM didn't use them."

**Blast radius**: Every propose_only-clamped CLI request gets an unnecessary retry that doubles the wall time.

**Fix options**:
1. Skip retry when `tools` list is empty or when effective policy is propose_only
2. Check if the tools list contains only read-only tools and skip retry for those
3. Add the effective policy to the adapter context so it can decide

---

## [RC-4] Tool schema injection bloats prompt past Windows argument limit

**Reported symptom**: Prompt starts at ~2500 chars (user message) but arrives at `generate()` as 7870-9742 chars.

**Entry point**: `providers/cli_account.py::_raw_chat_with_tools` (line 260)

**Trace**:
- `_raw_chat_with_tools` builds prompt from messages:
  - System message: SYSTEM_PROMPT_TEMPLATE (~600 chars) + workspace tree (~500-2000 chars)
  - System message gets TOOL_CALLING_SYSTEM_PROMPT appended (~300 chars template)
  - `_format_tools_for_prompt(tools)` adds ~2000-4000 chars of tool descriptions
  - User message: ~500-2500 chars
- Total: **7000-10000+ chars** per prompt
- `generate()` checks `len(prompt.encode("utf-8")) > 8000` → over limit → temp file pipe

**Prompt size breakdown** (measured):
| Component | Size |
|-----------|------|
| CHAT_TOOLS JSON schemas (12 tools) | 6804 chars |
| `_format_tools_for_prompt()` text output | ~3000-4000 chars |
| SYSTEM_PROMPT_TEMPLATE + tree | ~1500-2500 chars |
| User message | ~500-2500 chars |
| **Total to `generate()`** | **7000-10000+ chars** |

**Root cause**: Every CLI adapter call gets the full tool description injected into the prompt as text. For models like codex/GPT-5 that natively support function calling, this is wasteful — the tools are re-serialized as natural language instead of using the native format.

**Blast radius**: All codex-account prompts are inflated ~3x beyond the actual user content. On Windows, this consistently pushes over the 8000 char limit into the slower temp-file pipe path.

**Fix options**:
1. Short term: increase `_WIN_ARG_LIMIT` to match actual cmd.exe limit (~8191)
2. Medium term: skip tool injection for propose_only policy (no write tools = no need to describe them)
3. Long term: native function calling for codex-account (codex CLI may support it via --tools flag)

---

## [RC-5] httpx and subprocess race on identical 300s timeout

**Reported symptom**: Both `gimo_chat_error` (ReadTimeout) and `orchestrator` (subprocess timeout) errors appear on the same thread.

**Entry point**: `mcp_bridge/native_tools.py::_background_chat` (line 892)

**Trace**:
- `_background_chat()` → `httpx.AsyncClient(timeout=300.0)` → POST `/ops/threads/{id}/chat`
- Backend handler → agentic loop → adapter → `subprocess.run(timeout=300)`
- t=0.0: httpx sends POST
- t=0.5: subprocess starts codex exec
- t=300.0: httpx ReadTimeout fires (300s from t=0)
- t=300.5: subprocess TimeoutExpired fires (300s from t=0.5)
- Both errors are recorded independently to the thread

**Root cause**: The httpx client timeout and the subprocess timeout are both set to 300s, but httpx starts ~0.5s earlier. The httpx timeout fires first, the background task exception handler records `gimo_chat_error`. Then the subprocess timeout fires independently, the agentic loop records `orchestrator` error.

**Blast radius**: Double error recording. Confusing for diagnostics. The httpx error (`ReadTimeout:` with no details) obscures the real subprocess error.

**Fix options**:
1. Set httpx timeout higher than subprocess timeout (e.g., 360s vs 300s)
2. Add the subprocess timeout value to the error message for clarity

---

## [RC-6] GICS anomaly should degrade, not block

**Reported symptom**: GICS anomaly detection hard-clamps to propose_only, preventing all write operations.

**Entry point**: `services/constraint_compiler_service.py::apply_trust_authority` (line 222)

**Trace**:
- `return "propose_only", False` — unconditional hard clamp
- No graduated response (warning → soft degrade → hard clamp)
- No distinction between "unreliable model" and "model with no data"
- No debug mode bypass

**Root cause**: The current implementation treats GICS anomaly as a binary signal. The design philosophy of GICS (per user) is to **degrade and announce**, not to **prohibit**. The constraint compiler should show the anomaly data, suggest using a different model, but NOT block execution entirely. This is analogous to how TrustEngine debug mode works: show the data, don't enforce.

**Blast radius**: Any model that fails once on a new session starts a vicious cycle. Codex/GPT-5 was caught in this cycle because of previous timeout failures from the same session.

**Fix options**:
1. Change anomaly response from hard-clamp to soft-degrade:
   - Log warning with anomaly details
   - Add `X-GIMO-Trust-Warning` header or metadata flag
   - Don't change execution policy
2. Implement graduated trust: warn at >30% failure, require review at >50%, block only at >80%
3. In debug mode: always skip the clamp and just log

---

## Systemic Patterns

### Pattern A: Vicious failure cycle
GICS records failures → anomaly flag → policy clamp → restricted tools → retry → timeout → more failures. No circuit breaker. No expiry. No recovery path without manual intervention.

### Pattern B: Incomplete debug mode coverage
Debug mode was implemented in 5 services but not in the ConstraintCompilerService, which is the most impactful governance gate. The trust authority gate runs BEFORE the agentic loop starts — upstream of all other debug-moded services.

### Pattern C: CLI adapter assumes tool-calling intent
`_raw_chat_with_tools` always expects tool_calls and retries if not found. But when the execution policy is propose_only, tools are restricted to read-only. The adapter should not retry when the policy makes write-tool-calls impossible.

### Pattern D: Prompt inflation for non-native tool calling
The CLI adapter serializes OpenAI tool schemas as natural language text, inflating prompts ~3x. This is a fundamental cost of using CLI subprocesses instead of HTTP API with native function calling.

---

## Prioritized Fix Order

1. **[RC-2] Add DEBUG mode to ConstraintCompilerService** — immediate, unblocks all debug work
2. **[RC-6] Change GICS anomaly from hard-block to soft-degrade** — architectural, aligns with design philosophy
3. **[RC-3] Skip retry when policy is propose_only** — prevents timeout amplification
4. **[RC-5] Offset httpx timeout** — minor, prevents double error
5. **[RC-4] Reduce prompt inflation** — medium term optimization
6. **[RC-1] Clear stale GICS anomaly data** — operational fix for current session

---

## Preventive Risks

- If GICS anomaly data is never expired, models that fail during development will be permanently penalized in production
- If the retry loop in CLI adapter is removed entirely, legitimate retry cases (malformed tool_calls) would regress
- If propose_only policy is bypassed in debug mode, actual governance bugs may be masked during development
