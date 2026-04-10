# GIMO Mesh — Architecture Plan

**Status**: APPROVED — Feature module of GIMO  
**Date**: 2026-04-10  
**Owner**: shilo  
**Classification**: Product feature, modular, toggleable via `mesh_enabled` flag  
**Supersedes**: `docs/experiments/DEV_MESH_EXPERIMENT_PLAN_v2_SUPERSEDED.md`  
**Companion**: `docs/DEV_MESH_SOTA_AND_INNOVATION.md`  

---

## 0. Executive Summary

GIMO Mesh is a modular feature that extends GIMO's execution topology to any device on the local network or reachable endpoint — PCs, laptops, old smartphones, tablets, single-board computers. It solves three real problems:

1. **Device recycling** — give old hardware a productive second life instead of a landfill
2. **Cost reduction** — run inference on local devices instead of paying cloud API costs
3. **Distributed capability** — a mesh of cheap devices can cover many task types that don't need expensive models

Mesh operates in three device modes:

- **Inference Node** — loads a model, executes sub-tasks routed by GICS intelligence
- **Utility Node** — no model loaded; preprocessing, validation, relay, storage
- **Server Node** — runs GIMO Core itself; any client (Claude Code, browser, CLI) connects to it

Task routing is driven by **GICS task pattern intelligence**: learned per-installation, transparent, editable by the operator. Hardware protection is a **non-negotiable safety invariant** at every level.

When `mesh_enabled = false`, the feature is fully inert. When enabled, it extends GIMO's reach without altering its core execution model.

---

## 1. Architecture Decision Record

### 1.1 What GIMO Mesh IS

- A **product feature** of GIMO, not an experiment
- A **backend module** under `services/mesh/`
- A **lightweight device agent** at `tools/gimo_mesh_agent/`
- A **local device panel** (React+Vite) at `tools/gimo_mesh_panel/`
- A **mesh section** in the Core UI
- A **hook-based dispatch target** — not an engine, not a second orchestrator
- An **extension of GICS intelligence** — task pattern learning for model→device routing
- A **sustainability tool** — recycling old devices as compute nodes

### 1.2 What GIMO Mesh is NOT

- Not a second orchestrator (single-orchestrator invariant — SYSTEM.md §1.6)
- Not a new execution engine (uses existing RunWorker pipeline as execution target)
- Not a replacement for provider topology (providers remain canonical)
- Not a new authority (ExecutionAuthority singleton unchanged)
- Not a cluster scheduler (no distributed consensus, no leader election)
- Not a black box (all GICS patterns visible, editable, deletable by operator)

### 1.3 Canonical Invariants Respected

| Invariant | Source | How Mesh Respects It |
|-----------|--------|----------------------|
| Single orchestrator per session | SYSTEM.md §1.6 | Mesh devices are **workers** (inference/utility) or **host** (server mode), never competing orchestrators |
| Approval is security boundary | SYSTEM.md §2.4 | Task dispatch goes through existing RunWorker → Pipeline |
| SAGP evaluation mandatory | CLIENT_SURFACES.md | Device agent registers as surface, routes through SagpGateway |
| State durability canonical | SYSTEM.md §2 | Mesh state lives in `.orch_data/ops/mesh/` as first-class operational data |
| Proof chain append-only | security/execution_proof.py | Dispatch events generate proofs via SagpGateway |
| Provider catalog ownership | services/provider_catalog/ | Mesh does NOT create providers; device models register in existing inventory |
| GICS signals inform, never block | Constraint compiler philosophy | GICS task patterns are recommendations, not policy overrides |

### 1.4 Feature Flag Design

**Global flag location**: `OpsConfig.mesh_enabled: bool = False`

Follows the existing `RefactorConfig` pattern in `models/core.py:152-158`.

**Behavioral guarantee when `mesh_enabled = false`**:
- Router returns 404 on all `/ops/mesh/*` endpoints
- No background heartbeat loops start
- No device registry loads
- No dispatch hook activates
- No storage files are created
- Zero CPU/memory overhead beyond the import of the module itself

