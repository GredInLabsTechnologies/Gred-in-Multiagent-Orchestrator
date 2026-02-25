import React, { useMemo, useState } from 'react';
import { X, Activity, Terminal, Settings, ListChecks } from 'lucide-react';
import { AgentPlanPanel } from './AgentPlanPanel';
import { TrustBadge } from './TrustBadge';
import { QualityAlertPanel } from './QualityAlertPanel';
import AgentChat from './AgentChat';
import { SubAgentCluster } from './SubAgentCluster';
import { useNodes } from 'reactflow';
import { GraphNode, API_BASE } from '../types';
import { SystemPromptEditor } from './SystemPromptEditor';
import { useAvailableModels } from '../hooks/useAvailableModels';
import { useToast } from './Toast';

interface InspectPanelProps {
    selectedNodeId: string | null;
    onClose: () => void;
}

export const InspectPanel: React.FC<InspectPanelProps> = ({
    selectedNodeId,
    onClose,
}) => {
    const nodes = useNodes();
    const selectedNode = useMemo(() =>
        nodes.find(n => n.id === selectedNodeId) as GraphNode | undefined,
        [nodes, selectedNodeId]);

    const planData = selectedNode?.data?.plan;
    const qualityData = selectedNode?.data?.quality;

    const [view, setView] = useState<'overview' | 'plan' | 'quality' | 'chat' | 'delegation' | 'prompt' | 'config'>('overview');
    const { models, loading: modelsLoading } = useAvailableModels();
    const { addToast } = useToast();


    const handleSavePrompt = async (newPrompt: string) => {
        if (!selectedNodeId || !selectedNode?.data?.plan?.draft_id) return;
        const draftId = selectedNode.data.plan.draft_id;

        try {
            // 1. Fetch current draft to get full plan content
            const resp = await fetch(`${API_BASE}/ops/drafts/${draftId}`, {
                credentials: 'include'
            });
            if (!resp.ok) throw new Error('Failed to fetch draft');
            const draft = await resp.json();

            // 2. Update the specific task's system prompt in the content
            const plan = JSON.parse(draft.content);
            const task = plan.tasks.find((t: any) => t.id === selectedNodeId);
            if (task?.agent_assignee) {
                task.agent_assignee.system_prompt = newPrompt;
            }

            // 3. Save back to server
            const saveResp = await fetch(`${API_BASE}/ops/drafts/${draftId}`, {
                method: 'PUT',
                credentials: 'include',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    content: JSON.stringify(plan, null, 2)
                })
            });

            if (!saveResp.ok) throw new Error('Failed to save draft');
            addToast('Prompt guardado correctamente', 'success');
        } catch (err) {
            addToast('Error al guardar prompt: ' + (err instanceof Error ? err.message : String(err)), 'error');
        }
    };

    const handleModelChange = async (newModel: string) => {
        if (!selectedNodeId || !selectedNode?.data?.plan?.draft_id) return;
        const draftId = selectedNode.data.plan.draft_id;

        try {
            const resp = await fetch(`${API_BASE}/ops/drafts/${draftId}`, {
                credentials: 'include'
            });
            const draft = await resp.json();
            const plan = JSON.parse(draft.content);
            const task = plan.tasks.find((t: any) => t.id === selectedNodeId);
            if (task?.agent_assignee) {
                task.agent_assignee.model = newModel;
            }

            await fetch(`${API_BASE}/ops/drafts/${draftId}`, {
                method: 'PUT',
                credentials: 'include',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    content: JSON.stringify(plan, null, 2)
                })
            });
            addToast('Modelo actualizado', 'success');
        } catch {
            addToast('Error al actualizar modelo', 'error');
        }
    };

    return (
        <aside className="w-[380px] bg-[#0a0a0a] border-l border-[#2c2c2e] flex flex-col shrink-0 overflow-hidden shadow-2xl z-40">
            <div className="h-12 px-4 flex items-center justify-between border-b border-[#1c1c1e] shrink-0 bg-[#000000]/50">
                <div className="flex items-center gap-2 min-w-0">
                    <span className="text-xs font-semibold text-[#f5f5f7] truncate uppercase tracking-wider">
                        {`Nodo: ${selectedNode?.data?.label || selectedNodeId}`}
                    </span>
                    {selectedNode?.data?.trustLevel && (
                        <TrustBadge level={selectedNode.data.trustLevel} />
                    )}
                </div>
                <button
                    onClick={onClose}
                    className="w-7 h-7 rounded-lg flex items-center justify-center text-[#86868b] hover:text-[#f5f5f7] hover:bg-[#1c1c1e] transition-all"
                >
                    <X size={14} />
                </button>
            </div>

            <div className="flex px-4 pt-4 gap-4 border-b border-[#1c1c1e] bg-[#000000]/20 overflow-x-auto no-scrollbar">
                <button
                    onClick={() => setView('prompt')}
                    className={`pb-2 shrink-0 flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-widest transition-all relative ${view === 'prompt' ? 'text-blue-400' : 'text-white/20 hover:text-white/40'}`}
                >
                    <Terminal size={12} />
                    Prompt
                    {view === 'prompt' && <div className="absolute bottom-0 left-0 w-full h-0.5 bg-blue-500 shadow-[0_0_10px_rgba(59,130,246,0.5)]" />}
                </button>
                <button
                    onClick={() => setView('config')}
                    className={`pb-2 shrink-0 flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-widest transition-all relative ${view === 'config' ? 'text-blue-400' : 'text-white/20 hover:text-white/40'}`}
                >
                    <Settings size={12} />
                    Config
                    {view === 'config' && <div className="absolute bottom-0 left-0 w-full h-0.5 bg-blue-500 shadow-[0_0_10px_rgba(59,130,246,0.5)]" />}
                </button>
                <button
                    onClick={() => setView('plan')}
                    className={`pb-2 shrink-0 flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-widest transition-all relative ${view === 'plan' ? 'text-blue-400' : 'text-white/20 hover:text-white/40'}`}
                >
                    <ListChecks size={12} />
                    Plan
                    {view === 'plan' && <div className="absolute bottom-0 left-0 w-full h-0.5 bg-blue-500 shadow-[0_0_10px_rgba(59,130,246,0.5)]" />}
                </button>
                <button
                    onClick={() => setView('overview')}
                    className={`pb-2 shrink-0 text-[10px] font-bold uppercase tracking-widest transition-all relative ${view === 'overview' ? 'text-blue-400' : 'text-white/20 hover:text-white/40'}`}
                >
                    Info
                    {view === 'overview' && <div className="absolute bottom-0 left-0 w-full h-0.5 bg-blue-500 shadow-[0_0_10px_rgba(59,130,246,0.5)]" />}
                </button>
            </div>

            <div className="flex-1 overflow-y-auto custom-scrollbar p-5 space-y-6">
                {selectedNodeId ? (
                    <>
                        {/* Bloque de Preguntas oculto hasta soporte backend */}

                        {view === 'plan' && <AgentPlanPanel plan={planData} />}
                        {view === 'prompt' && (
                            <SystemPromptEditor
                                initialPrompt={selectedNode?.data?.system_prompt || ''}
                                onSave={handleSavePrompt}
                            />
                        )}
                        {view === 'config' && (
                            <div className="space-y-6 animate-fade-in">
                                <div className="p-4 rounded-2xl bg-white/5 border border-white/10 space-y-4">
                                    <div className="flex items-center gap-2 text-white/40 mb-2">
                                        <Settings size={14} />
                                        <span className="text-[10px] font-bold uppercase tracking-widest">Ajustes del Agente</span>
                                    </div>

                                    <div className="space-y-2">
                                        <label htmlFor="node-model-select" className="text-[10px] font-bold text-white/30 uppercase">Modelo Principal</label>
                                        {(!modelsLoading && models.length === 0) ? (
                                            <input
                                                id="node-model-select"
                                                type="text"
                                                className="w-full bg-black/40 border border-white/10 rounded-xl px-3 py-2 text-xs text-blue-100/80 focus:outline-none focus:border-blue-500/50"
                                                value={selectedNode?.data?.agent_config?.model || 'auto'}
                                                onChange={(e) => handleModelChange(e.target.value)}
                                                placeholder="Modelo..."
                                            />
                                        ) : (
                                            <select
                                                id="node-model-select"
                                                className="w-full bg-black/40 border border-white/10 rounded-xl px-3 py-2 text-xs text-blue-100/80 focus:outline-none focus:border-blue-500/50"
                                                value={selectedNode?.data?.agent_config?.model || 'auto'}
                                                onChange={(e) => handleModelChange(e.target.value)}
                                                disabled={modelsLoading}
                                            >
                                                <option value="auto" className="text-amber-400">⚡ Auto (selección del orquestador)</option>
                                                {modelsLoading && <option disabled>Cargando...</option>}
                                                {models.map(m => (
                                                    <option key={m.id} value={m.id}>{m.label || m.id} {m.installed ? ' (local)' : ''}</option>
                                                ))}
                                            </select>
                                        )}
                                        {(selectedNode?.data?.agent_config?.model === 'auto' || !selectedNode?.data?.agent_config?.model) && (
                                            <p className="text-[9px] text-amber-400/70 leading-relaxed">
                                                El orquestador auto-seleccionará el modelo más eficiente para esta tarea.
                                            </p>
                                        )}
                                    </div>

                                    <div className="space-y-2">
                                        <label htmlFor="node-role-input" className="text-[10px] font-bold text-white/30 uppercase">Definición de Rol</label>
                                        <input
                                            id="node-role-input"
                                            type="text"
                                            value={selectedNode?.data?.agent_config?.role || ''}
                                            className="w-full bg-black/40 border border-white/10 rounded-xl px-3 py-2 text-xs text-blue-100/80 focus:outline-none focus:border-blue-500/50"
                                            readOnly
                                        />
                                    </div>
                                </div>
                            </div>
                        )}
                        {view === 'quality' && <QualityAlertPanel quality={qualityData} />}
                        {view === 'delegation' && <SubAgentCluster agentId={selectedNodeId} />}
                        {view === 'chat' && <div className="h-[400px]"><AgentChat agentId={selectedNodeId} /></div>}
                        {view === 'overview' && (
                            <div className="space-y-4 animate-fade-in">
                                <div className="p-4 rounded-xl bg-white/5 border border-white/10">
                                    <div className="text-[10px] text-white/30 font-bold uppercase tracking-widest mb-3">Propiedades del Nodo</div>
                                    <div className="space-y-3">
                                        <div className="flex justify-between items-center text-xs">
                                            <span className="text-white/40">Tipo</span>
                                            <span className="text-white/80 font-mono bg-white/5 px-1.5 py-0.5 rounded">{selectedNode?.type}</span>
                                        </div>
                                        <div className="flex justify-between items-center text-xs">
                                            <span className="text-white/40">Estado</span>
                                            <span className="text-emerald-400 font-mono">{selectedNode?.data?.status || 'pending'}</span>
                                        </div>
                                        {selectedNode?.data?.estimated_tokens && (
                                            <div className="flex justify-between items-center text-xs">
                                                <span className="text-white/40">Tokens Est.</span>
                                                <span className="text-blue-400 font-mono">{selectedNode.data.estimated_tokens}</span>
                                            </div>
                                        )}
                                    </div>
                                </div>

                                {/* Delegation Trust UI hidden for Phase 1 as backend lacks support */}
                            </div>
                        )}
                    </>
                ) : (
                    <div className="flex flex-col items-center justify-center py-20 text-white/10 text-center px-6">
                        <Activity size={32} className="mb-4 opacity-10" />
                        <p className="text-sm font-medium">Ningún nodo seleccionado</p>
                        <p className="text-[10px] mt-1">Selecciona un agente o componente para inspeccionar su estado actual</p>
                    </div>
                )}
            </div>
        </aside>
    );
};
