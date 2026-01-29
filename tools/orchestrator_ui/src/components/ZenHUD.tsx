import React from 'react';
import { Zap, Square, RefreshCcw, Camera, Sparkles } from 'lucide-react';
import { useEngine } from '../context/EngineContext';

export const ZenHUD: React.FC = () => {
    const {
        telemetry,
        activeJob,
        startEngine,
        stopEngine,
        refreshData,
        isAutoTuneEnabled,
        setIsAutoTuneEnabled
    } = useEngine();

    const isRunning = activeJob !== null && activeJob.phase !== 'COMPLETE' && activeJob.phase !== 'FAILED';
    const progress = activeJob?.progress || 0;
    const status = telemetry?.engine_status || 'OFFLINE';
    const isReady = status === 'ONLINE' && !isRunning;

    // Local handle for variation (placeholder logic for now)
    const handleVariation = () => {
        // Logic will involve re-triggering with same params but different seed
        console.log("Zen Mode: Variation Requested");
    };

    return (
        <div className="fixed bottom-12 left-1/2 -translate-x-1/2 z-[100] animate-fade-in-up">
            <div className="flex items-center space-x-2 p-1.5 bg-black/60 backdrop-blur-2xl border border-white/10 rounded-full shadow-2xl">

                {/* Minimal Status Indicator */}
                <div className="px-4 py-2 flex items-center space-x-2 border-r border-white/5">
                    <div className={`w-2 h-2 rounded-full ${status === 'ONLINE' ? 'bg-emerald-500 animate-pulse' : 'bg-red-500'} shadow-[0_0_10px_rgba(16,185,129,0.3)]`} />
                    <span className="text-[10px] font-black tracking-widest text-white/40 uppercase">{status}</span>
                </div>

                {/* Main Action Group */}
                <div className="flex items-center space-x-1 px-2">
                    {isReady ? (
                        <button
                            onClick={() => startEngine()}
                            className="group relative flex items-center justify-center w-12 h-12 bg-accent-primary hover:bg-accent-primary/80 rounded-full transition-all duration-300 shadow-[0_0_20px_rgba(124,58,237,0.4)]"
                        >
                            <Zap className="w-5 h-5 text-white fill-white transition-transform group-hover:scale-110" />
                        </button>
                    ) : isRunning ? (
                        <button
                            onClick={stopEngine}
                            className="group relative flex items-center justify-center w-12 h-12 bg-red-600 hover:bg-red-500 rounded-full transition-all duration-300 shadow-[0_0_20px_rgba(220,38,38,0.4)] overflow-hidden"
                        >
                            {/* Progress Ring Background */}
                            <svg className="absolute inset-0 w-full h-full -rotate-90">
                                <circle
                                    cx="24"
                                    cy="24"
                                    r="22"
                                    fill="none"
                                    stroke="white"
                                    strokeWidth="2"
                                    strokeDasharray="138"
                                    strokeDashoffset={138 - (138 * progress) / 100}
                                    className="opacity-40 transition-all duration-500 ease-out"
                                />
                            </svg>
                            <Square className="w-4 h-4 text-white fill-white relative z-10" />
                        </button>
                    ) : (
                        <div className="flex items-center justify-center w-12 h-12 bg-white/5 rounded-full border border-white/10 opacity-50 cursor-not-allowed">
                            <Zap className="w-5 h-5 text-white/20" />
                        </div>
                    )}

                    {/* Secondary Actions */}
                    <div className="flex items-center space-x-1">
                        <button
                            onClick={handleVariation}
                            disabled={!isReady}
                            className="w-10 h-10 flex items-center justify-center bg-white/5 hover:bg-white/10 rounded-full border border-white/5 transition-all text-white/60 hover:text-white disabled:opacity-20 disabled:cursor-not-allowed"
                            title="Variation"
                        >
                            <RefreshCcw className="w-4 h-4" />
                        </button>
                        <button
                            onClick={() => setIsAutoTuneEnabled(!isAutoTuneEnabled)}
                            className={`w-10 h-10 flex items-center justify-center rounded-full border transition-all ${isAutoTuneEnabled ? 'bg-accent-secondary/20 border-accent-secondary/40 text-accent-secondary shadow-[0_0_15px_rgba(232,121,249,0.3)]' : 'bg-white/5 border-white/5 text-white/20 hover:text-white/40'}`}
                            title={isAutoTuneEnabled ? "AutoTune: Enabled" : "AutoTune: Disabled"}
                        >
                            <Sparkles className={`w-4 h-4 ${isAutoTuneEnabled ? 'animate-pulse' : ''}`} />
                        </button>
                        <button
                            onClick={() => refreshData()}
                            className="w-10 h-10 flex items-center justify-center bg-white/5 hover:bg-white/10 rounded-full border border-white/5 transition-all text-white/60 hover:text-white"
                            title="Snapshot"
                        >
                            <Camera className="w-4 h-4" />
                        </button>
                    </div>
                </div>

                {/* Progress Text (Internal) */}
                {isRunning && (
                    <div className="pl-2 pr-6 border-l border-white/5">
                        <span className="text-[10px] font-mono text-white/80">{progress}%</span>
                    </div>
                )}
            </div>
        </div>
    );
};
