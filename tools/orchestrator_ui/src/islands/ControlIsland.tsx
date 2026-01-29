import React from 'react';
import { FolderOpen } from 'lucide-react';
import { TelemetrySnapshot } from '../types/telemetry';
import { Backend as BackendType } from '../types';
import { Accordion } from '../components/Accordion';


interface ControlIslandProps {
    workflows: string[];
    activeWorkflow: string;
    setActiveWorkflow: (wf: string) => void;
    telemetry: TelemetrySnapshot | null;
    setIsVaultOpen: (val: boolean) => void;
    availableBackends: BackendType[];
    activeBackend: string;
    setActiveBackend: (id: string) => void;
    startEngine: (id: string) => Promise<void>;
    stopEngine: () => Promise<void>;
}


export const ControlIsland: React.FC<ControlIslandProps> = ({
    workflows,
    activeWorkflow,
    setActiveWorkflow,
    setIsVaultOpen,
    availableBackends,
    activeBackend,
    setActiveBackend,
    startEngine,
    stopEngine,
}) => {
    const activeBackendInfo = availableBackends.find(b => b.id === activeBackend);



    return (
        <nav className="flex-1 flex flex-col z-10 overflow-hidden relative space-y-3">
            {/* Workflow Selector Accordion */}
            <Accordion title="Workflow" defaultOpen={true}>
                <select
                    value={activeWorkflow}
                    onChange={(e) => setActiveWorkflow(e.target.value)}
                    className="w-full px-4 py-3 bg-black/40 border border-white/10 rounded-xl text-sm text-slate-200 focus:border-accent-primary/50 focus:outline-none transition-colors"
                >
                    {workflows.map((wf) => (
                        <option key={wf} value={wf} className="bg-slate-900">{wf}</option>
                    ))}
                </select>
            </Accordion>


            {/* Engine Control Accordion */}
            <Accordion title="Engine Control">
                <div className="space-y-3">
                    <select
                        value={activeBackend}
                        onChange={(e) => setActiveBackend(e.target.value)}
                        className="w-full px-4 py-3 bg-black/40 border border-white/10 rounded-xl text-sm text-slate-200 focus:border-accent-primary/50 focus:outline-none transition-colors"
                    >
                        {availableBackends.map((be) => (
                            <option key={be.id} value={be.id} className="bg-slate-900">{be.name}</option>
                        ))}
                    </select>

                    <div className="flex space-x-2">
                        <button
                            onClick={() => startEngine(activeBackend)}
                            disabled={activeBackendInfo?.status === 'running'}
                            className="flex-1 py-2 bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 rounded-xl text-[10px] font-bold uppercase tracking-wider hover:bg-emerald-500/30 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
                        >
                            Start
                        </button>
                        <button
                            onClick={() => stopEngine()}
                            disabled={activeBackendInfo?.status !== 'running'}
                            className="flex-1 py-2 bg-red-500/20 text-red-400 border border-red-500/30 rounded-xl text-[10px] font-bold uppercase tracking-wider hover:bg-red-500/30 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
                        >
                            Stop
                        </button>
                    </div>
                </div>
            </Accordion>


            {/* Spacer */}
            <div className="flex-1" />

            {/* Storage Vault Button */}
            <button
                onClick={() => setIsVaultOpen(true)}
                className="w-full py-4 bg-gradient-to-br from-slate-800/50 to-slate-950/50 border border-white/10 rounded-2xl flex items-center justify-center space-x-3 group hover:border-accent-primary/50 transition-all shadow-xl relative overflow-hidden"
            >
                <div className="absolute inset-0 bg-accent-primary/5 opacity-0 group-hover:opacity-100 transition-opacity" />
                <FolderOpen className="w-4 h-4 text-slate-400 group-hover:text-accent-primary transition-colors" />
                <span className="text-[10px] font-black uppercase tracking-[0.2em] text-slate-400 group-hover:text-white transition-colors">Storage Vault</span>
            </button>
        </nav>
    );
};
