import React, { createContext, useContext, useEffect, useRef, useState, useCallback } from 'react';
import {
    TelemetrySnapshot, ActiveJob, EngineFeatures, EngineState
} from '../types/telemetry';
import { Backend, StylePreset, isStylePresetArray } from '../types';

// Configuration
const WS_URL = `ws://${window.location.hostname}:8001/ws`;
const RECONNECT_DELAY_MS = 2000;
const PING_INTERVAL_MS = 2000;
const API_BASE = `http://${window.location.hostname}:8001`;

interface EngineContextValue {
    // State
    telemetry: TelemetrySnapshot | null;
    activeJob: ActiveJob | null;
    isPanic: boolean;
    bootStep: string;

    // Agentic Controls
    isAutoTuneEnabled: boolean;
    setIsAutoTuneEnabled: (val: boolean) => void;
    isAgentThinking: boolean;

    // Data
    history: string[];
    workflows: string[];
    availableBackends: Backend[];
    stylePresets: StylePreset[];

    // Actions
    startEngine: () => Promise<void>;
    stopEngine: () => Promise<void>;
    panic: () => Promise<void>;
    refreshData: () => Promise<void>;

    // Debug
    lastPing: number;
}

const EngineContext = createContext<EngineContextValue | null>(null);

export const useEngine = () => {
    const ctx = useContext(EngineContext);
    if (!ctx) throw new Error("useEngine must be used within EngineProvider");
    return ctx;
};

// Default Features
const DEFAULT_FEATURES: EngineFeatures = {
    pixel_art: false,
    animation: false,
    dynamic_schema: true,
    hot_swap: false
};

// Legacy Types
interface LegacyStatus {
    type: 'status_update';
    data: {
        status: string;
        vram?: { used_mb: number; total_mb: number; };
    };
}
interface LegacyProgress {
    type: 'comfy_progress';
    data: { value: number; max: number; };
}
interface LegacyExecutionStart {
    type: 'comfy_execution_start';
    data: { prompt_id: string; };
}
interface LegacyExecutionBlock {
    type: 'comfy_executing';
    data: { node: string | null; };
}
interface EnginePong {
    type: 'pong';
    timestamp: number;
}
type LegacyMessage = LegacyStatus | LegacyProgress | LegacyExecutionStart | LegacyExecutionBlock | EnginePong | { type: string; data: unknown };

