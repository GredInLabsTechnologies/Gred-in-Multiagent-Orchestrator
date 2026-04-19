# DEV MESH — Experiment Plan (Frozen v2)

**Status**: FROZEN — Phase 0 complete  
**Date**: 2026-04-10  
**Revision**: v2 — incorporates GICS task patterns, hardware protection invariant, mobile support  
**Owner**: shilo  
**Classification**: Experimental module, dev-mode only, NOT part of 1.0  

---

## 0. Executive Summary

Dev Mesh is an experimental module that allows GIMO Core to dispatch sub-tasks to local network devices (PCs, laptops, smartphones) running a lightweight agent. It operates under a **bilateral consent model** (Core approves device, device accepts control) with a **global kill switch** that renders the entire subsystem inert.

Task routing is driven by **GICS task pattern intelligence**: GICS learns which models perform best for which types of tasks, and each GIMO installation evolves its own routing patterns based on its unique combination of providers, models, and devices.

Hardware protection is a **non-negotiable invariant** — devices (including the host running GIMO Core) automatically lock out before suffering thermal or resource damage. This protection cannot be overridden by Core, by the operator, or by any flag.

When `dev_mesh_enabled = false`, GIMO behaves **exactly as it does today**. Zero runtime cost, zero dispatch, zero dependency.

---

## 1. Architecture Decision Record

### 1.1 What Dev Mesh IS

- A **backend experimental module** under `services/dev_mesh/`
- A **lightweight device agent** at `tools/gimo_dev_mesh_agent/`
- A **local device panel** (React+Vite) at `tools/gimo_dev_mesh_panel/`
- An **experimental section** in the Core UI
- A **hook-based dispatch target** — not an engine, not an orchestrator
- An **extension of GICS intelligence** — task pattern learning for model→device routing

### 1.2 What Dev Mesh is NOT

- Not a second orchestrator (violates single-orchestrator invariant — SYSTEM.md §1.6)
- Not a new execution engine (uses existing RunWorker pipeline as execution target)
- Not a replacement for provider topology (providers remain canonical)
- Not a new authority (ExecutionAuthority singleton unchanged)
- Not a cluster scheduler (no distributed consensus, no leader election)
- Not a black box (all GICS patterns visible, editable, deletable by human)
- Not part of 1.0 release scope

### 1.3 Canonical Invariants Respected

| Invariant | Source | How Dev Mesh Respects It |
|-----------|--------|--------------------------|
| Single orchestrator per session | SYSTEM.md §1.6 | Dev Mesh devices are **workers**, never orchestrators |
| Approval is security boundary | SYSTEM.md §2.4 | Task dispatch goes through existing RunWorker → Pipeline |
| SAGP evaluation mandatory | CLIENT_SURFACES.md | Device agent registers as surface, routes through SagpGateway |
| State durability canonical | SYSTEM.md §2 | Dev Mesh state lives in `.orch_data/experimental/`, never touches `.orch_data/ops/` |
| Proof chain append-only | security/execution_proof.py | Dispatch events generate proofs via SagpGateway |
| Provider catalog ownership | services/provider_catalog/ | Dev Mesh does NOT create providers; it uses existing adapters |
| GICS signals inform, never block | Constraint compiler philosophy | GICS task patterns are recommendations, not policy overrides |

### 1.4 Feature Flag Design

**Global flag location**: `OpsConfig.dev_mesh_enabled: bool = False`

This follows the existing `RefactorConfig` pattern in `models/core.py:152-158`, where experimental features are gated by boolean fields in the config model.

**Behavioral guarantee when `dev_mesh_enabled = false`**:
- Router returns 404 on all `/ops/dev-mesh/*` endpoints
- No background heartbeat loops start
- No device registry loads
- No dispatch hook activates
- No storage files are created
- Zero CPU/memory overhead beyond the import of the module itself

**Note**: Hardware protection (§5) is NOT gated by this flag. It is always active for the host system, regardless of Dev Mesh state.

---

## 2. State Machine

### 2.1 Connection States

```
offline → discoverable → pending_approval → approved → connected
                                          → refused
                       connected → reconnecting → connected
                       connected → offline
                       any → offline (kill switch)
                       any → thermal_lockout (hardware protection)
```

### 2.2 Operational States

```
idle → busy → idle
idle → paused → idle
idle → draining → idle
any → disabled
any → error → idle (after recovery)
any → locked_out (hardware protection — see §5)
```

### 2.3 Authorization Matrix

Execution is permitted **only** when ALL conditions are true:

| Condition | Owner |
|-----------|-------|
| `dev_mesh_enabled = true` | Core global config |
| `connection_state ∈ {approved, connected}` | Core decision |
| `core_enabled = true` | Core per-device toggle |
| `local_allow_core_control = true` | Device local decision |
| `local_allow_task_execution = true` | Device local decision |
| `operational_state ∉ {disabled, paused, error, draining, locked_out}` | Runtime state |
| `hardware_safe = true` | Hardware protection (non-negotiable) |

**Precedence rules**:
1. **Hardware protection** (`locked_out`) → absolute, overrides EVERYTHING, non-bypassable
2. Global kill switch (`dev_mesh_enabled = false`) → overrides all operational decisions
3. Local refusal (`local_allow_core_control = false`) → overrides Core enable
4. Core disable (`core_enabled = false`) → prevents dispatch regardless of local state

---

## 3. Contracts

### 3.1 Core → Device Messages

