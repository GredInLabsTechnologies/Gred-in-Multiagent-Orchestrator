import React, { useCallback, useEffect, useState } from 'react';
import { API_BASE, Skill, SkillTriggerResponse } from '../types';
import { useToast } from './Toast';
import {
    Zap, AlertCircle, RefreshCw,
    FileText, Plus, Play, Clock, Tag, ChevronRight,
    Loader2, X, Sparkles
} from 'lucide-react';

// ─── Helpers ─────────────────────────────────────────────────────────────────

const CATEGORY_META: Record<string, { color: string; bg: string }> = {
    security: { color: 'text-rose-400', bg: 'bg-rose-500/10 border-rose-500/20' },
    review: { color: 'text-amber-400', bg: 'bg-amber-500/10 border-amber-500/20' },
    quality: { color: 'text-emerald-400', bg: 'bg-emerald-500/10 border-emerald-500/20' },
    docs: { color: 'text-sky-400', bg: 'bg-sky-500/10 border-sky-500/20' },
    general: { color: 'text-violet-400', bg: 'bg-violet-500/10 border-violet-500/20' },
};

function categoryMeta(cat: string) {
    return CATEGORY_META[cat] ?? CATEGORY_META.general;
}

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

// ─── Sub-components ───────────────────────────────────────────────────────────

interface SkillCardProps {
    skill: Skill;
    onTrigger: (id: string) => void;
    triggering: boolean;
}

const SkillCard: React.FC<SkillCardProps> = ({ skill, onTrigger, triggering }) => {
    const meta = categoryMeta(skill.category);
    return (
        <div className={`group relative flex flex-col rounded-2xl border bg-[#111113] p-5 gap-3 transition-all duration-200 hover:border-white/20 hover:-translate-y-0.5 hover:shadow-lg hover:shadow-black/40 ${meta.bg}`}>
            {/* Icon + title */}
            <div className="flex items-start gap-3">
                <span className="text-2xl leading-none select-none">{skill.icon}</span>
                <div className="flex-1 min-w-0">
                    <h3 className="text-sm font-semibold text-[#f5f5f7] truncate">{skill.name}</h3>
                    <span className={`inline-block text-[10px] uppercase tracking-wider font-medium mt-0.5 ${meta.color}`}>
                        {skill.category}
                    </span>
                </div>
            </div>

            {/* Description */}
            <p className="text-xs text-[#86868b] leading-relaxed line-clamp-2">{skill.description}</p>

            {/* Tags */}
            {skill.tags.length > 0 && (
                <div className="flex flex-wrap gap-1">
                    {skill.tags.slice(0, 3).map(tag => (
                        <span key={tag} className="inline-flex items-center gap-0.5 text-[10px] px-1.5 py-0.5 rounded-md bg-white/5 text-[#86868b] border border-white/8">
                            <Tag size={8} />
                            {tag}
                        </span>
                    ))}
                </div>
            )}

            {/* Footer */}
            <div className="flex items-center justify-between mt-auto pt-2 border-t border-white/5">
                <div className="flex items-center gap-2 text-[10px] text-[#555]">
                    <Clock size={10} />
                    <span>{relativeTime(skill.last_run_at)}</span>
                    {skill.run_count > 0 && (
                        <span className="text-[#444]">· {skill.run_count}×</span>
                    )}
                </div>
                <button
                    onClick={() => onTrigger(skill.id)}
                    disabled={triggering}
                    className="flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-lg bg-white/8 hover:bg-white/15 text-[#f5f5f7] transition-colors disabled:opacity-50 disabled:cursor-not-allowed border border-white/10 hover:border-white/25"
                >
                    {triggering ? <Loader2 size={12} className="animate-spin" /> : <Play size={12} />}
                    Run
                </button>
            </div>
        </div>
    );
};

// ─── Create Skill Modal ───────────────────────────────────────────────────────

interface CreateModalProps {
    onClose: () => void;
    onCreate: (skill: Omit<Skill, 'id' | 'created_at' | 'updated_at' | 'run_count' | 'last_run_at'>) => Promise<void>;
}

