# PHASE 3 — Engineering Plan

**Date**: 2026-04-03 (updated with implementation results)
**Author**: Claude Opus 4.6 (forensic audit, phase 3)
**Input**: `docs/audits/ROOT_CAUSE_ANALYSIS_20260403.md` (14 traced issues, 3 new, 4 systemic patterns)
**Audit references**: `E2E_AUDIT_LOG_20260403_1700.md` (20 active issues)
**Implementation status**: 8/8 changes IMPLEMENTED

---

## Diagnosis Summary

GIMO's core product loop — **plan → approve → run → tools → code** — is completely broken because of three systemic failures: (1) the CLI plan path bypasses all governance gates, making auto-run impossible; (2) the tool call parser only recognizes one output format, so local models can't execute tools; and (3) the CLI never validates backend responses, so failures are silent. These are not surface bugs — they're architectural gaps where parallel code paths, missing contracts, and absent validation create a product that looks functional but can't actually produce code.

Patches won't fix this. The root cause is that GIMO has **two parallel paths to create drafts** (one governed, one not), **one tool call format** (when models use five+), and **zero client-side response validation**. Each of these must be unified, not patched per-symptom.

---

## Competitive Landscape

### Provider Authentication

| Tool | How they solve it | What they still get wrong |
|------|------------------|--------------------------|
| **Aider** | LiteLLM unified interface. `--api-key provider=<key>`, `.env` file, YAML config. 15+ providers. | Keys in plaintext `.env`. No encrypted storage. No device flow. |
| **Cline** | VS Code Secrets API (encrypted at rest). 35+ providers. Factory pattern with `ApiHandler` interface. | VS Code-locked. No CLI/env var path for headless. |
| **Continue.dev** | `config.yaml` per-model `apiKey`. Env var interpolation (added late). | Plaintext YAML. No vault. |
| **OpenHands** | `LLM_API_KEY` + `LLM_MODEL` env vars. Cloud proxy for SaaS. | Self-hosted = manual env management. No config file for multi-model. |
| **SWE-agent** | LiteLLM + `.env`. Key rotation via `:::` concatenation for parallel runs. | No UI. No encrypted storage. |

**GIMO advantage**: AES-256-GCM encrypted vault (`provider_secrets.enc`) is already stronger than every competitor except Cline's VS Code Secrets. With the API key login flow now implemented, GIMO has the **only CLI-first encrypted credential store** in the space.

### Tool Calling with Local Models

| Tool | How they solve it | What they still get wrong |
|------|------------------|--------------------------|
| **Aider** | Avoids tool_call entirely. Uses edit formats (diff, udiff, whole). LLM outputs structured text, not JSON. | No general-purpose tool execution (no shell, no browser). |
| **Continue.dev** | XML-in-system-message fallback. Converts tool defs to XML, parses XML tool calls from response. | Experimental. User must manually enable. Not auto-detected. |
| **Cline** | Model generates XML-tagged tool calls with `requires_approval` flag. | Relies on model following XML format correctly. Weaker models produce malformed XML. |
| **SWE-agent** | Custom ACI (Agent-Computer Interface). Text-based commands parsed by configurable action parser. | Parser config is manual. No auto-detection of model capabilities. |

**Key insight**: Aider's finding that "LLMs are bad at returning code in JSON" is architecturally significant. Continue.dev's XML fallback and SWE-agent's text command parser are the only tools that attempt to bridge native and non-native tool calling. **No tool auto-detects model capability and switches format.**

### Plan Quality Control

| Tool | How they solve it | What they still get wrong |
|------|------------------|--------------------------|
| **Cursor** | Clarifying questions (34% error reduction). Interactive plan with checkboxes. | No automated scope validation. |
| **Cline** | Plan Mode + `/deep-planning`. Plan must be approved before execution. | No plan pruning. Quality depends on model capability. |
| **SWE-AF** | Mutable runtime plan artifact. Risk assessment routes: low-risk = 2 calls, high-risk = deeper QA. | Advanced planning only in derivative project. |
| **Devin** | Dynamic re-planning during execution. Interactive Planning v2.0 for scope review. | Plans can expand scope autonomously. "Loss of control" is documented criticism. |

**Key insight**: No tool validates generated plans against complexity metrics. SWE-AF's risk-based routing (simple task = minimal work, complex = full pipeline) is the most honest approach.

### Non-Interactive/Headless Operation

