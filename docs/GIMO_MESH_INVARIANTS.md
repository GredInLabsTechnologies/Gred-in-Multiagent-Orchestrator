# GIMO Mesh — System Invariants

> Rules that **never break**, regardless of feature additions.
> Any new feature must comply. If an invariant needs changing, it requires explicit justification.

---

## I. Device Health (absolute priority)

```
INV-H1  Thermal lockout is non-bypassable.
        If cpu_temp > lockout_threshold OR battery_temp > lockout_threshold:
          -> connection_state = thermal_lockout
          -> operational_state = locked_out
          -> model_loaded = ""
          -> active_task_id = ""
          -> ALL in-flight tasks are aborted
        No override, flag, or workspace can bypass this.

INV-H2  Battery floor is non-bypassable.
        If battery_percent < min_battery_percent AND NOT charging:
          -> mesh stops
        No exception for workspace, mode, or task urgency.

INV-H3  Capability gate before assignment.
        A task is NEVER assigned to a device that fails any of 7 checks:
          1. RAM total >= task.min_ram_mb
          2. API level >= task.min_api_level
          3. Arch compatible (if task requires specific arch)
          4. Not thermal throttled
          5. Battery > min_battery
          6. RAM usage < 85%
          7. CPU load < 90%
        ALWAYS reject before risking the device.

INV-H4  Task timeout is non-negotiable.
        Every task has timeout_seconds (default 60, max 300).
        If exceeded -> status = timed_out, process killed.
        No task runs without a time limit.
```

## II. Security & Authentication

```
INV-S1  No secret, no heartbeat.
        Every heartbeat MUST include device_secret.
        If device_secret mismatch -> 403, heartbeat rejected.
        No anonymous heartbeats.

INV-S2  No invitation, no workspace.
        A device can only join a workspace via:
          a) Valid pairing code (not expired, not exhausted)
          b) Being the workspace creator
        No auto-discovery, no join without validation.

INV-S3  Pairing codes are ephemeral.
        Max TTL: 5 minutes. No exceptions.
        Used code = dead code (single-use by default).
        Expired codes are purged on every request.

INV-S4  device_id is globally unique.
        Two distinct physical devices cannot share a device_id.
        device_id is generated at first boot and persisted.
        On collision -> second device is rejected.

INV-S5  Task execution is sandboxed.
        Shell commands: allowlist only (ls, cat, df, free, uname, date, echo, wc, stat, uptime).
        Path traversal: every path validated with canonicalPath.
        Pipes, semicolons, backticks, rm, su, chmod -> DENIED.
```

## III. Workspaces (isolation)

```
INV-W1  Total isolation between workspaces.
        Tasks from workspace A are NEVER visible to devices in workspace B.
        Heartbeats report active workspace_id.
        Task queue filters by workspace_id in ALL queries.

INV-W2  A device operates in exactly 1 workspace at a time.
        It can belong to N workspaces, but only 1 is active.
        Switching active workspace:
          -> cancels in-flight tasks from previous workspace
          -> re-heartbeats with new workspace_id

INV-W3  device_mode is per-workspace.
        A device can be inference in "Home" and utility in "Office".
        Switching workspace loads that workspace's mode.
        No global mode exists -- there is always a workspace context.

INV-W4  Workspace "default" always exists.
        Created at first server boot.
        Devices without explicit workspace operate in "default".
        Backwards compatibility: pre-workspace devices auto-migrate to "default".

INV-W5  Owner cannot remove themselves.
        Every workspace has at least 1 owner.
        The last owner cannot leave or be removed.
        Ownership can be transferred, not destroyed.
```

## IV. Mode & Capabilities

```
INV-M1  mode_locked is absolute.
        If user activates the lock -> Core CANNOT change the mode.
        Not via API, CLI, MCP, or task assignment.
        User intent prevails over any automation.

INV-M2  Core can change mode by default.
        If mode_locked = false, Core has full freedom to change
        the device mode at any time.
        This is opt-out (locked), not opt-in.

INV-M3  Mode change with active task requires confirmation.
        If operational_state = busy:
          -> mode change from app: confirmation dialog
          -> mode change from Core: task completes or aborts first
        No silent mode change while a task is executing.

INV-M4  Hardware determines capabilities, modes are presets.
        Active capabilities of a device are determined by:
          1. Hardware (absolute ceiling -- non-negotiable)
          2. User restrictions (voluntary -- "no inference here")
          3. Current load (dynamic throttle -- "not right now")
        In that order. Hardware is never exceeded.
        User can always restrict further.
        System adapts in real time.

        Presets:
          inference = inference ON,  utility OFF, serve OFF
          utility   = inference OFF, utility ON,  serve OFF
          server    = inference OFF, utility OFF, serve ON
          hybrid    = configurable (default: inference + utility)
                      Core can adjust composition dynamically
                      unless mode_locked = true.
                      User configures hybrid composition in Settings.
```

## V. Heartbeat & Liveness

```
INV-L1  Device without heartbeat for 90s -> stale.
        connection_state = reconnecting.
        Tasks assigned to that device -> reassigned.
        No more tasks until it heartbeats again.

INV-L2  Device without heartbeat for 5min -> offline.
        connection_state = offline.
        Released from all tasks.
        Not removed from workspace (can return).

INV-L3  Heartbeat interval is 30s +/- jitter.
        No heartbeat more frequent than 10s (bandwidth protection).
        No heartbeat less frequent than 60s (timely failure detection).

INV-L4  Heartbeat is idempotent.
        Processing the same heartbeat twice does not change state.
        No cumulative side effects.
```

## VI. Task Lifecycle

```
INV-T1  Lifecycle is unidirectional.
        pending -> assigned -> running -> completed|failed|timed_out
        No rollback. A completed task cannot return to running.
        A failed task is not auto-reassigned (new task, new ID).

INV-T2  A task belongs to exactly 1 workspace.
        workspace_id is immutable after creation.
        No "global" or "cross-workspace" tasks.

INV-T3  An assigned task belongs to exactly 1 device.
        No parallel execution of the same task on multiple devices.
        If device dies, task expires via INV-L1 and can be recreated.

INV-T4  Poll is the only assignment mechanism.
        Server does NOT push tasks to devices.
        Device always polls -> server does lazy expiry + auto-assign.
        This guarantees the device only receives work when ready.

INV-T5  Results are immutable.
        Once a task has status completed/failed/timed_out,
        its result cannot be overwritten.
        Second submit of same task_id -> 409 Conflict.
```

## VII. Persistence

```
INV-P1  Atomic writes everywhere.
        Every disk write uses tempfile + rename.
        No partially written state. A mid-write crash
        leaves the previous state intact, not corrupt.

INV-P2  FileLock for concurrency.
        Every read-modify-write operation uses a lock.
        No race conditions in registry or task queue.

INV-P3  Mesh state survives server restarts.
        Devices, workspaces, memberships -> persisted to disk.
        In-flight tasks at restart -> expire by timeout.
        No memory-only state that is critical.
```

## VIII. Observability

```
INV-O1  Every state change is logged to terminal.
        Mode changes, lock/unlock, workspace switch, task assign/complete,
        thermal events, heartbeat errors -> visible in Term.
        No silent changes.

INV-O2  Thermal events are recorded to file.
        Every warning, throttle, or lockout -> append to thermal_log.jsonl.
        This log is append-only, never auto-truncated.
        It is the forensic evidence that we protected the device.
```
