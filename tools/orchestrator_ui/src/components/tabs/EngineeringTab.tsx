import React from 'react';
import { Square, RefreshCw, Play, ChevronDown, Activity, Cpu, ShieldCheck } from 'lucide-react';
import { TelemetrySnapshot } from '../../types/telemetry';
import { Backend as BackendType } from '../../types';

interface StatusItemProps {
    label: string;
    value: string;
    ok: boolean;
}

const StatusItem: React.FC<StatusItemProps> = ({ label, value, ok }) => (
    <div className="flex items-center justify-between py-2 border-b border-white/5 last:border-0">
        <span className="text-[10px] font-bold text-slate-500 uppercase tracking-tighter">{label}</span>
        <div className="flex items-center space-x-2">
            <span className={`text-[10px] font-mono ${ok ? 'text-slate-300' : 'text-red-400'}`}>{value}</span>
            <div className={`w-1.5 h-1.5 rounded-full ${ok ? 'bg-emerald-500 shadow-[0_0_5px_rgba(16,185,129,0.5)]' : 'bg-red-500 shadow-[0_0_5px_rgba(239,68,68,0.5)]'}`} />
        </div>
    </div>
);

interface EngineeringTabProps {
    telemetry: TelemetrySnapshot | null;
    availableBackends: BackendType[];
    activeBackend: string;
    setActiveBackend: (id: string) => void;
    startEngine: (id: string) => Promise<void>;
    stopEngine: () => Promise<void>;
    isAutoTuneEnabled: boolean;
    setIsAutoTuneEnabled: (val: boolean) => void;
}