| Message | Purpose | Requires Device Consent |
|---------|---------|------------------------|
| `connect_request` | Initiate connection | Yes (pending_approval) |
| `disconnect_request` | Graceful disconnect | No (informational) |
| `enable_request` | Enable task execution | Yes (local_allow) |
| `disable_request` | Disable task execution | No (Core authority) |
| `drain_request` | Finish current, accept no new | No |
| `shutdown_runtime_request` | Stop device agent | No (Core authority) |
| `probe_request` | Health check | No |
| `reconnect_request` | Re-establish connection | Yes (re-approval if expired) |
| `run_task_request` | Dispatch sub-task | Yes (full authorization matrix) |
| `cancel_task_request` | Cancel running task | No |

### 3.2 Device → Core Messages

| Message | Purpose | Frequency |
|---------|---------|-----------|
| `heartbeat` | Alive signal + metrics summary | Every 10s |
| `connection_state` | State change notification | On change |
| `approval_state` | Local consent update | On change |
| `runtime_state` | Operational state update | On change |
| `hardware_metrics` | Full hardware snapshot | Every 30s |
| `battery_metrics` | Battery level/charging/temp | Every 60s |
| `active_task` | Current task status | On change |
| `live_activity_event` | Structured activity stream | On event |
| `execution_receipt` | Task completion proof | On task end |
| `thermal_warning` | "I'm heating up, need rest soon" | On threshold cross |
| `thermal_lockout` | "Locked out, model unloaded, reason attached" | On lockout trigger |

### 3.3 Live Activity Protocol

No VNC. No screen share. Structured stream only:

```json
{
  "event_id": "evt_...",
  "task_id": "t_...",
  "timestamp": "2026-04-10T...",
  "event_type": "progress|log|artifact|error|metric",
  "payload": {
    "task_fingerprint": "review_python_consistency",
    "model_used": "ollama/qwen2.5:0.5b",
    "state": "running",
    "progress_pct": 45,
    "log_line": "Processing chunk 18/40...",
    "tokens_used": 1240,
    "cost_usd": 0.0,
    "hardware_state": {"cpu_temp_c": 72, "battery_pct": 68},
    "artifacts": []
  }
}
```

---

## 4. GICS Task Pattern Intelligence

### 4.1 Design Principle

GIMO does NOT use a fixed catalog of task verbs. Instead, **GICS learns which models perform best for which types of tasks** through operational evidence. Each GIMO installation evolves differently based on the models, providers, and devices its operator uses.

The operator can see, edit, create, and delete task patterns. This is NOT a black box.

### 4.2 Plan Decomposition

Today, the orchestrator sends a monolithic system prompt to a worker. The decomposer intercepts before execution and breaks it into auditable, actionable sub-tasks.

```
Orchestrator plan: "Implement rate limiting middleware with sliding window"
                              ↓
                    Plan Decomposer (GIMO Core)
                              ↓
    SubTask 1: "Create rate_limiter.py with SlidingWindowCounter class"
        → capabilities: {coding: 0.9, architecture: 0.7}
        → constraints: {context_needed_kb: 12, complexity: "moderate"}

    SubTask 2: "Write unit tests for SlidingWindowCounter"
        → capabilities: {coding: 0.7, testing: 0.8}
        → constraints: {context_needed_kb: 8, complexity: "simple"}

    SubTask 3: "Review existing middleware for integration points"
        → capabilities: {code_review: 0.5, comprehension: 0.6}
        → constraints: {context_needed_kb: 20, complexity: "simple", read_only: true}
```

SubTask 1 requires high coding capability → goes to a large model (claude-sonnet, gpt-5, qwen3-coder-32b@groq).
SubTask 3 is read-only review → GICS might route it to a 1B model on a mesh device.

### 4.3 Task Fingerprinting

Each sub-task gets a fingerprint for GICS pattern matching:

```python
@dataclass(frozen=True)
class TaskFingerprint:
    # Structural characteristics (deterministic extraction)
    action_class: str           # "create", "review", "refactor", "document", "test"
    target_type: str            # "python_file", "config", "docs", "test_suite"
    domain_hints: list[str]     # ["middleware", "auth", "database", "api"]
    estimated_complexity: str   # "trivial", "simple", "moderate", "complex"
    requires_context_kb: int    # how much context the task needs
    read_only: bool             # can it be done without writes?

    # Semantic vector for similarity matching
    embedding: list[float]      # computed by cheap embedding model or heuristic
```

### 4.4 GICS Task Pattern Store

GICS stores learned patterns linking task types to model performance:

```json
{
  "pattern_id": "P47",
  "label": "review Python code for inconsistencies",
  "centroid_fingerprint": {
    "action_class": "review",
    "target_type": "python_file",
    "domain_hints": ["code_quality"],
    "complexity": "simple",
    "read_only": true
  },
  "model_history": {
    "qwen2.5:0.5b": {"executions": 87, "success_rate": 0.91, "avg_latency_s": 4.2, "avg_cost_usd": 0.0},
    "llama3.2:3b":  {"executions": 42, "success_rate": 0.95, "avg_latency_s": 8.1, "avg_cost_usd": 0.0},
    "gpt-4o-mini":  {"executions": 31, "success_rate": 0.97, "avg_latency_s": 2.8, "avg_cost_usd": 0.003}
  },
  "thermal_history": {
    "qwen2.5:0.5b@s10_shilo": {"lockouts": 2, "warnings": 7, "avg_duration_before_warning_min": 8.4},
    "qwen2.5:0.5b@desktop":   {"lockouts": 0, "warnings": 0}
  },
  "recommendation": {
    "best_local": "qwen2.5:0.5b",
    "best_overall": "gpt-4o-mini",
    "best_for_device:s10_shilo": "qwen2.5:0.5b with max_duration=6min"
  }
}
```

