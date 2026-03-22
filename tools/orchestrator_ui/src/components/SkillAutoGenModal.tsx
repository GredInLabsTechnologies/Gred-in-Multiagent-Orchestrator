import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { X, Sparkles, Loader2, Brain, Zap, Shield, MessageCircle, Paintbrush, GraduationCap, Minus } from 'lucide-react';
import { API_BASE, AgentMood, Skill } from '../types';
import { fetchWithRetry } from '../lib/fetchWithRetry';

interface SkillAutoGenModalProps {
    isOpen: boolean;
    onClose: () => void;
    onSkillGenerated: (skill: Skill) => void;
}

const MOOD_OPTIONS: { value: AgentMood; label: string; icon: React.ReactNode; color: string }[] = [
    { value: 'neutral', label: 'Neutral', icon: <Minus size={14} />, color: 'text-gray-400' },
    { value: 'forensic', label: 'Forense', icon: <Brain size={14} />, color: 'text-blue-400' },
    { value: 'executor', label: 'Ejecutor', icon: <Zap size={14} />, color: 'text-amber-400' },
    { value: 'dialoger', label: 'Dialogador', icon: <MessageCircle size={14} />, color: 'text-emerald-400' },
    { value: 'creative', label: 'Creativo', icon: <Paintbrush size={14} />, color: 'text-purple-400' },
    { value: 'guardian', label: 'Guardián', icon: <Shield size={14} />, color: 'text-rose-400' },
    { value: 'mentor', label: 'Mentor', icon: <GraduationCap size={14} />, color: 'text-cyan-400' },
];

