import React, { useState } from 'react';
import { Layers, Zap, Sliders, ChevronDown } from 'lucide-react';
import { DynamicFormRenderer } from '../DynamicFormRenderer';
import { WorkflowSchema, StylePreset } from '../../types';
import { useEngine } from '../../context/EngineContext';

interface CreativeTabProps {
    workflows: string[];
    activeWorkflow: string;
    setActiveWorkflow: (wf: string) => void;
    currentSchema: WorkflowSchema | null;
    overrides: Record<string, unknown>;
    setOverrides: React.Dispatch<React.SetStateAction<Record<string, unknown>>>;
    params: { seed: number };
    setParams: React.Dispatch<React.SetStateAction<{ seed: number }>>;
    activeStylePreset: string | null;
    setActiveStylePreset: (id: string | null) => void;
}

export const CreativeTab: React.FC<CreativeTabProps> = ({
    workflows,
    activeWorkflow,
    setActiveWorkflow,
    currentSchema,
    overrides,
    setOverrides,
    params,
    setParams,
    activeStylePreset,
    setActiveStylePreset
}) => {
    const { stylePresets } = useEngine();
    const [isSettingsOpen, setIsSettingsOpen] = useState(false);

    return (
        <div className="space-y-6">
            {/* Workflows (Pipelines) */}
            <div>
                <div className="px-4 mb-3 text-[10px] font-black text-slate-500 uppercase tracking-[0.2em] flex items-center">
                    <Layers className="w-3.5 h-3.5 mr-2" />
                    Pipelines
                </div>
                <div className="space-y-1.5 px-2">
                    {workflows.map((wf) => (
                        <button
                            key={wf}
                            onClick={() => setActiveWorkflow(wf)}
                            className={`w-full flex items-center py-3 px-5 rounded-2xl text-[10px] font-black transition-all relative ${activeWorkflow === wf
                                ? 'bg-accent-primary/10 text-accent-primary border border-accent-primary/20 shadow-[0_0_20px_rgba(124,58,237,0.05)]'
                                : 'text-slate-400 hover:bg-white/5 hover:text-white border border-transparent'
                                }`}
                        >
                            <span className="truncate text-left tracking-widest">{wf.replace(/_/g, ' ').toUpperCase()}</span>
                            {activeWorkflow === wf && <div className="absolute right-4 w-1.5 h-1.5 rounded-full bg-accent-primary animate-pulse shadow-[0_0_8px_#7c3aed]" />}
                        </button>
                    ))}
                </div>
            </div>

            {/* Style Presets (Actual Logic) */}
            {stylePresets && stylePresets.length > 0 && (
                <div>
                    <div className="px-4 mb-3 text-[10px] font-black text-slate-500 uppercase tracking-[0.2em] flex items-center mt-6">
                        <Layers className="w-3.5 h-3.5 mr-2 text-emerald-400" />
                        Logic Presets
                    </div>
                    <div className="px-2 grid grid-cols-2 gap-2">
                        {stylePresets.map((preset: StylePreset) => (
                            <button
                                key={preset.id}
                                onClick={() => setActiveStylePreset(activeStylePreset === preset.id ? null : preset.id)}
                                className={`py-3 px-4 rounded-xl text-[9px] font-black uppercase tracking-wider transition-all border ${activeStylePreset === preset.id
                                    ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30 shadow-[0_0_15px_rgba(52,211,153,0.1)]'
                                    : 'bg-black/20 text-slate-500 border-white/5 hover:border-white/10 hover:text-white'
                                    }`}
                            >
                                {preset.name}
                            </button>
                        ))}
                    </div>
                </div>
            )}

            {/* Global Controls */}
            <div className="px-2">
                <div className="p-5 bg-black/20 rounded-3xl border border-white/5 shadow-inner">
                    <div className="flex items-center justify-between mb-4">
                        <span className="text-[10px] font-black text-slate-500 uppercase tracking-[0.2em]">Variability (Seed)</span>
                        <div title="Randomize" className="cursor-pointer p-1 rounded-md hover:bg-white/5 transition-colors" onClick={() => setParams(prev => ({ ...prev, seed: -1 }))}>
                            <Zap
                                className={`w-3.5 h-3.5 transition-all ${params.seed === -1 ? 'text-accent-secondary animate-pulse' : 'text-slate-500 hover:text-white'}`}
                            />
                        </div>
                    </div>
                    <div className="flex items-center space-x-3">
                        <input
                            type="number"
                            value={params.seed}
                            onChange={e => setParams(prev => ({ ...prev, seed: parseInt(e.target.value) || -1 }))}
                            placeholder="Dynamic (-1)"
                            className="w-full bg-transparent text-slate-200 font-mono text-xs py-1 outline-none border-b border-white/10 focus:border-accent-secondary transition-colors"
                        />
                        {params.seed !== -1 && (
                            <span className="text-[8px] text-accent-secondary font-black uppercase tracking-widest bg-accent-secondary/10 px-2 py-0.5 rounded">Fixed</span>
                        )}
                    </div>
                </div>
            </div>

            {/* Advanced Params */}
            <div>
                <div
                    className="px-4 mb-4 text-[10px] font-black text-slate-500 uppercase tracking-[0.2em] flex items-center cursor-pointer hover:text-white transition-colors group"
                    onClick={() => setIsSettingsOpen(!isSettingsOpen)}
                >
                    <Sliders className="w-3.5 h-3.5 mr-2 group-hover:text-accent-primary transition-colors" />
                    Advanced Config
                    <ChevronDown className={`w-3.5 h-3.5 ml-auto transition-transform duration-300 ${isSettingsOpen ? 'rotate-180' : ''}`} />
                </div>

                {isSettingsOpen && (
                    <div className="px-2 animate-fade-in">
                        <div className="p-1 bg-black/10 rounded-2xl border border-white/5">
                            <DynamicFormRenderer
                                schema={currentSchema}
                                overrides={overrides}
                                onChange={(id: string, val: unknown) => setOverrides(prev => ({ ...prev, [id]: val }))}
                            />
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
};