**Note**: Hardware protection (§5) is NOT gated by this flag. It is always active for the host system, regardless of Mesh state.

---

## 2. Device Modes

### 2.1 Inference Node

The device loads a model (via llama.cpp, ExecuTorch, or other runtime) and executes sub-tasks routed by GICS.

| Property | Value |
|----------|-------|
| Minimum RAM | ~2GB free (for 0.5B Q4) |
| Model loaded | Yes |
| Executes inference | Yes |
| Example devices | S10/S21, old laptops, Raspberry Pi 5, any PC |
| Example tasks | Classification, summarization, review, extraction, translation |

### 2.2 Utility Node

The device does NOT load any model. It runs lightweight Python/Node tasks.

| Property | Value |
|----------|-------|
| Minimum RAM | ~512MB free |
| Model loaded | No |
| Executes inference | No |
| Example devices | Galaxy S5, old tablets, any device with Termux/Python |
| Example tasks | JSON validation, text chunking, tokenization, file relay, result caching |

### 2.3 Server Node

The device runs GIMO Core itself (`main.py` + FastAPI). Any client connects to it.

| Property | Value |
|----------|-------|
| Minimum RAM | ~512MB for server + optional model |
| Model loaded | Optional (can also be Inference Node simultaneously) |
| Runs GIMO backend | Yes |
| Example devices | S10+ (8GB), old laptop, Raspberry Pi 4/5, any PC |
| Use case | Run GIMO from phone (3W) instead of desktop (200W) |

**Server Node topology**:
```
S10 running GIMO Core (3W)
├── Claude Code MCP → connects to S10:9325
├── Browser UI → connects to S10:5173
├── CLI → connects to S10:9325
├── Remote APIs (Claude, Groq, OpenRouter) → inference for complex tasks
├── Other mesh devices → inference for simple tasks
└── Desktop PC → only powers on when GPU-heavy local inference needed
```

**The three modes are NOT mutually exclusive.** A device with enough resources can be Server + Inference simultaneously.

---

## 3. State Machine

### 3.1 Connection States

```
offline → discoverable → pending_approval → approved → connected
                                          → refused
                       connected → reconnecting → connected
                       connected → offline
                       any → offline (kill switch)
                       any → thermal_lockout (hardware protection)
```

### 3.2 Operational States

```
idle → busy → idle
idle → paused → idle
idle → draining → idle
any → disabled
any → error → idle (after recovery)
any → locked_out (hardware protection — see §5)
```

### 3.3 Device Mode States

```
mode: inference_node | utility_node | server_node | hybrid (server + inference)
```

Mode is declared by the device during enrollment and can change at runtime.

### 3.4 Authorization Matrix

Execution is permitted **only** when ALL conditions are true:

| Condition | Owner |
|-----------|-------|
| `mesh_enabled = true` | Core global config |
| `connection_state ∈ {approved, connected}` | Core decision |
| `core_enabled = true` | Core per-device toggle |
| `local_allow_core_control = true` | Device local decision |
| `local_allow_task_execution = true` | Device local decision |
| `operational_state ∉ {disabled, paused, error, draining, locked_out}` | Runtime state |
| `hardware_safe = true` | Hardware protection (non-negotiable) |

**Precedence rules**:
1. **Hardware protection** (`locked_out`) → absolute, overrides EVERYTHING, non-bypassable
2. Global kill switch (`mesh_enabled = false`) → overrides all operational decisions
3. Local refusal (`local_allow_core_control = false`) → overrides Core enable
4. Core disable (`core_enabled = false`) → prevents dispatch regardless of local state

---

## 4. GICS Task Pattern Intelligence

### 4.1 Design Principle

GIMO does NOT use a fixed catalog of task verbs. GICS learns which models perform best for which types of tasks through operational evidence. Each GIMO installation evolves differently.

The operator can see, edit, create, and delete task patterns. This is NOT a black box.

