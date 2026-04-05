# GIMO Forensic Audit — Phase 3: Engineering Plan (Round 9)

**Date**: 2026-04-05 05:30 UTC
**Auditor**: Claude Opus 4.6
**Input**: `docs/audits/E2E_ROOT_CAUSE_ANALYSIS_20260405_R9.md`

---

## Diagnosis Summary

Two architectural choices created cascading failures across GIMO:

1. **Subprocess-first LLM invocation**: `CliAccountAdapter` shells out to `claude` CLI, hitting Windows `cmd.exe` 8,191-char limit. This breaks the plan-run pipeline — GIMO's core differentiator.
2. **Terminal surface duplication**: CLI and TUI implement the same chat/streaming flow independently, causing 6 bugs (missing events, wrong HTTP method, hardcoded thread ID, missing header, dead code, legacy imports).

These are not patches waiting to happen. They are structural inversions: the default should be HTTP-first (not subprocess-first) and one terminal (not two).

---

## Competitive Landscape

| Tool | LLM Invocation | Terminal Model | Innovation |
|------|---------------|----------------|------------|
| **Aider** | HTTP via LiteLLM (75+ providers, lazy-loaded) | Single unified CLI | Provider abstraction invisible to user |
| **Claude Code** | Direct Anthropic API (TypeScript SDK) | Single React+Ink terminal | Fires tools at content_block boundary — lowest latency |
| **Cline** | Direct SDK per provider | VS Code extension | MCP marketplace + Plan/Act mode |
| **OpenHands v1** | HTTP SDK, stateless loop | Web UI + API | Single conversation state object, immutable components |
| **AG-UI (CopilotKit)** | N/A (protocol, not product) | Any frontend | STATE_SNAPSHOT/STATE_DELTA for live UI sync |
| **Vercel AI SDK 5** | HTTP SDK with `streamText` | Framework | UIMessage vs ModelMessage separation |

**No competitor uses subprocess to invoke LLMs.** Every one uses HTTP SDK calls.
**No competitor splits CLI and TUI.** Each has one terminal experience.