const CreateModal: React.FC<CreateModalProps> = ({ onClose, onCreate }) => {
    const [name, setName] = useState('');
    const [icon, setIcon] = useState('⚡');
    const [description, setDescription] = useState('');
    const [category, setCategory] = useState('general');
    const [template, setTemplate] = useState('');
    const [loading, setLoading] = useState(false);

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!name.trim() || !template.trim()) return;
        setLoading(true);
        await onCreate({ name, icon, description, category, prompt_template: template, tags: [] });
        setLoading(false);
        onClose();
    };

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm">
            <div className="w-full max-w-lg bg-[#111113] rounded-2xl border border-white/10 shadow-2xl p-6">
                <div className="flex items-center justify-between mb-5">
                    <h2 className="text-sm font-bold text-[#f5f5f7] flex items-center gap-2">
                        <Sparkles size={16} className="text-violet-400" />
                        New Skill
                    </h2>
                    <button onClick={onClose} className="text-[#555] hover:text-[#f5f5f7] transition-colors"><X size={16} /></button>
                </div>
                <form onSubmit={handleSubmit} className="flex flex-col gap-3">
                    <div className="flex gap-2">
                        <input value={icon} onChange={e => setIcon(e.target.value)} maxLength={2}
                            className="w-12 text-center rounded-xl bg-white/5 border border-white/10 text-[#f5f5f7] text-lg p-2 focus:outline-none focus:border-violet-500" />
                        <input value={name} onChange={e => setName(e.target.value)} placeholder="Skill name" required
                            className="flex-1 rounded-xl bg-white/5 border border-white/10 text-[#f5f5f7] text-sm py-2 px-3 placeholder:text-[#555] focus:outline-none focus:border-violet-500" />
                    </div>
                    <input value={description} onChange={e => setDescription(e.target.value)} placeholder="Short description"
                        className="rounded-xl bg-white/5 border border-white/10 text-[#f5f5f7] text-sm py-2 px-3 placeholder:text-[#555] focus:outline-none focus:border-violet-500" />
                    <select value={category} onChange={e => setCategory(e.target.value)}
                        className="rounded-xl bg-white/5 border border-white/10 text-[#f5f5f7] text-sm py-2 px-3 focus:outline-none focus:border-violet-500">
                        {Object.keys(CATEGORY_META).map(c => <option key={c} value={c}>{c}</option>)}
                    </select>
                    <textarea value={template} onChange={e => setTemplate(e.target.value)} placeholder="Prompt template..." required rows={5}
                        className="rounded-xl bg-white/5 border border-white/10 text-[#f5f5f7] text-sm py-2 px-3 placeholder:text-[#555] focus:outline-none focus:border-violet-500 resize-none" />
                    <div className="flex justify-end gap-2 pt-1">
                        <button type="button" onClick={onClose} className="text-xs px-4 py-2 rounded-xl bg-white/5 hover:bg-white/10 text-[#86868b] border border-white/8 transition-colors">Cancel</button>
                        <button type="submit" disabled={loading}
                            className="text-xs px-4 py-2 rounded-xl bg-violet-600 hover:bg-violet-500 text-white font-medium transition-colors disabled:opacity-50 flex items-center gap-1.5">
                            {loading ? <Loader2 size={12} className="animate-spin" /> : <Plus size={12} />}
                            Create
                        </button>
                    </div>
                </form>
            </div>
        </div>
    );
};

// ─── Draft Created Toast Helper ───────────────────────────────────────────────

const DraftBadge: React.FC<{ draftId: string }> = ({ draftId }) => (
    <span className="inline-flex items-center gap-1 text-[10px] font-mono bg-amber-500/10 text-amber-400 border border-amber-500/20 px-1.5 py-0.5 rounded-md">
        <FileText size={9} />
        {draftId.slice(0, 18)}…
    </span>
);

// ─── Main Panel ───────────────────────────────────────────────────────────────