Patterns are clustered by similarity (cosine distance on embeddings + structural match). New tasks find the nearest cluster and use its historical data for routing.

### 4.5 Per-Installation Evolution

Each GIMO installation builds its own pattern library:

- **User A** (pays for Claude + Groq): GICS learns that `claude-sonnet` excels at architecture tasks, `qwen3-coder-32b@groq` handles coding, and `llama3.2:1b@phone` handles reviews.
- **User B** (uses only Chinese models): GICS learns that `deepseek-r1:1.5b` handles simple coding, `minimax-01` does architecture, no mesh devices.
- **User C** (local-only, no API keys): GICS learns everything runs on Ollama, routes by model size and device thermal profile.

All three follow the same rules, same governance, same audit. But their GICS patterns diverge naturally.

### 4.6 Human CRUD on Patterns

GICS patterns are NOT a black box. The operator can:

| Action | How | Example |
|--------|-----|---------|
| **View** all patterns | `GET /ops/gics/patterns` | See learned task→model mappings |
| **View** one pattern | `GET /ops/gics/patterns/{id}` | See full history, thermal data, recommendations |
| **Edit** a pattern | `PATCH /ops/gics/patterns/{id}` | Adjust recommendation, change constraints |
| **Create** a pattern | `POST /ops/gics/patterns` | "For SQL tasks, always prefer model X" |
| **Delete** a pattern | `DELETE /ops/gics/patterns/{id}` | Remove a bad or stale pattern |
| **Reset** all patterns | `POST /ops/gics/patterns/reset` | Start fresh (keeps raw execution history) |

Data lives in GICS. CRUD surface lives in GIMO. GIMO is the window, GICS is the store.

### 4.7 Routing Pipeline

```
Step 1: Plan arrives at GIMO Core
Step 2: Plan Decomposer breaks it into sub-tasks with TaskFingerprints
Step 3: GICS pattern match → finds closest known pattern per sub-task
Step 4: GICS recommends model per sub-task (considering device thermal history)
Step 5: ModelRouter resolves: which device has that model, with capacity, and safe hardware state?
Step 6: Dispatch to target (mesh device, local Ollama, or remote API)
Step 7: Execution + structured output validation
Step 8: GICS records outcome PER sub-task (success, latency, cost, thermal impact)
Step 9: Reducer aggregates sub-task results
Step 10: Arbiter (expensive model) resolves conflicts ONLY IF needed
```

### 4.8 Ownership Boundary: GIMO vs GICS

| Responsibility | Owner | Reasoning |
|---|---|---|
| Store task patterns + model history | **GICS** | Operational intelligence is GICS's domain |
| Cluster patterns by similarity | **GICS** | Statistical analysis of performance data |
| Recommend model for task pattern | **GICS** | Core GICS function |
| Store thermal/lockout history per device | **GICS** | Part of model reliability intelligence |
| Expose pattern CRUD to human | **GIMO** | GIMO is the surface layer |
| Decompose plan into sub-tasks | **GIMO** | Orchestration logic |
| Register device models in inventory | **GIMO** | Device management is GIMO's domain |
| Dispatch to devices | **GIMO** | Execution authority stays in GIMO |
| Hardware protection enforcement | **Device agent** | Local safety, non-negotiable |

---

## 5. Hardware Protection Invariant

### 5.1 Scope

Hardware protection applies to **ALL devices in the system**:
- The host PC/laptop running GIMO Core
- Every device in the mesh (phones, tablets, old laptops)
- Any system running inference for GIMO

This is NOT gated by `dev_mesh_enabled`. It is ALWAYS active.

### 5.2 Precedence

Hardware protection has **absolute precedence** over everything:
- Over the global kill switch
- Over Core commands
- Over operator decisions
- Over any flag, config, or setting

No entity — human, Core, or agent — can override a hardware lockout. Only the device returning to safe operating conditions (or the device user manually unlocking) releases the lock.

### 5.3 Three-Phase Response

**Phase 1 — Warning** (pre-emptive, informational)

| Sensor | Warning Threshold | Action |
|--------|-------------------|--------|
| CPU temperature | > 75°C | Send `thermal_warning` to Core via metadata |
| GPU temperature | > 80°C | Send `thermal_warning` to Core via metadata |
| Battery level | < 20% (not charging) | Send `thermal_warning` to Core via metadata |
| Battery temperature | > 40°C | Send `thermal_warning` to Core via metadata |
| RAM available | < 15% of total | Send `thermal_warning` to Core via metadata |

Warning message to Core: *"Device is heating up / running low. Requesting reduced load or rest period."*

GICS receives this warning and factors it into routing: avoid sending more tasks to this device until conditions improve.

**Phase 2 — Throttle** (automatic, reduces load)

| Sensor | Throttle Threshold | Action |
|--------|-------------------|--------|
| CPU temperature | > 82°C | Reject new tasks, let current task finish |
| GPU temperature | > 87°C | Reject new tasks, let current task finish |
| Battery level | < 10% (not charging) | Reject new tasks, let current task finish |
| Battery temperature | > 45°C | Reject new tasks, let current task finish |
| RAM available | < 10% of total | Reject new tasks, let current task finish |