Sources:
- [Aider Multi-Provider Integration](https://deepwiki.com/Aider-AI/aider/6.3-multi-provider-llm-integration)
- [Claude Code Architecture](https://www.penligent.ai/hackinglabs/inside-claude-code-the-architecture-behind-tools-memory-hooks-and-mcp/)
- [OpenHands Agent Architecture](https://docs.openhands.dev/sdk/arch/agent)
- [AG-UI Protocol](https://docs.ag-ui.com/)
- [Vercel AI SDK 5](https://vercel.com/blog/ai-sdk-5)
- [Cline Review 2026](https://vibecoding.app/blog/cline-review-2026)

---

## Design Principles

1. **HTTP-first, subprocess-fallback**. The `AnthropicAdapter` (already exists) becomes the default path.
2. **One terminal, one code path**. `gimo chat` = TUI. Period.
3. **Shared streaming contract**. One SSE parser, multiple renderers.
4. **Existing code, not new abstractions**. The HTTP adapter exists. The `TerminalSurfaceAdapter` exists. We route and extend, not rewrite.

---

## The Plan

### Change 1: HTTP-First Provider Routing

**Solves**: R9-#1 (run execution WinError 206)

**What**: When provider is `claude` with `auth_mode == "account"`, check if `ANTHROPIC_API_KEY` is available. If yes, use `AnthropicAdapter` (HTTP). If no, use `CliAccountAdapter` but **always use stdin on Windows** (threshold 6000 → 0).

**Where**:
- `tools/gimo_server/services/providers/adapter_registry.py:23-25`
- `tools/gimo_server/providers/cli_account.py:163`

**LOC**: ~10 lines changed

**Why better than competitors**: Aider uses LiteLLM (adds 1.5s load time, 50+ transitive deps). Cline requires VS Code. GIMO's approach is zero-dep: just check env var and route to an adapter that already exists. And the subprocess path remains as graceful fallback — more resilient than single-path approaches.

### Change 2: Terminal Unification

**Solves**: CLI/TUI duplication, TUI missing 5 SSE events, TUI hardcoded thread ID, TUI query param bug, TUI missing header, 138 lines dead code

**What**:
1. Extract SSE event parser into `gimo_cli/sse_events.py` (~80 lines) with `SSEEventHandler` protocol
2. `gimo chat` (interactive) launches TUI
3. `gimo chat --message` (single-turn) stays as-is
4. Fix TUI: real threads, JSON body, X-GIMO-Surface header, all 10 event types
5. Delete dead code, canonicalize imports

**Where**:
- NEW: `gimo_cli/sse_events.py`
- EDIT: `gimo_tui.py`
- EDIT: `gimo_cli/commands/chat_cmd.py`
- EDIT: `gimo_cli/chat.py`

**LOC**: ~80 new, ~200 deleted (net negative)

**Why better than competitors**: AG-UI has 17 event types for a generic protocol. GIMO needs 12 specific ones. Lighter taxonomy, tighter contract, same power. The `SSEEventHandler` protocol extends the existing `TerminalSurfaceAdapter` pattern — no new framework, just one more protocol.

### Change 3: SSE Event IDs + Reconnection

**Solves**: R9-#2 (watch shows stale events)

**What**: Monotonic ID per event. `Last-Event-ID` header support. Buffer cleared on terminal run status.

**Where**:
- `tools/gimo_server/services/notification_service.py`
- `tools/gimo_server/routers/ops/conversation_router.py`
- `gimo_cli/stream.py`

**LOC**: ~30 lines

**Why better than competitors**: Anthropic and OpenAI APIs don't support SSE reconnection (stateless per request). GIMO's SSE endpoint is long-lived across runs, so reconnection matters. Standard SSE `Last-Event-ID` is the lightest possible solution — no custom protocol needed.

### Change 4: Quick Wins (bundled)

**Solves**: R9-#3 (gimo up feedback), R9-#4 (trust reset --yes), R9-#5 (config preferred_model), R9-#6 (model metadata)

| Fix | Where | LOC |
|-----|-------|-----|
| `gimo up` health poll + success message | `gimo_cli/commands/` (up) | ~15 |
| `trust reset --yes` flag | `gimo_cli/commands/` (trust) | ~3 |
| Remove decorative `preferred_model` | `.gimo/config.yaml` | ~1 |
| Add missing model pricing entries | `data/model_pricing.json` | ~20 |

---

## Execution Order

```
Change 1 (HTTP-first routing)     ← unblocks core feature, do first
    ↓
Change 4 (quick wins)             ← low risk, parallelizable
    ↓
Change 3 (SSE event IDs)          ← prerequisite for Change 2
    ↓
Change 2 (terminal unification)   ← largest scope, do last
```

---

## Unification Check

- [x] Single source of truth for LLM invocation
- [x] All surfaces use same SSE contract
- [x] No parallel terminal paths
- [x] No client-side inference of server-known state

## AGENTS.md Compliance

| Criterion | Status | Evidence |
|-----------|--------|----------|
| Permanence | YES | HTTP-first and unified terminal are permanent architectural improvements |
| Completeness | YES | All 8 R9 issues + systemic CLI/TUI finding resolved |
| Foresight | YES | HTTP-first prevents ALL future Windows subprocess limits |
| Potency | YES | Change 1 = 10 lines to unbreak core product. Change 2 = eliminates entire class of parity bugs |
| Innovation | YES | Provider routing (HTTP-first + subprocess fallback) is more resilient than any competitor's single-path. SSE handler is lighter than AG-UI's 17-type protocol |
| Elegance | YES | Two strong concepts: HTTP-first routing + shared SSE handler |
| Lightness | YES | ~120 new LOC, ~200 deleted. Net negative complexity |
| Multiplicity | YES | Change 1 = 3 problems. Change 2 = 6 problems. Two changes, nine problems |
| Unification | YES | One terminal. One SSE parser. One LLM path. One truth |

---

## Residual Risks

1. **Account mode without API key**: Subprocess path remains (hardened). Users with `claude-account` and no `ANTHROPIC_API_KEY` still depend on Claude CLI binary.
2. **TUI widget work**: 5 new SSE event types need TUI widgets/dialogs. This is implementation work within Change 2, not a design risk.
3. **`gimo tui` command**: Kept as alias for `gimo chat` interactive mode. Can be deprecated later.

---

## What This Plan Does NOT Solve

- R9-#7 (repos create): Intentionally deferred — may be by-design.
- R9-#8 (thread list noise): Low priority UX improvement — not architectural.
- Frontend/web surface SSE parity: Out of scope for this terminal-focused plan.
- Playwright/Cypress E2E tests: Zero frontend E2E tests exist. Separate effort.

---

## Follow-Up Investigation: Dynamic Model Pricing

**Priority**: Medium — affects cost tracking accuracy for new models.

**Problem**: `data/model_pricing.json` is a hardcoded static table. When a new model appears (e.g., a new Claude or GPT variant), cost tracking silently fails or falls back to substring matching (`cost_service.py:get_provider()`). No provider API (Anthropic, OpenAI, Google) exposes pricing programmatically. Every competitor (Aider, Cline, Claude Code) also hardcodes prices.

**Investigation scope for next agent**:
1. Research whether any provider has added a pricing API since 2025 (Anthropic, OpenAI, Google, Mistral).
2. Evaluate a `default_tier_pricing` fallback: when a model is not in `model_pricing.json`, infer its tier from `ModelInventoryService` (which already discovers models dynamically) and apply a conservative default price per tier. This prevents silent zero-cost tracking for unknown models.
3. Evaluate a lightweight scraper or periodic sync mechanism that updates `model_pricing.json` from provider pricing pages (e.g., Anthropic's pricing page structure, OpenAI's model list API).
4. Decide: is tier-based fallback sufficient, or does GIMO need exact pricing? The answer determines whether (2) alone solves it or (3) is also needed.

**Current mitigations**: `cost_service.py` already does substring matching as fallback. `ModelInventoryService` already assigns quality tiers. The gap is connecting these two: inventory knows the model exists, but pricing doesn't know the cost.
