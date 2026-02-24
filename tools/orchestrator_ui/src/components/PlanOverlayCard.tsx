import React, { useState } from 'react';
import { Panel } from 'reactflow';
import { CheckCircle2, XCircle, Pencil, FileText, Cpu } from 'lucide-react';
import { useAvailableModels } from '../hooks/useAvailableModels';

interface PlanOverlayCardProps {
    prompt: string;
    draftId: string;
    onApprove: (model?: string) => void;
    onReject: () => void;
    onEdit: () => void;
    loading?: boolean;
}

export const PlanOverlayCard: React.FC<PlanOverlayCardProps> = ({
    prompt,
    draftId,
    onApprove,
    onReject,
    onEdit,
    loading = false,
}) => {
    const [orchestratorModel, setOrchestratorModel] = useState<string>('auto');
    const { models, loading: modelsLoading } = useAvailableModels();

    return (
        <Panel position="bottom-right" className="!m-4">
            <div className="w-[340px] bg-[#141414]/95 backdrop-blur-xl rounded-2xl border border-[#2c2c2e] shadow-2xl overflow-hidden animate-in fade-in slide-in-from-top-2 duration-300">
                {/* Header */}
                <div className="px-4 pt-3 pb-2 border-b border-[#1c1c1e] flex items-center gap-2">
                    <div className="p-1 rounded-md bg-[#0a84ff]/10 text-[#0a84ff]">
                        <FileText size={14} />
                    </div>
                    <span className="text-[10px] font-black text-[#86868b] uppercase tracking-widest">Plan</span>
                    <span className="ml-auto text-[9px] font-mono text-[#424245]">{draftId.slice(0, 12)}</span>
                </div>

                {/* Plan text */}
                <div className="px-4 py-3">
                    <p className="text-xs text-[#f5f5f7] leading-relaxed line-clamp-3 font-medium">
                        {prompt}
                    </p>
                </div>

                {/* Orchestrator Model Selector */}
                <div className="px-4 pb-3 flex items-center gap-2">
                    <Cpu size={12} className="text-amber-400 shrink-0" />
                    <label htmlFor="orch-model-select" className="text-[9px] text-white/30 uppercase tracking-wider shrink-0">Modelo Orch.</label>
                    {(!modelsLoading && models.length === 0) ? (
                        <input
                            id="orch-model-select"
                            type="text"
                            value={orchestratorModel}
                            onChange={(e) => setOrchestratorModel(e.target.value)}
                            disabled={loading}
                            placeholder="Modelo..."
                            className="flex-1 bg-black/40 border border-white/10 rounded-lg px-2 py-1 text-[10px] text-amber-300/80 focus:outline-none focus:border-amber-500/40 disabled:opacity-50"
                        />
                    ) : (
                        <select
                            id="orch-model-select"
                            value={orchestratorModel}
                            onChange={(e) => setOrchestratorModel(e.target.value)}
                            disabled={loading || modelsLoading}
                            className="flex-1 bg-black/40 border border-white/10 rounded-lg px-2 py-1 text-[10px] text-amber-300/80 focus:outline-none focus:border-amber-500/40 disabled:opacity-50"
                        >
                            <option value="auto">⚡ Auto (Orquestador decide)</option>
                            {modelsLoading && <option disabled>Cargando modelos...</option>}
                            {[...models]
                                .sort((a, b) => (a.label || a.id).localeCompare(b.label || b.id))
                                .map(m => (
                                    <option key={m.id} value={m.id}>{m.label || m.id} {m.installed ? ' (Local)' : ''}</option>
                                ))}
                        </select>
                    )}
                </div>

                {/* Action buttons */}
                <div className="px-4 pb-3 flex gap-2">
                    <button
                        onClick={() => onApprove(orchestratorModel === 'auto' ? undefined : orchestratorModel)}
                        disabled={loading}
                        className="flex-1 h-8 rounded-xl bg-[#32d74b]/10 border border-[#32d74b]/20 text-[#32d74b] text-[10px] font-black uppercase tracking-wider hover:bg-[#32d74b]/20 transition-all flex items-center justify-center gap-1.5 disabled:opacity-50"
                    >
                        <CheckCircle2 size={12} />
                        Aprobar
                    </button>
                    <button
                        onClick={onReject}
                        disabled={loading}
                        className="flex-1 h-8 rounded-xl bg-[#ff453a]/10 border border-[#ff453a]/20 text-[#ff453a] text-[10px] font-black uppercase tracking-wider hover:bg-[#ff453a]/20 transition-all flex items-center justify-center gap-1.5 disabled:opacity-50"
                    >
                        <XCircle size={12} />
                        Denegar
                    </button>
                    <button
                        onClick={onEdit}
                        disabled={loading}
                        className="h-8 px-3 rounded-xl bg-[#1c1c1e] border border-[#2c2c2e] text-[#86868b] text-[10px] font-black uppercase tracking-wider hover:text-[#f5f5f7] hover:border-[#3c3c3e] transition-all flex items-center justify-center gap-1.5 disabled:opacity-50"
                    >
                        <Pencil size={12} />
                        Editar
                    </button>
                </div>
            </div>
        </Panel>
    );
};
