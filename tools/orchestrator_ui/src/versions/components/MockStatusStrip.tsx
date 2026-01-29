import React from 'react';
import { Activity, Zap, Cpu, ShieldAlert } from 'lucide-react';

interface MockStatusStripProps {
    isZenMode: boolean;
    setIsZenMode: (val: boolean) => void;
}

export const MockStatusStrip: React.FC<MockStatusStripProps> = ({ isZenMode, setIsZenMode }) => {
    return (
        <div className="w-full h-10 bg-black/40 backdrop-blur-xl border-b border-white/5 flex items-center px-6 justify-between select-none z-50">
            <div className="flex items-center space-x-8">
                {/* Logo Area */}
                <div className="flex items-center space-x-2 mr-4 opacity-80">
                    <div className="w-1.5 h-1.5 rounded-full bg-accent-primary animate-pulse shadow-[0_0_8px_#7c3aed]" />
                    <span className="text-[10px] font-black tracking-[0.2em] text-white">GRED <span className="text-accent-primary font-light">IN</span></span>
                </div>

                {/* API Status */}
                <div className="flex items-center space-x-2">
                    <Activity className="w-3.5 h-3.5 text-emerald-400" />
                    <span className="text-[9px] font-bold text-slate-500 uppercase tracking-widest">Network</span>
                </div>

                {/* Engine Status */}
                <div className="flex items-center space-x-3 border-l border-white/5 pl-8">
                    <Zap className="w-3.5 h-3.5 text-slate-600" />
                    <div className="flex flex-col">
                        <span className="text-[9px] font-bold text-slate-500 uppercase tracking-widest leading-none mb-0.5">Engine</span>
                        <span className="text-[9px] font-mono text-slate-300 leading-none">OFFLINE</span>
                    </div>
                </div>

                {/* VRAM Flow Mock */}
                <div className="flex items-center space-x-4 border-l border-white/5 pl-8">
                    <Cpu className="w-3.5 h-3.5 text-slate-500" />
                    <div className="flex flex-col">
                        <span className="text-[9px] font-bold text-slate-500 uppercase tracking-widest leading-none mb-0.5">VRAM Flow</span>
                        <div className="flex items-center space-x-2">
                            <div className="w-20 h-1.5 bg-white/5 rounded-full overflow-hidden">
                                <div className="h-full bg-accent-primary w-1/4 rounded-full" />
                            </div>
                            <span className="text-[9px] font-mono text-slate-400 leading-none">1.2G</span>
                        </div>
                    </div>
                </div>
            </div>

            <div className="flex items-center space-x-6">
                {/* Panic Button Mock */}
                <div className="rounded-full border border-red-500/30 bg-red-950/30 px-3 py-1.5 flex items-center space-x-2 opacity-50">
                    <ShieldAlert className="w-3 h-3 text-red-500" />
                    <span className="text-[9px] font-black uppercase tracking-widest text-red-400">PANIC</span>
                </div>

                {/* Pro/Zen Toggle */}
                <div className="flex items-center space-x-3 bg-white/5 px-3 py-1.5 rounded-full border border-white/5">
                    <span className={`text-[10px] font-black uppercase tracking-widest ${!isZenMode ? 'text-accent-primary' : 'text-slate-500'}`}>Pro</span>
                    <button
                        onClick={() => setIsZenMode(!isZenMode)}
                        className={`relative inline-flex h-4 w-8 items-center rounded-full transition-colors duration-300 ${isZenMode ? 'bg-slate-700' : 'bg-accent-primary'}`}
                    >
                        <span
                            className={`inline-block h-2.5 w-2.5 transform rounded-full bg-white transition-transform duration-300 ${isZenMode ? 'translate-x-1' : 'translate-x-4.5'}`}
                            style={{ transform: isZenMode ? 'translateX(0.25rem)' : 'translateX(1.125rem)' }}
                        />
                    </button>
                    <span className={`text-[10px] font-black uppercase tracking-widest ${isZenMode ? 'text-emerald-400' : 'text-slate-500'}`}>Zen</span>
                </div>
            </div>
        </div>
    );
};
