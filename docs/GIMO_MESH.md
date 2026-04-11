# GIMO Mesh — Documentation

**Version**: 1.0  
**Date**: 2026-04-11  
**Status**: Production — Inference mode validated on Galaxy S10  

---

## 1. What is GIMO Mesh?

GIMO Mesh is a modular feature that extends GIMO's execution topology to any device on the local network or reachable endpoint. Old smartphones, tablets, laptops, single-board computers, and desktops become compute nodes in a unified mesh coordinated by GIMO Core.

### 1.1 Problems It Solves

1. **Device recycling** — old hardware gets a productive second life instead of a landfill
2. **Cost reduction** — run inference on local devices instead of paying cloud API costs
3. **Distributed capability** — a mesh of cheap devices covers many task types without expensive models
4. **Portable operations** — run GIMO from a phone (3W) instead of a desktop (200W)

### 1.2 Design Principles

- **Product feature**, not experiment — toggleable via `mesh_enabled` flag
- **Single orchestrator invariant** — mesh devices are workers, never competing orchestrators
- **Device health is absolute priority** — hardware protection overrides everything
- **GICS-driven routing** — learned task→model patterns, not hardcoded rules
- **Operator transparency** — all patterns visible, editable, deletable
- **Zero overhead when off** — `mesh_enabled = false` means zero CPU/memory cost

---

## 2. Device Modes

### 2.1 Inference Node

The device loads a GGUF model via llama.cpp and serves inference via OpenAI-compatible HTTP endpoint.

| Property | Value |
|----------|-------|
| Model loaded | Yes |
| Minimum RAM | ~2GB free (for 0.5B Q4) |
| Executes LLM inference | Yes |
| Example devices | Galaxy S10/S21, old laptops, Raspberry Pi 5, any PC |
| Example tasks | Classification, summarization, code review, extraction, translation |
| Validated | Yes — S10 running qwen2.5:3b at 3.9 tok/s |

**How it works:**
1. `MeshAgentService` starts `InferenceService` which launches `libllama_server.so` from `nativeLibraryDir`
2. Model file loaded from `filesDir/models/<model>.gguf`
3. HTTP server listens on `0.0.0.0:<inferencePort>` (default 8080)
4. Core sends inference requests to `http://<device_ip>:<port>/v1/completions`
5. Heartbeat reports `inference_endpoint` so Core knows where to route

### 2.2 Utility Node

The device does NOT load any model. It executes lightweight tasks assigned by GIMO Core: text validation, format checking, file operations, shell commands.

| Property | Value |
|----------|-------|
| Model loaded | No |
| Minimum RAM | ~512MB free |
| Executes LLM inference | No |
| Example devices | Galaxy S5, old tablets, any device with limited RAM |
| Example tasks | JSON validation, text transform, file hashing, ping, shell commands |
| Status | In development — task queue + executor |

**How it works:**
1. `MeshAgentService` skips `InferenceService` entirely
2. Starts a task polling loop (5s interval) against `GET /ops/mesh/tasks/poll/{device_id}`
3. `TaskExecutor` processes each task type with sandboxed execution
4. Results uploaded via `POST /ops/mesh/tasks/{task_id}/result`
5. Device reports `DeviceCapabilities` — server only assigns tasks the hardware can handle

**Supported task types (v1):**

| Task Type | Description | Min RAM |
|-----------|-------------|---------|
| `ping` | Health check / no-op | 0 |
| `text_validate` | Regex pattern matching | 64 MB |
| `text_transform` | lowercase / uppercase / trim / reverse | 64 MB |
| `json_validate` | Parse and validate JSON | 128 MB |
| `shell_exec` | Sandboxed shell command (allowlist only) | 256 MB |
| `file_read` | Read file from app sandbox | 128 MB |
| `file_hash` | SHA-256 hash of file | 256 MB |

### 2.3 Server Node

The device runs GIMO Core itself (FastAPI backend). Any client connects to it — Claude Code via MCP, browser via web UI, CLI, or direct API.

| Property | Value |
|----------|-------|
| Runs GIMO backend | Yes |
| Model loaded | Optional (can combine with inference) |
| Minimum RAM | ~512MB for server |
| Example devices | Galaxy S10+ (8GB), old laptop, Raspberry Pi 4/5, any PC |
| Use case | Run GIMO from phone (3W) instead of desktop (200W) |
| Status | Planned |

