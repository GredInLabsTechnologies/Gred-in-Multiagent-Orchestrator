import React, { useState, useEffect, useRef } from 'react';
import { Activity, Cpu, AlertCircle, Zap, ShieldAlert } from 'lucide-react';
import { TelemetrySnapshot } from '../types/telemetry';

interface StatusStripProps {
    telemetry: TelemetrySnapshot | null;
    isZenMode: boolean;
    setIsZenMode: (val: boolean) => void;
    panic: () => Promise<void>;
}

// Simple Sparkline Component
const Sparkline: React.FC<{ data: number[], color: string, max: number }> = ({ data, color, max }) => {
    if (data.length < 2) return null;
    const height = 16;
    const width = 60;
    const step = width / (data.length - 1);

    const points = data.map((val, i) => {
        const x = i * step;
        const normalized = Math.min(val, max) / max;
        const y = height - (normalized * height);
        return `${x},${y}`;
    }).join(' ');

    return (
        <svg width={width} height={height} className="overflow-visible">
            <polyline
                fill="none"
                stroke={color}
                strokeWidth="1.5"
                points={points}
                strokeLinecap="round"
                strokeLinejoin="round"
            />
        </svg>
    );
};

export const StatusStrip: React.FC<StatusStripProps> = ({
    telemetry,
    isZenMode,
    setIsZenMode,
    panic
}) => {
    const apiAvailable = !!telemetry;
    const status = telemetry?.engine_status || 'OFFLINE';

    // --- Sparkline Logic ---
    const [vramHistory, setVramHistory] = useState<number[]>([]);
    useEffect(() => {
        if (!telemetry) return;
        const used = telemetry.performance.vram_used_mb || 0;
        setVramHistory(prev => {
            const next = [...prev, used];
            if (next.length > 20) next.shift();
            return next;
        });
    }, [telemetry?.performance.vram_used_mb]);

    // --- Panic Button Logic (Hold to Trigger) ---
    const [panicProgress, setPanicProgress] = useState(0);
    const panicIntervalRef = useRef<number | undefined>(undefined);
    const isPanicTriggered = panicProgress >= 100;

    const startPanic = () => {
        if (isPanicTriggered || panicIntervalRef.current) return;
        panicIntervalRef.current = window.setInterval(() => {
            setPanicProgress(prev => {
                if (prev >= 100) {
                    clearInterval(panicIntervalRef.current);
                    panicIntervalRef.current = undefined; // Clear Ref
                    panic(); // FIRE!
                    return 100;
                }
                // 2000ms target / 50ms interval = 40 ticks
                // 100% / 40 ticks = 2.5% per tick
                return prev + 2.5;
            });
        }, 50);
    };

    const cancelPanic = () => {
        if (isPanicTriggered) {
            // Reset after heavy delay or manual reset? 
            setTimeout(() => setPanicProgress(0), 3000);
            return;
        }
        if (panicIntervalRef.current) {
            clearInterval(panicIntervalRef.current);
            panicIntervalRef.current = undefined;
        }
        setPanicProgress(0);
    };

    // Keyboard Accessibility
    const handleKeyDown = (e: React.KeyboardEvent) => {
        if (e.key === ' ' || e.key === 'Enter') {
            e.preventDefault();
            startPanic();
        }
    };

    const handleKeyUp = (e: React.KeyboardEvent) => {
        if (e.key === ' ' || e.key === 'Enter') {
            e.preventDefault();
            cancelPanic();
        }
    };

    return (
        <div className="w-full h-10 bg-black/40 backdrop-blur-xl border-b border-white/5 flex items-center px-6 justify-between select-none z-50">
            <div className="flex items-center space-x-8">
                {/* Logo Area */}
                <div className="flex items-center space-x-2 mr-4 pointer-events-none opacity-80">
                    <div className="w-1.5 h-1.5 rounded-full bg-accent-primary animate-pulse shadow-[0_0_8px_#7c3aed]" />
                    <span className="text-[10px] font-black tracking-[0.2em] text-white">GRED <span className="text-accent-primary font-light">IN</span></span>
                </div>

                {/* API Status */}
                <div className="flex items-center space-x-2">
                    <Activity className={`w-3.5 h-3.5 ${apiAvailable ? 'text-emerald-400' : 'text-red-500'} transition-colors`} />
                    <span className="text-[9px] font-bold text-slate-500 uppercase tracking-widest hidden sm:inline">Network</span>
                </div>

                {/* Engine Status */}
                <div className="flex items-center space-x-3 border-l border-white/5 pl-8">
                    <Zap className={`w-3.5 h-3.5 ${status === 'ONLINE' ? 'text-accent-secondary' : 'text-slate-600'} transition-colors`} />
                    <div className="flex flex-col">
                        <span className="text-[9px] font-bold text-slate-500 uppercase tracking-widest leading-none mb-0.5">Engine</span>
                        <span className="text-[9px] font-mono text-slate-300 leading-none">
                            {status}
                        </span>
                    </div>
                </div>

                {/* VRAM Sparkline */}
                {!isZenMode && (
                    <div className="flex items-center space-x-4 border-l border-white/5 pl-8 animate-fade-in group">
                        <Cpu className="w-3.5 h-3.5 text-slate-500 group-hover:text-purple-400 transition-colors" />
                        <div className="flex flex-col">
                            <span className="text-[9px] font-bold text-slate-500 uppercase tracking-widest leading-none mb-0.5">VRAM Flow</span>
                            <div className="flex items-end space-x-2">
                                <Sparkline
                                    data={vramHistory}
                                    color={telemetry?.performance.vram_used_mb && telemetry.performance.vram_used_mb > 20000 ? '#ef4444' : '#a855f7'}
                                    max={telemetry?.performance.vram_total_mb || 24576}
                                />
                                <span className="text-[9px] font-mono text-slate-400 leading-none">
                                    {(telemetry?.performance.vram_used_mb || 0) / 1024 > 1 ? `${((telemetry?.performance.vram_used_mb || 0) / 1024).toFixed(1)}G` : `${telemetry?.performance.vram_used_mb || 0}M`}
                                </span>
                            </div>
                        </div>
                    </div>
                )}
            </div>

            <div className="flex items-center space-x-6">
                {/* Panic Button */}
                <div
                    className="relative group focus:outline-none focus:ring-2 focus:ring-red-500/50 rounded-full"
                    role="button"
                    tabIndex={0}
                    aria-label="Panic Button: Hold Space or Click for 2 seconds to emergency stop"
                    onPointerDown={startPanic}
                    onPointerUp={cancelPanic}
                    onPointerLeave={cancelPanic}
                    onKeyDown={handleKeyDown}
                    onKeyUp={handleKeyUp}
                >
                    <div className={`overflow-hidden rounded-full border border-red-500/30 bg-red-950/30 px-3 py-1.5 flex items-center space-x-2 cursor-pointer transition-all ${isPanicTriggered ? 'animate-pulse bg-red-600 border-red-400' : 'hover:bg-red-900/40'}`}>
                        <ShieldAlert className={`w-3 h-3 ${isPanicTriggered ? 'text-white' : 'text-red-500'}`} />
                        <span className={`text-[9px] font-black uppercase tracking-widest ${isPanicTriggered ? 'text-white' : 'text-red-400'}`}>
                            {isPanicTriggered ? 'KILLING SYSTEM' : panicProgress > 0 ? `HOLD ${Math.round(panicProgress)}%` : 'PANIC'}
                        </span>
                    </div>
                    {/* Progress Bar Overlay */}
                    <div
                        className="absolute bottom-0 left-0 h-full bg-red-600 opacity-30 pointer-events-none transition-all duration-75 rounded-full"
                        style={{ width: `${panicProgress}%` }}
                    />
                </div>

                {/* Zen/Pro Toggle */}
                <div className="flex items-center space-x-3 bg-white/5 px-3 py-1.5 rounded-full border border-white/5 hover:border-white/10 transition-all">
                    <span className={`text-[10px] font-black uppercase tracking-widest transition-colors ${!isZenMode ? 'text-accent-primary' : 'text-slate-500'}`}>Pro</span>
                    <button
                        onClick={() => setIsZenMode(!isZenMode)}
                        className={`relative inline-flex h-4 w-8 items-center rounded-full transition-colors duration-300 focus:outline-none ${isZenMode ? 'bg-slate-700' : 'bg-accent-primary'}`}
                    >
                        <span
                            className={`inline-block h-2.5 w-2.5 transform rounded-full bg-white transition-transform duration-300 ${isZenMode ? 'translate-x-1' : 'translate-x-4.5'}`}
                            style={{ transform: isZenMode ? 'translateX(0.25rem)' : 'translateX(1.125rem)' }}
                        />
                    </button>
                    <span className={`text-[10px] font-black uppercase tracking-widest transition-colors ${isZenMode ? 'text-emerald-400' : 'text-slate-500'}`}>Zen</span>
                </div>

                {/* Last Error (Mini) */}
                {telemetry?.last_error && (
                    <div className="hidden md:flex items-center space-x-2 text-red-400 animate-pulse bg-red-500/10 px-3 py-1 rounded-full border border-red-500/20" title={telemetry.last_error.message}>
                        <AlertCircle className="w-3.5 h-3.5" />
                        <span className="text-[9px] font-bold uppercase tracking-widest">Error {telemetry.last_error.code}</span>
                    </div>
                )}
            </div>
        </div>
    );
};
