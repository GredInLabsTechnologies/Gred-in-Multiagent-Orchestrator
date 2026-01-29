export type EngineState = 'OFFLINE' | 'BOOTING' | 'ONLINE' | 'STOPPING' | 'CONFLICT' | 'ERROR';
export type BridgeState = 'DISCONNECTED' | 'CONNECTING' | 'CONNECTED' | 'RETRYING' | 'FAILED';
export type JobPhase = 'IDLE' | 'ROUTING' | 'FORGING' | 'RENDERING' | 'QA' | 'COMPLETE' | 'FAILED' | 'CANCELED';

export interface PerformanceSnapshot {
    vram_used_mb: number;
    vram_total_mb: number;
    gpu_util_percent: number;
    ram_used_gb: number;
    queue_depth: number;
    latency_ms: number; // Ping to backend
    throughput_steps_sec?: number; // Optional, only during gen
}

export interface EngineFeatures {
    pixel_art: boolean;
    animation: boolean;
    dynamic_schema: boolean;
    hot_swap: boolean;
}

export interface EngineError {
    code: string; // e.g., 'GPU_OOM', 'BRIDGE_TIMEOUT'
    message: string;
    timestamp: number;
    component: 'BRIDGE' | 'ENGINE' | 'ROUTER' | 'WORKER';
    stack?: string;
}

export interface TelemetrySnapshot {
    timestamp: number; // Epoch ms

    // Identity & Versioning
    connection_id: string; // Socket ID
    session_id: string;    // Browser Session
    schema_version: number;
    backend_version: string;
    frontend_version: string;

    engine_status: EngineState;
    bridge_status: BridgeState;

    performance: PerformanceSnapshot;
    features: EngineFeatures;

    last_error?: EngineError;
}

// --- Job & Agent Events ---

export interface JobEvent {
    id: string; // Event UUID
    seq: number; // Monotonic sequence for ordering
    job_id: string;
    type: 'JOB_ENQUEUED' | 'JOB_STARTED' | 'PHASE_CHANGED' | 'PROGRESS_UPDATE' | 'JOB_DONE' | 'JOB_FAILED' | 'JOB_CANCELED';
    timestamp: number;
    payload: {
        phase?: JobPhase;
        progress_percent?: number;
        step_current?: number;
        step_total?: number;
        error_detail?: string;
    };
}

export interface JobResult {
    job_id: string;
    status: 'PASS' | 'FAIL';

    // Audit & Reproducibility
    job_fingerprint: string; // Hash(effective_params + model + seed)
    effective_params: Record<string, unknown>;
    agent_patch_id?: string; // Link to what the agent changed

    outputs: Array<{
        path: string;
        type: 'image' | 'json' | 'video';
        hash?: string;
    }>;

    metrics: {
        total_time_ms: number;
        qa_score?: number;
    };
}

export interface AgentPatch {
    id: string;
    timestamp: number;
    reason: string;
    changes: Array<{
        path: string;
        from: unknown;
        to: unknown;
    }>;
}

export interface ActiveJob {
    id: string;
    prompt: string;
    start_time: number;
    phase: JobPhase;
    progress: number;

    // Control
    pinned_paths: string[]; // Paths the agent CANNOT touch
    patches: AgentPatch[]; // Audit trail
    effective_params?: Record<string, unknown>;
}