**Topology:**
```
Phone running GIMO Core (3W)
  |- Claude Code MCP --> phone:9325
  |- Browser UI --> phone:5173
  |- CLI --> phone:9325
  |- Remote APIs (Claude, Groq, OpenRouter) --> complex tasks
  |- Other mesh devices --> simple tasks via dispatch
  '- Desktop PC --> only powers on when GPU-heavy work needed
```

### 2.4 Hybrid Node

Combines Server + Inference. The device runs GIMO Core AND loads a model. Most resource-intensive mode — only for capable hardware with stable power.

| Property | Value |
|----------|-------|
| Runs GIMO backend | Yes |
| Model loaded | Yes |
| Minimum RAM | ~4GB free |
| Status | Planned (depends on Server mode) |

### 2.5 Mode Selection Logic

```
deviceMode == "inference" || deviceMode == "hybrid"  --> start llama-server
deviceMode == "utility"                               --> start task poll loop
deviceMode == "server"                                --> start GIMO Core
deviceMode == "hybrid"                                --> start both
```

Modes are NOT mutually exclusive architecturally. A device with enough resources can be Server + Inference simultaneously.

---

## 3. Device Capabilities

Each device reports its hardware profile on first heartbeat. The server uses this to filter which tasks can be safely assigned.

### 3.1 Capability Profile

| Field | Source | Purpose |
|-------|--------|---------|
| `arch` | `Build.SUPPORTED_ABIS[0]` | arm64-v8a, armeabi-v7a, x86_64 |
| `cpu_cores` | `Runtime.availableProcessors()` | Thread allocation |
| `ram_total_mb` | `/proc/meminfo` MemTotal | Task capacity gate |
| `storage_free_mb` | `StatFs(filesDir)` | File operation capacity |
| `api_level` | `Build.VERSION.SDK_INT` | API compatibility |
| `soc_model` | `Build.SOC_MODEL` / `/proc/cpuinfo` | Performance profiling |
| `has_gpu_compute` | Vulkan support check | GPU-accelerated tasks |
| `max_file_descriptors` | `/proc/sys/fs/file-max` | Concurrent I/O limit |

### 3.2 Capability Gate

The server REJECTS task assignment if ANY condition is true:

1. `device.capabilities.ram_total_mb < task.min_ram_mb`
2. `device.capabilities.api_level < task.min_api_level`
3. `task.requires_arch` specified and doesn't match device arch
4. `device.thermal_throttled == true` and task type != `ping`
5. `device.battery_percent < 20%` and device is not charging
6. `device.ram_percent > 85%` (insufficient free RAM)
7. `device.cpu_percent > 90%` (CPU saturated)

**Philosophy: always reject before risking the device.**

---

## 4. State Machine

### 4.1 Connection States

```
offline --> discoverable --> pending_approval --> approved --> connected
                                              --> refused
                          connected --> reconnecting --> connected
                          connected --> offline
                          any --> offline (kill switch)
                          any --> thermal_lockout (hardware protection)
```

### 4.2 Operational States

```
idle --> busy --> idle
idle --> paused --> idle
idle --> draining --> idle
any --> disabled
any --> error --> idle (after recovery)
any --> locked_out (hardware protection)
```

### 4.3 Authorization Matrix

Execution permitted ONLY when ALL conditions are true:

| Condition | Owner | Override Level |
|-----------|-------|----------------|
| `mesh_enabled = true` | Core global config | Global kill switch |
| `connection_state in {approved, connected}` | Core decision | Per-device |
| `core_enabled = true` | Core per-device toggle | Per-device |
| `local_allow_core_control = true` | Device local decision | Device autonomy |
| `local_allow_task_execution = true` | Device local decision | Device autonomy |
| `operational_state not in {disabled, paused, error, draining, locked_out}` | Runtime state | Dynamic |
| `hardware_safe = true` | Hardware protection | **ABSOLUTE** |

**Precedence:**
1. Hardware protection (`locked_out`) — absolute, overrides EVERYTHING
2. Global kill switch (`mesh_enabled = false`) — overrides all operational decisions
3. Local refusal (`local_allow_core_control = false`) — overrides Core enable
4. Core disable (`core_enabled = false`) — prevents dispatch

---

## 5. Hardware Protection

### 5.1 Scope

Applies to ALL systems: host PC, every mesh device, server nodes. NOT gated by `mesh_enabled` — always active.