### 4.2 Plan Decomposition

The orchestrator's plan is broken into auditable, actionable sub-tasks before execution.

```
Orchestrator plan: "Implement rate limiting middleware with sliding window"
                              ↓
                    Plan Decomposer (GIMO Core)
                              ↓
    SubTask 1: "Create rate_limiter.py with SlidingWindowCounter class"
        → capabilities: {coding: 0.9, architecture: 0.7}
        → complexity: "moderate", context: 12KB
        → GICS: needs large model → claude-sonnet / gpt-5

    SubTask 2: "Review existing middleware for integration points"
        → capabilities: {code_review: 0.5, comprehension: 0.6}
        → complexity: "simple", context: 20KB, read_only: true
        → GICS: simple review → qwen2.5:0.5b on mesh device OK
```

### 4.3 Task Fingerprinting

```python
@dataclass(frozen=True)
class TaskFingerprint:
    action_class: str           # "create", "review", "refactor", "document", "test"
    target_type: str            # "python_file", "config", "docs", "test_suite"
    domain_hints: list[str]     # ["middleware", "auth", "database", "api"]
    estimated_complexity: str   # "trivial", "simple", "moderate", "complex"
    requires_context_kb: int    # how much context the task needs
    read_only: bool             # can it be done without writes?
    embedding: list[float]      # semantic vector for similarity matching
```

### 4.4 GICS Task Pattern Store

```json
{
  "pattern_id": "P47",
  "label": "review Python code for inconsistencies",
  "centroid_fingerprint": {
    "action_class": "review",
    "target_type": "python_file",
    "complexity": "simple",
    "read_only": true
  },
  "model_history": {
    "qwen2.5:0.5b": {"executions": 87, "success_rate": 0.91, "avg_latency_s": 4.2},
    "gpt-4o-mini":  {"executions": 31, "success_rate": 0.97, "avg_latency_s": 2.8}
  },
  "thermal_history": {
    "qwen2.5:0.5b@s10_shilo": {"lockouts": 2, "warnings": 7, "avg_duration_before_warning_min": 8.4}
  },
  "recommendation": {
    "best_local": "qwen2.5:0.5b",
    "best_overall": "gpt-4o-mini",
    "best_for_device:s10_shilo": "qwen2.5:0.5b with max_duration=6min"
  }
}
```

### 4.5 Per-Installation Evolution

Each GIMO builds its own pattern library. User A (Claude + Groq) evolves differently from User B (MiniMax + DeepSeek). Both follow the same rules, same governance, same audit. But GICS patterns diverge naturally based on usage.

### 4.6 Human CRUD on Patterns

| Action | Endpoint | Purpose |
|--------|----------|---------|
| View all | `GET /ops/gics/patterns` | See learned task→model mappings |
| View one | `GET /ops/gics/patterns/{id}` | Full history, thermal data, recommendations |
| Edit | `PATCH /ops/gics/patterns/{id}` | Adjust recommendation, change constraints |
| Create | `POST /ops/gics/patterns` | Manual rule: "for SQL tasks, always prefer model X" |
| Delete | `DELETE /ops/gics/patterns/{id}` | Remove a bad or stale pattern |
| Reset | `POST /ops/gics/patterns/reset` | Start fresh (keeps raw execution history) |

### 4.7 Routing Pipeline

```
Step 1:  Plan arrives at GIMO Core
Step 2:  Plan Decomposer → sub-tasks with TaskFingerprints
Step 3:  GICS pattern match → closest known pattern per sub-task
Step 4:  GICS recommends model (considering thermal history + device health)
Step 5:  Device selection: which device has that model, capacity, safe hardware state?
Step 6:  Thermal headroom check: does the device have enough headroom for estimated duration?
Step 7:  Dispatch to target (mesh device, local, or remote API)
Step 8:  Execution + structured output validation
Step 9:  GICS records outcome PER sub-task (success, latency, cost, thermal impact)
Step 10: Reducer aggregates sub-task results
Step 11: Arbiter (expensive model) resolves conflicts ONLY IF needed
```