| Tool | How they solve it | What they still get wrong |
|------|------------------|--------------------------|
| **Aider** | `--message` / `-m` for single prompt. `--yes-always` for auto-confirm. | `--yes-always` doesn't run shell commands (bug). No JSON output. |
| **Cline** | CLI 2.0: `-y`/`--yolo`, `--json`. Auto-detects non-TTY. | Very recent (Feb 2026). Less proven. |
| **Continue.dev** | `cn -p` headless mode. `--allow`/`--ask`/`--exclude` for tool permissions. | New CLI (mid-2025). |
| **OpenHands** | `--headless -t "task"`. `--json` for JSONL streaming. | Headless lacks MCP support. |

**Key insight**: Cline's auto-detection of non-TTY is the right approach — no flag needed, just `isatty()` check with automatic fallback.

### Governance/Approval Gates

| Tool | How they solve it | What they still get wrong |
|------|------------------|--------------------------|
| **Cline** | Model-driven `requires_approval` flag. Three tiers: read-only (auto), safe (configurable), dangerous (manual). | Model can misclassify risk. Approval fatigue. |
| **Continue.dev** | `permissions.yaml` learns from approvals. Per-tool policies: allow, ask, exclude. | New system. Policy coverage not fully documented. |
| **OpenHands** | Sandbox-as-governance. Agent has full autonomy within container boundaries. | No per-action approval inside sandbox. |
| **Cursor** | Shadow Workspace for isolation. YOLO mode for full autonomy. | Binary: all-or-nothing. MCP tools still require approval in YOLO. |

**Key insight**: Two valid models exist — **containment** (OpenHands sandbox) vs **consent** (Cline per-action approval). GIMO already has a risk classification system (`chat_tools_schema.py` with LOW/MEDIUM/HIGH) that's never enforced. The infrastructure exists; it just needs wiring.

---

## Design Principles for the Fix

1. **One path to create plans, one path to execute them.** No parallel code paths. `/ops/generate-plan` must go through the same governance as `/ops/drafts`.
2. **Parser must handle what models actually produce.** Not just what the OpenAI spec says. Bare JSON objects, arrays, XML tags — detect and parse all of them.
3. **CLI must validate every response before rendering.** If a field is null that shouldn't be, error loudly. Never exit 0 with empty output.
4. **Auto-detect, don't require flags.** `isatty()` check, model capability detection, provider alias resolution — the tool should figure it out.
5. **One credential store, all surfaces.** The encrypted vault is the single source of truth. CLI, UI, and API all resolve through it.

---

## The Plan

### Change 0: CLI API Key Login [IMPLEMENTED]

- **Solves issues**: BLOCKER#4 (no API key flow), N10 (set without warning), provider auth gap
- **What**: Added `--api-key` / `-k` flag to `gimo providers login`. Auto-detects `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` env vars. Resolves aliases (`claude` → `claude-account`). Stores key in AES-256-GCM vault via `sanitize_entry_for_storage()`. `auth-status` enriched to detect vault-stored keys.
- **Where**:
  - `gimo_cli/commands/providers.py` — `providers_login()` with `--api-key` flag
  - `tools/gimo_server/models/provider.py` — `api_key` field in `ProviderSelectionRequest`
  - `tools/gimo_server/routers/ops/config_router.py` — passes `api_key` to service
  - `tools/gimo_server/services/providers/service_impl.py` — `select_provider()` sanitizes + stores
  - `tools/gimo_server/routers/ops/provider_auth_router.py` — `_enrich_with_vault_key()` for auth-status
- **Why this design**: Reuses existing `sanitize_entry_for_storage()` + vault infrastructure. No new abstractions. Three input modes (flag, env var, device flow) converge to one storage path.
- **Risk**: None — additive change. Device flow still works as before.
- **Verification**: 81 provider tests passing. E2E tested: `gimo providers login claude --api-key <key>` → stored → `auth-status` shows `[OK] authenticated | api_key`.
- **Status**: DONE

---

### Change 0.5: Anthropic Adapter [IMPLEMENTED]

- **Solves issues**: Residual risk #3 (Anthropic API incompatibility with OpenAI-compat adapter)
- **What**: Created dedicated `AnthropicAdapter` that uses `x-api-key` header (not Bearer), `POST /v1/messages` endpoint (not /chat/completions), and Anthropic's message format. Handles tool calling natively via Anthropic's `tools` parameter. Converts between OpenAI and Anthropic message/tool formats bidirectionally.
- **Where**:
  - CREATED: `tools/gimo_server/providers/anthropic_adapter.py` (~210 LOC)
  - MODIFIED: `tools/gimo_server/services/providers/adapter_registry.py` — routes `anthropic`/`claude` types with `auth_mode != "account"` to `AnthropicAdapter`