### 5.2 Three-Phase Response

#### Phase 1 — Warning (device keeps working)

| Sensor | Threshold |
|--------|-----------|
| CPU temp | > 75 C |
| GPU temp | > 80 C |
| Battery (not charging) | < 20% |
| Battery temp | > 40 C |
| RAM available | < 15% |

Device notifies Core. GICS avoids sending more tasks.

#### Phase 2 — Throttle (rejects new work)

| Sensor | Threshold |
|--------|-----------|
| CPU temp | > 82 C |
| GPU temp | > 87 C |
| Battery (not charging) | < 10% |
| Battery temp | > 45 C |
| RAM available | < 10% |

Device rejects new tasks. Current task finishes normally.

#### Phase 3 — Lockout (immediate, non-bypassable)

| Sensor | Threshold |
|--------|-----------|
| CPU temp | > 90 C |
| GPU temp | > 93 C |
| Battery (not charging) | < 5% |
| Battery temp | > 50 C |
| RAM available | < 5% |

**Lockout sequence (atomic):**
1. Stop accepting work
2. Cancel current task (checkpoint if possible)
3. Unload model from memory
4. Send `thermal_lockout` event to Core
5. Device becomes unreachable by GIMO
6. Device user retains full access
7. Device user can manually unlock

**Automatic unlock conditions:**
- All sensors return to warning threshold or below
- Minimum cooldown elapsed (default 5 min)
- Device re-announces as `reconnecting`

### 5.3 Thermal-Predictive Routing

Before dispatching, GICS checks:
- Task estimated duration (from pattern history)
- Device thermal headroom
- Device thermal profile (from lockout history)

If estimated duration > available headroom, task routes elsewhere or splits into shorter chunks with cooldown gaps.

### 5.4 Duty Cycle Scheduling

Learned from thermal event history per device:

| Device | Work Cycle | Rest Cycle | Result |
|--------|-----------|------------|--------|
| Galaxy S10 | 6 min | 3 min | Indefinite operation |
| Desktop with fan | Continuous | None | No thermal issues |
| Old laptop | 15 min | 5 min | Sustainable |

### 5.5 Device Health Score

Composite score from long-term metrics:

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

## 6. GICS Task Pattern Intelligence

### 6.1 Design Principle

GIMO does NOT use a fixed catalog of task verbs. GICS learns which models perform best for which types of tasks through operational evidence. Each GIMO installation evolves differently based on usage patterns.

### 6.2 Task Fingerprinting

Every plan is decomposed into sub-tasks with fingerprints:

```python
class TaskFingerprint:
    action_class: str           # "create", "review", "refactor", "document", "test"
    target_type: str            # "python_file", "config", "docs", "test_suite"
    domain_hints: list[str]     # ["middleware", "auth", "database", "api"]
    estimated_complexity: str   # "trivial", "simple", "moderate", "complex"
    requires_context_kb: int    # how much context the task needs
    read_only: bool             # can it be done without writes?
```

### 6.3 Pattern Learning