### 4.8 Ownership Boundary: GIMO vs GICS

| Responsibility | Owner |
|---|---|
| Store task patterns + model history | **GICS** |
| Cluster patterns by similarity | **GICS** |
| Recommend model for task pattern | **GICS** |
| Store thermal/lockout history per device | **GICS** |
| Expose pattern CRUD to human | **GIMO** |
| Decompose plan into sub-tasks | **GIMO** |
| Register device models in inventory | **GIMO** |
| Dispatch to devices | **GIMO** |
| Hardware protection enforcement | **Device agent** |

---

## 5. Hardware Protection Invariant

### 5.1 Scope

Hardware protection applies to **ALL systems**:
- The host PC/laptop running GIMO Core
- Every device in the mesh (phones, tablets, old laptops, SBCs)
- Server Node devices running GIMO itself

This is NOT gated by `mesh_enabled`. It is ALWAYS active.

### 5.2 Precedence

Hardware protection has **absolute precedence** — no entity can override it.

### 5.3 Three-Phase Response

**Phase 1 — Warning** (informational, device keeps working)

| Sensor | Threshold |
|--------|-----------|
| CPU temp | > 75°C |
| GPU temp | > 80°C |
| Battery (not charging) | < 20% |
| Battery temp | > 40°C |
| RAM available | < 15% |

Device sends `thermal_warning` to Core: *"Heating up / running low. Requesting reduced load."*
GICS factors this into routing — avoids sending more tasks.

**Phase 2 — Throttle** (automatic, rejects new work)

| Sensor | Threshold |
|--------|-----------|
| CPU temp | > 82°C |
| GPU temp | > 87°C |
| Battery (not charging) | < 10% |
| Battery temp | > 45°C |
| RAM available | < 10% |

Device rejects new tasks. Current task finishes.

**Phase 3 — Lockout** (immediate, non-bypassable)

| Sensor | Threshold |
|--------|-----------|
| CPU temp | > 90°C |
| GPU temp | > 93°C |
| Battery (not charging) | < 5% |
| Battery temp | > 50°C |
| RAM available | < 5% |

**Lockout sequence** (atomic):
1. Stop accepting any work from GIMO
2. Cancel current task (save checkpoint if possible)
3. Unload model from memory completely
4. Send `thermal_lockout` event to Core with full context
5. Device becomes unreachable by GIMO — Core cannot send commands
6. Device user CAN still access the device normally
7. Device user CAN manually unlock

**Unlock conditions** (automatic):
- All triggering sensors return to warning threshold or below
- Minimum cooldown elapsed (default 5 min)
- Device re-announces as `reconnecting`

### 5.4 Lockout Metadata (feeds GICS)

```json
{
  "device_id": "s10_shilo",
  "event_type": "thermal_lockout",
  "timestamp": "2026-04-15T14:32:00Z",
  "trigger_sensor": "cpu_temp",
  "trigger_value": 93,
  "context": {
    "duration_before_trigger_minutes": 11.4,
    "task_id": "t_00482",
    "task_fingerprint": "generate_python_heuristics",
    "model_loaded": "qwen2.5:1.5b-q4",
    "ram_usage_pct": 87,
    "battery_pct": 34,
    "battery_charging": false
  }
}
```

GICS builds **thermal profiles per device** from this history and uses them as routing constraints.

### 5.5 Host System Protection

Same protection applies to the machine running GIMO Core. On lockout, only local inference stops — GIMO continues functioning with remote providers.

### 5.6 Thermal-Predictive Routing (Innovation)

Before dispatching, GICS checks:
- Task estimated duration (from pattern history)
- Device thermal headroom (`getThermalHeadroom()` on Android, sensor readings elsewhere)
- Device thermal profile (from lockout history)

If estimated duration > available headroom with safety margin, the task routes elsewhere or splits into shorter chunks with cooldown gaps.