**Phase 3 — Lockout** (automatic, immediate, non-bypassable)

| Sensor | Lockout Threshold | Action |
|--------|-------------------|--------|
| CPU temperature | > 90°C | LOCKOUT |
| GPU temperature | > 93°C | LOCKOUT |
| Battery level | < 5% (not charging) | LOCKOUT |
| Battery temperature | > 50°C | LOCKOUT |
| RAM available | < 5% of total | LOCKOUT |

**Lockout sequence** (executes atomically, in order):
1. Immediately stop accepting any work from GIMO
2. Cancel current task (save checkpoint/backup of progress if possible)
3. Unload model from memory completely
4. Send `thermal_lockout` event to Core with full context
5. Device becomes **unreachable by GIMO** — Core cannot send commands
6. Device user CAN still access the device normally
7. Device user CAN manually unlock if they choose

**Unlock conditions** (automatic, no intervention needed):
- All sensors that triggered lockout return to **warning threshold or below**
- A minimum cooldown period has elapsed (configurable, default 5 minutes)
- Device re-announces itself to Core as `reconnecting`

### 5.4 Lockout Metadata (feeds GICS)

Every thermal event (warning, throttle, lockout) generates metadata that travels to GICS:

```json
{
  "device_id": "s10_shilo",
  "event_type": "thermal_lockout",
  "timestamp": "2026-04-15T14:32:00Z",
  "trigger_sensor": "cpu_temp",
  "trigger_value": 93,
  "trigger_threshold": 90,
  "context": {
    "continuous_execution_since": "2026-04-15T14:20:36Z",
    "duration_before_trigger_minutes": 11.4,
    "task_id": "t_00482",
    "task_fingerprint": "generate_python_heuristics",
    "model_loaded": "qwen2.5:1.5b-q4",
    "ram_usage_pct": 87,
    "battery_pct": 34,
    "battery_charging": false,
    "ambient_temp_c": null
  }
}
```

GICS stores this and builds a **thermal profile per device**:

- "s10_shilo: can sustain inference for ~8 min before warning, ~11 min before lockout"
- "desktop_main: can sustain inference indefinitely with active cooling"
- "old_laptop: can sustain 6 min with GPU, 20 min CPU-only"

This becomes a **routing constraint**: don't send tasks estimated at >8 min of inference to s10_shilo. Or split into 2x 4-min chunks with a cooldown between them.

### 5.5 Host System Protection

The same protection applies to the PC/laptop running GIMO Core itself. If the host system overheats from running local Ollama inference:

1. Warning → GIMO logs it, GICS notes it
2. Throttle → GIMO stops accepting new runs that require local inference
3. Lockout → GIMO unloads the local model, continues operating for remote-only tasks

GIMO Core itself does NOT shut down on lockout — only local inference stops. The orchestrator continues functioning with remote providers (API-based models are unaffected by local thermal state).

---

## 6. Hardware Detection (Mobile + Desktop)

### 6.1 Design Principle

Do NOT create separate collector files. **Expand `HardwareMonitorService`** to detect mobile architectures (Android, iOS) alongside existing desktop detection.

### 6.2 New Fields in HardwareSnapshot

```python
# Added to existing HardwareSnapshot dataclass:
device_class: str           # "desktop" | "laptop" | "smartphone" | "tablet"
soc_model: str              # "Snapdragon 855" | "Exynos 2100" | "Apple A15" | ""
soc_vendor: str             # "qualcomm" | "samsung" | "apple" | "mediatek" | ""
gpu_compute_api: str        # "cuda" | "vulkan" | "metal" | "opencl" | ""
max_model_params_b: float   # estimated max model size in billions (RAM / 2 for Q4 GGUF)
battery_percent: float      # 0-100, -1 if not applicable
battery_charging: bool      # true if plugged in
battery_temp_c: float       # -1 if not available
thermal_throttled: bool     # true if any sensor above warning threshold
thermal_locked_out: bool    # true if lockout active
```

### 6.3 Platform Detection

```python
def _detect_device_class() -> str:
    if os.path.exists("/system/build.prop"):      # Android
        return "smartphone"  # or "tablet" via screen/prop heuristic
    if Path("/var/mobile").exists():               # iOS (jailbreak/sideload)
        return "smartphone"
    if _has_battery() and not _is_desktop_form():
        return "laptop"
    return "desktop"
```

### 6.4 Android Metric Sources (no root required)

| Metric | Source |
|--------|--------|
| CPU % | `/proc/stat` |
| RAM | `/proc/meminfo` |
| Battery % | `/sys/class/power_supply/battery/capacity` or `termux-battery-status` |
| Battery temp | `/sys/class/power_supply/battery/temp` |
| Battery charging | `/sys/class/power_supply/battery/status` |
| CPU temperature | `/sys/class/thermal/thermal_zone*/temp` |
| GPU model | `getprop ro.hardware.chipname` |
| GPU usage | `/sys/class/kgsl/kgsl-3d0/gpubusy` (Adreno) |
| SoC | `getprop ro.board.platform` |

### 6.5 max_model_params_b Calculation

This field tells GICS the maximum model size the device can load:

```
Available RAM (GB) / 2 = max_model_params_b (Q4 GGUF rule of thumb)

S10 (8GB RAM, ~4GB free)     → max_model_params_b ≈ 2.0
S21 (8GB RAM, ~5GB free)     → max_model_params_b ≈ 2.5
PC (32GB RAM, 24GB free)     → max_model_params_b ≈ 12.0
MacBook M2 (16GB unified)    → max_model_params_b ≈ 8.0
Old laptop (4GB RAM, 2GB free) → max_model_params_b ≈ 1.0
```