export const EngineProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
    // === Core State ===
    const [telemetry, setTelemetry] = useState<TelemetrySnapshot | null>(null);
    const [activeJob, setActiveJob] = useState<ActiveJob | null>(null);
    const [isPanic, setIsPanic] = useState(false);
    const [bootStep, setBootStep] = useState<string>("Initializing Neural Core...");

    const [latency, setLatency] = useState<number>(0);
    const latencyRef = useRef<number>(0);

    // === Agentic State ===
    const [isAutoTuneEnabled, setIsAutoTuneEnabled] = useState(true);
    const [isAgentThinking, setIsAgentThinking] = useState(false);

    // Watchdog
    const lastPongTimeRef = useRef<number>(0);

    // === Data State ===
    const [history, setHistory] = useState<string[]>([]);
    const [workflows, setWorkflows] = useState<string[]>([]);
    const [availableBackends, setAvailableBackends] = useState<Backend[]>([]);
    const [stylePresets, setStylePresets] = useState<StylePreset[]>([]);

    // === Refs ===
    const wsRef = useRef<WebSocket | null>(null);
    const timerRef = useRef<number | undefined>(undefined); // Reconnect timer
    const pingTimerRef = useRef<number | undefined>(undefined);
    const jobClearTimerRef = useRef<number | undefined>(undefined); // Job clear timer

    const shouldReconnectRef = useRef<boolean>(true); // Preventing zombie reconnects

    // === Stable Callback Refs ===
    const latestParseLegacyMessage = useRef<(msg: LegacyMessage) => void>(() => { });

    // === Fetchers ===
    const refreshData = useCallback(async (full = false) => {
        try {
            const promises = [fetch(`${API_BASE}/latest_outputs`)];
            if (full) {
                promises.push(fetch(`${API_BASE}/workflows`));
                promises.push(fetch(`${API_BASE}/backends`));
            }

            const results = await Promise.all(promises);
            const hResp = results[0];

            if (hResp.ok) setHistory(await hResp.json());

            if (full) {
                const wResp = results[1];
                const bResp = results[2];
                if (wResp.ok) setWorkflows(await wResp.json());
                if (bResp.ok) setAvailableBackends(await bResp.json());

                // Fetch Style Presets
                fetch(`${API_BASE}/copilot/presets`)
                    .then(r => r.json())
                    .then(data => {
                        if (isStylePresetArray(data)) {
                            setStylePresets(data);
                        } else {
                            console.warn("Received malformed style presets", data);
                        }
                    })
                    .catch(e => console.error("Failed to fetch presets", e));
            }
        } catch (e) {
            console.error("Data Sync Error:", e);
        }
    }, []);

    // Initial Fetch & Low Frequency Polling for History
    useEffect(() => {
        refreshData(true);
        const interval = setInterval(() => refreshData(false), 5000);
        return () => clearInterval(interval);
    }, [refreshData]);

    // === Telemetry Logic ===
    const parseLegacyMessage = useCallback((msg: LegacyMessage) => {
        if (msg.type === 'pong') {
            const now = Date.now();
            const sent = (msg as EnginePong).timestamp;
            const rtt = now - sent;
            const newLatency = Math.max(0, Math.floor(rtt / 2));
            setLatency(newLatency);
            latencyRef.current = newLatency;
            lastPongTimeRef.current = now; // Update watchdog
            return;
        }

        if (msg.type === 'status_update') {
            const m = msg as LegacyStatus;
            setTelemetry(prev => ({
                ...prev,
                timestamp: Date.now(),
                connection_id: prev?.connection_id || "legacy_socket",
                session_id: prev?.session_id || "legacy_session",
                schema_version: 1,
                backend_version: '0.9.0',
                frontend_version: '0.9.5',

                engine_status: m.data.status as EngineState,
                bridge_status: 'CONNECTED',
                performance: {
                    ...prev?.performance,
                    vram_used_mb: m.data.vram?.used_mb || 0,
                    vram_total_mb: m.data.vram?.total_mb || 24576,
                    gpu_util_percent: 0,
                    ram_used_gb: 0,
                    queue_depth: 0,
                    latency_ms: latencyRef.current
                },
                features: DEFAULT_FEATURES,
            } as TelemetrySnapshot));

            // Update Boot Step based on Engine Status
            switch (m.data.status) {
                case 'ONLINE': setBootStep("Engine Ready"); break;
                case 'BOOTING': setBootStep("Engine Igniting..."); break;
                case 'OFFLINE': setBootStep("Engine Staged (Offline)"); break;
                case 'ERROR': setBootStep("Engine Failure - Recovery Mode"); break;
                case 'STOPPING': setBootStep("Engine Cooling Down..."); break;
                case 'CONFLICT': setBootStep("Engine Collision Detected"); break;
                default: setBootStep(`Status: ${m.data.status}`);
            }
        }

        if (msg.type === 'comfy_execution_start') {
            const m = msg as LegacyExecutionStart;
            if (jobClearTimerRef.current) clearTimeout(jobClearTimerRef.current);

            // Agent starts thinking when forging
            setIsAgentThinking(true);

            setActiveJob({
                id: m.data.prompt_id,
                prompt: "Unknown (Legacy)",
                start_time: Date.now(),
                phase: 'FORGING',
                progress: 0,
                pinned_paths: [],
                patches: []
            });
        }

        if (msg.type === 'comfy_progress') {
            const m = msg as LegacyProgress;

            // If rendering, agent is no longer 'thinking' in the chat sense
            if (m.data.value > 0) setIsAgentThinking(false);

            setActiveJob(prev => {
                if (!prev) return null;
                return {
                    ...prev,
                    progress: Math.round((m.data.value / m.data.max) * 100),
                    phase: 'RENDERING'
                };
            });
        }

        if (msg.type === 'comfy_executing') {
            const m = msg as LegacyExecutionBlock;
            if (m.data.node === null) {
                setIsAgentThinking(false);
                setActiveJob(prev => {
                    if (!prev) return null;
                    return { ...prev, phase: 'COMPLETE', progress: 100 };
                });

                if (jobClearTimerRef.current) clearTimeout(jobClearTimerRef.current);
                jobClearTimerRef.current = window.setTimeout(() => {
                    setActiveJob(null);
                    refreshData(false);
                }, 2000);
            }
        }
    }, [refreshData]);

    // Keep the Ref updated
    useEffect(() => {
        latestParseLegacyMessage.current = parseLegacyMessage;
    }, [parseLegacyMessage]);

    // === Socket Logic ===
    const cleanup = useCallback(() => {
        shouldReconnectRef.current = false; // Prevent zombies
        if (pingTimerRef.current) clearInterval(pingTimerRef.current);
        if (timerRef.current) clearTimeout(timerRef.current);
        if (jobClearTimerRef.current) clearTimeout(jobClearTimerRef.current);
        if (wsRef.current) {
            wsRef.current.close();
            wsRef.current = null;
        }
    }, []);

    const connect = useCallback(() => {
        if (!shouldReconnectRef.current) return;
        if (wsRef.current?.readyState === WebSocket.OPEN) return;

        if (pingTimerRef.current) clearInterval(pingTimerRef.current);

        setBootStep("Establishing Neural Link...");
        const socket = new WebSocket(WS_URL);

        socket.onopen = () => {
            console.log("[Engine] Neural Link Established");
            setBootStep("Verifying Neural Handshake...");
            lastPongTimeRef.current = Date.now();
            // Don't set "Engine Ready" here! Telemetry should drive it.

            pingTimerRef.current = window.setInterval(() => {
                if (socket.readyState === WebSocket.OPEN) {
                    const ts = Date.now();
                    if (ts - lastPongTimeRef.current > (PING_INTERVAL_MS * 3)) {
                        setLatency(0);
                        latencyRef.current = 0;
                    }
                    try {
                        socket.send(JSON.stringify({ type: 'ping', timestamp: ts }));
                    } catch (e) { /* Socket closed */ }
                }
            }, PING_INTERVAL_MS);
        };

        socket.onmessage = (event) => {
            try {
                const msg = JSON.parse(event.data) as LegacyMessage;
                // Use the Ref!
                latestParseLegacyMessage.current(msg);
            } catch (e) {
                console.error("Telemetry Parse Error:", e);
            }
        };

        socket.onclose = () => {
            console.warn("[Engine] Link Lost. Retrying...");

            // UX Improvement: Distinguish between Boot and Crash
            if (telemetry?.engine_status === 'ONLINE') {
                setBootStep("Connection Lost - Retrying...");
            } else {
                setBootStep("Waiting for Neural Core...");
            }

            if (pingTimerRef.current) clearInterval(pingTimerRef.current);

            setTelemetry(prev => prev ? ({
                ...prev,
                bridge_status: 'RETRYING',
                engine_status: 'OFFLINE'
            } as TelemetrySnapshot) : null);

            if (shouldReconnectRef.current) {
                timerRef.current = window.setTimeout(connect, RECONNECT_DELAY_MS);
            }
        };

        wsRef.current = socket;
    }, []); // Zero dependencies!

    useEffect(() => {
        shouldReconnectRef.current = true;
        connect();
        return cleanup;
    }, [connect, cleanup]);

    // === Actions ===
    const startEngine = async () => {
        setBootStep("Ignition Sequence Start...");
        try {
            await fetch(`${API_BASE}/engine/start`, { method: 'POST' });
            refreshData(true);
        } catch (e) {
            setBootStep("Ignition Failed: Bridge Error");
        }
    };

    const stopEngine = async () => {
        await fetch(`${API_BASE}/engine/stop`, { method: 'POST' });
        refreshData(false);
    };

    const panic = async () => {
        setIsPanic(true);
        console.error("!!! PANIC PROTOCOL INITIATED !!!");

        try {
            // Placeholder
        } catch (e) { console.warn("Soft cancel failed"); }

        await stopEngine();

        if (jobClearTimerRef.current) clearTimeout(jobClearTimerRef.current);
        setActiveJob(null);
        setTelemetry(null);
        setIsAgentThinking(false);
        refreshData(true);

        setTimeout(() => setIsPanic(false), 3000);
    };

    return (
        <EngineContext.Provider value={{
            telemetry,
            activeJob,
            isPanic,
            bootStep,

            isAutoTuneEnabled,
            setIsAutoTuneEnabled,
            isAgentThinking,

            history,
            workflows,
            availableBackends,
            stylePresets,

            startEngine,
            stopEngine,
            panic,
            refreshData: () => refreshData(true),

            lastPing: latency
        }}>
            {children}
        </EngineContext.Provider>
    );
};