### 5.7 Duty Cycle Scheduling

For sustained operation, devices operate in cycles derived from their thermal profile:

```
S10: 6 min work / 3 min rest → can operate indefinitely without reaching warning
Desktop with fan: continuous → no duty cycle needed
Old laptop: 15 min work / 5 min rest → sustainable
```

Parameters are learned automatically by GICS from thermal event history.

### 5.8 Device Health Score

Composite score that degrades over time:

```
health_score = f(battery_capacity_retention, thermal_event_frequency,
                 inference_hours_total, avg_operating_temperature)
```

| Score | Routing Policy |
|-------|---------------|
| > 80% | Full workload |
| 60-80% | Reduced duty cycle |
| 40-60% | Light tasks only |
| < 40% | Retire from mesh, notify operator |

---

## 6. Hardware Detection

### 6.1 Expanded HardwareSnapshot

```python
# New fields added to existing HardwareSnapshot:
device_class: str           # "desktop" | "laptop" | "smartphone" | "tablet" | "sbc"
soc_model: str              # "Snapdragon 855" | "Exynos 2100" | ""
soc_vendor: str             # "qualcomm" | "samsung" | "apple" | "mediatek" | ""
gpu_compute_api: str        # "cuda" | "vulkan" | "metal" | "opencl" | ""
max_model_params_b: float   # RAM available / 2 (Q4 GGUF estimate)
battery_percent: float      # 0-100, -1 if N/A
battery_charging: bool
battery_temp_c: float       # -1 if N/A
thermal_throttled: bool
thermal_locked_out: bool
device_mode: str            # "inference" | "utility" | "server" | "hybrid"
```

### 6.2 Android Metrics (no root)

| Metric | Source |
|--------|--------|
| CPU % | `/proc/stat` |
| RAM | `/proc/meminfo` |
| Battery | `/sys/class/power_supply/battery/capacity` |
| Battery temp | `/sys/class/power_supply/battery/temp` |
| CPU temp | `/sys/class/thermal/thermal_zone*/temp` |
| GPU model | `getprop ro.hardware.chipname` |
| SoC | `getprop ro.board.platform` |
| Thermal headroom | `PowerManager.getThermalHeadroom()` (Android 12+) |

---

## 7. Contracts

### 7.1 Core → Device Messages

| Message | Purpose | Requires Consent |
|---------|---------|-----------------|
| `connect_request` | Initiate connection | Yes |
| `disconnect_request` | Graceful disconnect | No |
| `enable_request` | Enable task execution | Yes |
| `disable_request` | Disable task execution | No |
| `drain_request` | Finish current, no new | No |
| `shutdown_runtime_request` | Stop device agent | No |
| `probe_request` | Health check | No |
| `reconnect_request` | Re-establish connection | Yes |
| `run_task_request` | Dispatch sub-task | Yes (full auth matrix) |
| `cancel_task_request` | Cancel running task | No |
| `change_mode_request` | Switch device mode | Yes |

### 7.2 Device → Core Messages

| Message | Purpose | Frequency |
|---------|---------|-----------|
| `heartbeat` | Alive + metrics summary | Every 10s |
| `connection_state` | State change | On change |
| `approval_state` | Local consent update | On change |
| `runtime_state` | Operational state | On change |
| `hardware_metrics` | Full snapshot | Every 30s |
| `battery_metrics` | Battery details | Every 60s |
| `active_task` | Current task status | On change |
| `live_activity_event` | Structured activity | On event |
| `execution_receipt` | Task completion proof | On task end |
| `thermal_warning` | "Need rest soon" | On threshold |
| `thermal_lockout` | "Locked, model unloaded" | On lockout |
| `mode_declaration` | Current device mode | On change |

---

## 8. File Map

### 8.1 Files to CREATE

