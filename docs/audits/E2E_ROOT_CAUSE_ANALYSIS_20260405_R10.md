# GIMO Forensic Audit — Phase 2: Root-Cause Analysis (Round 10)

**Date**: 2026-04-05 17:00 UTC
**Auditor**: Claude Opus 4.6 (independent auditor, tenth audit round)
**Input**: `docs/audits/E2E_AUDIT_LOG_20260405_R10.md` (Phase 1 report)

---

## Issue #1 — AnthropicAdapter double `/v1/v1/messages` URL [BLOCKER]

### Symptom
Every LLM call (chat, plan, run) returns `404 Not Found` for URL `https://api.anthropic.com/v1/v1/messages`.

### Trace

```
adapter_registry.py:30
  base_url = entry.base_url or DEFAULT_BASE_URLS.get(canonical_type, "https://api.anthropic.com")
  → picks "https://api.anthropic.com/v1" from DEFAULT_BASE_URLS["claude"]

metadata.py:48-49
  "anthropic": "https://api.anthropic.com/v1",
  "claude": "https://api.anthropic.com/v1",
  → These URLs include /v1 because DEFAULT_BASE_URLS was designed for the OpenAI-compat adapter,
    which expects the full base URL including version prefix

anthropic_adapter.py:180,212,225
  f"{self.base_url}/v1/messages"
  → Appends /v1/messages to a base_url that already ends in /v1
  → Result: https://api.anthropic.com/v1/v1/messages (404)

anthropic_adapter.py:29
  base_url: str = "https://api.anthropic.com"  (correct default, no /v1)
  → Never used because adapter_registry.py always passes the DEFAULT_BASE_URLS value
```

### Root Cause

**Architectural mismatch between two conventions**:

1. `DEFAULT_BASE_URLS` (metadata.py) uses the **OpenAI-compat convention**: base URL includes the version prefix (`/v1`). This is correct for the `OpenAICompatAdapter` which appends only `/chat/completions`.

2. `AnthropicAdapter` uses the **Anthropic SDK convention**: base URL is the bare domain, and the adapter appends `/v1/messages` itself. This matches Anthropic's official Python SDK behavior.

R9's HTTP-first routing change (`adapter_registry.py:25-31`) connected these two systems for the first time — `AnthropicAdapter` now receives a URL from `DEFAULT_BASE_URLS` instead of using its own default. The conventions collided, producing the double path.

### Fix Options

| Option | Location | Change | Risk |
|--------|----------|--------|------|
| A | `anthropic_adapter.py:180,212,225` | Strip `/v1` from `self.base_url` if present, then append `/v1/messages` | Low — localized to adapter |
| B | `adapter_registry.py:30` | Use `"https://api.anthropic.com"` as fallback instead of `DEFAULT_BASE_URLS` for AnthropicAdapter | Low — but special-cases one adapter |
| **C (recommended)** | `adapter_registry.py:30` | Strip trailing `/v1` from base_url before passing to AnthropicAdapter | Low — single point of fix, adapter-agnostic |

**Recommendation**: Option C — `base_url.rstrip("/v1")` before constructing `AnthropicAdapter`. This respects both conventions: `DEFAULT_BASE_URLS` keeps its OpenAI-compat `/v1` suffix for other adapters, while `AnthropicAdapter` receives the bare domain it expects.

Actually, `rstrip("/v1")` is unsafe (strips individual chars). Better: explicit suffix removal.

```python
# adapter_registry.py, before AnthropicAdapter construction:
if base_url.endswith("/v1"):
    base_url = base_url[:-3]
```

---

## Issue #2 — `repos list` shows `dummy_repo` from pytest temp dir [GAP]

### Symptom
`python gimo.py repos list` shows a `dummy_repo` from `C:\Users\shilo\AppData\Local\Temp\pytest-of-shilo\pytest-604\test_context_request_active_an0\dummy_repo`.

### Trace

```
repo_registry.json (line 1):
  {"repos": ["C:\\Users\\shilo\\AppData\\Local\\Temp\\pytest-of-shilo\\pytest-604\\test_context_request_active_an0\\dummy_repo"]}

tests/integration/test_app_cross_surface_lifecycle.py:
  → Test `test_context_request_active_an*` registers a dummy_repo during execution

repo_router.py → reads repo_registry.json → returns all entries
```

### Root Cause

The test `test_context_request_active_an0` registers a repo path into the **production** `repo_registry.json` file (not a test-scoped copy). When the test finishes, it doesn't clean up the registry entry. The R6/R7 fix made `repos list` use only the registry (reducing from 17 scan-discovered repos to registry-only), but the registry itself was polluted by tests.

### Fix

Two options:
1. **Test cleanup**: Add teardown to the test that removes its dummy_repo from the registry.
2. **Registry validation**: `repos list` filters out paths that don't exist on disk.

**Recommendation**: Option 2 — filter non-existent paths at read time. This is defensive and handles any future test pollution. One line in `repo_router.py`.

---

## Issue #3 — Historical threads titled "New Conversation" [FRICTION]

### Symptom
9 of 20 threads show "New Conversation" as title.

### Root Cause

These threads were created before R6's title auto-generation fix. Post-R6 threads correctly use first-message-based titles. This is **not a regression** — it's historical data.

### Fix

**No code fix needed**. The title generation works for new threads. Options for cleanup:
- A one-time migration script to retitle old threads from their first message (low value, high effort)
- Leave as-is (recommended — these threads will age out naturally)

---

## Issue #4 — `status` shows `Permissions: suggest` without explanation [INCONSISTENCY]

### Symptom
`gimo status` shows `Permissions: suggest` — unclear to users what this means.

### Trace