GICS uses this as a hard filter: never recommend a model larger than `max_model_params_b` for this device.

---

## 7. File Map

### 7.1 Files to CREATE (safe, no conflicts)

| File | Purpose |
|------|---------|
| `docs/experiments/DEV_MESH_EXPERIMENT_PLAN.md` | This document |
| `tools/gimo_server/models/dev_mesh.py` | Pydantic models: device state, fingerprints, thermal events |
| `tools/gimo_server/services/dev_mesh/__init__.py` | Package init |
| `tools/gimo_server/services/dev_mesh/registry.py` | Device registry + state machine |
| `tools/gimo_server/services/dev_mesh/dispatch.py` | Sub-task dispatch via GICS routing |
| `tools/gimo_server/services/dev_mesh/telemetry.py` | Telemetry ingestion + aggregation |
| `tools/gimo_server/services/dev_mesh/decomposer.py` | Plan → sub-tasks with TaskFingerprints |
| `tools/gimo_server/services/dev_mesh/enrollment.py` | Device enrollment flow |
| `tools/gimo_server/services/dev_mesh/audit.py` | Audit log for Dev Mesh events |
| `tools/gimo_server/routers/ops/dev_mesh_router.py` | REST endpoints for Dev Mesh |
| `tools/gimo_server/routers/ops/gics_patterns_router.py` | CRUD endpoints for GICS task patterns |
| `tools/gimo_dev_mesh_agent/` | Device agent (separate package) |
| `tools/gimo_dev_mesh_panel/` | Device local panel (React+Vite) |
| `.orch_data/experimental/dev_mesh/` | Runtime state storage |

### 7.2 Files to MODIFY (minimal, justified)

| File | Change | Justification |
|------|--------|---------------|
| `tools/gimo_server/models/core.py` | Add `dev_mesh_enabled: bool = False` to `OpsConfig` | Feature flag — follows existing `RefactorConfig` pattern |
| `tools/gimo_server/main.py` | Add conditional router include for dev_mesh_router | Follows existing late-loaded router pattern (lines 796-802) |
| `tools/gimo_server/main.py` | Add conditional lifespan hook for dev_mesh service | Follows existing lifespan pattern |
| `tools/gimo_server/services/hardware_monitor_service.py` | Add `device_class`, `soc_model`, `max_model_params_b`, battery/thermal fields to `HardwareSnapshot`; add platform detection; add thermal protection thresholds and lockout logic | Expand existing service, do NOT create new files |

### 7.3 Files PROHIBITED from modification

| File | Reason |
|------|--------|
| `docs/SYSTEM.md` | Canonical architecture — Dev Mesh is experimental |
| `docs/CLIENT_SURFACES.md` | Surface contracts — Dev Mesh is not a canonical surface yet |
| `tools/gimo_server/services/ops/` | OPS canonical state — read-only from experiments |
| `tools/gimo_server/engine/pipeline.py` | Core execution pipeline — Dev Mesh uses it, doesn't modify it |
| `tools/gimo_server/services/sagp_gateway.py` | Governance authority — consumed, not modified |
| `tools/gimo_server/services/provider_catalog/` | Provider topology — not Dev Mesh's domain |
| `tools/gimo_server/security/` | Security infrastructure — consumed, not modified |
| `vendor/gics/` | GICS is sibling repo, not ours to modify |
| `.orch_data/ops/` | Canonical operational state — Dev Mesh writes to `.orch_data/experimental/` |

---

## 8. Endpoints

### 8.1 Dev Mesh Endpoints

All under `/ops/dev-mesh/`. All require `operator` or `admin` role. All return 404 when `dev_mesh_enabled = false`.

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/ops/dev-mesh/status` | Global status + device count |
| `POST` | `/ops/dev-mesh/toggle` | Enable/disable global flag |
| `GET` | `/ops/dev-mesh/devices` | List registered devices |
| `GET` | `/ops/dev-mesh/devices/{id}` | Device detail + metrics + thermal profile |
| `POST` | `/ops/dev-mesh/devices/{id}/approve` | Approve device connection |
| `POST` | `/ops/dev-mesh/devices/{id}/refuse` | Refuse device connection |
| `POST` | `/ops/dev-mesh/devices/{id}/enable` | Enable task dispatch to device |
| `POST` | `/ops/dev-mesh/devices/{id}/disable` | Disable task dispatch |
| `POST` | `/ops/dev-mesh/devices/{id}/drain` | Drain (finish current, no new) |
| `POST` | `/ops/dev-mesh/devices/{id}/reconnect` | Request reconnection |
| `POST` | `/ops/dev-mesh/devices/{id}/shutdown` | Shutdown device runtime |
| `GET` | `/ops/dev-mesh/telemetry` | Aggregated telemetry |
| `GET` | `/ops/dev-mesh/telemetry/{id}` | Per-device telemetry + thermal history |
| `GET` | `/ops/dev-mesh/activity/{id}` | Live activity stream |
| `POST` | `/ops/dev-mesh/enroll` | Generate enrollment token |
| `GET` | `/ops/dev-mesh/audit` | Audit log |
| `GET` | `/ops/dev-mesh/tasks` | Task history |
| `GET` | `/ops/dev-mesh/tasks/{id}` | Task detail + receipt |

### 8.2 GICS Pattern CRUD Endpoints

All under `/ops/gics/patterns/`. Require `operator` or `admin` role. Active regardless of `dev_mesh_enabled` (patterns inform all routing, not just mesh).

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/ops/gics/patterns` | List all learned task patterns |
| `GET` | `/ops/gics/patterns/{id}` | Pattern detail: history, thermal data, recommendations |
| `PATCH` | `/ops/gics/patterns/{id}` | Edit pattern (adjust recommendations, constraints) |
| `POST` | `/ops/gics/patterns` | Create manual pattern ("for SQL tasks, prefer model X") |
| `DELETE` | `/ops/gics/patterns/{id}` | Delete a pattern |
| `POST` | `/ops/gics/patterns/reset` | Reset all patterns (keeps raw execution history) |