| File | Purpose |
|------|---------|
| `docs/DEV_MESH_ARCHITECTURE.md` | This document |
| `tools/gimo_server/models/mesh.py` | Pydantic models: device state, fingerprints, thermal events, modes |
| `tools/gimo_server/services/mesh/__init__.py` | Package init |
| `tools/gimo_server/services/mesh/registry.py` | Device registry + state machine |
| `tools/gimo_server/services/mesh/dispatch.py` | Sub-task dispatch via GICS routing |
| `tools/gimo_server/services/mesh/telemetry.py` | Telemetry ingestion + aggregation |
| `tools/gimo_server/services/mesh/decomposer.py` | Plan → sub-tasks with TaskFingerprints |
| `tools/gimo_server/services/mesh/enrollment.py` | Device enrollment flow |
| `tools/gimo_server/services/mesh/audit.py` | Audit log |
| `tools/gimo_server/services/mesh/health.py` | Device health score + lifecycle |
| `tools/gimo_server/routers/ops/mesh_router.py` | REST endpoints |
| `tools/gimo_server/routers/ops/gics_patterns_router.py` | CRUD for GICS task patterns |
| `tools/gimo_mesh_agent/` | Device agent package |
| `tools/gimo_mesh_panel/` | Device local panel (React+Vite) |
| `.orch_data/ops/mesh/` | Mesh operational state |

### 8.2 Files to MODIFY

| File | Change | Justification |
|------|--------|---------------|
| `tools/gimo_server/models/core.py` | Add `mesh_enabled: bool = False` to `OpsConfig` | Feature flag |
| `tools/gimo_server/main.py` | Conditional router include + lifespan hook | Standard pattern |
| `tools/gimo_server/services/hardware_monitor_service.py` | Add mobile detection, thermal protection, battery/SoC fields | Expand existing service |
| `docs/SYSTEM.md` | Add Mesh section documenting device modes + single-orchestrator compliance | Feature is now canonical |
| `docs/CLIENT_SURFACES.md` | Add mesh device as surface type | Feature is now canonical |

### 8.3 Files PROHIBITED from modification

| File | Reason |
|------|--------|
| `tools/gimo_server/engine/pipeline.py` | Core execution pipeline — Mesh uses it, doesn't modify it |
| `tools/gimo_server/services/sagp_gateway.py` | Governance authority — consumed, not modified |
| `tools/gimo_server/services/provider_catalog/` | Provider topology — not Mesh's domain |
| `tools/gimo_server/security/` | Security infrastructure — consumed, not modified |
| `vendor/gics/` | GICS is sibling repo |

---

## 9. Endpoints

### 9.1 Mesh Endpoints (`/ops/mesh/`)

All require `operator` or `admin`. Return 404 when `mesh_enabled = false`.

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/ops/mesh/status` | Global status + device count by mode |
| `POST` | `/ops/mesh/toggle` | Enable/disable mesh |
| `GET` | `/ops/mesh/devices` | List all devices |
| `GET` | `/ops/mesh/devices/{id}` | Device detail + metrics + thermal profile + health score |
| `POST` | `/ops/mesh/devices/{id}/approve` | Approve connection |
| `POST` | `/ops/mesh/devices/{id}/refuse` | Refuse connection |
| `POST` | `/ops/mesh/devices/{id}/enable` | Enable dispatch |
| `POST` | `/ops/mesh/devices/{id}/disable` | Disable dispatch |
| `POST` | `/ops/mesh/devices/{id}/drain` | Drain |
| `POST` | `/ops/mesh/devices/{id}/reconnect` | Reconnect |
| `POST` | `/ops/mesh/devices/{id}/shutdown` | Shutdown runtime |
| `POST` | `/ops/mesh/devices/{id}/mode` | Change device mode |
| `GET` | `/ops/mesh/telemetry` | Aggregated telemetry |
| `GET` | `/ops/mesh/telemetry/{id}` | Per-device telemetry + thermal history |
| `GET` | `/ops/mesh/activity/{id}` | Live activity stream |
| `POST` | `/ops/mesh/enroll` | Generate enrollment token |
| `GET` | `/ops/mesh/audit` | Audit log |
| `GET` | `/ops/mesh/tasks` | Task history |
| `GET` | `/ops/mesh/tasks/{id}` | Task detail + receipt |
| `GET` | `/ops/mesh/health` | Fleet health overview |
| `GET` | `/ops/mesh/health/{id}` | Device health score + lifecycle prediction |

### 9.2 GICS Pattern CRUD (`/ops/gics/patterns/`)

Active regardless of `mesh_enabled` — patterns inform all routing.

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/ops/gics/patterns` | List all patterns |
| `GET` | `/ops/gics/patterns/{id}` | Pattern detail |
| `PATCH` | `/ops/gics/patterns/{id}` | Edit pattern |
| `POST` | `/ops/gics/patterns` | Create manual pattern |
| `DELETE` | `/ops/gics/patterns/{id}` | Delete pattern |
| `POST` | `/ops/gics/patterns/reset` | Reset all (keeps raw history) |