```
gimo_cli/chat.py:77
  permissions = str(snapshot.get("permissions") or "suggest")

cli_commands.py:37
  SlashCommand("/permissions", "Change HITL mode live: suggest | auto-edit | full-auto")
```

### Root Cause

`suggest` is a valid HITL (Human-In-The-Loop) mode — one of three levels: `suggest`, `auto-edit`, `full-auto`. The value is correct but **undocumented in the status display**. Users don't know:
- What `suggest` means (agent proposes changes, user approves)
- How to change it (`/permissions` slash command)
- What the alternatives are

### Fix

Enhance `gimo status` output to show: `Permissions: suggest (agent proposes, you approve) — change with /permissions`

---

## Dynamic Model Pricing Investigation (R9 Follow-Up Task)

### Current Architecture

```
model_pricing.json (27 static entries)
       ↓
CostService.get_pricing(model_name)
  1. Direct match in PRICING_REGISTRY
  2. Substring match via MODEL_MAPPING
  3. Fallback: "local" → {input: 0.0, output: 0.0}
       ↓
ModelInventoryService.refresh_inventory()
  → Calls CostService.get_pricing() per model
  → Also calls _infer_tier() for quality_tier
  → Populates ModelEntry.cost_input/cost_output
       ↓
CascadeService.execute_with_cascade()
  → Uses ModelInventoryService for tier-based escalation
  → Uses CostService.calculate_cost() for budget tracking
```

### The Gap

When a model is NOT in `model_pricing.json` and doesn't match any `MODEL_MAPPING` entry:
- `CostService.get_pricing()` returns `{"input": 0.0, "output": 0.0}` (the "local" fallback)
- `CascadeService` tracks $0.00 cost for that model's usage
- Budget alerts never fire for unknown models
- Cost analytics show artificially low spend

**Affected models** (not in `model_pricing.json`):
- OpenAI reasoning: `o3`, `o4-mini`, `o3-mini`
- Mistral: `mistral-large`, `mistral-medium`, `mistral-small`, `codestral`
- Cohere: `command-r-plus`, `command-r`
- Any new model released after the static file was last updated

### Investigation Findings

**1. Provider Pricing APIs**: No provider (Anthropic, OpenAI, Google, Mistral, Cohere) exposes a programmatic pricing API as of 2026-04. Every competitor (Aider, Claude Code, Cline, Cursor) also hardcodes prices. This was confirmed in R9 research.

**2. Tier-Based Fallback (recommended)**:

`ModelInventoryService._infer_tier()` already assigns quality tiers 1-5 to ANY model via regex patterns. The gap is that `CostService` doesn't use this tier information when a model isn't in the static registry.

Proposed tier-based default pricing (conservative, USD per 1M tokens):

| Tier | Name | Default Input | Default Output | Rationale |
|------|------|---------------|----------------|-----------|
| 1 | nano | $0.10 | $0.10 | Cheapest models (1B params) |
| 2 | small | $0.25 | $0.50 | Mini/small models |
| 3 | balanced | $1.00 | $2.00 | Mid-range (haiku, 7B-14B) |
| 4 | premium | $3.00 | $10.00 | Large models (sonnet, 70B) |
| 5 | flagship | $10.00 | $30.00 | Top-tier (opus, o1-pro) |

This ensures:
- Unknown models get **non-zero** cost tracking
- Budget alerts work for any model
- Cost is conservative (slightly high) rather than zero
- No external dependency needed

**3. Scraper/Sync**: Not recommended. Provider pricing pages change format, no stable API. Maintenance burden outweighs benefit given tier-based fallback solves the critical gap.

### Recommendation

Add `TIER_DEFAULT_PRICING` dict to `CostService`. When `get_pricing()` falls through to the "local" fallback, instead query `ModelInventoryService._infer_tier()` for the model and return tier-based defaults. ~15 lines of code. No new dependencies.

**The connection that's missing**: `ModelInventoryService` already knows the tier. `CostService` already knows the pricing. They just don't talk to each other for unknown models.

---

## CLI/TUI Unification Status (R9 Follow-Up)

### Confirmed Working (R10 Phase 1 Verification)

| Feature | Status | Evidence |
|---------|--------|----------|
| `gimo chat` interactive = TUI | WORKS | TUI launches with real thread |
| `gimo chat -m` = single-turn CLI | WORKS (except #1 URL bug) | Correct path, JSON body |
| TUI: `X-GIMO-Surface: tui` header | WORKS | Confirmed in gimo_tui.py:498 |
| TUI: `json={"content": ...}` body | WORKS | Confirmed in gimo_tui.py:516 |
| TUI: real thread creation | WORKS | POST /ops/threads via API |
| TUI: 10/10 SSE event handlers | WORKS | All handlers present |
| Dead code removed | WORKS | 138 lines deleted in R9 |

### Assessment

Terminal unification from R9 is **solid**. The only regression is #1 (URL bug), which affects both CLI and TUI equally — it's a provider-layer issue, not a surface-layer issue. Once #1 is fixed, both surfaces will work identically.

---

## Summary

| Issue | Root Cause | Fix Complexity | Priority |
|-------|-----------|----------------|----------|
| #1 `/v1/v1` URL | Convention mismatch: OpenAI-compat URLs fed to Anthropic-native adapter | 1 line | BLOCKER |
| #2 dummy_repo | Test pollution of production registry, no path-existence validation | 2 lines | Low |
| #3 Old thread titles | Historical data, pre-R6 | None (leave as-is) | None |
| #4 Permissions: suggest | Undocumented HITL mode in status display | 1 line | Low |
| Pricing gap | No tier↔cost bridge for unknown models | ~15 lines | Medium |

**Total fix estimate**: ~20 lines of code for all actionable issues.