---

## 9. Reusable Components (Existing Code)

### 9.1 Direct Reuse

| Component | Location | How Dev Mesh Uses It |
|-----------|----------|---------------------|
| `HardwareMonitorService` | `services/hardware_monitor_service.py` | **Expanded** with mobile detection + thermal protection |
| `verify_token` / `_require_role` | `routers/ops/common.py` | Auth on all endpoints |
| `OpsService.get_config()` | `services/ops/ops_service.py` | Read `dev_mesh_enabled` flag |
| `SagpGateway.evaluate_action()` | `services/sagp_gateway.py` | Governance check before dispatch |
| `GicsService.record_model_outcome()` | `services/gics_service.py` | Record task outcomes + thermal events |
| `CostService.estimate()` | `services/cost_service.py` | Cost estimation per sub-task |
| `ModelInventoryService` | `services/providers/model_inventory_service.py` | Register mesh device models in existing inventory |
| `ModelRouterService` | `services/providers/model_router_service.py` | Route sub-tasks using GICS intelligence |
| File-locked JSON persistence | `services/ops/_lock.py` | Storage pattern for experimental state |

### 9.2 Pattern Reuse (same pattern, not direct import)

| Pattern | Source | Dev Mesh Equivalent |
|---------|--------|---------------------|
| `RefactorConfig` feature flags | `models/core.py:152-158` | `dev_mesh_enabled` in `OpsConfig` |
| Late-loaded router include | `main.py:796-802` | Conditional include of `dev_mesh_router` |
| `RunWorker` poll loop | `services/execution/run_worker.py` | Heartbeat monitor loop |
| `SupervisedTask` | `main.py` lifespan | Device connection supervision |
| Structured event stream | `services/ops/_telemetry.py` | Live activity events |
| `CapabilityProfileService` dimensions | `services/capability_profile_service.py` | TaskFingerprint capability requirements |

### 9.3 Dangerous to Reuse (historical debt)

| Component | Risk | Recommendation |
|-----------|------|----------------|
| Legacy `routes.py` | 475 LOC monolith, 308 redirects | Do NOT integrate; use only `/ops/` pattern |
| `gimo_ops.db` (SQLite) | Legacy, optional, not canonical | Use JSON file storage like canonical OPS |
| Old provider auth patterns | Pre-SAGP, inconsistent | Use only current `SagpGateway` |

---

## 10. Implementation Phases

### Phase 0 — Freeze (THIS DOCUMENT) ✅

Gate: This document exists, reviewed, frozen.

### Phase 1 — Core Backend Skeleton + Hardware Protection

| ID | Task | Depends On | Est. LOC |
|----|------|-----------|----------|
| 1A | `models/dev_mesh.py` — Pydantic models, device state, thermal events, fingerprints | — | ~250 |
| 1B | `routers/ops/dev_mesh_router.py` — endpoints with auth | 1A | ~300 |
| 1C | `services/dev_mesh/registry.py` — device registry + state machine | 1A | ~250 |
| 1D | `services/dev_mesh/` storage in `.orch_data/experimental/` | 1A | ~100 |
| 1E | Feature flag in `OpsConfig` + conditional router registration | 1B | ~20 |
| 1F | Expand `HardwareMonitorService` — mobile detection, thermal thresholds, lockout logic | — | ~200 |

**Gate tests:**
- [ ] All endpoints return 404 when `dev_mesh_enabled = false`
- [ ] State transitions follow state machine exactly
- [ ] Auth requires `operator` or `admin` role
- [ ] Storage writes only to `.orch_data/experimental/`
- [ ] Thermal lockout triggers at threshold on host system
- [ ] Lockout cannot be overridden by any API call
- [ ] Lockout releases only when sensors return to safe zone

### Phase 2 — GICS Task Pattern Infrastructure

| ID | Task | Depends On | Est. LOC |
|----|------|-----------|----------|
| 2A | `services/dev_mesh/decomposer.py` — plan → sub-tasks with TaskFingerprints | — | ~250 |
| 2B | `routers/ops/gics_patterns_router.py` — CRUD endpoints for patterns | — | ~200 |
| 2C | GICS integration: record outcomes per sub-task (via `GicsService`) | 2A | ~150 |
| 2D | GICS integration: query patterns for routing recommendations | 2C | ~150 |
| 2E | Pattern similarity matching (embedding or structural) | 2A | ~200 |

**Gate tests:**
- [ ] Plan decomposes into sub-tasks with fingerprints
- [ ] GICS stores per-sub-task outcomes
- [ ] Pattern CRUD works (create, read, update, delete)
- [ ] Similar tasks match to same pattern
- [ ] Patterns visible and editable by human