---

## 10. Implementation Phases

### Phase 1 — Core Backend + Hardware Protection

| ID | Task | LOC |
|----|------|-----|
| 1A | `models/mesh.py` — all Pydantic models, enums, modes | ~300 |
| 1B | `routers/ops/mesh_router.py` — endpoints with auth | ~350 |
| 1C | `services/mesh/registry.py` — device registry + state machine + modes | ~300 |
| 1D | Storage in `.orch_data/ops/mesh/` | ~100 |
| 1E | Feature flag + conditional router registration | ~20 |
| 1F | Expand `HardwareMonitorService` — mobile, thermal protection, lockout | ~250 |

### Phase 2 — GICS Task Patterns

| ID | Task | LOC |
|----|------|-----|
| 2A | `services/mesh/decomposer.py` — plan → sub-tasks | ~250 |
| 2B | `routers/ops/gics_patterns_router.py` — CRUD | ~200 |
| 2C | GICS: record outcomes per sub-task | ~150 |
| 2D | GICS: pattern match + Thompson Sampling | ~200 |
| 2E | Pattern similarity (HDBSCAN + embeddings) | ~200 |

### Phase 3 — Device Agent

| ID | Task | LOC |
|----|------|-----|
| 3A | Agent package + CLI + Termux installer | ~150 |
| 3B | Hardware metrics (reuses expanded HardwareMonitorService) | ~100 |
| 3C | Heartbeat + API server | ~200 |
| 3D | Task execution wrapper (inference + utility modes) | ~250 |
| 3E | Receipts + logging | ~100 |
| 3F | Local control state | ~100 |
| 3G | Three-phase thermal protection | ~200 |
| 3H | Lockout: model unload, checkpoint, block | ~150 |
| 3I | Server mode: run GIMO Core on device | ~100 |

### Phase 4 — Enrollment & Connection

| ID | Task | LOC |
|----|------|-----|
| 4A | Enrollment endpoint + token | ~150 |
| 4B | Agent claim flow | ~100 |
| 4C | QR code (optional) | ~50 |
| 4D | Token expiration + anti-replay | ~80 |

### Phase 5 — Telemetry + Thermal Intelligence

| ID | Task | LOC |
|----|------|-----|
| 5A | Agent-side metrics + thermal events | ~100 |
| 5B | Event stream protocol | ~80 |
| 5C | Backend ingestion (thermal → GICS) | ~200 |
| 5D | Aggregation + endpoints | ~150 |
| 5E | Thermal profiles per device | ~100 |
| 5F | Device health score + lifecycle prediction | ~150 |
| 5G | Duty cycle scheduling from profiles | ~100 |

### Phase 6 — Device Panel (React+Vite)

| ID | Task | LOC |
|----|------|-----|
| 6A | Scaffold | ~50 |
| 6B | State management | ~150 |
| 6C | Metrics (CPU, RAM, GPU, battery, temp) | ~200 |
| 6D | Controls (connect/disconnect/refuse/pause/mode) | ~250 |
| 6E | Activity log | ~150 |
| 6F | Thermal status + lockout indicator | ~100 |
| 6G | Health score display | ~80 |