export const SkillAutoGenModal: React.FC<SkillAutoGenModalProps> = ({ isOpen, onClose, onSkillGenerated }) => {
    const [prompt, setPrompt] = useState('');
    const [nameHint, setNameHint] = useState('');
    const [mood, setMood] = useState<AgentMood>('neutral');
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');

    const handleGenerate = async () => {
        if (!prompt.trim() || prompt.length < 5) return;
        setLoading(true);
        setError('');
        try {
            const res = await fetchWithRetry(`${API_BASE}/ops/skills/generate-from-prompt`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify({
                    prompt: prompt.trim(),
                    name_hint: nameHint.trim() || undefined,
                    mood,
                    replace_graph: false,
                }),
            });
            if (!res.ok) {
                const data = await res.json().catch(() => ({ detail: 'Error desconocido' }));
                throw new Error(data.detail || `Error ${res.status}`);
            }
            const skill: Skill = await res.json();
            onSkillGenerated(skill);
            onClose();
            setPrompt('');
            setNameHint('');
            setMood('neutral');
        } catch (e: any) {
            setError(e.message || 'Error generando skill');
        } finally {
            setLoading(false);
        }
    };

    if (!isOpen) return null;

    return (
        <AnimatePresence>
            <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
                onClick={onClose}
            >
                <motion.div
                    initial={{ scale: 0.9, opacity: 0, y: 20 }}
                    animate={{ scale: 1, opacity: 1, y: 0 }}
                    exit={{ scale: 0.9, opacity: 0, y: 20 }}
                    className="w-[560px] max-h-[85vh] overflow-y-auto rounded-2xl border border-white/10 bg-surface-1 shadow-2xl"
                    onClick={e => e.stopPropagation()}
                >
                    {/* Header */}
                    <div className="flex items-center justify-between p-5 border-b border-white/5">
                        <div className="flex items-center gap-3">
                            <div className="p-2 rounded-xl bg-gradient-to-br from-violet-500/20 to-fuchsia-500/20">
                                <Sparkles size={18} className="text-violet-400" />
                            </div>
                            <div>
                                <h2 className="text-sm font-bold text-text-primary">Auto-Generar Skill con IA</h2>
                                <p className="text-[10px] text-text-tertiary mt-0.5">Describe lo que quieres y GIMO construye el grafo</p>
                            </div>
                        </div>
                        <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-white/5 text-text-tertiary">
                            <X size={16} />
                        </button>
                    </div>

                    {/* Body */}
                    <div className="p-5 space-y-4">
                        {/* Prompt */}
                        <div>
                            <label className="block text-[11px] font-bold text-text-secondary uppercase tracking-wider mb-2">
                                Describe tu skill en lenguaje natural
                            </label>
                            <textarea
                                value={prompt}
                                onChange={e => setPrompt(e.target.value)}
                                placeholder="Ejemplo: Quiero un skill que analice un repositorio de código, identifique archivos con deuda técnica, y genere un informe con recomendaciones priorizadas..."
                                className="w-full h-28 px-3 py-2.5 rounded-xl border border-white/10 bg-surface-2 text-sm text-text-primary placeholder:text-text-tertiary focus:outline-none focus:ring-1 focus:ring-violet-500/50 resize-none"
                                disabled={loading}
                            />
                            <p className="text-[10px] text-text-tertiary mt-1">
                                Mínimo 5 caracteres. Sé específico sobre los pasos que debe seguir el skill.
                            </p>
                        </div>

                        {/* Name hint */}
                        <div>
                            <label className="block text-[11px] font-bold text-text-secondary uppercase tracking-wider mb-2">
                                Nombre (opcional)
                            </label>
                            <input
                                value={nameHint}
                                onChange={e => setNameHint(e.target.value)}
                                placeholder="Análisis de Deuda Técnica"
                                className="w-full px-3 py-2 rounded-xl border border-white/10 bg-surface-2 text-sm text-text-primary placeholder:text-text-tertiary focus:outline-none focus:ring-1 focus:ring-violet-500/50"
                                disabled={loading}
                            />
                        </div>

                        {/* Mood selector */}
                        <div>
                            <label className="block text-[11px] font-bold text-text-secondary uppercase tracking-wider mb-2">
                                Mood del agente
                            </label>
                            <div className="grid grid-cols-4 gap-1.5">
                                {MOOD_OPTIONS.map(m => (
                                    <button
                                        key={m.value}
                                        onClick={() => setMood(m.value)}
                                        disabled={loading}
                                        className={`flex items-center gap-1.5 px-2.5 py-2 rounded-lg border text-[11px] font-medium transition-all ${mood === m.value
                                                ? 'border-violet-500/50 bg-violet-500/10 text-violet-300'
                                                : 'border-white/5 bg-surface-2 text-text-tertiary hover:border-white/10 hover:text-text-secondary'
                                            }`}
                                    >
                                        <span className={m.color}>{m.icon}</span>
                                        {m.label}
                                    </button>
                                ))}
                            </div>
                        </div>

                        {/* Error */}
                        {error && (
                            <div className="px-3 py-2 rounded-lg bg-rose-500/10 border border-rose-500/20 text-rose-400 text-[11px]">
                                {error}
                            </div>
                        )}
                    </div>

                    {/* Footer */}
                    <div className="flex justify-end gap-2 p-5 border-t border-white/5">
                        <button
                            onClick={onClose}
                            disabled={loading}
                            className="px-4 py-2 rounded-xl text-[11px] font-bold text-text-tertiary hover:text-text-secondary hover:bg-white/5 transition-colors"
                        >
                            Cancelar
                        </button>
                        <button
                            onClick={handleGenerate}
                            disabled={loading || prompt.length < 5}
                            className="flex items-center gap-2 px-5 py-2 rounded-xl text-[11px] font-bold bg-gradient-to-r from-violet-600 to-fuchsia-600 text-white hover:from-violet-500 hover:to-fuchsia-500 disabled:opacity-40 disabled:cursor-not-allowed transition-all shadow-lg shadow-violet-500/20"
                        >
                            {loading ? (
                                <>
                                    <Loader2 size={14} className="animate-spin" />
                                    Generando...
                                </>
                            ) : (
                                <>
                                    <Sparkles size={14} />
                                    Generar Skill
                                </>
                            )}
                        </button>
                    </div>
                </motion.div>
            </motion.div>
        </AnimatePresence>
    );
};