### Phase 3 — Device Agent

| ID | Task | Depends On | Est. LOC |
|----|------|-----------|----------|
| 3A | Agent package structure + CLI launcher | — | ~100 |
| 3B | Hardware metrics (reuses expanded HardwareMonitorService) | 1F | ~100 |
| 3C | Heartbeat + API server | 3A | ~200 |
| 3D | Task execution wrapper | 3A | ~200 |
| 3E | Receipt generation + logging | 3D | ~100 |
| 3F | Local control state (allow/deny/pause) | 3A | ~100 |
| 3G | Hardware protection — thermal warning/throttle/lockout sequence | 3B | ~200 |
| 3H | Lockout: model unload, checkpoint save, GIMO block, user-only unlock | 3G | ~150 |

**Gate tests:**
- [ ] Agent starts and stops cleanly
- [ ] Heartbeat sends every 10s
- [ ] Agent works standalone without GIMO running
- [ ] Local refusal prevents task execution
- [ ] Thermal warning sends metadata to Core
- [ ] Thermal lockout: model unloaded, GIMO blocked, user can still access device
- [ ] Lockout auto-releases when conditions return to safe zone
- [ ] Lockout cannot be bypassed by Core, operator, or any command

### Phase 4 — Enrollment & Connection

| ID | Task | Depends On | Est. LOC |
|----|------|-----------|----------|
| 4A | Backend enrollment endpoint + token generation | 1B | ~150 |
| 4B | Agent claim flow | 3A, 4A | ~100 |
| 4C | QR code generation (optional) | 4A | ~50 |
| 4D | Token expiration + anti-replay | 4A | ~80 |

**Gate tests:**
- [ ] Token is single-use
- [ ] Token expires after configurable TTL
- [ ] Revoked token cannot be reused
- [ ] Reconnect uses different token path

### Phase 5 — Telemetry, Live Activity & Thermal History

| ID | Task | Depends On | Est. LOC |
|----|------|-----------|----------|
| 5A | Agent-side metrics + thermal event emission | 3B, 3G | ~100 |
| 5B | Event stream protocol (includes thermal metadata) | — | ~80 |
| 5C | Backend telemetry ingestion (includes thermal events → GICS) | 1C, 5B | ~200 |
| 5D | Backend telemetry aggregation + endpoints | 5C | ~150 |
| 5E | Thermal profile per device (built from lockout history) | 5C, 2C | ~100 |

**Gate tests:**
- [ ] Core sees real-time device metrics
- [ ] Thermal warnings visible in Core panel
- [ ] Lockout events recorded in GICS with full context
- [ ] Thermal profile builds over time from real events
- [ ] GICS uses thermal history for routing (avoids overworking devices)

### Phase 6 — Device Local Panel (React+Vite)

| ID | Task | Depends On | Est. LOC |
|----|------|-----------|----------|
| 6A | Vite project scaffold | — | ~50 |
| 6B | State management (zustand or context) | 6A | ~150 |
| 6C | Metrics display panels (CPU, RAM, GPU, battery, temperature) | 6B, 3B | ~200 |
| 6D | Action controls (connect/disconnect/refuse/pause) | 6B | ~200 |
| 6E | Activity log viewer | 6B | ~150 |
| 6F | Thermal status + lockout indicator | 6B, 3G | ~100 |

**Gate tests (Vitest):**
- [ ] Toggles persist state correctly
- [ ] Refusal state is durable across refresh
- [ ] Panel works without Core connection (shows offline state)
- [ ] Lockout state clearly visible with reason and estimated unlock time

### Phase 7 — Core Experimental Panel

| ID | Task | Depends On | Est. LOC |
|----|------|-----------|----------|
| 7A | API consumption hooks | 1B | ~100 |
| 7B | Device list + detail views (with thermal profile) | 7A | ~250 |
| 7C | Action controls | 7A | ~150 |
| 7D | Timeline / live activity view | 7A, 5D | ~200 |
| 7E | GICS pattern viewer/editor | 2B | ~200 |

**Gate tests:**
- [ ] Panel hidden when `dev_mesh_enabled = false`
- [ ] All data from API, zero local computation of state
- [ ] States consistent with backend
- [ ] Thermal history visible per device
- [ ] GICS patterns editable from panel

### Phase 8 — Intelligent Dispatch

| ID | Task | Depends On | Est. LOC |
|----|------|-----------|----------|
| 8A | Sub-task routing via GICS pattern match | 2D | ~150 |
| 8B | Device selection (capacity + thermal + GICS recommendation) | 8A, 1C | ~150 |
| 8C | Receipt integration with audit | 3E, 9A | ~100 |
| 8D | Fallback to local/remote execution | 8B | ~80 |
| 8E | GICS feedback loop (record outcome per sub-task) | 8A, 2C | ~80 |

**Gate tests:**
- [ ] Flag off → never dispatches
- [ ] Refused device → never receives tasks
- [ ] Locked-out device → never receives tasks
- [ ] GICS routes simple tasks to small models, complex tasks to large models
- [ ] Thermal history influences routing (avoids overworked devices)
- [ ] Fallback works when no mesh device qualifies
- [ ] Each execution updates GICS pattern with outcome

### Phase 9 — Audit & Hardening

| ID | Task | Depends On | Est. LOC |
|----|------|-----------|----------|
| 9A | `audit.py` — structured audit log | 1C | ~150 |
| 9B | Receipt correlation by IDs | 3E, 9A | ~100 |
| 9C | Precedence rules documentation | — | ~50 |
| 9D | Failure/reconnect/lockout stress tests | All | ~300 |