export const SkillsPanel: React.FC = () => {
    const { addToast } = useToast();
    const [skills, setSkills] = useState<Skill[]>([]);
    const [loading, setLoading] = useState(true);
    const [triggeringId, setTriggeringId] = useState<string | null>(null);
    const [showCreate, setShowCreate] = useState(false);
    const [filter, setFilter] = useState('all');

    const fetchSkills = useCallback(async () => {
        try {
            const res = await fetch(`${API_BASE}/ops/skills`, { credentials: 'include' });
            if (res.ok) setSkills(await res.json());
        } catch {
            addToast('Could not load skills.', 'error');
        } finally {
            setLoading(false);
        }
    }, [addToast]);

    useEffect(() => { fetchSkills(); }, [fetchSkills]);

    const handleTrigger = async (skillId: string) => {
        setTriggeringId(skillId);
        try {
            const res = await fetch(`${API_BASE}/ops/skills/${skillId}/trigger`, {
                method: 'POST',
                credentials: 'include',
            });
            if (res.ok) {
                const data: SkillTriggerResponse = await res.json();
                addToast(
                    <span className="flex flex-col gap-1">
                        <span className="font-semibold text-xs">Draft created — go approve it in Plans</span>
                        <DraftBadge draftId={data.draft_id} />
                    </span> as unknown as string,
                    'success'
                );
                fetchSkills(); // refresh run_count / last_run_at
            } else {
                addToast('Failed to trigger skill.', 'error');
            }
        } catch {
            addToast('Failed to trigger skill.', 'error');
        } finally {
            setTriggeringId(null);
        }
    };

    const handleCreate = async (payload: Omit<Skill, 'id' | 'created_at' | 'updated_at' | 'run_count' | 'last_run_at'>) => {
        const res = await fetch(`${API_BASE}/ops/skills`, {
            method: 'POST',
            credentials: 'include',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        if (res.ok) {
            addToast('Skill created!', 'success');
            fetchSkills();
        } else {
            addToast('Failed to create skill.', 'error');
        }
    };

    const categories = ['all', ...Array.from(new Set(skills.map(s => s.category)))];
    const filtered = filter === 'all' ? skills : skills.filter(s => s.category === filter);

    return (
        <div className="h-full overflow-y-auto custom-scrollbar bg-[#0a0a0a] p-6">
            {/* Header */}
            <div className="max-w-6xl mx-auto">
                <div className="flex items-center justify-between mb-6">
                    <div>
                        <h1 className="text-lg font-black text-[#f5f5f7] flex items-center gap-2">
                            <Zap size={20} className="text-violet-400" />
                            Skills Library
                        </h1>
                        <p className="text-xs text-[#555] mt-0.5">One-click automation templates. Trigger → Draft → Approve → Run.</p>
                    </div>
                    <div className="flex items-center gap-2">
                        <button
                            onClick={fetchSkills}
                            className="p-2 rounded-xl bg-white/5 hover:bg-white/10 text-[#86868b] hover:text-[#f5f5f7] border border-white/8 transition-colors"
                            title="Refresh"
                        >
                            <RefreshCw size={14} />
                        </button>
                        <button
                            onClick={() => setShowCreate(true)}
                            className="flex items-center gap-1.5 text-xs font-medium px-3 py-2 rounded-xl bg-violet-600 hover:bg-violet-500 text-white transition-colors"
                        >
                            <Plus size={14} />
                            New Skill
                        </button>
                    </div>
                </div>

                {/* Category filter tabs */}
                <div className="flex items-center gap-1.5 mb-5 overflow-x-auto pb-1 custom-scrollbar">
                    {categories.map(cat => {
                        const meta = cat === 'all' ? null : categoryMeta(cat);
                        return (
                            <button
                                key={cat}
                                onClick={() => setFilter(cat)}
                                className={`flex-shrink-0 text-[11px] font-medium px-3 py-1.5 rounded-lg border transition-colors capitalize ${filter === cat
                                    ? 'bg-white/12 border-white/20 text-[#f5f5f7]'
                                    : 'bg-transparent border-white/5 text-[#555] hover:text-[#86868b] hover:border-white/10'
                                    } ${meta ? meta.color : ''}`}
                            >
                                {cat}
                                <span className="ml-1.5 text-[9px] text-[#444]">
                                    {cat === 'all' ? skills.length : skills.filter(s => s.category === cat).length}
                                </span>
                            </button>
                        );
                    })}
                </div>

                {/* Grid */}
                {loading ? (
                    <div className="flex items-center justify-center h-48 text-[#555]">
                        <Loader2 size={24} className="animate-spin" />
                    </div>
                ) : filtered.length === 0 ? (
                    <div className="flex flex-col items-center justify-center h-48 gap-3 text-[#555] border border-dashed border-white/8 rounded-2xl">
                        <AlertCircle size={24} />
                        <p className="text-xs">No skills in this category.</p>
                        <button onClick={() => setShowCreate(true)} className="text-xs text-violet-400 hover:underline flex items-center gap-1">
                            <Plus size={12} /> Create one
                        </button>
                    </div>
                ) : (
                    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
                        {filtered.map(skill => (
                            <SkillCard
                                key={skill.id}
                                skill={skill}
                                onTrigger={handleTrigger}
                                triggering={triggeringId === skill.id}
                            />
                        ))}
                    </div>
                )}

                {/* Info callout */}
                <div className="mt-8 flex items-start gap-3 rounded-2xl border border-amber-500/15 bg-amber-500/5 p-4">
                    <ChevronRight size={14} className="text-amber-400 mt-0.5 flex-shrink-0" />
                    <p className="text-xs text-[#86868b] leading-relaxed">
                        Triggering a skill creates a <strong className="text-[#f5f5f7]">draft plan</strong> in the <strong className="text-[#f5f5f7]">Plans</strong> tab.
                        Review it there before approving execution — your Playground, your control.
                    </p>
                </div>
            </div>

            {showCreate && (
                <CreateModal onClose={() => setShowCreate(false)} onCreate={handleCreate} />
            )}
        </div>
    );
};