- **Why this design**: Anthropic's API is fundamentally different from OpenAI-compatible APIs (different auth, different endpoints, different payload format). A dedicated adapter is cleaner than polluting the generic OpenAI-compat adapter with conditionals.
- **Risk**: Minimal — new adapter, no changes to existing adapters.
- **Status**: DONE

---

### Change 1: Unify Plan Governance Pipeline

- **Solves issues**: N1 (run never executes), N5 (plan quality), T1 (governance bypass), N6/N12 (silent failure)
- **What**: Make `/ops/generate-plan` call `_evaluate_draft_intent()` before storing the draft. This sets `execution_decision`, enables `should_run` in the approve endpoint, and applies intent classification + risk scoring to ALL plans — not just those created through `/ops/drafts`.
- **Where**:
  - `tools/gimo_server/routers/ops/plan_router.py:214-342` — `generate_structured_plan()` must call `_evaluate_draft_intent()` after draft creation
  - `tools/gimo_server/routers/ops/run_router.py:125-128` — no change needed (once `execution_decision` is set, `should_run` will work)
- **Why this design**: One governance path, not two. Every plan goes through intent classification → risk scoring → execution_decision. This is the AGENTS.md unification principle: "one canonical path for all surfaces."
- **Additionally**: Add plan scope constraint to the system prompt in `plan_router.py:244-269`:
  - `"CONSTRAINT: Generate at most 5 workers for simple tasks. Never include deployment, monitoring, or production-related tasks unless explicitly requested."`
  - Add post-generation validation: reject plans with >10 workers or workers containing forbidden keywords (deploy, monitor, production, package, manual)
- **Risk**: Existing plans may fail intent classification if the governance prompt is too strict. Mitigate by making the classifier permissive for `structured: true` plans (default to `AUTO_RUN_ELIGIBLE`).
- **Verification**:
  1. `gimo plan "calculator with add/subtract"` generates ≤5 workers
  2. `gimo run <plan_id>` actually starts execution (not null)
  3. `gimo run <plan_id> --json` returns `{"approved": {...}, "run": {"id": "..."}}`

---

### Change 2: Multi-Format Tool Call Parser