**Gate tests:**
- [ ] Every significant event logged (dispatch, execution, thermal, lockout)
- [ ] Local refusal documented in audit
- [ ] Kill switch documented in audit
- [ ] Thermal lockout documented with full context
- [ ] Reconnect after lockout recovery works
- [ ] GICS pattern evolution is traceable

### Phase 10 — Cleanup & Promotion Decision

- [ ] Remove provisional utilities
- [ ] Final experiment documentation
- [ ] GICS pattern data format documented for long-term stability
- [ ] Decision memo: KILL / KEEP EXPERIMENTAL / PROMOTE

---

## 11. Workstream Parallelism

```
Time →

WS-A (Docs/Contracts):       [P0]────[P1E]──────────────────────────[P9C]──[P10]
WS-B (Backend+HW):           ·····[P1A─P1B─P1C─P1D─P1F]──[P5C─P5D─P5E]──[P9A]
WS-C (GICS Patterns):        ·····[P2A─P2B─P2C─P2D─P2E]──[P8A─P8E]
WS-D (Device Agent):         ·····[P3A─P3B─P3C─P3D─P3E─P3F─P3G─P3H]──[P5A]
WS-E (Enrollment):           ··········────────[P4A─P4B─P4C─P4D]
WS-F (Device Panel):         ··········────────────────[P6A─P6B─P6C─P6D─P6E─P6F]
WS-G (Core Panel):           ··········────────────────[P7A─P7B─P7C─P7D─P7E]
WS-H (Dispatch):             ·····────────────────────────────[P8A─P8B─P8C─P8D─P8E]
WS-I (Audit):                ··········────────────────────────────[P9A─P9B─P9D]
```

WS-B, WS-C, WS-D can start in parallel after Phase 0 freeze.
WS-E, WS-F, WS-G can start once Phase 1 models exist.
WS-H depends on WS-C (GICS patterns) + WS-B (registry).
WS-I runs last as integration verification.

---

## 12. Risks & Controls

| # | Risk | Probability | Impact | Control |
|---|------|-------------|--------|---------|
| R1 | Module contaminates Core | Medium | Critical | Feature flag, separate storage, separate routes, prohibited file list |
| R2 | Becomes second execution engine | Medium | Critical | Dispatch hook only, no Pipeline modification, GICS-routed tasks only |
| R3 | Device loses autonomy | Low | High | Local refusal has precedence, bilateral consent, hardware lockout non-bypassable |
| R4 | GICS patterns become black box | Medium | High | Full CRUD exposed to operator, all patterns viewable/editable/deletable |
| R5 | Telemetry too shallow | Medium | Medium | Structured activity stream + receipts + thermal events mandatory |
| R6 | Experiment becomes permanent debt | High | Medium | Phase 10 decision memo required, cleanup checklist |
| R7 | Network unreliability | High | Low | Heartbeat timeout, reconnect flow, buffered events |
| R8 | Device hardware damage | Low | Critical | Three-phase protection (warn→throttle→lockout), non-bypassable, model unload on lockout |
| R9 | GICS pattern drift misleads routing | Medium | Medium | Patterns auditable, human can override, reset available |

---

## 13. Acceptance Criteria

### Functional

1. Global enable/disable works with zero side effects when off
2. Device can be approved/refused from Core
3. Device can accept/refuse control locally
4. Core can enable/disable/drain/reconnect/shutdown devices
5. Device can pause/disconnect/refuse independently
6. Local panel shows hardware metrics + activity + thermal state
7. Core panel shows same telemetry + GICS patterns
8. Dispatch routes via GICS pattern intelligence (simple → small model, complex → large model)
9. GICS learns from every execution and builds per-installation patterns
10. Operator can view, edit, create, delete GICS patterns
11. Hardware protection locks out device before damage, non-bypassable
12. Thermal/lockout history feeds GICS for routing optimization
13. Host system has same thermal protection as mesh devices
14. All events audited with receipts

### Non-Regression

- [ ] Full GIMO test suite passes with `dev_mesh_enabled = false`
- [ ] No new imports in canonical modules (except conditional router registration + HardwareMonitorService expansion)
- [ ] No duplicate state or logic in clients
- [ ] No new authority created
- [ ] `.orch_data/ops/` untouched by Dev Mesh
- [ ] Host system thermal protection does not interfere with remote-only operation

---

## 14. Agent Evaluation Protocol

Any agent evaluating this plan MUST:

1. **Read first**: `docs/SYSTEM.md`, `docs/CLIENT_SURFACES.md`, `main.py` entry points
2. **Verify** real routes exist before proposing files
3. **Identify** reusable canonical components (see §9)
4. **Mark** dangerous debt (see §9.3)
5. **NOT implement** anything until this plan is frozen and accepted
6. **Propose** changes by phase with bounded impact
7. **Prove** before declaring DONE:
   - Flag off = zero impact
   - Toggle per device works
   - Local refusal works
   - Thermal lockout works and cannot be bypassed
   - GICS patterns visible and editable
   - Telemetry visible
   - No regression in existing tests

### Required Agent Output

- Architecture evaluation (pass/fail per invariant)
- File diff map (create/modify/prohibited)
- Risk assessment
- Implementation sequence
- Tests per phase
- Rejections (parts of plan the agent disagrees with, with reasoning)
