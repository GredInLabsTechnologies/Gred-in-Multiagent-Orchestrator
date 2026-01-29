import React, { useEffect, useState } from 'react';
import { useEngine } from '../context/EngineContext';
import { RefreshCw, Terminal, AlertTriangle, Cpu } from 'lucide-react';

export const SplashGate: React.FC = () => {
    const { telemetry, bootStep, startEngine } = useEngine();
    const [isVisible, setIsVisible] = useState(true);

    const isReady = telemetry?.engine_status === 'ONLINE' || telemetry?.engine_status === 'OFFLINE';
    const isError = telemetry?.engine_status === 'ERROR' || (telemetry && !isReady && telemetry.engine_status !== 'BOOTING');

    useEffect(() => {
        if (isReady) {
            const timer = setTimeout(() => setIsVisible(false), 800);
            return () => clearTimeout(timer);
        } else {
            setIsVisible(true);
        }
    }, [isReady]);

    if (!isVisible) return null;

    return (
        <div className="fixed inset-0 z-[100] bg-[#09090b] flex flex-col items-center justify-center select-none font-mono">
            {/* Cinematic Background Grid */}
            <div className="absolute inset-0 bg-[linear-gradient(rgba(255,255,255,0.03)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,0.03)_1px,transparent_1px)] bg-[size:32px_32px] pointer-events-none" />

            <div className="relative z-10 flex flex-col items-center space-y-8 max-w-md w-full px-8">
                {/* Logo Glitch Effect */}
                <div className="relative group cursor-default">
                    <div className="absolute -inset-1 bg-gradient-to-r from-purple-600 to-blue-600 rounded blur opacity-25 group-hover:opacity-50 transition duration-1000 group-hover:duration-200"></div>
                    <h1 className="relative text-4xl font-black tracking-[0.3em] text-white">
                        GRED <span className="text-purple-500">IN</span>
                    </h1>
                </div>

                {/* Terminal Window */}
                <div className="w-full bg-black/50 border border-white/10 rounded-lg p-4 backdrop-blur-md shadow-2xl space-y-4">
                    <div className="flex items-center space-x-2 border-b border-white/5 pb-2">
                        <Terminal className="w-4 h-4 text-slate-500" />
                        <span className="text-[10px] text-slate-500 uppercase tracking-widest">System Sequence</span>
                    </div>

                    <div className="space-y-2">
                        <div className="flex justify-between items-center text-xs">
                            <span className="text-slate-400">Current Step:</span>
                            <span className="text-purple-400 font-bold animate-pulse">{bootStep}</span>
                        </div>

                        {/* Dynamic Progress Bar */}
                        <div className="w-full h-1 bg-white/10 rounded-full overflow-hidden">
                            <div
                                className={`h-full bg-purple-500 transition-all duration-1000 ${isReady ? 'w-full' : 'animate-[loading_2s_ease-in-out_infinite] w-1/3'}`}
                            />
                        </div>
                    </div>

                    {isError && (
                        <div className="bg-red-500/10 border border-red-500/20 p-3 rounded flex items-start space-x-3 mt-4">
                            <AlertTriangle className="w-4 h-4 text-red-500 shrink-0 mt-0.5" />
                            <div className="space-y-2">
                                <p className="text-[10px] text-red-400 leading-relaxed">
                                    Link stability compromised. The engine may be offline or unreachable.
                                </p>
                                <div className="flex space-x-2">
                                    <button
                                        onClick={() => startEngine()}
                                        className="px-3 py-1 bg-red-500/20 hover:bg-red-500/30 text-red-400 text-[9px] font-bold uppercase tracking-widest rounded transition-colors flex items-center"
                                    >
                                        <RefreshCw className="w-3 h-3 mr-1.5" />
                                        Initialize Engine
                                    </button>
                                </div>
                            </div>
                        </div>
                    )}
                </div>

                {/* Footer Metrics */}
                <div className="flex justify-between w-full text-[9px] text-slate-600 uppercase tracking-widest">
                    <span>V.0.9.2 (Alpha)</span>
                    <span className="flex items-center">
                        <Cpu className="w-3 h-3 mr-1" />
                        System Check
                    </span>
                </div>
            </div>
        </div>
    );
};