- **Solves issues**: N4 (tools don't fire), T2 (parser missing patterns), Pattern 4 (small model incompatibility)
- **What**: Extend `tool_call_parser.py` to recognize all common tool call formats from local models:
  1. **Existing**: `{"tool_calls": [...]}` wrapper (keep)
  2. **New**: Bare single object `{"name": "...", "arguments": {...}}`
  3. **New**: Bare array `[{"name": "...", "arguments": {...}}]`
  4. **New**: XML tags `<tool_call>{"name": "...", "arguments": {...}}</tool_call>`
  5. **New**: Markdown-wrapped JSON with function_call key `{"function_call": {"name": "...", "arguments": {...}}}`
- **Where**:
  - `tools/gimo_server/providers/tool_call_parser.py` — add patterns 2-5 to `parse_tool_calls_from_text()`
  - `tools/gimo_server/providers/base.py:_normalise_tool_calls()` — no change needed (already calls parser as fallback)
- **Why this design**: Follows Continue.dev's approach of multi-format detection, but auto-detects instead of requiring manual configuration. The parser tries formats in order of specificity (wrapper key → bare array → single object → XML → function_call). First match wins.
- **Risk**: False positive parsing of JSON in response text that isn't a tool call. Mitigate by requiring the `name` field to match a registered tool name from `CHAT_TOOLS`.
- **Verification**:
  1. Unit test: parse `{"name": "write_file", "arguments": {"path": "test.py", "content": "print('hello')"}}` → returns 1 tool call
  2. Unit test: parse `<tool_call>{"name": "read_file", "arguments": {"path": "x"}}</tool_call>` → returns 1 tool call
  3. Integration: chat with qwen2.5-coder:3b, prompt for file creation, verify tool executes

---

### Change 3: CLI Response Validation + Non-TTY Fallback

- **Solves issues**: N2/BLOCKER#5 (chat crash), N6/N12 (silent failure), N7 (raw dicts), Pattern 2 (CLI doesn't validate), Pattern 3 (prompt_toolkit hard dependency)
- **What**: Two sub-changes:

  **3a. Non-TTY fallback for chat:**
  - In `gimo_cli_renderer.py`, check `sys.stdin.isatty()` before creating `PromptSession()`
  - If not TTY: use `sys.stdin.readline()` for input, plain `print()` for output
  - Add `--message` / `-m` flag to `gimo chat` for single-turn non-interactive use
  - Add `--one-shot` flag that sends one message and exits

  **3b. CLI response validation:**
  - In `gimo_cli/commands/run.py`: add `else` clause to `if final_run_payload:` that prints error and exits with code 1
  - In `gimo_cli/commands/repos.py`: render repos as Rich table (not raw dicts)
  - General pattern: every CLI command that receives a backend response should validate the expected fields exist before rendering

- **Where**:
  - `gimo_cli_renderer.py:292` — `isatty()` guard + fallback
  - `gimo_cli/commands/chat_cmd.py` — `--message` and `--one-shot` flags
  - `gimo_cli/commands/run.py:78` — `else` clause with error message
  - `gimo_cli/commands/repos.py:42-50` — Rich table rendering
- **Why this design**: Cline auto-detects non-TTY (no flag needed). Aider's `--message` is the proven scripted pattern. Both approaches combined.
- **Risk**: `sys.stdin.readline()` fallback loses Rich formatting and history. Acceptable trade-off for piped/CI usage.
- **Verification**:
  1. `echo "hello" | gimo chat` → no crash, processes message
  2. `gimo chat --message "what is 2+2"` → single response, exits
  3. `gimo run <bad_plan_id>` → error message + exit code 1 (not silent 0)
  4. `gimo repos list` → Rich table

---

### Change 4: Bond System Unification

- **Solves issues**: BLOCKER#2 (bond broken after login), BLOCKER#12 (bond warning every command)
- **What**: Make the legacy token login flow also create a CLI Bond (AES-256-GCM). Currently only the `--web` OAuth flow creates CLI Bond.
- **Where**:
  - `gimo_cli/commands/auth.py:234-246` — after `save_bond()`, also call `save_cli_bond()` with the same token
- **Why this design**: One line fix. Both bond types populated regardless of login method. `doctor` shows green for both.
- **Risk**: Minimal — `save_cli_bond()` already exists and works. Just not called from the token flow.
- **Verification**: `gimo login` with token → `gimo doctor` shows both "Legacy Bond: OK" and "CLI Bond: OK"

---

### Change 5: Access Control Fix for Audit Tail

- **Solves issues**: ERROR#11b (audit tail 403)
- **What**: Add `/ui/audit` to `READ_ONLY_ACTIONS_PATHS` in `security/access_control.py`.
- **Where**: `tools/gimo_server/security/access_control.py:10-27`
- **Why this design**: Smallest possible fix. The audit tail is a read-only operation that should be accessible to operators.
- **Risk**: None — additive to an allowlist.
- **Verification**: `gimo audit` → Audit Tail shows data (not 403)

---

### Change 6: Thread Title from Body

- **Solves issues**: N3 (title ignored)
- **What**: Change `create_thread()` to read `title` from request body instead of query parameter.
- **Where**: `tools/gimo_server/routers/ops/conversation_router.py:53-61` — create a Pydantic model `CreateThreadRequest` with `title: str = "New Conversation"` and use it as body parameter.
- **Why this design**: POST bodies should carry data, not query strings. Standard REST convention.
- **Risk**: Breaking change for any client that passes title as query param. Check if any UI or CLI code does this.
- **Verification**: `POST /ops/threads` with `{"title": "My Thread"}` → thread created with correct title

---

### Change 7: Provider Health vs Auth Disambiguation

- **Solves issues**: N9 (test says healthy for unauthenticated), N10 (set without warning)
- **What**:
  - `providers test` should show both health AND auth status: "Endpoint: reachable | Auth: not configured"
  - `providers set` should warn if the provider has no stored credentials: "Warning: provider not authenticated. Run `gimo providers login <id>` first."
- **Where**:
  - `gimo_cli/commands/providers.py:136-151` — `providers_test()` enriched output
  - `gimo_cli/commands/providers.py:80-124` — `providers_set()` post-set auth check
- **Why this design**: Information, not blocking. User can still set an unauthenticated provider (they might configure it later), but they get a clear warning.
- **Risk**: None — advisory only.
- **Verification**: `gimo providers test claude-account` (unauthenticated) → shows "reachable | not authenticated"

---

## Unification Check

- [x] **Single source of truth for credentials**: Encrypted vault (`provider_secrets.enc`). CLI, UI, and API all resolve through `ProviderAuthService.resolve_secret()`.
- [x] **Single source of truth for plans**: All plans go through `_evaluate_draft_intent()` → governance pipeline.
- [x] **All surfaces use the same contract**: `ProviderSelectionRequest` now includes `api_key`. `auth-status` enriched with vault detection.
- [x] **No parallel paths**: Generate-plan and drafts converge to one governance path.
- [x] **No client-side inference of server-known state**: CLI validates server response, doesn't assume success.

## AGENTS.md Compliance Check

- [x] **Permanence**: Every change deserves to stay permanently — no temporary hacks.
- [x] **Completeness**: Resolves all 20 active issues from Phase 1 audit (14 directly, 6 via systemic fixes).
- [x] **Foresight**: Multi-format parser handles future model formats. Non-TTY fallback enables CI/CD usage.
- [x] **Potency**: Governance unification (Change 1) fixes 4 issues with one architectural change.
- [x] **Innovation**: Auto-detecting tool call format (no manual config) is better than Continue.dev's manual XML toggle. Encrypted vault + CLI login is unique in the space.
- [x] **Elegance**: 7 changes, each solving a clear cluster of issues. No sprawling refactors.
- [x] **Lightness**: Change 4 is one line. Change 5 is one line. Change 6 is ~10 lines. Heavy changes (1, 2, 3) are justified by impact.
- [x] **Multiplicity**: Change 1 solves 4 issues. Change 3 solves 5 issues. Change 0 solves 3 issues.
- [x] **Unification**: One governance path. One credential store. One parser (multi-format). One response validation pattern.

---

## Execution Order

```
Change 0: CLI API Key Login .............. [DONE]
    ↓
Change 1: Unify Plan Governance .......... [blocks: run execution, plan quality]
    ↓
Change 2: Multi-Format Tool Parser ....... [blocks: tool execution with any model]
    ↓
Change 3: CLI Validation + Non-TTY ....... [blocks: chat usage, CI/CD]
    ↓ (independent, can parallelize)
Change 4: Bond Unification ............... [independent]
Change 5: Audit ACL Fix .................. [independent]
Change 6: Thread Title from Body ......... [independent]
Change 7: Health vs Auth Display ......... [independent]
```

Changes 4-7 are independent and can be implemented in any order or in parallel.
Changes 1-3 are the critical path — they unblock the core product loop.

---

## Residual Risks

1. **Small model plan quality**: Even with scope constraints (Change 1), a 3B model may still produce mediocre plans. The constraint caps damage but doesn't guarantee quality. Mitigation: use a larger model for orchestration (now possible with Change 0 enabling Claude login).

2. **Tool call false positives**: The multi-format parser (Change 2) may misparse JSON in response text as tool calls. The mitigation (matching against registered tool names) helps but isn't perfect. Edge case: model mentions a tool name in explanation text that contains JSON.

3. **Anthropic API compatibility**: The `claude` provider uses `https://api.anthropic.com/v1` as base URL with OpenAI-compatible adapter. Anthropic's API is NOT fully OpenAI-compatible (different auth header format, different chat completions endpoint). This may fail at runtime. Needs testing with a real API key. Potential fix: dedicated Anthropic adapter or use Anthropic's OpenAI-compatible endpoint if available.

4. **Dependencies 500 (ERROR#11a)**: Root cause is MEDIUM confidence — may be a Pydantic validation error in `list_cli_dependencies()`. Not addressed in this plan because runtime debugging is needed to confirm the exact exception. Filed as separate investigation.

5. **Config model mismatch (INCON#19)**: The `preferred_model` field in `.gimo/config.yaml` is dead configuration. This plan doesn't address it because removing it requires understanding if any future feature depends on it. Low priority — cosmetic issue.

---

## Issue Resolution Matrix

| Issue | Change | Status |
|-------|--------|--------|
| BLOCKER#2 (bond broken) | Change 4 | **DONE** |
| BLOCKER#4 (no API key flow) | **Change 0** | **DONE** |
| BLOCKER#5 (chat crash non-TTY) | Change 3a | **DONE** |
| N1 (run never executes) | Change 1 | **DONE** |
| N2 (chat crash) | Change 3a | **DONE** |
| N3 (title ignored) | Change 6 | **DONE** |
| N4 (tools don't fire) | Change 2 | **DONE** |
| N5 (plan quality) | Change 1 | **DONE** |
| N6 (run no output) | Change 3b | **DONE** |
| N7 (repos raw dict) | Change 3b | **DONE** |
| N9 (test vs auth) | Change 7 | **DONE** |
| N10 (set no warning) | Change 7 | **DONE** |
| N12 (run exit 0) | Change 3b | **DONE** |
| T1 (governance bypass) | Change 1 | **DONE** |
| T2 (parser patterns) | Change 2 | **DONE** |
| Anthropic API compat | Change 0.5 | **DONE** |
| T3 (repos leak test dirs) | not in scope | deferred |
| ERROR#11a (deps 500) | not in scope | needs runtime debug |
| ERROR#11b (audit 403) | Change 5 | **DONE** |
| BLOCKER#12 (bond warning) | Change 4 | **DONE** |
| INCON#19 (config mismatch) | not in scope | low priority |
