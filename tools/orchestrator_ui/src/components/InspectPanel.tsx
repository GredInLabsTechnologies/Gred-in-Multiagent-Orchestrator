import React, { useEffect, useMemo, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { X, Activity, Terminal, Settings, ListChecks, Cpu, AlertTriangle } from 'lucide-react';
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

interface HardwareInfo {
    cpu_percent: number;
    ram_percent: number;
    load_level: 'safe' | 'caution' | 'critical';
    available_models: number;
    local_safe: boolean;
}

interface RoutingInfo {
    selected_model: string;
    reason: string;
    provider_id: string;
    hardware_state: string;
    tier: number;
}

interface InspectPanelProps {
    selectedNodeId: string | null;
    onClose: () => void;
}

type PanelView = 'overview' | 'plan' | 'quality' | 'chat' | 'delegation' | 'prompt' | 'config';

const TABS: { id: PanelView; label: string; icon: typeof Terminal }[] = [
    { id: 'prompt', label: 'Prompt', icon: Terminal },
    { id: 'config', label: 'Config', icon: Settings },
    { id: 'plan', label: 'Plan', icon: ListChecks },
    { id: 'overview', label: 'Info', icon: Activity },
];

export const InspectPanel: React.FC<InspectPanelProps> = ({
    selectedNodeId,
    onClose,
}) => {
    const nodes = useNodes();
    const selectedNode = useMemo(
        () => nodes.find((n) => n.id === selectedNodeId) as GraphNode | undefined,
        [nodes, selectedNodeId],
    );

    const planData = selectedNode?.data?.plan;
    const qualityData = selectedNode?.data?.quality;

    const [view, setView] = useState<PanelView>('overview');
    const { models, loading: modelsLoading } = useAvailableModels();
    const { addToast } = useToast();
    const [hwInfo, setHwInfo] = useState<HardwareInfo | null>(null);

    // Fetch hardware state
    useEffect(() => {
        let active = true;
        const poll = async () => {
            try {
                const res = await fetch(`${API_BASE}/ops/mastery/hardware`, { credentials: 'include' });
                if (res.ok && active) setHwInfo(await res.json());
            } catch { /* ignore */ }
        };
        poll();
        const id = setInterval(poll, 15_000);
        return () => { active = false; clearInterval(id); };
    }, []);

    // Extract routing info from node data (set by graph engine after execution)
    const routingInfo: RoutingInfo | null = useMemo(() => {
        const d = selectedNode?.data as any;
        const trace = d?.model_router_last;
        if (trace?.selected_model) return trace;
        return null;
    }, [selectedNode]);

    const handleSavePrompt = async (newPrompt: string) => {
        if (!selectedNodeId || !selectedNode?.data?.plan?.draft_id) return;
        const draftId = selectedNode.data.plan.draft_id;
        try {
            const resp = await fetch(`${API_BASE}/ops/drafts/${draftId}`, { credentials: 'include' });
            if (!resp.ok) throw new Error('Failed to fetch draft');
            const draft = await resp.json();
            let plan: any;
            try {
                plan = typeof draft.content === 'string' ? JSON.parse(draft.content) : draft.content;
            } catch {
                addToast('El contenido del draft no es JSON valido', 'error');
                return;
            }
            if (!plan?.tasks) return;
            const task = plan.tasks.find((t: any) => t.id === selectedNodeId);
            if (task?.agent_assignee) task.agent_assignee.system_prompt = newPrompt;
            const saveResp = await fetch(`${API_BASE}/ops/drafts/${draftId}`, {
                method: 'PUT',
                credentials: 'include',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ content: JSON.stringify(plan, null, 2) }),
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
            const resp = await fetch(`${API_BASE}/ops/drafts/${draftId}`, { credentials: 'include' });
            const draft = await resp.json();
            let plan: any;
            try {
                plan = typeof draft.content === 'string' ? JSON.parse(draft.content) : draft.content;
            } catch {
                addToast('El contenido del draft no es JSON valido', 'error');
                return;
            }
            if (!plan?.tasks) return;
            const task = plan.tasks.find((t: any) => t.id === selectedNodeId);
            if (task?.agent_assignee) task.agent_assignee.model = newModel;
            await fetch(`${API_BASE}/ops/drafts/${draftId}`, {
                method: 'PUT',
                credentials: 'include',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ content: JSON.stringify(plan, null, 2) }),
            });
            addToast('Modelo actualizado', 'success');
        } catch {
            addToast('Error al actualizar modelo', 'error');
        }
    };

    /* ── Status color for node type ── */
    const nodeData = selectedNode?.data as any;
    const nodeTypeColor = useMemo(() => {
        const t = nodeData?.node_type || nodeData?.role || 'worker';
        const map: Record<string, string> = {
            orchestrator: 'text-cyan-400',
            worker: 'text-blue-400',
            reviewer: 'text-orange-400',
            researcher: 'text-purple-400',
            tool: 'text-emerald-400',
            human_gate: 'text-amber-400',
        };
        return map[t] || 'text-blue-400';
    }, [nodeData]);

    return (
        <aside className="w-[380px] h-full bg-surface-0/90 backdrop-blur-2xl border-l border-white/[0.06] flex flex-col shrink-0 overflow-hidden shadow-2xl shadow-black/30 z-40">
            {/* Header */}
            <div className="h-12 px-4 flex items-center justify-between border-b border-white/[0.04] shrink-0">
                <div className="flex items-center gap-2 min-w-0">
                    <span className={`text-[10px] font-bold uppercase tracking-wider ${nodeTypeColor}`}>
                        {nodeData?.node_type || nodeData?.role || 'Nodo'}
                    </span>
                    <span className="text-xs font-semibold text-text-primary truncate">
                        {selectedNode?.data?.label || selectedNodeId}
                    </span>
                    {selectedNode?.data?.trustLevel && (
                        <TrustBadge level={selectedNode.data.trustLevel} />
                    )}
                </div>
                <button
                    onClick={onClose}
                    className="w-7 h-7 rounded-lg flex items-center justify-center text-text-secondary hover:text-text-primary hover:bg-white/[0.06] transition-all"
                    aria-label="Cerrar panel"
                >
                    <X size={14} />
                </button>
            </div>

            {/* Tabs as pills */}
            <div className="flex px-4 pt-3 pb-2 gap-1 border-b border-white/[0.04] overflow-x-auto no-scrollbar">
                {TABS.map((tab) => {
                    const Icon = tab.icon;
                    const isActive = view === tab.id;
                    return (
                        <button
                            key={tab.id}
                            onClick={() => setView(tab.id)}
                            className={`relative px-3 py-1.5 rounded-lg flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wider shrink-0 transition-all ${isActive
                                ? 'bg-accent-primary/15 text-accent-primary'
                                : 'text-text-tertiary hover:text-text-secondary hover:bg-white/[0.04]'
                                }`}
                        >
                            <Icon size={12} />
                            {tab.label}
                        </button>
                    );
                })}
            </div>

            {/* Content */}
            <div className="flex-1 overflow-y-auto custom-scrollbar p-5 space-y-6">
                <AnimatePresence mode="wait">
                    {selectedNodeId ? (
                        <motion.div
                            key={view}
                            initial={{ opacity: 0, x: 8 }}
                            animate={{ opacity: 1, x: 0 }}
                            exit={{ opacity: 0, x: -8 }}
                            transition={{ type: 'spring', stiffness: 400, damping: 30 }}
                        >
                            {view === 'plan' && <AgentPlanPanel plan={planData} />}
                            {view === 'prompt' && (
                                <SystemPromptEditor
                                    initialPrompt={selectedNode?.data?.system_prompt || ''}
                                    onSave={handleSavePrompt}
                                />
                            )}
                            {view === 'config' && (
                                <div className="space-y-6">
                                    <div className="p-4 rounded-xl bg-surface-2/50 border border-white/[0.04] space-y-4">
                                        <div className="flex items-center gap-2 text-text-secondary mb-2">
                                            <Settings size={14} />
                                            <span className="text-[10px] font-bold uppercase tracking-widest">
                                                Ajustes del Agente
                                            </span>
                                        </div>
                                        <div className="space-y-2">
                                            <label htmlFor="node-model-select" className="text-[10px] font-bold text-text-secondary uppercase">
                                                Modelo Principal
                                            </label>
                                            {!modelsLoading && models.length === 0 ? (
                                                <input
                                                    id="node-model-select"
                                                    type="text"
                                                    className="input-field"
                                                    value={selectedNode?.data?.agent_config?.model || 'auto'}
                                                    onChange={(e) => handleModelChange(e.target.value)}
                                                    placeholder="Modelo..."
                                                />
                                            ) : (
                                                <select
                                                    id="node-model-select"
                                                    className="input-field"
                                                    value={selectedNode?.data?.agent_config?.model || 'auto'}
                                                    onChange={(e) => handleModelChange(e.target.value)}
                                                    disabled={modelsLoading}
                                                >
                                                    <option value="auto">Auto (seleccion del orquestador)</option>
                                                    {modelsLoading && <option disabled>Cargando...</option>}
                                                    {models.map((m) => (
                                                        <option key={m.id} value={m.id}>
                                                            {m.label || m.id}
                                                            {m.installed ? ' (local)' : ''}
                                                        </option>
                                                    ))}
                                                </select>
                                            )}
                                            {(selectedNode?.data?.agent_config?.model === 'auto' || !selectedNode?.data?.agent_config?.model) && (
                                                <p className="text-[9px] text-amber-400/70 leading-relaxed">
                                                    El orquestador auto-seleccionara el modelo mas eficiente para esta tarea.
                                                </p>
                                            )}
                                        </div>
                                        <div className="space-y-2">
                                            <label htmlFor="node-role-input" className="text-[10px] font-bold text-text-secondary uppercase">
                                                Definicion de Rol
                                            </label>
                                            <input
                                                id="node-role-input"
                                                type="text"
                                                value={selectedNode?.data?.agent_config?.role || ''}
                                                className="input-field"
                                                readOnly
                                            />
                                        </div>
                                    </div>

                                    {/* Hardware & Routing Info */}
                                    {hwInfo && (() => {
                                        const getBgClass = (level: string) => {
                                            if (level === 'critical') return 'bg-red-500/10 border-red-500/20';
                                            if (level === 'caution') return 'bg-amber-500/10 border-amber-500/20';
                                            return 'bg-surface-2/50 border-white/[0.04]';
                                        };
                                        const bgClass = getBgClass(hwInfo.load_level);
                                        return (
                                            <div className={`p-4 rounded-xl border space-y-3 ${bgClass}`}>
                                                <div className="flex items-center gap-2 text-text-secondary">
                                                    <Cpu size={14} />
                                                    <span className="text-[10px] font-bold uppercase tracking-widest">
                                                        Estado del Sistema
                                                    </span>
                                                </div>
                                                <div className="flex gap-4 text-xs">
                                                    <div className="flex items-center gap-1.5">
                                                        <span className="text-text-secondary">CPU</span>
                                                        <span className={`font-mono ${hwInfo.cpu_percent > 80 ? 'text-amber-400' : 'text-text-primary'}`}>
                                                            {hwInfo.cpu_percent.toFixed(0)}%
                                                        </span>
                                                    </div>
                                                    <div className="flex items-center gap-1.5">
                                                        <span className="text-text-secondary">RAM</span>
                                                        <span className={`font-mono ${hwInfo.ram_percent > 85 ? 'text-amber-400' : 'text-text-primary'}`}>
                                                            {hwInfo.ram_percent.toFixed(0)}%
                                                        </span>
                                                    </div>
                                                    <div className="flex items-center gap-1.5">
                                                        <span className="text-text-secondary">Modelos</span>
                                                        <span className="font-mono text-text-primary">{hwInfo.available_models}</span>
                                                    </div>
                                                </div>
                                                {hwInfo.load_level === 'critical' && (
                                                    <div className="flex items-center gap-2 text-[10px] text-red-400">
                                                        <AlertTriangle size={12} />
                                                        <span>Carga critica — solo modelos remotos disponibles</span>
                                                    </div>
                                                )}
                                                {hwInfo.load_level === 'caution' && (
                                                    <div className="flex items-center gap-2 text-[10px] text-amber-400">
                                                        <AlertTriangle size={12} />
                                                        <span>Carga elevada — modelos locales grandes limitados</span>
                                                    </div>
                                                )}
                                                {hwInfo.load_level === 'safe' && !hwInfo.local_safe && (
                                                    <div className="flex items-center gap-2 text-[10px] text-amber-400">
                                                        <AlertTriangle size={12} />
                                                        <span>RAM insuficiente para modelos locales grandes</span>
                                                    </div>
                                                )}
                                            </div>
                                        );
                                    })()}

                                    {/* Last Routing Decision */}
                                    {routingInfo && (
                                        <div className="p-4 rounded-xl bg-surface-2/50 border border-white/[0.04] space-y-3">
                                            <div className="text-[10px] font-bold text-text-secondary uppercase tracking-widest">
                                                Ultima Decision de Routing
                                            </div>
                                            <div className="space-y-2 text-xs">
                                                <div className="flex justify-between">
                                                    <span className="text-text-secondary">Modelo</span>
                                                    <span className="font-mono text-accent-primary">{routingInfo.selected_model}</span>
                                                </div>
                                                <div className="flex justify-between">
                                                    <span className="text-text-secondary">Provider</span>
                                                    <span className="font-mono text-text-primary">{routingInfo.provider_id}</span>
                                                </div>
                                                <div className="flex justify-between">
                                                    <span className="text-text-secondary">Tier</span>
                                                    <span className="font-mono text-text-primary">{routingInfo.tier}/5</span>
                                                </div>
                                                <div className="flex justify-between">
                                                    <span className="text-text-secondary">Hardware</span>
                                                    <span className={`font-mono ${(() => {
                                                        if (routingInfo.hardware_state === 'critical') return 'text-red-400';
                                                        if (routingInfo.hardware_state === 'caution') return 'text-amber-400';
                                                        return 'text-emerald-400';
                                                    })()
                                                        }`}>{routingInfo.hardware_state}</span>
                                                </div>
                                            </div>
                                            <div className="mt-2">
                                                <span className="text-[10px] text-text-secondary">Razon:</span>
                                                <p className="text-[10px] font-mono text-text-tertiary mt-1 leading-relaxed break-all">
                                                    {routingInfo.reason}
                                                </p>
                                            </div>
                                        </div>
                                    )}
                                </div>
                            )}
                            {view === 'quality' && <QualityAlertPanel quality={qualityData} />}
                            {view === 'delegation' && <SubAgentCluster agentId={selectedNodeId} />}
                            {view === 'chat' && (
                                <div className="h-[400px]">
                                    <AgentChat agentId={selectedNodeId} />
                                </div>
                            )}
                            {view === 'overview' && (
                                <div className="space-y-4">
                                    <div className="p-4 rounded-xl bg-surface-2/50 border border-white/[0.04]">
                                        <div className="text-[10px] text-text-secondary font-bold uppercase tracking-widest mb-3">
                                            Propiedades del Nodo
                                        </div>
                                        <div className="space-y-3">
                                            {[
                                                ['Tipo', nodeData?.node_type || nodeData?.role || 'worker', 'text-text-primary'],
                                                ['Estado', selectedNode?.data?.status || 'pending', 'text-emerald-400'],
                                                ...(selectedNode?.data?.estimated_tokens
                                                    ? [['Tokens Est.', String(selectedNode.data.estimated_tokens), 'text-accent-primary']]
                                                    : []),
                                            ].map(([label, value, color]) => (
                                                <div key={label} className="flex justify-between items-center text-xs">
                                                    <span className="text-text-secondary">{label}</span>
                                                    <span className={`font-mono bg-white/[0.03] px-1.5 py-0.5 rounded ${color}`}>
                                                        {value}
                                                    </span>
                                                </div>
                                            ))}
                                        </div>
                                    </div>
                                </div>
                            )}
                        </motion.div>
                    ) : (
                        <div className="flex flex-col items-center justify-center py-20 text-text-tertiary text-center px-6">
                            <Activity size={32} className="mb-4 opacity-10" />
                            <p className="text-sm font-medium text-text-secondary">Ningun nodo seleccionado</p>
                            <p className="text-[10px] mt-1 text-text-tertiary">
                                Selecciona un agente o componente para inspeccionar su estado
                            </p>
                        </div>
                    )}
                </AnimatePresence>
            </div>
        </aside>
    );
};