### Phase 7 — Core Mesh Panel

| ID | Task | LOC |
|----|------|-----|
| 7A | API hooks | ~100 |
| 7B | Device list + detail (with mode, thermal, health) | ~300 |
| 7C | Action controls | ~150 |
| 7D | Timeline / activity | ~200 |
| 7E | GICS pattern viewer/editor | ~200 |
| 7F | Fleet health overview | ~150 |

### Phase 8 — Intelligent Dispatch

| ID | Task | LOC |
|----|------|-----|
| 8A | Routing via GICS patterns | ~150 |
| 8B | Device selection (capacity + thermal + health) | ~150 |
| 8C | Thermal-predictive pre-check | ~100 |
| 8D | Receipts + audit integration | ~100 |
| 8E | Fallback to local/remote | ~80 |
| 8F | GICS feedback loop | ~80 |
| 8G | Quantization-aware routing (Q4 vs Q8 per thermal state) | ~80 |

### Phase 9 — Audit & Hardening

| ID | Task | LOC |
|----|------|-----|
| 9A | Structured audit log | ~150 |
| 9B | Receipt correlation | ~100 |
| 9C | Stress tests (lockout, reconnect, mode switch) | ~300 |
| 9D | Documentation updates (SYSTEM.md, CLIENT_SURFACES.md) | ~100 |

---

## 11. Use Cases

### 11.1 Solo Developer — Recycle Old Phone

```
Setup: MacBook (primary) + Galaxy S10 (mesh)
S10 runs: gimo-mesh-agent in Termux, qwen2.5:0.5b loaded
Usage: GICS routes code reviews and text extraction to S10
       Complex coding goes to Claude/Groq via API
Savings: ~30% of API calls handled locally for free
Power: S10 uses 3W, always available
```

### 11.2 Solo Developer — Phone as Server

```
Setup: Galaxy S21 running GIMO Core (Server Node)
Client: Claude Code on any device via MCP → S21:9325
Usage: S21 orchestrates, inference via remote APIs
       Desktop PC stays OFF unless GPU-heavy work needed
Savings: 97% electricity reduction (3W vs 200W)
```

### 11.3 Small Team — Office Mesh

```
Setup: 1 server (desktop) + 5 old laptops + 3 old phones
Models: 7B on desktop, 3B on laptops, 0.5B on phones
Usage: GICS learns team patterns over weeks
       Documentation reviews → phones
       Code reviews → laptops
       Feature implementation → desktop/API
Savings: Significant API cost reduction, old hardware has purpose
```

### 11.4 Enterprise — Cost Optimization

```
Setup: 50 decommissioned laptops in server room + GIMO Core
Models: Mix of 3B-7B models across fleet
Usage: Internal code review, documentation, testing tasks
       Only complex/creative work goes to paid APIs
       GICS patterns optimized over months
Savings: Major reduction in API spend
Compliance: Full audit trail, SAGP governance on every dispatch
```

---

## 12. Acceptance Criteria

### Functional

1. Global enable/disable with zero side effects when off
2. Three device modes work (inference, utility, server)
3. Bilateral consent (Core approves + device accepts)
4. Core can enable/disable/drain/reconnect/shutdown/change-mode
5. Device can pause/disconnect/refuse independently
6. Hardware protection locks out before damage, non-bypassable
7. GICS learns task patterns per installation
8. Patterns visible, editable, deletable by operator
9. Dispatch routes intelligently (simple → small model/device, complex → large model/API)
10. Thermal history feeds routing decisions
11. Device health score tracks long-term device condition
12. Server mode allows running GIMO from phone
13. All events audited with receipts

### Non-Regression

- [ ] Full GIMO test suite passes with `mesh_enabled = false`
- [ ] No duplicate state or logic in clients
- [ ] No new authority created
- [ ] Single-orchestrator invariant maintained in all modes
