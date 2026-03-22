import React, { useState } from 'react';
import { Sparkles, Loader2, Save, X, Brain, Zap, MessageCircle, Paintbrush, Shield, GraduationCap, Minus } from 'lucide-react';
import { API_BASE, AgentMood } from '../../types';
import { fetchWithRetry } from '../../lib/fetchWithRetry';
import { useToast } from '../Toast';

const MOOD_OPTIONS: { value: AgentMood; label: string; icon: React.ReactNode }[] = [
    { value: 'neutral', label: 'Neutral', icon: <Minus size={12} /> },
    { value: 'forensic', label: 'Forense', icon: <Brain size={12} /> },
    { value: 'executor', label: 'Ejecutor', icon: <Zap size={12} /> },
    { value: 'dialoger', label: 'Dialogador', icon: <MessageCircle size={12} /> },
    { value: 'creative', label: 'Creativo', icon: <Paintbrush size={12} /> },
    { value: 'guardian', label: 'Guardián', icon: <Shield size={12} /> },
    { value: 'mentor', label: 'Mentor', icon: <GraduationCap size={12} /> },
];

interface SkillCreateModalProps {
    onClose: () => void;
    nodesPayload: any[];
    edgesPayload: any[];
    onSuccess?: () => void;
}

export const SkillCreateModal: React.FC<SkillCreateModalProps> = ({ onClose, nodesPayload, edgesPayload, onSuccess }) => {
    const { addToast } = useToast();
    const [name, setName] = useState('');
    const [command, setCommand] = useState('');
    const [replaceGraph, setReplaceGraph] = useState(false);
    const [description, setDescription] = useState('');
    const [isGenerating, setIsGenerating] = useState(false);
    const [isSaving, setIsSaving] = useState(false);
    const [mood, setMood] = useState<AgentMood>('neutral');

    const handleGenerateDesc = async () => {
        setIsGenerating(true);
        try {
            const res = await fetchWithRetry(`${API_BASE}/ops/skills/generate-description`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name, command, nodes: nodesPayload, edges: edgesPayload }),
            });
            if (res.ok) {
                const data = await res.json();
                setDescription(data.description ?? '');
            } else {
                addToast('Error generando descripción', 'error');
            }
        } catch {
            addToast('Error de red', 'error');
        } finally {
            setIsGenerating(false);
        }
    };

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!name.trim() || !command.trim()) return;
        setIsSaving(true);
        try {
            const res = await fetchWithRetry(`${API_BASE}/ops/skills`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    name,
                    command: command.startsWith('/') ? command : `/${command}`,
                    description,
                    replace_graph: replaceGraph,
                    nodes: nodesPayload,
                    edges: edgesPayload,
                    mood
                }),
            });
            if (res.ok) {
                addToast('Skill guardada con éxito', 'success');
                if (onSuccess) onSuccess();
                onClose();
            } else {
                const data = await res.json().catch(() => null);
                addToast(data?.detail || 'Error guardando skill', 'error');
            }
        } catch {
            addToast('Error de red al guardar skill', 'error');
        } finally {
            setIsSaving(false);
        }
    };

    return (
        <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/70 backdrop-blur-sm">
            <div className="w-full max-w-lg bg-surface-0 rounded-2xl border border-white/10 shadow-2xl p-6">
                <div className="flex items-center justify-between mb-5">
                    <h2 className="text-sm font-bold text-text-primary flex items-center gap-2">
                        <Sparkles size={16} className="text-violet-400" />
                        Guardar como Skill
                    </h2>
                    <button onClick={onClose} className="text-text-tertiary hover:text-text-primary transition-colors"><X size={16} /></button>
                </div>
                <form onSubmit={handleSubmit} className="flex flex-col gap-4">
                    <div className="flex flex-col gap-1.5">
                        <label htmlFor="skill-name" className="text-[11px] font-medium text-text-secondary uppercase tracking-wider">Name</label>
                        <input id="skill-name" value={name} onChange={e => setName(e.target.value)} placeholder="E.g. Repo Explorer" required
                            className="rounded-xl bg-white/5 border border-white/10 text-text-primary text-sm py-2 px-3 placeholder:text-text-tertiary focus:outline-none focus:border-violet-500" />
                    </div>

                    <div className="flex flex-col gap-1.5">
                        <label htmlFor="skill-command" className="text-[11px] font-medium text-text-secondary uppercase tracking-wider">Comando (/slash_command)</label>
                        <input id="skill-command" value={command} onChange={e => {
                            let val = e.target.value.toLowerCase().replaceAll(/[^a-z0-9_/-]/g, '');
                            if (!val.startsWith('/')) val = '/' + val.replace(/^\//, '');
                            setCommand(val);
                        }} placeholder="/explorar" required pattern="^/[a-z0-9_-]{2,32}$"
                            className="rounded-xl bg-white/5 border border-white/10 text-text-primary text-sm py-2 px-3 placeholder:text-text-tertiary focus:outline-none focus:border-violet-500" />
                    </div>

                    <div className="flex flex-col gap-1.5">
                        <div className="flex items-center justify-between">
                            <label htmlFor="skill-desc" className="text-[11px] font-medium text-text-secondary uppercase tracking-wider">Descripción (opcional)</label>
                            <button type="button" onClick={handleGenerateDesc} disabled={isGenerating} className="text-[10px] text-violet-400 hover:text-violet-300 transition-colors flex items-center gap-1">
                                {isGenerating ? <Loader2 size={10} className="animate-spin" /> : <Sparkles size={10} />}
                                Generar IA
                            </button>
                        </div>
                        <textarea id="skill-desc" value={description} onChange={e => setDescription(e.target.value)} placeholder="Descripción generada u original..." rows={3}
                            className="rounded-xl bg-white/5 border border-white/10 text-text-primary text-sm py-2 px-3 placeholder:text-text-tertiary focus:outline-none focus:border-violet-500 resize-none" />
                    </div>

                    {/* Mood selector */}
                    <div className="flex flex-col gap-1.5">
                        <label className="text-[11px] font-medium text-text-secondary uppercase tracking-wider">Mood del Agente</label>
                        <div className="flex flex-wrap gap-1.5">
                            {MOOD_OPTIONS.map(m => (
                                <button
                                    key={m.value}
                                    type="button"
                                    onClick={() => setMood(m.value)}
                                    className={`flex items-center gap-1 px-2 py-1 rounded-lg border text-[10px] font-medium transition-all ${mood === m.value
                                            ? 'border-violet-500/50 bg-violet-500/10 text-violet-300'
                                            : 'border-white/5 bg-white/5 text-text-tertiary hover:border-white/10'
                                        }`}
                                >
                                    {m.icon} {m.label}
                                </button>
                            ))}
                        </div>
                    </div>

                    <label className="flex items-center gap-2 cursor-pointer mt-1">
                        <input type="checkbox" checked={replaceGraph} onChange={e => setReplaceGraph(e.target.checked)} className="rounded border-white/20 bg-white/5 accent-violet-500 focus:ring-violet-500" />
                        <span className="text-xs text-text-secondary">Reemplazar grafo actual al ejecutar (replace_graph)</span>
                    </label>

                    <div className="flex justify-end gap-2 pt-2 mt-2 border-t border-white/5">
                        <button type="button" onClick={onClose} className="text-xs px-4 py-2 rounded-xl bg-white/5 hover:bg-white/10 text-text-secondary border border-white/8 transition-colors">Cancel</button>
                        <button type="submit" disabled={isSaving || !name || !command || command.length < 3}
                            className="text-xs px-4 py-2 rounded-xl bg-violet-600 hover:bg-violet-500 text-white font-medium transition-colors disabled:opacity-50 flex items-center gap-1.5">
                            {isSaving ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />}
                            Guardar Skill
                        </button>
                    </div>
                </form>
            </div>
        </div>
    );
};