export const EngineeringTab: React.FC<EngineeringTabProps> = ({
    telemetry,
    availableBackends,
    activeBackend,
    setActiveBackend,
    startEngine,
    stopEngine,
    isAutoTuneEnabled,
    setIsAutoTuneEnabled
}) => {
    // Derived Metrics
    const status = telemetry?.engine_status || 'OFFLINE';
    const vramFree = telemetry?.performance ? (telemetry.performance.vram_total_mb - telemetry.performance.vram_used_mb) : 0;

    return (
        <div className="space-y-6">
            {/* Engine Selector */}
            <div className="px-2">
                <label className="text-[10px] font-black text-slate-500 uppercase tracking-[0.2em] mb-3 block pl-1">AI Backend Kernel</label>
                <div className="space-y-3">
                    <div className="relative group">
                        <select
                            value={activeBackend}
                            onChange={(e) => setActiveBackend(e.target.value)}
                            className="w-full bg-black/40 border border-white/5 rounded-2xl px-5 py-4 text-[11px] font-bold text-white appearance-none focus:outline-none focus:border-accent-primary transition-all cursor-pointer group-hover:bg-black/60 shadow-inner"
                        >
                            {availableBackends.map(b => (
                                <option key={b.id} value={b.id} className="bg-slate-900">{b.display_name.toUpperCase()}</option>
                            ))}
                        </select>
                        <ChevronDown className="absolute right-5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500 pointer-events-none group-hover:text-white transition-colors" />
                    </div>

                    <div className="flex space-x-2">
                        {(status === 'ONLINE') ? (
                            <button
                                onClick={() => stopEngine()}
                                className="flex-1 py-4 bg-red-500/5 hover:bg-red-500/10 border border-red-500/10 rounded-2xl text-[10px] font-black uppercase tracking-[0.2em] text-red-400 flex items-center justify-center transition-all shadow-lg"
                            >
                                <Square className="w-3 h-3 mr-2 fill-current" />
                                Stop Model
                            </button>
                        ) : (
                            <button
                                onClick={() => startEngine(activeBackend)}
                                disabled={status === 'BOOTING'}
                                className="flex-1 py-4 bg-accent-primary/10 hover:bg-accent-primary/20 border border-accent-primary/20 rounded-2xl text-[10px] font-black uppercase tracking-[0.2em] text-accent-primary flex items-center justify-center transition-all disabled:opacity-50 disabled:cursor-wait shadow-lg"
                            >
                                {status === 'BOOTING' ? (
                                    <RefreshCw className="w-3 h-3 mr-2 animate-spin" />
                                ) : (
                                    <Play className="w-3 h-3 mr-2 fill-current" />
                                )}
                                {status === 'BOOTING' ? 'Igniting...' : 'Ignite Model'}
                            </button>
                        )}
                    </div>
                </div>
            </div>

            {/* Agentic Governance */}
            <div className="px-2">
                <div className="p-4 bg-accent-primary/5 rounded-2xl border border-accent-primary/10 space-y-4">
                    <div className="flex items-center justify-between">
                        <h3 className="text-[10px] font-bold text-accent-primary uppercase tracking-widest flex items-center">
                            <ShieldCheck className="w-3 h-3 mr-2" />
                            Agentic Governance
                        </h3>
                        <div className="flex items-center space-x-2">
                            <span className="text-[9px] font-bold text-slate-500 uppercase">AutoTune</span>
                            <button
                                onClick={() => setIsAutoTuneEnabled(!isAutoTuneEnabled)}
                                className={`w-8 h-2 rounded-full relative transition-colors ${isAutoTuneEnabled ? 'bg-accent-primary' : 'bg-slate-800'}`}
                            >
                                <div className={`absolute -top-1 w-4 h-4 rounded-full bg-white shadow-md transition-all ${isAutoTuneEnabled ? 'left-4' : 'left-0'}`} />
                            </button>
                        </div>
                    </div>
                    <p className="text-[9px] text-slate-500 leading-tight">
                        When active, the Agent policy can autonomously tune hyper-params and retry failed nodes using neural heuristics.
                    </p>
                </div>
            </div>

            {/* Health & Metrics */}
            <div className="space-y-6 px-2">
                <div className="p-4 bg-black/20 rounded-2xl border border-white/5 space-y-4">
                    <div className="flex items-center justify-between">
                        <h3 className="text-[10px] font-bold text-slate-400 uppercase tracking-widest flex items-center">
                            <Activity className="w-3 h-3 mr-2" />
                            Health Check
                        </h3>
                        <div className={`px-2 py-0.5 rounded text-[9px] font-bold uppercase ${status === 'ONLINE' ? 'bg-emerald-500/20 text-emerald-400' :
                                status === 'BOOTING' ? 'bg-amber-500/20 text-amber-400' :
                                    'bg-red-500/20 text-red-400'
                            }`}>
                            {status}
                        </div>
                    </div>

                    <div className="space-y-1">
                        <StatusItem label="Engine Core" value={telemetry?.backend_version ? `v${telemetry.backend_version}` : "---"} ok={status !== 'OFFLINE'} />
                        <StatusItem label="Bridge Latency" value={`${telemetry?.performance?.latency_ms || 0}ms`} ok={(telemetry?.performance?.latency_ms || 999) < 100} />
                        <StatusItem label="Session ID" value={telemetry?.session_id?.substring(0, 8) || "---"} ok={!!telemetry?.session_id} />
                    </div>
                </div>

                {/* Resources */}
                <div className="p-4 bg-black/20 rounded-2xl border border-white/5 space-y-4">
                    <h3 className="text-[10px] font-bold text-slate-400 uppercase tracking-widest flex items-center">
                        <Cpu className="w-3 h-3 mr-2" />
                        Resources
                    </h3>
                    <div className="space-y-1">
                        <StatusItem label="VRAM Available" value={vramFree ? `${vramFree} MB` : '---'} ok={vramFree > 1000} />
                        <StatusItem label="Swap Capable" value={telemetry?.features?.hot_swap ? "Yes" : "No"} ok={telemetry?.features?.hot_swap || false} />
                        <StatusItem label="Dynamic Schema" value={telemetry?.features?.dynamic_schema ? "Active" : "Disabled"} ok={telemetry?.features?.dynamic_schema || false} />
                    </div>
                </div>

                {/* Last Error Log */}
                {telemetry?.last_error && (
                    <div className="p-4 bg-red-500/5 rounded-2xl border border-red-500/10 space-y-2">
                        <h3 className="text-[10px] font-bold text-red-400 uppercase tracking-widest mb-2">Last Incident</h3>
                        <div className="font-mono text-[9px] text-red-300/80 leading-relaxed break-all bg-black/20 p-2 rounded-lg border border-red-500/10">
                            [{telemetry.last_error.code}] {telemetry.last_error.message}
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
};
