import React, { useCallback, useEffect, useState } from 'react';
import {
    Zap, RefreshCw, Play, Clock, Loader2, Download, Trash2,
    Code2, ShoppingBag, User, Brain, MessageCircle,
    Paintbrush, Shield, GraduationCap, Minus, BarChart3, History, Globe, Sparkles
} from 'lucide-react';
import { API_BASE, Skill, SkillExecuteResponse, AgentMood, SkillAnalytics } from '../types';
import { fetchWithRetry } from '../lib/fetchWithRetry';
import { useToast } from './Toast';
import { SkillAutoGenModal } from './SkillAutoGenModal';

// ─── Helpers ─────────────────────────────────────────────────────────────────

function relativeTime(iso?: string | null): string {
    if (!iso) return 'Never';
    const diff = Date.now() - new Date(iso).getTime();
    const m = Math.floor(diff / 60000);
    if (m < 1) return 'Just now';
    if (m < 60) return `${m}m ago`;
    const h = Math.floor(m / 60);
    if (h < 24) return `${h}h ago`;
    return `${Math.floor(h / 24)}d ago`;
}

const MOOD_ICONS: Record<AgentMood, React.ReactNode> = {
    neutral: <Minus size={10} />,
    forensic: <Brain size={10} />,
    executor: <Zap size={10} />,
    dialoger: <MessageCircle size={10} />,
    creative: <Paintbrush size={10} />,
    guardian: <Shield size={10} />,
    mentor: <GraduationCap size={10} />,
};

const MOOD_COLORS: Record<AgentMood, string> = {
    neutral: 'text-gray-400 bg-gray-400/10 border-gray-400/20',
    forensic: 'text-blue-400 bg-blue-400/10 border-blue-400/20',
    executor: 'text-amber-400 bg-amber-400/10 border-amber-400/20',
    dialoger: 'text-emerald-400 bg-emerald-400/10 border-emerald-400/20',
    creative: 'text-purple-400 bg-purple-400/10 border-purple-400/20',
    guardian: 'text-rose-400 bg-rose-400/10 border-rose-400/20',
    mentor: 'text-cyan-400 bg-cyan-400/10 border-cyan-400/20',
};

// ─── Sub-components ───────────────────────────────────────────────────────────

interface SkillCardProps {
    skill: Skill;
    onExecute: (id: string, replaceGraph: boolean) => void;
    onLoadToGraph: (skill: Skill) => void;
    onDelete: (id: string) => void;
    onPublish?: (id: string) => void;
    executing: boolean;
    deleting: boolean;
    isMarketplace?: boolean;
    compact?: boolean;
}

