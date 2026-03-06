import React, { useEffect, useState, useCallback } from 'react';
import { motion } from 'framer-motion';
import { Shield, Activity, Zap, AlertCircle, RefreshCw, BarChart3, ChevronRight, Info } from 'lucide-react';
import { API_BASE, AgentActionEvent, AgentInsight } from '../types';

interface OpsFlowProps {
    agentId?: string;
}

export const OpsFlow: React.FC<OpsFlowProps> = ({ agentId }) => {
    const [events, setEvents] = useState<AgentActionEvent[]>([]);
    const [insights, setInsights] = useState<AgentInsight[]>([]);
    const [loading, setLoading] = useState(true);
    const [refreshing, setRefreshing] = useState(false);

    const fetchData = useCallback(async () => {
        setRefreshing(true);
        try {
            const agentParam = agentId ? `?agent_id=${agentId}` : '';
            const [evResp, inResp] = await Promise.all([
                fetch(`${API_BASE}/ops/trust/ids/events${agentParam}`, { credentials: 'include' }),
                fetch(`${API_BASE}/ops/trust/ids/insights${agentParam}`, { credentials: 'include' })
            ]);

            if (evResp.ok) {
                const data = await evResp.json();
                setEvents(data.items || []);
            }
            if (inResp.ok) {
                const data = await inResp.json();
                setInsights(data.items || []);
            }
        } catch (error) {
            console.error('Failed to fetch IDS data:', error);
        } finally {
            setLoading(false);
            setRefreshing(false);
        }
    }, [agentId]);

    useEffect(() => {
        fetchData();
        const interval = setInterval(fetchData, 10000);
        return () => clearInterval(interval);
    }, [fetchData]);

    const getOutcomeColor = (outcome: string) => {
        switch (outcome) {
            case 'success': return 'text-emerald-400';
            case 'error': return 'text-red-400';
            case 'timeout': return 'text-amber-400';
            case 'rejected': return 'text-zinc-500';
            default: return 'text-text-tertiary';
        }
    };

    const getPriorityColor = (priority: string) => {
        switch (priority) {
            case 'high': return 'bg-red-500/10 text-red-400 border-red-500/20';
            case 'medium': return 'bg-amber-500/10 text-amber-400 border-amber-500/20';
            case 'low': return 'bg-blue-500/10 text-blue-400 border-blue-500/20';
            default: return 'bg-surface-3 text-text-tertiary border-white/10';
        }
    };

    if (loading && !refreshing) {
        return (
            <div className="flex items-center justify-center h-full text-text-tertiary">
                <RefreshCw size={16} className="animate-spin mr-2" />
                <span>Cargando telemetría IDS...</span>
            </div>
        );
    }

    return (
        <section className="h-full flex flex-col bg-surface-1 overflow-hidden">
            {/* Insights Header */}
            {insights.length > 0 && (
                <div className="shrink-0 p-4 border-b border-white/[0.04] bg-surface-2/30">
                    <h3 className="text-[10px] uppercase tracking-widest font-bold text-accent-primary mb-3 flex items-center gap-2">
                        <Zap size={12} />
                        Recomendaciones Estructurales (Insights)
                    </h3>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                        {insights.map((insight, idx) => (
                            <motion.div
                                key={`${insight.type}-${idx}`}
                                initial={{ opacity: 0, y: 5 }}
                                animate={{ opacity: 1, y: 0 }}
                                className={`p-3 rounded-lg border flex flex-col gap-2 ${getPriorityColor(insight.priority)}`}
                            >
                                <div className="flex items-start justify-between gap-4">
                                    <span className="text-xs font-medium leading-tight">{insight.message}</span>
                                    <Shield size={14} className="shrink-0 mt-0.5 opacity-50" />
                                </div>
                                <div className="flex items-start gap-2 pt-1 border-t border-current/10">
                                    <ChevronRight size={12} className="shrink-0 mt-0.5 opacity-50" />
                                    <span className="text-[10px] font-semibold uppercase tracking-tight opacity-90">
                                        {insight.recommendation}
                                    </span>
                                </div>
                            </motion.div>
                        ))}
                    </div>
                </div>
            )}

            {/* Event List Header */}
            <div className="shrink-0 h-10 px-4 border-b border-white/[0.04] flex items-center justify-between">
                <div className="flex items-center gap-3">
                    <h3 className="text-[10px] uppercase tracking-widest font-bold text-text-secondary flex items-center gap-2">
                        <Activity size={12} />
                        Histórico de Acciones
                    </h3>
                    <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-surface-3 text-text-tertiary border border-white/5">
                        {events.length} eventos
                    </span>
                </div>
                <button
                    onClick={() => fetchData()}
                    className={`text-text-tertiary hover:text-text-primary transition-colors ${refreshing ? 'animate-spin' : ''}`}
                >
                    <RefreshCw size={14} />
                </button>
            </div>

            {/* Event Feed */}
            <div className="flex-1 overflow-y-auto px-4 py-2 custom-scrollbar">
                <div className="space-y-2 pb-8">
                    {events.length === 0 ? (
                        <div className="py-12 flex flex-col items-center justify-center text-text-tertiary opacity-40">
                            <BarChart3 size={32} strokeWidth={1.5} className="mb-2" />
                            <p className="text-xs italic">Esperando telemetría de agentes...</p>
                        </div>
                    ) : (
                        events.map((e, idx) => (
                            <motion.div
                                key={`${e.timestamp}-${e.agent_id}-${idx}`}
                                initial={{ opacity: 0, x: -4 }}
                                animate={{ opacity: 1, x: 0 }}
                                transition={{ delay: idx * 0.02 }}
                                className="group flex items-start gap-3 py-2 border-b border-white/[0.02] last:border-0"
                            >
                                <div className={`mt-1 shrink-0 ${getOutcomeColor(e.outcome)}`}>
                                    <AlertCircle size={14} fill="currentColor" fillOpacity={0.1} />
                                </div>
                                <div className="flex-1 min-w-0">
                                    <div className="flex items-center flex-wrap gap-x-3 gap-y-1 mb-0.5">
                                        <span className="text-[11px] font-mono text-text-primary/90">
                                            {e.agent_id}
                                        </span>
                                        <span className="text-[9px] px-1 rounded bg-white/[0.04] text-text-tertiary uppercase">
                                            {e.agent_role}
                                        </span>
                                        <span className={`text-[10px] font-semibold ${getOutcomeColor(e.outcome)} uppercase`}>
                                            {e.outcome}
                                        </span>
                                        <span className="ml-auto text-[9px] text-text-tertiary font-mono">
                                            {new Date(e.timestamp).toLocaleTimeString()}
                                        </span>
                                    </div>
                                    <div className="text-[11px] text-zinc-400 group-hover:text-zinc-200 transition-colors truncate">
                                        <span className="text-accent-primary opacity-60 mr-1.5">[{e.channel}]</span>
                                        {e.tool && <span className="text-amber-400/80 mr-1.5">{e.tool}:</span>}
                                        <span>{e.action || e.context || 'Agent performed action'}</span>
                                    </div>
                                    <div className="flex items-center gap-3 mt-1.5 opacity-0 group-hover:opacity-100 transition-opacity">
                                        {e.policy_decision && (
                                            <span className="text-[8px] flex items-center gap-1 text-text-tertiary italic">
                                                <Shield size={8} /> Decisión: {e.policy_decision}
                                            </span>
                                        )}
                                        {e.duration_ms && (
                                            <span className="text-[8px] flex items-center gap-1 text-text-tertiary italic">
                                                <Activity size={8} /> {e.duration_ms.toFixed(1)}ms
                                            </span>
                                        )}
                                        {e.cost_usd && e.cost_usd > 0 && (
                                            <span className="text-[8px] flex items-center gap-1 text-text-accent italic">
                                                ${e.cost_usd.toFixed(4)}
                                            </span>
                                        )}
                                    </div>
                                </div>
                            </motion.div>
                        ))
                    )}
                </div>
            </div>

            {/* Sticky Footnote */}
            <div className="shrink-0 p-3 bg-surface-2 border-t border-white/[0.04] flex items-center justify-between">
                <div className="flex items-center gap-2 text-text-tertiary">
                    <Info size={12} />
                    <span className="text-[9px] italic">Gobernanza IDS activa. Telemetría transmitida vía GICS.</span>
                </div>
                <div className="flex items-center gap-1.5">
                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
                    <span className="text-[9px] font-bold text-emerald-500/80 uppercase">Vivo</span>
                </div>
            </div>
        </section>
    );
};