GICS builds patterns from execution history:

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
  }
}
```

### 6.4 Routing Pipeline

```
1. Plan arrives at GIMO Core
2. Plan Decomposer --> sub-tasks with TaskFingerprints
3. GICS pattern match --> closest known pattern per sub-task
4. GICS recommends model (considering thermal history + device health)
5. Device selection: which device has model, capacity, safe hardware state?
6. Thermal headroom check: enough headroom for estimated duration?
7. Dispatch to target (mesh device, local, or remote API)
8. Execution + structured output validation
9. GICS records outcome PER sub-task
10. Reducer aggregates sub-task results
11. Arbiter resolves conflicts ONLY IF needed
```

### 6.5 Operator Control

Patterns are NOT a black box. Full CRUD:

| Action | Endpoint | Purpose |
|--------|----------|---------|
| View all | `GET /ops/gics/patterns` | See learned task-model mappings |
| View one | `GET /ops/gics/patterns/{id}` | Full history, thermal data |
| Edit | `PATCH /ops/gics/patterns/{id}` | Adjust constraints |
| Create | `POST /ops/gics/patterns` | Manual rule |
| Delete | `DELETE /ops/gics/patterns/{id}` | Remove bad pattern |
| Reset | `POST /ops/gics/patterns/reset` | Start fresh |

---

## 7. Architecture

### 7.1 Android App

**Package**: `com.gredinlabs.gimomesh`  
**Stack**: Kotlin + Jetpack Compose + Material 3  
**Min SDK**: 28 (Android 9)  
**Target SDK**: 35

#### Key Components

| Component | File | Purpose |
|-----------|------|---------|
| `GimoMeshApp` | `GimoMeshApp.kt` | Application class, initializes TerminalBuffer + SettingsStore |
| `MainActivity` | `MainActivity.kt` | Entry point, ADB provisioning via intent extras |
| `MeshAgentService` | `service/MeshAgentService.kt` | Foreground service — heartbeat, inference, task polling |
| `InferenceService` | `service/InferenceService.kt` | Manages llama-server native process |
| `TaskExecutor` | `service/TaskExecutor.kt` | Sandboxed utility task execution |
| `MetricsCollector` | `service/MetricsCollector.kt` | CPU/RAM/battery/thermal from /proc and /sys |
| `TerminalBuffer` | `service/TerminalBuffer.kt` | Ring buffer (5000 lines), StateFlow |
| `GimoCoreClient` | `data/api/GimoCoreClient.kt` | HTTP client for GIMO Core (OkHttp) |
| `SettingsStore` | `data/store/SettingsStore.kt` | DataStore Preferences persistence |
| `MeshViewModel` | `ui/MeshViewModel.kt` | UI state management |

#### Native Binaries (arm64-v8a)

Packaged in `app/src/main/jniLibs/arm64-v8a/` as `.so` files. Android extracts to `nativeLibraryDir` with `apk_data_file` SELinux context (allows exec).

| Binary | Size | Purpose |
|--------|------|---------|
| `libllama_server.so` | 99 MB | llama.cpp HTTP server |
| `libllama.so` | 34 MB | Core llama.cpp library |
| `libmtmd.so` | 9.9 MB | Multimodal support |
| `libggml-base.so` | 6.1 MB | GGML base tensors |
| `libggml-cpu.so` | 4.0 MB | GGML CPU backend |
| `libggml.so` | 614 KB | GGML interface |

#### UI Screens

| Screen | Purpose |
|--------|---------|
| Dashboard | Health ring, mesh status, device metrics, KillSwitch |
| Terminal | Log viewer with filters (AGENT, INFER, SYS, TASK) |
| Mesh | Device list, connection states |
| Settings | Core URL, token, device mode, model, threads, thermal thresholds |

#### Two UI Modes

| Mode | When | CPU Cost | RAM |
|------|------|----------|-----|
| **Instrument** | idle, paused, error | Normal (~2-5%) | ~40 MB |
| **Blackout** | busy (inference) | ~0% | ~15 MB |

During inference, the app enters Blackout mode — static screen showing only tok/s counter. Zero recomposition, zero animation. 100% of CPU goes to llama-server.

### 7.2 Server Backend

All mesh services live under `tools/gimo_server/services/mesh/`:

| Service | File | Purpose |
|---------|------|---------|
| `MeshRegistry` | `registry.py` | Device state machine, file-backed storage |
| `DispatchService` | `dispatch.py` | Task-to-device routing via GICS + Thompson Sampling |
| `PlanDecomposer` | `decomposer.py` | Plan steps to TaskFingerprint list |
| `PatternMatcher` | `pattern_matcher.py` | GICS pattern matching for dispatch |
| `TelemetryService` | `telemetry.py` | Thermal event ingestion |
| `TaskQueue` | `task_queue.py` | Utility task lifecycle management |

**Storage**: `.orch_data/ops/mesh/devices/<device_id>.json` (atomic writes via temp+rename)

### 7.3 Models

All Pydantic models in `tools/gimo_server/models/mesh.py`:

| Model | Purpose |
|-------|---------|
| `DeviceMode` | Enum: inference, utility, server, hybrid |
| `ConnectionState` | Enum: offline, discoverable, pending_approval, approved, refused, connected, reconnecting, thermal_lockout |
| `OperationalState` | Enum: idle, busy, paused, draining, disabled, error, locked_out |
| `DeviceCapabilities` | Hardware profile: arch, cores, RAM, storage, API level, SoC |
| `MeshDeviceInfo` | Full device state including capabilities and health |
| `HeartbeatPayload` | Device telemetry sent every 30s |
| `TaskFingerprint` | Task classification for GICS routing |
| `ThermalEvent` | Warning/throttle/lockout event |
| `MeshStatus` | Fleet overview |
| `TaskStatus` | Enum: pending, assigned, running, completed, failed, timed_out |
| `UtilityTaskType` | Enum: ping, text_validate, text_transform, json_validate, shell_exec, file_read, file_hash |
| `MeshTask` | Task definition with payload and hardware requirements |
| `TaskResult` | Device response with result data and timing |

---

## 8. API Endpoints

### 8.1 Mesh Management (`/ops/mesh/`)

All require `operator` or `admin` auth. Return 404 when `mesh_enabled = false`.

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/ops/mesh/status` | Global status + device count by mode |
| `GET` | `/ops/mesh/devices` | List all devices |
| `GET` | `/ops/mesh/devices/{id}` | Device detail + metrics |
| `POST` | `/ops/mesh/enroll` | Enroll new device |
| `POST` | `/ops/mesh/devices/{id}/approve` | Approve connection |
| `POST` | `/ops/mesh/devices/{id}/refuse` | Refuse connection |
| `DELETE` | `/ops/mesh/devices/{id}` | Remove device |
| `POST` | `/ops/mesh/heartbeat` | Receive device telemetry |
| `POST` | `/ops/mesh/thermal-event` | Record thermal event |
| `GET` | `/ops/mesh/thermal-history` | Thermal event log |
| `GET` | `/ops/mesh/eligible` | List eligible devices |
| `GET` | `/ops/mesh/profiles` | Device profiles |
| `GET` | `/ops/mesh/profiles/{id}` | Single device profile |