const SkillCard: React.FC<SkillCardProps> = ({
    skill, onExecute, onLoadToGraph, onDelete, onPublish, executing, deleting, isMarketplace, compact
}) => {
    const [analytics, setAnalytics] = useState<SkillAnalytics | null>(null);

    useEffect(() => {
        if (!isMarketplace) {
            fetchWithRetry(`${API_BASE}/ops/skills/${skill.id}/analytics`, { credentials: 'include' })
                .then(res => res.json())
                .then(setAnalytics)
                .catch(() => { });
        }
    }, [skill.id, isMarketplace]);

    return (
        <div className={`group relative flex flex-col rounded-2xl border bg-surface-0 ${compact ? 'p-3 gap-2' : 'p-5 gap-3'} transition-all duration-200 hover:border-white/20 hover:-translate-y-0.5 hover:shadow-lg hover:shadow-black/40`}>
            {/* Version & Mood Badges */}
            <div className={`absolute top-3 right-3 flex gap-1.5 ${compact ? 'scale-90' : ''} opacity-0 group-hover:opacity-100 transition-opacity`}>
                <div className={`flex items-center gap-1 px-1.5 py-0.5 rounded-md border text-[9px] font-bold uppercase tracking-tighter ${MOOD_COLORS[skill.mood || 'neutral']}`}>
                    {MOOD_ICONS[skill.mood || 'neutral']}
                    {!compact && (skill.mood || 'neutral')}
                </div>
                <div className="px-1.5 py-0.5 rounded-md border border-white/10 bg-white/5 text-text-tertiary text-[9px] font-mono">
                    v{skill.version || 1}
                </div>
            </div>

            {/* Header */}
            <div className="flex items-start justify-between gap-3">
                <div className="flex-1 min-w-0">
                    <h3 className={`${compact ? 'text-[11px]' : 'text-sm'} font-semibold text-text-primary truncate flex items-center gap-2`}>
                        <Zap size={compact ? 12 : 16} className={isMarketplace ? "text-amber-400" : "text-violet-400"} />
                        {skill.name}
                    </h3>
                    {!compact && (
                        <div className="flex items-center gap-2 mt-1">
                            <span className="text-[10px] font-mono text-text-tertiary">
                                {skill.command}
                            </span>
                            {skill.author && (
                                <span className="flex items-center gap-1 text-[9px] text-text-tertiary">
                                    <User size={8} /> {skill.author}
                                </span>
                            )}
                        </div>
                    )}
                </div>
            </div>

            {/* Description */}
            <p className={`text-text-secondary leading-relaxed line-clamp-2 ${compact ? 'text-[10px] min-h-[28px]' : 'text-xs min-h-[32px]'}`}>
                {skill.description || "Sin descripción"}
            </p>

            {/* Analytics/Stats */}
            <div className={`flex items-center justify-between text-text-tertiary mt-auto pt-2 border-t border-white/5 ${compact ? 'text-[9px]' : 'text-[10px]'}`}>
                <div className="flex items-center gap-3">
                    <span className="flex items-center gap-1" title="Última actualización">
                        <Clock size={compact ? 8 : 10} />
                        {relativeTime(skill.updated_at)}
                    </span>
                    {!compact && (
                        <span className="flex items-center gap-1" title="Nodos del grafo">
                            <Code2 size={10} />
                            {skill.nodes?.length || 0}
                        </span>
                    )}
                </div>
                {analytics && analytics.total_runs > 0 && (
                    <div className="flex items-center gap-2 text-emerald-400/70 font-medium">
                        <BarChart3 size={compact ? 8 : 10} />
                        {analytics.success_rate * 100}% OK
                    </div>
                )}
            </div>

            {/* Actions */}
            <div className="flex items-center justify-between mt-2 pt-2">
                <div className="flex items-center gap-1">
                    {!isMarketplace && (
                        <>
                            <button
                                onClick={() => onDelete(skill.id)}
                                disabled={deleting}
                                className="p-1.5 rounded-lg text-text-tertiary hover:text-rose-400 hover:bg-rose-500/10 transition-colors disabled:opacity-50"
                                title="Eliminar"
                            >
                                {deleting ? <Loader2 size={compact ? 12 : 14} className="animate-spin" /> : <Trash2 size={compact ? 12 : 14} />}
                            </button>
                            {!compact && !skill.published && onPublish && (
                                <button
                                    onClick={() => onPublish(skill.id)}
                                    className="p-1.5 rounded-lg text-text-tertiary hover:text-amber-400 hover:bg-amber-500/10 transition-colors"
                                    title="Publicar en Marketplace"
                                >
                                    <Globe size={14} />
                                </button>
                            )}
                        </>
                    )}
                </div>
                <div className="flex items-center gap-1.5">
                    <button
                        onClick={() => onLoadToGraph(skill)}
                        className={`flex items-center gap-1 font-medium rounded-lg bg-white/5 hover:bg-white/10 text-text-secondary hover:text-text-primary transition-colors border border-white/10 ${compact ? 'text-[9px] px-2 py-1' : 'text-[11px] px-2.5 py-1.5'}`}
                    >
                        {isMarketplace ? <Download size={compact ? 10 : 12} /> : <History size={compact ? 10 : 12} />}
                        {isMarketplace ? 'Instalar' : 'Cargar'}
                    </button>
                    {!isMarketplace && (
                        <button
                            onClick={() => onExecute(skill.id, skill.replace_graph)}
                            disabled={executing}
                            className={`flex items-center gap-1 font-medium rounded-lg bg-violet-500/10 hover:bg-violet-500/20 text-violet-400 transition-colors disabled:opacity-50 border border-violet-500/20 ${compact ? 'text-[9px] px-2 py-1' : 'text-[11px] px-2.5 py-1.5'}`}
                        >
                            {executing ? <Loader2 size={compact ? 10 : 12} className="animate-spin" /> : <Play size={compact ? 10 : 12} />}
                            Run
                        </button>
                    )}
                </div>
            </div>
        </div>
    );
};

// ─── Shared Content Logic ─────────────────────────────────────────────────────────

type Tab = 'my-skills' | 'marketplace';

interface SkillsContentProps {
    compact?: boolean;
}

export const SkillsContent: React.FC<SkillsContentProps> = ({ compact }) => {
    const { addToast } = useToast();
    const [skills, setSkills] = useState<Skill[]>([]);
    const [marketplace, setMarketplace] = useState<Skill[]>([]);
    const [tab, setTab] = useState<Tab>('my-skills');
    const [loading, setLoading] = useState(true);
    const [executingId, setExecutingId] = useState<string | null>(null);
    const [deletingId, setDeletingId] = useState<string | null>(null);
    const [isAutoGenOpen, setIsAutoGenOpen] = useState(false);

    const fetchSkills = useCallback(async () => {
        try {
            const endpoint = tab === 'my-skills' ? '/ops/skills' : '/ops/skills/marketplace';
            const res = await fetchWithRetry(`${API_BASE}${endpoint}`, { credentials: 'include' });
            if (res.ok) {
                const data = await res.json();
                if (tab === 'my-skills') setSkills(data);
                else setMarketplace(data);
            }
        } catch {
            addToast('Error al cargar skills.', 'error');
        } finally {
            setLoading(false);
        }
    }, [addToast, tab]);

    useEffect(() => { fetchSkills(); }, [fetchSkills]);

    const handleExecute = async (skillId: string, replaceGraph: boolean) => {
        setExecutingId(skillId);
        try {
            const res = await fetchWithRetry(`${API_BASE}/ops/skills/${skillId}/execute`, {
                method: 'POST',
                credentials: 'include',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ replace_graph: replaceGraph, context: {} }),
            });
            if (res.ok) {
                const data: SkillExecuteResponse = await res.json();
                addToast(`Skill iniciada: ${data.skill_run_id}`, 'success');
            }
        } catch {
            addToast('Error al ejecutar skill.', 'error');
        } finally {
            setExecutingId(null);
        }
    };

    const handleDelete = async (skillId: string) => {
        if (!globalThis.confirm('¿Seguro de que quieres eliminar esta skill?')) return;
        setDeletingId(skillId);
        try {
            const res = await fetchWithRetry(`${API_BASE}/ops/skills/${skillId}`, {
                method: 'DELETE',
                credentials: 'include',
            });
            if (res.ok) {
                addToast('Skill eliminada', 'success');
                fetchSkills();
            }
        } catch {
            addToast('Error al eliminar.', 'error');
        } finally {
            setDeletingId(null);
        }
    };

    const handlePublish = async (skillId: string) => {
        try {
            const res = await fetchWithRetry(`${API_BASE}/ops/skills/${skillId}/publish`, {
                method: 'POST',
                credentials: 'include',
            });
            if (res.ok) {
                addToast('Skill publicada en el Marketplace', 'success');
                fetchSkills();
            }
        } catch {
            addToast('Error al publicar.', 'error');
        }
    };

    const handleInstall = async (skill: Skill) => {
        try {
            const res = await fetchWithRetry(`${API_BASE}/ops/skills/marketplace/${skill.id}/install`, {
                method: 'POST',
                credentials: 'include',
            });
            if (res.ok) {
                addToast('Skill instalada correctamente', 'success');
                setTab('my-skills');
            } else if (res.status === 409) {
                addToast('Ya tienes una skill con el mismo comando', 'info');
            }
        } catch {
            addToast('Error al instalar.', 'error');
        }
    };

    const handleLoadToGraph = (skill: Skill) => {
        if (tab === 'marketplace') {
            handleInstall(skill);
            return;
        }
        const event = new CustomEvent('ops:load_skill_to_graph', { detail: skill });
        globalThis.dispatchEvent(event);
        addToast(`${skill.name} cargada al editor visual.`, 'info');
    };

    const renderEmptyState = () => (
        <div className="flex flex-col items-center justify-center p-8 gap-3 text-text-tertiary border border-dashed border-white/8 rounded-2xl">
            <ShoppingBag size={24} className="text-white/20" />
            <p className="text-[11px] text-center">
                {tab === 'my-skills'
                    ? "No tienes skills aún."
                    : "Marketplace vacío."}
            </p>
        </div>
    );

    const renderList = () => {
        if (loading) return (
            <div className="flex items-center justify-center py-12 text-text-tertiary">
                <Loader2 size={24} className="animate-spin" />
            </div>
        );

        const list = tab === 'my-skills' ? skills : marketplace;
        if (list.length === 0) return renderEmptyState();

        return (
            <div className={`grid gap-4 ${compact ? 'grid-cols-1' : 'grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4'}`}>
                {list.map(skill => (
                    <SkillCard
                        key={skill.id}
                        skill={skill}
                        onExecute={handleExecute}
                        onLoadToGraph={handleLoadToGraph}
                        onDelete={handleDelete}
                        onPublish={handlePublish}
                        executing={executingId === skill.id}
                        deleting={deletingId === skill.id}
                        isMarketplace={tab === 'marketplace'}
                        compact={compact}
                    />
                ))}
            </div>
        );
    };

    return (
        <div className="flex flex-col flex-1 min-h-0">
            {/* Toolbar */}
            <div className="flex items-center justify-between gap-3 mb-4">
                <div className="flex p-1 rounded-xl bg-surface-1 border border-white/5">
                    <button
                        onClick={() => { setTab('my-skills'); setLoading(true); }}
                        className={`flex items-center gap-1.5 px-3 py-1 rounded-lg text-[10px] font-bold transition-all ${tab === 'my-skills' ? 'bg-white/5 text-text-primary shadow-sm' : 'text-text-tertiary hover:text-text-secondary'}`}
                    >
                        <User size={12} /> Mis Skills
                    </button>
                    <button
                        onClick={() => { setTab('marketplace'); setLoading(true); }}
                        className={`flex items-center gap-1.5 px-3 py-1 rounded-lg text-[10px] font-bold transition-all ${tab === 'marketplace' ? 'bg-white/5 text-text-primary shadow-sm' : 'text-text-tertiary hover:text-text-secondary'}`}
                    >
                        <ShoppingBag size={12} /> {compact ? 'Market' : 'Marketplace'}
                    </button>
                </div>

                <div className="flex items-center gap-2">
                    {!compact && (
                        <button
                            onClick={() => setIsAutoGenOpen(true)}
                            className="flex items-center gap-2 px-3 py-1.5 rounded-xl bg-gradient-to-r from-violet-600 to-fuchsia-600 text-white text-[10px] font-bold shadow-lg shadow-violet-500/10 hover:shadow-violet-500/20 transition-all active:scale-95"
                        >
                            <Sparkles size={12} />
                            Autogenerar
                        </button>
                    )}
                    <button
                        onClick={fetchSkills}
                        className="p-1.5 rounded-lg bg-white/5 hover:bg-white/10 text-text-secondary border border-white/8 transition-colors"
                    >
                        <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
                    </button>
                </div>
            </div>

            {/* Content Area */}
            <div className="flex-1 overflow-y-auto custom-scrollbar">
                {renderList()}
            </div>

            <SkillAutoGenModal
                isOpen={isAutoGenOpen}
                onClose={() => setIsAutoGenOpen(false)}
                onSkillGenerated={(s) => {
                    setSkills(prev => [s, ...prev]);
                    setTab('my-skills');
                    addToast(`Skill "${s.name}" generada con éxito`, 'success');
                }}
            />
        </div>
    );
};