### 8.2 Enrollment (`/ops/mesh/enrollment/`)

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/ops/mesh/enrollment/token` | Generate enrollment token |
| `GET` | `/ops/mesh/enrollment/tokens` | List active tokens |
| `POST` | `/ops/mesh/enrollment/claim` | Device claims token |
| `DELETE` | `/ops/mesh/enrollment/token/{token}` | Revoke token |

### 8.3 Task Queue (`/ops/mesh/tasks/`)

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/ops/mesh/tasks` | Create task |
| `GET` | `/ops/mesh/tasks` | List tasks (filter by ?status=) |
| `GET` | `/ops/mesh/tasks/{id}` | Task detail |
| `GET` | `/ops/mesh/tasks/poll/{device_id}` | Poll assigned tasks (device calls this) |
| `POST` | `/ops/mesh/tasks/{id}/result` | Submit task result |
| `DELETE` | `/ops/mesh/tasks/{id}` | Cancel task |

### 8.4 Audit (`/ops/mesh/audit/`)

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/ops/mesh/audit` | Audit log |
| `GET` | `/ops/mesh/audit/receipt/{id}` | Execution receipt |

---

## 9. Communication Protocol

### 9.1 Heartbeat (Device -> Core)

Every 30 seconds via `POST /ops/mesh/heartbeat`:

```json
{
  "device_id": "s10-shilo",
  "device_secret": "<hmac_secret>",
  "device_mode": "inference",
  "operational_state": "idle",
  "cpu_percent": 23.4,
  "ram_percent": 67.1,
  "battery_percent": 78.0,
  "battery_charging": false,
  "cpu_temp_c": 42.3,
  "gpu_temp_c": -1,
  "battery_temp_c": 31.2,
  "thermal_throttled": false,
  "thermal_locked_out": false,
  "model_loaded": "qwen2.5:3b",
  "inference_endpoint": "http://192.168.0.244:8080",
  "active_task_id": "",
  "capabilities": {
    "arch": "arm64-v8a",
    "cpu_cores": 8,
    "ram_total_mb": 5734,
    "storage_free_mb": 12480,
    "api_level": 31,
    "soc_model": "exynos9820",
    "has_gpu_compute": true,
    "max_file_descriptors": 32768
  }
}
```

### 9.2 Task Poll (Device -> Core)

Every 5 seconds (utility mode only) via `GET /ops/mesh/tasks/poll/{device_id}`:

```json
[
  {
    "task_id": "t-abc123",
    "task_type": "json_validate",
    "payload": {"json_string": "{\"key\": \"value\"}"},
    "timeout_seconds": 30
  }
]
```

### 9.3 Task Result (Device -> Core)

Via `POST /ops/mesh/tasks/{task_id}/result`:

```json
{
  "task_id": "t-abc123",
  "device_id": "s10-shilo",
  "device_secret": "<hmac_secret>",
  "status": "completed",
  "result": {"valid": true, "parsed_keys": ["key"]},
  "error": "",
  "duration_ms": 12
}
```

---

## 10. Security

### 10.1 Device Authentication

- Enrollment generates HMAC secret shared between Core and device
- Every heartbeat includes `device_secret` for verification
- Enrollment tokens are time-limited and single-use

### 10.2 Task Executor Sandboxing

- **shell_exec**: Strict allowlist — `ls`, `cat`, `df`, `free`, `uname`, `date`, `echo`, `wc`, `stat`, `uptime` only. Rejects pipes, semicolons, backticks, `rm`, `su`, `chmod`.
- **file_read / file_hash**: Restricted to app's `filesDir`. Path traversal check via `canonicalPath.startsWith(filesDir.canonicalPath)`.
- **All tasks**: Hard timeout via `withTimeout(task.timeoutSeconds * 1000L)`

### 10.3 Network

- Bearer token authentication on all `/ops/mesh/*` endpoints
- `usesCleartextTraffic="true"` for LAN communication (HTTPS optional for local mesh)
- Foreground service with notification (Android requirement for persistent connections)

---

## 11. ADB Provisioning

The Android app accepts configuration via intent extras, enabling headless setup:

```bash
# Set Core server URL
adb shell am start -n com.gredinlabs.gimomesh/.MainActivity \
    --es config_core_url "http://192.168.0.49:9325"

# Set authentication token
adb shell am start -n com.gredinlabs.gimomesh/.MainActivity \
    --es config_token "your_token_here"

# Set device mode
adb shell am start -n com.gredinlabs.gimomesh/.MainActivity \
    --es config_device_mode "utility"

# Auto-start mesh on launch (BLE wake scenario)
adb shell am start -n com.gredinlabs.gimomesh/.MainActivity \
    --ez auto_start_mesh true

# Combine multiple settings
adb shell am start -n com.gredinlabs.gimomesh/.MainActivity \
    --es config_core_url "http://192.168.0.49:9325" \
    --es config_token "token" \
    --es config_device_mode "inference" \
    --ez auto_start_mesh true
```

---

## 12. Settings Reference

| Setting | Default | Description |
|---------|---------|-------------|
| `coreUrl` | `http://192.168.0.49:9325` | GIMO Core server address |
| `token` | `""` | Bearer authentication token |
| `deviceId` | `""` | Unique device identifier (auto-generated from Build.MODEL if empty) |
| `deviceName` | `""` | Human-readable device name |
| `deviceMode` | `"inference"` | Device mode: inference, utility, server, hybrid |
| `model` | `"qwen2.5:3b"` | Model to load (inference/hybrid modes) |
| `inferencePort` | `8080` | llama-server HTTP port |
| `threads` | `4` | CPU threads for inference |
| `contextSize` | `2048` | Context window size (tokens) |
| `bleWakeEnabled` | `true` | BLE proximity wake |
| `bleWakeKey` | `""` | BLE advertisement key |
| `cpuWarningTemp` | `65` | CPU warning threshold (C) |
| `cpuLockoutTemp` | `75` | CPU lockout threshold (C) |
| `batteryWarningTemp` | `38` | Battery warning threshold (C) |
| `batteryLockoutTemp` | `42` | Battery lockout threshold (C) |
| `minBatteryPercent` | `20` | Minimum battery to accept work |

---

## 13. Use Cases

### 13.1 Solo Developer — Recycle Old Phone

```
Setup: MacBook (primary) + Galaxy S10 (inference mesh node)
S10: qwen2.5:3b loaded, ~3.9 tok/s
Usage: GICS routes code reviews and text extraction to S10
       Complex coding goes to Claude/Groq via API
Savings: ~30% of API calls handled locally for free
Power: S10 uses 3W, always available
```

### 13.2 Solo Developer — Phone as Server (GIMO Cloud)

```
Setup: Galaxy S21 running GIMO Core (server mode)
Client: Claude Code on any device via MCP --> S21:9325
Usage: S21 orchestrates, inference via remote APIs
       Desktop PC stays OFF unless GPU-heavy work needed
Savings: 97% electricity reduction (3W vs 200W)
Benefit: GIMO available everywhere, not just at home
```

### 13.3 Small Team — Office Mesh

```
Setup: 1 server (desktop) + 5 old laptops + 3 old phones
Models: 7B on desktop, 3B on laptops, 0.5B on phones
Usage: GICS learns team patterns over weeks
       Documentation reviews --> phones
       Code reviews --> laptops
       Feature implementation --> desktop/API
Savings: Significant API cost reduction, old hardware repurposed
```

### 13.4 Enterprise — Cost Optimization

```
Setup: 50 decommissioned laptops in server room + GIMO Core
Models: Mix of 3B-7B models across fleet
Usage: Internal code review, documentation, testing
       Only complex/creative work goes to paid APIs
       GICS patterns optimized over months
Compliance: Full audit trail, SAGP governance on every dispatch
```

---

## 14. File Map

### 14.1 Android App (`apps/android/gimomesh/`)

```
app/
  build.gradle.kts                          -- Dependencies, jniLibs config
  src/main/
    AndroidManifest.xml                     -- Permissions, service, receivers
    jniLibs/arm64-v8a/                      -- Native binaries (llama.cpp)
    java/com/gredinlabs/gimomesh/
      GimoMeshApp.kt                       -- Application class
      MainActivity.kt                      -- Entry + ADB provisioning
      ble/
        BleWakeReceiver.kt                  -- BLE proximity wake
        BootReceiver.kt                     -- Re-register BLE after reboot
      data/
        api/GimoCoreClient.kt              -- HTTP client for Core
        model/MeshModels.kt                -- All data models + enums
        model/MeshState.kt                 -- UI state
        store/SettingsStore.kt             -- DataStore Preferences
      service/
        MeshAgentService.kt                -- Foreground service (heartbeat + inference + tasks)
        InferenceService.kt                -- llama-server process manager
        TaskExecutor.kt                    -- Utility task executor (sandboxed)
        MetricsCollector.kt                -- Hardware metrics collection
        TerminalBuffer.kt                  -- Log ring buffer
      ui/
        MeshViewModel.kt                   -- ViewModel
        dashboard/DashboardScreen.kt       -- Main dashboard
        terminal/TerminalScreen.kt         -- Log viewer
        mesh/MeshScreen.kt                 -- Device list
        settings/SettingsScreen.kt         -- Configuration
        navigation/GimoMeshNavHost.kt      -- Navigation graph
        theme/                             -- Colors, typography, surfaces
```

### 14.2 Server Backend (`tools/gimo_server/`)

```
models/
  mesh.py                                   -- All Pydantic models
services/mesh/
  __init__.py
  registry.py                              -- Device registry + state machine
  dispatch.py                              -- Task-to-device routing
  decomposer.py                            -- Plan --> sub-tasks
  pattern_matcher.py                       -- GICS pattern matching
  telemetry.py                             -- Thermal event ingestion
  task_queue.py                            -- Utility task lifecycle
routers/ops/
  mesh_router.py                           -- All /ops/mesh/* endpoints
```

### 14.3 Storage

```
.orch_data/ops/mesh/
  devices/<device_id>.json                 -- Device state (one file per device)
  tasks/<task_id>.json                     -- Task state (one file per task)
  thermal_events.jsonl                     -- Thermal event log
```

---

## 15. Implementation Status

| Component | Status | Notes |
|-----------|--------|-------|
| Server models | Done | DeviceMode, MeshDeviceInfo, HeartbeatPayload, TaskFingerprint, capabilities, task types |
| Server registry | Done | File-backed, atomic writes, state machine |
| Server dispatch | Done | GICS routing, Thompson Sampling, thermal pre-check |
| Server mesh router | Done | 20+ endpoints |
| Server task queue | In progress | Utility task lifecycle |
| Android app scaffold | Done | Kotlin + Compose, 4 screens |
| Android inference mode | Validated | S10, qwen2.5:3b, 3.9 tok/s |
| Android utility mode | In progress | Task polling + executor |
| Android server mode | Planned | Requires embedding GIMO Core |
| Android hybrid mode | Planned | Depends on server mode |
| BLE wake | Done | Proximity-based mesh activation |
| ADB provisioning | Done | Intent extras for headless setup |
| Hardware protection | Done | 3-phase (warn/throttle/lockout) |
| GICS task patterns | Done | Pattern learning, CRUD, thermal history |
| Device capabilities | In progress | Hardware profile for capability gate |
