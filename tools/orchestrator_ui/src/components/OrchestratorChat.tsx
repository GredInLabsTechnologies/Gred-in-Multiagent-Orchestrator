import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { motion, AnimatePresence } from 'framer-motion';
import { Check, Loader2, Send, Sparkles, X, RefreshCw, AlertTriangle, ChevronDown, Activity, Bot, User, MessageSquare, Wrench, ShieldAlert } from 'lucide-react';
import { API_BASE, ChatExecutionStep, ChatExecutionStepStatus, OpsApproveResponse, OpsDraft, Skill, SkillExecuteResponse } from '../types';
import { fetchWithRetry } from '../lib/fetchWithRetry';
import { useToast } from './Toast';
import { AgentActionApproval, ActionDraftUi } from './AgentActionApproval';

type ComposerMode = 'generate' | 'draft' | 'agentic';
type DraftViewTab = 'pending' | 'approved' | 'rejected_error' | 'all';

interface AgenticToolCall {
    tool_call_id: string;
    tool_name: string;
    arguments: Record<string, unknown>;
    status: string;
    risk: string;
    duration?: number;
    message?: string;
}

// P2: Conversational Planning Interfaces
interface UserQuestion {
    question: string;
    options?: string[];
    context?: string;
}

interface PlanTask {
    id: string;
    title: string;
    description: string;
    depends_on?: string[];
    agent_mood: string;
    agent_rationale: string;
    model?: string;
}

interface ProposedPlan {
    title: string;
    objective: string;
    tasks: PlanTask[];
}

interface ThreadSummary {
    id: string;
    title: string;
    created_at?: string;
    turns?: unknown[];
}

interface ChatMessage {
    id: string;
    role: 'user' | 'assistant' | 'system';
    text: string;
    ts: string;
    draftId?: string;
    approvedId?: string;
    runId?: string;
    detectedIntent?: string;
    decisionPath?: string;
    executionDecision?: string;
    decisionReason?: string;
    riskScore?: number;
    errorActionable?: string;
    executionSteps?: ChatExecutionStep[];
    failed?: boolean;
    failedPrompt?: string;
    approvalDraft?: ActionDraftUi;
}

const getMessageStyle = (role: string, failed?: boolean) => {
    if (role === 'user') return 'bg-accent-primary/8 border-accent-primary/15 ml-12 rounded-br-lg';
    if (role === 'assistant') return 'bg-surface-2/70 border-white/[0.04] mr-12 rounded-bl-lg';
    if (failed) return 'bg-red-500/8 border-red-500/20';
    return 'bg-surface-2/40 border-white/[0.03]';
};

const getRoleTextStyle = (role: string, failed?: boolean) => {
    if (role === 'user') return 'text-accent-primary/60';
    if (failed) return 'text-red-400/60';
    return 'text-text-tertiary';
};

const getRoleLabel = (role: string) => {
    if (role === 'user') return 'Tu';
    if (role === 'assistant') return 'GIMO';
    return 'Sistema';
};

const getRoleAvatar = (role: string) => {
    if (role === 'user') return <User size={12} />;
    return <Bot size={12} />;
};

const getStepStyle = (status: string) => {
    if (status === 'done') return 'border-emerald-500/20 bg-emerald-500/5 text-emerald-400';
    if (status === 'error') return 'border-red-500/20 bg-red-500/5 text-red-400';
    return 'border-white/[0.04] bg-surface-3/30 text-text-secondary';
};

const buildDraftSteps = (
    draft: OpsDraft,
    extras?: Partial<Pick<ChatMessage, 'approvedId' | 'runId'>>,
): ChatExecutionStep[] => {
    const intentDetected = Boolean(draft.context?.detected_intent);
    const hasError = draft.status === 'error';
    const hasApproval = Boolean(extras?.approvedId);
    const hasRun = Boolean(extras?.runId);
    let runStatusKey: ChatExecutionStepStatus = 'pending';
    let runDetail = undefined;
    if (hasError) {
        runStatusKey = 'error';
        runDetail = draft.error || draft.context?.error_actionable;
    } else if (hasRun) {
        runStatusKey = 'done';
        runDetail = 'pending';
    }

    return [
        { key: 'intent_detected', label: 'Intencion detectada', status: intentDetected ? 'done' : 'pending', detail: draft.context?.detected_intent },
        { key: 'draft_created', label: 'Draft creado', status: hasError ? 'error' : 'done', detail: hasError ? (draft.error || 'No se pudo crear el draft') : draft.id },
        { key: 'approved', label: 'Draft aprobado', status: hasApproval ? 'done' : 'pending', detail: extras?.approvedId },
        { key: 'run_created', label: 'Run creado', status: hasRun ? 'done' : 'pending', detail: extras?.runId },
        { key: 'run_status', label: 'Estado de run', status: runStatusKey, detail: runDetail },
    ];
};

interface OrchestratorChatProps {
    isCollapsed?: boolean;
    providerConnected?: boolean;
    onPlanGenerated?: (planId: string) => void;
    onNavigateToSettings?: () => void;
    onSendToTerminal?: (payload: { text: string; ts: string; source: 'chat' }) => void;
    onViewInFlow?: (agentId?: string) => void;
    inboundTerminalSummary?: { id: string; text: string; ts: string } | null;
}

/* ── Timestamp formatter ── */
function formatTime(iso: string) {
    const d = new Date(iso);
    const now = new Date();
    const diffMs = now.getTime() - d.getTime();
    const diffMin = Math.floor(diffMs / 60000);
    if (diffMin < 1) return 'ahora';
    if (diffMin < 60) return `hace ${diffMin}m`;
    if (d.toDateString() === now.toDateString()) return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    return d.toLocaleDateString([], { day: 'numeric', month: 'short' }) + ' ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

/* ── Message animation ── */
const msgVariants = {
    hidden: { opacity: 0, y: 12, scale: 0.97 },
    visible: { opacity: 1, y: 0, scale: 1 },
};

// ── P2: Mood Indicator Component ──────────────────────────────────────────────

const MoodIndicator: React.FC<{ mood: string }> = ({ mood }) => {
    const moodConfig: Record<string, { color: string; emoji: string; label: string }> = {
        neutral: { color: 'text-gray-400', emoji: '🤖', label: 'Neutral' },
        forensic: { color: 'text-blue-400', emoji: '🔍', label: 'Investigando' },
        executor: { color: 'text-green-400', emoji: '⚙️', label: 'Ejecutando' },
        dialoger: { color: 'text-cyan-400', emoji: '💬', label: 'Conversando' },
        creative: { color: 'text-magenta-400', emoji: '✨', label: 'Creativo' },
        guardian: { color: 'text-red-400', emoji: '🛡️', label: 'Cauteloso' },
        mentor: { color: 'text-yellow-400', emoji: '🎯', label: 'Enseñando' },
    };

    const config = moodConfig[mood] || moodConfig.neutral;

    return (
        <div className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-surface-2/40 border border-white/[0.06] text-[10px] ${config.color}`}>
            <span>{config.emoji}</span>
            <span className="uppercase tracking-wider">{config.label}</span>
        </div>
    );
};

// ── P2: Plan Review Component ─────────────────────────────────────────────────

interface PlanReviewProps {
    plan: ProposedPlan;
    onApprove: () => void;
    onReject: (feedback: string) => void;
    onModify: () => void;
    isProcessing: boolean;
}

const PlanReview: React.FC<PlanReviewProps> = ({ plan, onApprove, onReject, onModify, isProcessing }) => {
    const [feedback, setFeedback] = useState('');
    const [showRejectInput, setShowRejectInput] = useState(false);

    const moodEmojis: Record<string, string> = {
        forensic: '🔍',
        executor: '⚙️',
        dialoger: '💬',
        creative: '✨',
        guardian: '🛡️',
        mentor: '🎯',
        neutral: '🤖',
    };

    return (
        <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            className="rounded-xl border border-magenta-500/30 bg-gradient-to-br from-magenta-500/10 to-purple-500/5 p-4 space-y-3"
        >
            {/* Header */}
            <div className="flex items-start justify-between">
                <div>
                    <div className="text-xs uppercase tracking-wider text-magenta-400 font-bold flex items-center gap-1.5">
                        📋 Plan Propuesto
                    </div>
                    <h3 className="text-lg font-bold text-text-primary mt-1">{plan.title}</h3>
                    <p className="text-sm text-text-secondary mt-0.5">{plan.objective}</p>
                </div>
            </div>

            {/* Tasks */}
            <div className="space-y-2 max-h-80 overflow-y-auto custom-scrollbar">
                {plan.tasks.map((task, idx) => {
                    const moodEmoji = moodEmojis[task.agent_mood] || '🤖';
                    const depends = task.depends_on || [];

                    return (
                        <div
                            key={task.id}
                            className="rounded-lg border border-white/[0.06] bg-surface-2/40 p-3 space-y-1.5"
                        >
                            <div className="flex items-start justify-between">
                                <div className="flex items-center gap-2">
                                    <span className="text-lg">{moodEmoji}</span>
                                    <div>
                                        <div className="text-sm font-semibold text-text-primary">{task.title}</div>
                                        <div className="text-[10px] text-text-tertiary">
                                            Mood: <span className="text-accent-primary">{task.agent_mood}</span>
                                            {task.model && task.model !== 'auto' && ` · Modelo: ${task.model}`}
                                        </div>
                                    </div>
                                </div>
                                <span className="text-[10px] text-text-tertiary">#{idx + 1}</span>
                            </div>

                            {task.description && (
                                <p className="text-xs text-text-secondary pl-8">{task.description}</p>
                            )}

                            {task.agent_rationale && (
                                <div className="pl-8 mt-1">
                                    <div className="text-[10px] text-text-tertiary italic">
                                        💡 {task.agent_rationale}
                                    </div>
                                </div>
                            )}

                            {depends.length > 0 && (
                                <div className="pl-8 mt-1 text-[10px] text-text-tertiary">
                                    Depende de: {depends.join(', ')}
                                </div>
                            )}
                        </div>
                    );
                })}
            </div>

            {/* Actions */}
            <div className="pt-2 border-t border-white/[0.06] flex items-center gap-2">
                {!showRejectInput ? (
                    <>
                        <button
                            onClick={onApprove}
                            disabled={isProcessing}
                            className="flex-1 px-3 py-2 rounded-lg bg-emerald-500/20 hover:bg-emerald-500/30 border border-emerald-500/30 text-emerald-400 text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                        >
                            {isProcessing ? <Loader2 size={14} className="inline animate-spin mr-1" /> : <Check size={14} className="inline mr-1" />}
                            Aprobar y Ejecutar
                        </button>
                        <button
                            onClick={() => setShowRejectInput(true)}
                            disabled={isProcessing}
                            className="px-3 py-2 rounded-lg bg-red-500/20 hover:bg-red-500/30 border border-red-500/30 text-red-400 text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                        >
                            <X size={14} className="inline mr-1" />
                            Rechazar
                        </button>
                        <button
                            onClick={onModify}
                            disabled={isProcessing}
                            className="px-3 py-2 rounded-lg bg-amber-500/20 hover:bg-amber-500/30 border border-amber-500/30 text-amber-400 text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                            title="Modificar (próximamente)"
                        >
                            <RefreshCw size={14} />
                        </button>
                    </>
                ) : (
                    <div className="flex-1 flex items-center gap-2">
                        <input
                            type="text"
                            value={feedback}
                            onChange={(e) => setFeedback(e.target.value)}
                            placeholder="Razón del rechazo (opcional)..."
                            className="flex-1 px-3 py-2 rounded-lg bg-surface-3/50 border border-white/[0.06] text-sm text-text-primary placeholder:text-text-tertiary outline-none focus:border-accent-primary/50"
                            autoFocus
                        />
                        <button
                            onClick={() => {
                                onReject(feedback);
                                setShowRejectInput(false);
                                setFeedback('');
                            }}
                            className="px-3 py-2 rounded-lg bg-red-500/20 border border-red-500/30 text-red-400 text-sm font-medium"
                        >
                            Confirmar
                        </button>
                        <button
                            onClick={() => {
                                setShowRejectInput(false);
                                setFeedback('');
                            }}
                            className="px-3 py-2 rounded-lg bg-surface-2/40 border border-white/[0.06] text-text-secondary text-sm"
                        >
                            Cancelar
                        </button>
                    </div>
                )}
            </div>
        </motion.div>
    );
};

// ── P2: User Question Component ───────────────────────────────────────────────

interface UserQuestionProps {
    question: UserQuestion;
    onAnswer: (answer: string) => void;
}

const UserQuestionPrompt: React.FC<UserQuestionProps> = ({ question, onAnswer }) => {
    const [customAnswer, setCustomAnswer] = useState('');

    return (
        <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            className="rounded-xl border border-cyan-500/30 bg-gradient-to-br from-cyan-500/10 to-blue-500/5 p-4 space-y-3"
        >
            <div className="flex items-start gap-3">
                <div className="text-2xl">❓</div>
                <div className="flex-1">
                    <div className="text-xs uppercase tracking-wider text-cyan-400 font-bold">
                        Pregunta del Agente
                    </div>
                    <p className="text-sm font-semibold text-text-primary mt-1">{question.question}</p>
                    {question.context && (
                        <p className="text-xs text-text-tertiary mt-1 italic">{question.context}</p>
                    )}
                </div>
            </div>

            {/* Options */}
            {question.options && question.options.length > 0 ? (
                <div className="space-y-2">
                    <div className="text-[10px] uppercase tracking-wider text-text-tertiary">Opciones sugeridas:</div>
                    <div className="grid grid-cols-2 gap-2">
                        {question.options.map((opt, idx) => (
                            <button
                                key={idx}
                                onClick={() => onAnswer(opt)}
                                className="px-3 py-2 rounded-lg bg-surface-2/60 hover:bg-accent-primary/20 border border-white/[0.06] hover:border-accent-primary/30 text-sm text-text-primary transition-all text-left"
                            >
                                {opt}
                            </button>
                        ))}
                    </div>
                    <div className="text-[10px] text-text-tertiary text-center">O escribe tu respuesta:</div>
                </div>
            ) : null}

            {/* Custom answer */}
            <div className="flex items-center gap-2">
                <input
                    type="text"
                    value={customAnswer}
                    onChange={(e) => setCustomAnswer(e.target.value)}
                    onKeyDown={(e) => {
                        if (e.key === 'Enter' && customAnswer.trim()) {
                            onAnswer(customAnswer);
                            setCustomAnswer('');
                        }
                    }}
                    placeholder="Tu respuesta..."
                    className="flex-1 px-3 py-2 rounded-lg bg-surface-3/50 border border-white/[0.06] text-sm text-text-primary placeholder:text-text-tertiary outline-none focus:border-accent-primary/50"
                    autoFocus
                />
                <button
                    onClick={() => {
                        if (customAnswer.trim()) {
                            onAnswer(customAnswer);
                            setCustomAnswer('');
                        }
                    }}
                    disabled={!customAnswer.trim()}
                    className="px-3 py-2 rounded-lg bg-accent-primary/20 hover:bg-accent-primary/30 border border-accent-primary/30 text-accent-primary text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                >
                    <Send size={14} />
                </button>
            </div>
        </motion.div>
    );
};

export const OrchestratorChat: React.FC<OrchestratorChatProps> = ({
    isCollapsed = false,
    providerConnected = true,
    onPlanGenerated,
    onNavigateToSettings,
    onSendToTerminal,
    onViewInFlow,
    inboundTerminalSummary,
}) => {
    const { t } = useTranslation();
    const [messages, setMessages] = useState<ChatMessage[]>([
        {
            id: 'm-welcome',
            role: 'system',
            text: 'Chat del orquestador listo. Describe un workflow para generar un plan con IA, o crea un draft manual.',
            ts: new Date().toISOString(),
        },
    ]);
    const [drafts, setDrafts] = useState<OpsDraft[]>([]);
    const [input, setInput] = useState('');
    const [mode, setMode] = useState<ComposerMode>('generate');
    const [isSending, setIsSending] = useState(false);
    const [isLoadingDrafts, setIsLoadingDrafts] = useState(false);
    const [draftViewTab, setDraftViewTab] = useState<DraftViewTab>('pending');
    const [approvingId, setApprovingId] = useState<string | null>(null);
    const [stepsCollapsed, setStepsCollapsed] = useState<Set<string>>(new Set());
    const [skillsCatalog, setSkillsCatalog] = useState<Skill[]>([]);
    const [skillsLoaded, setSkillsLoaded] = useState(false);
    const [skillsLoading, setSkillsLoading] = useState(false);
    const [selectedSuggestionIdx, setSelectedSuggestionIdx] = useState(0);
    // Agentic chat state
    const [agenticThreadId, setAgenticThreadId] = useState<string | null>(null);
    const [agenticToolCalls, setAgenticToolCalls] = useState<AgenticToolCall[]>([]);
    const [pendingApproval, setPendingApproval] = useState<AgenticToolCall | null>(null);
    const [threadHistory, setThreadHistory] = useState<ThreadSummary[]>([]);
    // P2: Conversational Planning State
    const [currentMood, setCurrentMood] = useState<string>('neutral');
    const [pendingQuestion, setPendingQuestion] = useState<UserQuestion | null>(null);
    const [proposedPlan, setProposedPlan] = useState<ProposedPlan | null>(null);
    const { addToast } = useToast();
    const scrollRef = useRef<HTMLDivElement>(null);
    const inputRef = useRef<HTMLTextAreaElement>(null);
    const skillsLoadingRef = useRef(false);

    /* ── Auto-scroll ── */
    useEffect(() => {
        if (scrollRef.current) {
            scrollRef.current.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
        }
    }, [messages]);

    /* ── Auto-resize textarea ── */
    useEffect(() => {
        const el = inputRef.current;
        if (!el) return;
        el.style.height = '0';
        el.style.height = `${Math.min(el.scrollHeight, 120)}px`;
    }, [input]);

    const sortedDrafts = useMemo(
        () => [...drafts].sort((a, b) => +new Date(b.created_at) - +new Date(a.created_at)),
        [drafts],
    );

    const draftCounts = useMemo(() => {
        const pending = drafts.filter((d) => d.status === 'draft').length;
        const approved = drafts.filter((d) => d.status === 'approved').length;
        const rejectedError = drafts.filter((d) => d.status === 'rejected' || d.status === 'error').length;
        return {
            pending,
            approved,
            rejectedError,
            all: drafts.length,
        };
    }, [drafts]);

    const visibleDrafts = useMemo(() => {
        if (draftViewTab === 'pending') return sortedDrafts.filter((d) => d.status === 'draft');
        if (draftViewTab === 'approved') return sortedDrafts.filter((d) => d.status === 'approved');
        if (draftViewTab === 'rejected_error') return sortedDrafts.filter((d) => d.status === 'rejected' || d.status === 'error');
        return sortedDrafts;
    }, [draftViewTab, sortedDrafts]);

    const parseSlash = useCallback((value: string) => {
        const trimmed = value.trim();
        if (!trimmed.startsWith('/')) return null;
        const [commandRaw, ...argsParts] = trimmed.split(/\s+/);
        return {
            command: commandRaw.toLowerCase(),
            argsRaw: argsParts.join(' ').trim(),
        };
    }, []);

    const commandToSkill = useMemo(() => {
        const map = new Map<string, Skill>();
        for (const skill of skillsCatalog) {
            map.set(skill.command.toLowerCase(), skill);
        }
        return map;
    }, [skillsCatalog]);

    const isSlashInput = input.trim().startsWith('/');
    const slashQuery = useMemo(() => {
        const parsed = parseSlash(input);
        return parsed ? parsed.command.slice(1) : '';
    }, [input, parseSlash]);

    const slashSuggestions = useMemo(() => {
        if (!isSlashInput) return [];
        if (input.trim().includes(' ')) return [];
        const q = slashQuery.toLowerCase();
        const filtered = skillsCatalog.filter((skill) => (
            skill.command.slice(1).toLowerCase().includes(q) ||
            skill.name.toLowerCase().includes(q)
        ));
        return filtered.slice(0, 7);
    }, [isSlashInput, slashQuery, skillsCatalog]);

    const handleSuggestionKeyDown = (
        e: React.KeyboardEvent,
        inputValue: string,
        suggestions: Skill[],
        selectedIndex: number,
        setVal: (v: string) => void
    ) => {
        const hasArgs = inputValue.trim().includes(' ');
        if (e.key === 'ArrowDown') {
            e.preventDefault();
            setSelectedSuggestionIdx((prev) => (prev + 1) % suggestions.length);
            return true;
        }
        if (e.key === 'ArrowUp') {
            e.preventDefault();
            setSelectedSuggestionIdx((prev) => (prev - 1 + suggestions.length) % suggestions.length);
            return true;
        }
        if (e.key === 'Escape') {
            e.preventDefault();
            setVal('/');
            return true;
        }
        if (e.key === 'Enter' && !e.shiftKey) {
            const current = suggestions[selectedIndex];
            if (!hasArgs && current && inputValue.trim() !== current.command) {
                e.preventDefault();
                setVal(`${current.command} `);
                return true;
            }
        }
        return false;
    };

    const appendMessage = useCallback((message: ChatMessage) => {
        setMessages((prev) => [...prev, message]);
    }, []);

    const upsertDraft = useCallback((draft: OpsDraft) => {
        setDrafts((prev) => {
            const idx = prev.findIndex((d) => d.id === draft.id);
            if (idx === -1) return [draft, ...prev];
            const clone = [...prev];
            clone[idx] = { ...clone[idx], ...draft };
            return clone;
        });
    }, []);

    const fetchDrafts = useCallback(async () => {
        setIsLoadingDrafts(true);
        try {
            const response = await fetchWithRetry(`${API_BASE}/ops/drafts`, { credentials: 'include' });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const data: OpsDraft[] = await response.json();
            setDrafts(data);
        } catch {
            addToast('No se pudieron cargar los drafts', 'error');
        } finally {
            setIsLoadingDrafts(false);
        }
    }, [addToast]);

    useEffect(() => { fetchDrafts(); }, [fetchDrafts]);

    useEffect(() => {
        const eventSource = new EventSource(`${API_BASE}/ops/stream`, { withCredentials: true });
        eventSource.onmessage = (evt) => {
            try {
                const payload = JSON.parse(evt.data);
                const type = payload?.event;
                const data = payload?.data;
                if (type !== 'action_requires_approval' || !data?.draft) return;
                const draft = data.draft as ActionDraftUi;
                appendMessage({
                    id: `m-approval-${draft.id}`,
                    role: 'system',
                    text: `Solicitud HITL: ${draft.agent_id} solicita ${draft.tool}`,
                    ts: new Date().toISOString(),
                    approvalDraft: draft,
                });
            } catch {
                // ignore malformed SSE payloads
            }
        };
        return () => eventSource.close();
    }, [appendMessage]);

    useEffect(() => {
        if (!inboundTerminalSummary) return;
        appendMessage({
            id: `m-terminal-summary-${inboundTerminalSummary.id}`,
            role: 'system',
            text: `[Terminal] ${inboundTerminalSummary.text}`,
            ts: inboundTerminalSummary.ts,
        });
    }, [appendMessage, inboundTerminalSummary]);

    const fetchSkillsCatalog = useCallback(async (): Promise<Skill[]> => {
        if (skillsLoadingRef.current) return [];
        skillsLoadingRef.current = true;
        setSkillsLoading(true);
        try {
            const response = await fetchWithRetry(`${API_BASE}/ops/skills`, { credentials: 'include' });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const data: Skill[] = await response.json();
            setSkillsCatalog(data);
            setSkillsLoaded(true);
            return data;
        } catch {
            addToast('No se pudieron cargar los slash commands de skills', 'error');
            return [];
        } finally {
            skillsLoadingRef.current = false;
            setSkillsLoading(false);
        }
    }, [addToast]);

    useEffect(() => {
        void fetchSkillsCatalog();
    }, [fetchSkillsCatalog]);

    useEffect(() => {
        if (isSlashInput && !skillsLoaded && !skillsLoading) {
            void fetchSkillsCatalog();
        }
    }, [fetchSkillsCatalog, isSlashInput, skillsLoaded, skillsLoading]);

    useEffect(() => {
        setSelectedSuggestionIdx(0);
    }, [slashQuery]);

    const approveDraft = async (draftId: string) => {
        if (approvingId) return;
        setApprovingId(draftId);
        try {
            const currentDraft = drafts.find((d) => d.id === draftId);
            const response = await fetchWithRetry(`${API_BASE}/ops/drafts/${draftId}/approve`, { method: 'POST', credentials: 'include' });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const data: OpsApproveResponse = await response.json();
            setDrafts((prev) => prev.map((d) => (d.id === draftId ? { ...d, status: 'approved' } : d)));
            const draftState = currentDraft || { id: draftId, prompt: '', status: 'approved', created_at: new Date().toISOString() };
            const draftSteps = buildDraftSteps(
                { ...draftState, status: 'approved' } as OpsDraft,
                { approvedId: data.approved.id, runId: data.run?.id },
            );
            appendMessage({
                id: `m-approve-${Date.now()}`,
                role: 'system',
                text: `Draft ${draftId} aprobado y listo para ejecucion.`,
                ts: new Date().toISOString(),
                draftId,
                approvedId: data.approved.id,
                runId: data.run?.id,
                detectedIntent: currentDraft?.context?.detected_intent,
                decisionPath: currentDraft?.context?.decision_path,
                executionDecision: currentDraft?.context?.execution_decision,
                decisionReason: currentDraft?.context?.decision_reason,
                riskScore: typeof currentDraft?.context?.risk_score === 'number' ? currentDraft.context.risk_score : undefined,
                executionSteps: draftSteps,
            });
            addToast('Draft aprobado', 'success');
        } catch {
            addToast('No se pudo aprobar el draft', 'error');
        } finally {
            setApprovingId(null);
        }
    };

    const rejectDraft = async (draftId: string) => {
        try {
            const response = await fetchWithRetry(`${API_BASE}/ops/drafts/${draftId}/reject`, { method: 'POST', credentials: 'include' });
            if (!response.ok) {
                if (response.status === 403) {
                    addToast('No autorizado para rechazar draft (requiere operator/admin)', 'error');
                    return;
                }
                throw new Error(`HTTP ${response.status}`);
            }
            setDrafts((prev) => prev.map((d) => (d.id === draftId ? { ...d, status: 'rejected' } : d)));
            appendMessage({ id: `m-reject-${Date.now()}`, role: 'system', text: `Draft ${draftId} rechazado.`, ts: new Date().toISOString(), draftId });
            addToast('Draft rechazado', 'info');
        } catch {
            addToast('No se pudo rechazar el draft', 'error');
        }
    };

    const createRunFromApproved = async (approvedId: string, sourceDraftId?: string) => {
        try {
            const response = await fetchWithRetry(`${API_BASE}/ops/runs`, {
                method: 'POST',
                credentials: 'include',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ approved_id: approvedId }),
            });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const run = await response.json();
            appendMessage({
                id: `m-run-${run.id}`,
                role: 'system',
                text: `Run ${run.id} iniciado para approved ${approvedId}.`,
                ts: new Date().toISOString(),
                draftId: sourceDraftId,
                approvedId,
                runId: run.id,
                executionSteps: [
                    { key: 'run_created', label: 'Run creado', status: 'done', detail: run.id },
                    { key: 'run_status', label: 'Estado de run', status: run.status === 'error' ? 'error' : 'done', detail: run.status },
                ],
            });
            addToast('Run creado', 'success');
        } catch {
            addToast('No se pudo crear el run', 'error');
        }
    };

    const handleSendError = (err: any, prompt: string) => {
        const errMsg = err?.message || '';
        let actionable: string | undefined;
        let text = 'No se pudo procesar la solicitud del chat.';
        if (errMsg.includes('401') || errMsg.includes('403')) {
            text = 'Sesion expirada o sin permisos.';
            actionable = 'Revalida la sesion desde Archivo > Revalidar sesion.';
        } else if (errMsg.includes('Connection refused') || errMsg.includes('fetch')) {
            text = 'No se pudo conectar al servidor backend.';
            actionable = 'Verifica que el servidor GIMO esta corriendo en el puerto 9325.';
        } else if (errMsg.includes('Provider') || errMsg.includes('provider')) {
            text = 'Error del provider de IA.';
            actionable = 'Verifica la configuracion del provider en Ajustes.';
        }
        appendMessage({
            id: `m-error-${Date.now()}`,
            role: 'system',
            text,
            ts: new Date().toISOString(),
            errorActionable: actionable,
            failed: true,
            failedPrompt: prompt,
        });
        addToast('Error en la operacion de chat', 'error');
    };

    const handleGenerateDraft = async (prompt: string) => {
        const response = await fetchWithRetry(`${API_BASE}/ops/generate?prompt=${encodeURIComponent(prompt)}`, { method: 'POST', credentials: 'include' });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const generated: OpsDraft = await response.json();
        upsertDraft(generated);
        const customPlanId = generated.context?.custom_plan_id as string | undefined;
        appendMessage({
            id: `m-gen-${generated.id}`,
            role: generated.status === 'error' ? 'system' : 'assistant',
            text: generated.content || generated.error || 'Draft generado sin contenido.',
            ts: generated.created_at,
            draftId: generated.id,
            detectedIntent: generated.context?.detected_intent,
            decisionPath: generated.context?.decision_path,
            executionDecision: generated.context?.execution_decision,
            decisionReason: generated.context?.decision_reason,
            riskScore: typeof generated.context?.risk_score === 'number' ? generated.context.risk_score : undefined,
            errorActionable: generated.context?.error_actionable || generated.error || undefined,
            executionSteps: buildDraftSteps(generated),
        });
        addToast('Draft generado con IA', 'success');
        if (customPlanId && onPlanGenerated) onPlanGenerated(customPlanId);
    };

    const handleManualDraft = async (prompt: string) => {
        const response = await fetchWithRetry(`${API_BASE}/ops/drafts`, {
            method: 'POST',
            credentials: 'include',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ prompt, context: { source: 'orchestrator-chat' } }),
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const created: OpsDraft = await response.json();
        upsertDraft(created);
        appendMessage({
            id: `m-draft-${created.id}`,
            role: 'assistant',
            text: `Draft manual ${created.id} creado y pendiente de aprobacion.`,
            ts: created.created_at,
            draftId: created.id,
            executionSteps: buildDraftSteps(created),
        });
        addToast('Draft manual creado', 'success');
    };

    const executeSlashSkill = async (prompt: string) => {
        const parsed = parseSlash(prompt);
        if (!parsed) return false;

        let lookupMap = commandToSkill;
        if (!skillsLoaded) {
            const freshSkills = await fetchSkillsCatalog();
            lookupMap = new Map(freshSkills.map((s) => [s.command.toLowerCase(), s]));
        }

        const skill = lookupMap.get(parsed.command);
        if (!skill) {
            const similar = slashSuggestions.slice(0, 3).map((s) => s.command);
            appendMessage({
                id: `m-slash-invalid-${Date.now()}`,
                role: 'system',
                text: similar.length > 0
                    ? `Comando ${parsed.command} no encontrado. Sugerencias: ${similar.join(', ')}`
                    : `Comando ${parsed.command} no encontrado.`,
                ts: new Date().toISOString(),
                errorActionable: 'Usa / para ver comandos disponibles o abre Skills Library.',
            });
            addToast('Slash command no válido', 'error');
            return true;
        }

        if (skill.replace_graph) {
            globalThis.dispatchEvent(new CustomEvent('ops:load_skill_to_graph', { detail: skill }));
        }

        const response = await fetchWithRetry(`${API_BASE}/ops/skills/${skill.id}/execute`, {
            method: 'POST',
            credentials: 'include',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                replace_graph: skill.replace_graph,
                context: {
                    source: 'orchestrator-chat',
                    command: parsed.command,
                    args_raw: parsed.argsRaw,
                },
            }),
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data: SkillExecuteResponse = await response.json();

        appendMessage({
            id: `m-skill-run-${data.skill_run_id}`,
            role: 'system',
            text: `Skill ${skill.command} en cola (${data.skill_run_id}). Modo: ${data.replace_graph ? 'replace_graph' : 'background'}.`,
            ts: new Date().toISOString(),
        });
        addToast(`Skill ejecutándose: ${data.skill_run_id}`, 'success');
        return true;
    };

    /* ── Agentic chat via SSE ── */
    const handleAgenticChat = async (prompt: string) => {
        let threadId = agenticThreadId;

        // Create thread if needed
        if (!threadId) {
            const createResp = await fetchWithRetry(`${API_BASE}/ops/threads?workspace_root=.&title=UI+Agentic+Session`, {
                method: 'POST', credentials: 'include',
            });
            if (!createResp.ok) throw new Error(`HTTP ${createResp.status}`);
            const threadData = await createResp.json();
            threadId = threadData.id;
            setAgenticThreadId(threadId);
        }

        // Open SSE stream
        const resp = await fetch(`${API_BASE}/ops/threads/${threadId}/chat/stream?content=${encodeURIComponent(prompt)}`, {
            method: 'POST', credentials: 'include',
        });

        if (!resp.ok || !resp.body) throw new Error(`HTTP ${resp.status}`);

        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        let accumulatedText = '';
        let currentEventType = 'message';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });

            const lines = buffer.split('\n');
            buffer = lines.pop() || '';

            for (const line of lines) {
                if (line.startsWith('event: ')) {
                    currentEventType = line.slice(7).trim();
                    continue;
                }
                if (!line.startsWith('data: ')) continue;
                const raw = line.slice(6).trim();
                if (!raw) continue;

                let data: Record<string, unknown>;
                try { data = JSON.parse(raw); } catch { continue; }

                switch (currentEventType) {
                    case 'text_delta':
                        accumulatedText += (data.content as string) || '';
                        break;

                    case 'tool_call_start': {
                        const tc: AgenticToolCall = {
                            tool_call_id: data.tool_call_id as string,
                            tool_name: data.tool_name as string,
                            arguments: (data.arguments as Record<string, unknown>) || {},
                            status: 'running',
                            risk: (data.risk as string) || 'LOW',
                        };
                        setAgenticToolCalls(prev => [...prev, tc]);
                        break;
                    }

                    case 'tool_call_end':
                        setAgenticToolCalls(prev => prev.map(tc =>
                            tc.tool_call_id === data.tool_call_id
                                ? { ...tc, status: data.status as string, duration: data.duration as number, message: (data.message as string)?.slice(0, 200) }
                                : tc
                        ));
                        break;

                    case 'tool_approval_required':
                        setPendingApproval({
                            tool_call_id: data.tool_call_id as string,
                            tool_name: data.tool_name as string,
                            arguments: (data.arguments as Record<string, unknown>) || {},
                            status: 'pending_approval',
                            risk: 'HIGH',
                        });
                        break;

                    // ── P2: Conversational Planning Events ────────────────────

                    case 'session_start':
                        // Mood info in session start
                        if (data.mood) setCurrentMood(data.mood as string);
                        break;

                    case 'user_question':
                        // Agent is asking a question
                        setPendingQuestion({
                            question: (data.question as string) || '',
                            options: (data.options as string[]) || [],
                            context: (data.context as string) || '',
                        });
                        appendMessage({
                            id: `m-question-${Date.now()}`,
                            role: 'assistant',
                            text: `❓ ${data.question as string}`,
                            ts: new Date().toISOString(),
                        });
                        break;

                    case 'plan_proposed':
                        // Agent proposed a plan
                        setProposedPlan(data as ProposedPlan);
                        appendMessage({
                            id: `m-plan-${Date.now()}`,
                            role: 'assistant',
                            text: `📋 Plan propuesto: ${(data as ProposedPlan).title}`,
                            ts: new Date().toISOString(),
                        });
                        break;

                    case 'confirmation_required':
                        // Tool requires confirmation due to mood constraints
                        appendMessage({
                            id: `m-confirm-${Date.now()}`,
                            role: 'system',
                            text: `⚠️ ${(data.message as string) || 'Confirmación requerida para continuar'}`,
                            ts: new Date().toISOString(),
                        });
                        break;

                    case 'done': {
                        const finalResp = (data.response as string) || accumulatedText;
                        const toolCalls = (data.tool_calls as AgenticToolCall[]) || [];
                        const usage = (data.usage as Record<string, number>) || {};
                        appendMessage({
                            id: `m-agentic-${Date.now()}`,
                            role: 'assistant',
                            text: finalResp,
                            ts: new Date().toISOString(),
                        });
                        if (toolCalls.length > 0) {
                            setAgenticToolCalls(toolCalls);
                        }
                        const tokens = usage.total_tokens || 0;
                        const cost = usage.cost_usd || 0;
                        if (tokens) {
                            addToast(`${tokens.toLocaleString()} tokens | $${cost.toFixed(4)}`, 'info');
                        }
                        break;
                    }

                    case 'error':
                        appendMessage({
                            id: `m-agentic-err-${Date.now()}`,
                            role: 'system',
                            text: (data.message as string) || 'Error en el loop agentic.',
                            ts: new Date().toISOString(),
                            failed: true,
                        });
                        break;
                }
            }
        }

        setAgenticToolCalls([]);
        setPendingApproval(null);
    };

    const handleApproveHitl = async (toolCallId: string, approved: boolean) => {
        if (!agenticThreadId) return;
        try {
            await fetchWithRetry(
                `${API_BASE}/ops/threads/${agenticThreadId}/approve-tool?tool_call_id=${toolCallId}&approved=${approved}`,
                { method: 'POST', credentials: 'include' },
            );
            setPendingApproval(null);
            addToast(approved ? 'Tool aprobado' : 'Tool rechazado', approved ? 'success' : 'info');
        } catch {
            addToast('Error al enviar aprobacion', 'error');
        }
    };

    // ── P2: Plan Approval Handlers ────────────────────────────────────────────

    const handleApprovePlan = async () => {
        if (!agenticThreadId || !proposedPlan) return;
        try {
            const resp = await fetchWithRetry(
                `${API_BASE}/ops/threads/${agenticThreadId}/plan/respond`,
                {
                    method: 'POST',
                    credentials: 'include',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ action: 'approve', feedback: '' }),
                },
            );
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            const result = await resp.json();

            setProposedPlan(null);
            setCurrentMood('executor');
            addToast('Plan aprobado. Ejecución iniciada.', 'success');

            appendMessage({
                id: `m-plan-approved-${Date.now()}`,
                role: 'system',
                text: `✓ Plan aprobado. Ejecución en progreso (plan_id: ${result.plan_id || '?'})`,
                ts: new Date().toISOString(),
            });
        } catch (err) {
            addToast('Error al aprobar el plan', 'error');
        }
    };

    const handleRejectPlan = async (feedback: string) => {
        if (!agenticThreadId || !proposedPlan) return;
        try {
            const resp = await fetchWithRetry(
                `${API_BASE}/ops/threads/${agenticThreadId}/plan/respond`,
                {
                    method: 'POST',
                    credentials: 'include',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ action: 'reject', feedback: feedback || 'Plan rechazado' }),
                },
            );
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);

            setProposedPlan(null);
            setCurrentMood('dialoger');
            addToast('Plan rechazado. El agente revisará.', 'info');

            appendMessage({
                id: `m-plan-rejected-${Date.now()}`,
                role: 'system',
                text: `✗ Plan rechazado. El agente revisará basándose en tu feedback.`,
                ts: new Date().toISOString(),
            });
        } catch (err) {
            addToast('Error al rechazar el plan', 'error');
        }
    };

    const handleModifyPlan = () => {
        addToast('Modificación de plan aún no implementada', 'info');
    };

    const handleAnswerQuestion = async (answer: string) => {
        if (!pendingQuestion) return;
        setPendingQuestion(null);

        // Send answer as a new user message
        appendMessage({
            id: `m-answer-${Date.now()}`,
            role: 'user',
            text: answer,
            ts: new Date().toISOString(),
        });

        // Continue the chat with the answer
        setIsSending(true);
        try {
            await handleAgenticChat(answer);
        } catch (err: any) {
            handleSendError(err, answer);
        } finally {
            setIsSending(false);
        }
    };

    const fetchThreadHistory = useCallback(async () => {
        try {
            const resp = await fetchWithRetry(`${API_BASE}/ops/threads`, { credentials: 'include' });
            if (!resp.ok) return;
            const data: ThreadSummary[] = await resp.json();
            setThreadHistory(data);
        } catch { /* ignore */ }
    }, []);

    useEffect(() => {
        if (mode === 'agentic') void fetchThreadHistory();
    }, [mode, fetchThreadHistory]);

    /* ── Send logic ── */
    const handleSend = async (retryPrompt?: string) => {
        const prompt = retryPrompt || input.trim();
        if (!prompt || isSending) return;

        const slash = parseSlash(prompt);

        if (!slash && mode === 'generate' && !providerConnected) {
            appendMessage({
                id: `m-noprovider-${Date.now()}`,
                role: 'system',
                text: 'No hay provider configurado. Configura un provider de IA para generar planes.',
                ts: new Date().toISOString(),
                errorActionable: 'Abre Ajustes para configurar tu conexion.',
            });
            if (onNavigateToSettings) addToast('Configura un provider primero', 'info');
            return;
        }

        if (!retryPrompt) {
            appendMessage({ id: `m-user-${Date.now()}`, role: 'user', text: prompt, ts: new Date().toISOString() });
            setInput('');
        }
        setIsSending(true);

        try {
            if (slash) {
                await executeSlashSkill(prompt);
            } else if (mode === 'agentic') {
                await handleAgenticChat(prompt);
            } else if (mode === 'generate') {
                await handleGenerateDraft(prompt);
            } else {
                await handleManualDraft(prompt);
            }
        } catch (err: any) {
            handleSendError(err, prompt);
        } finally {
            setIsSending(false);
        }
    };

    const toggleStepsCollapse = (msgId: string) => {
        setStepsCollapsed((prev) => {
            const next = new Set(prev);
            if (next.has(msgId)) next.delete(msgId);
            else next.add(msgId);
            return next;
        });
    };

    /* ── Render ── */
    return (
        <section className="h-full bg-surface-1/80 backdrop-blur-xl flex min-h-0">
            {/* Main chat area */}
            <div className={`flex flex-col min-h-0 ${isCollapsed ? 'w-full' : 'flex-1 border-r border-white/[0.04]'}`}>
                {/* Header */}
                {!isCollapsed && (
                    <div className="h-11 px-4 border-b border-white/[0.04] flex items-center justify-between shrink-0">
                        <div className="text-[11px] uppercase tracking-wider font-semibold text-text-primary">
                            Chat del Orquestador
                        </div>
                        <div className="flex items-center gap-0.5 rounded-lg border border-white/[0.06] bg-surface-2/60 p-0.5">
                            <button
                                onClick={() => setMode('generate')}
                                className={`px-2.5 py-1 rounded-md text-[10px] uppercase tracking-wider transition-all ${mode === 'generate' ? 'bg-accent-primary/20 text-accent-primary' : 'text-text-secondary hover:text-text-primary'}`}
                            >
                                <Sparkles size={11} className="inline mr-1" />
                                IA
                            </button>
                            <button
                                onClick={() => setMode('draft')}
                                className={`px-2.5 py-1 rounded-md text-[10px] uppercase tracking-wider transition-all ${mode === 'draft' ? 'bg-accent-primary/20 text-accent-primary' : 'text-text-secondary hover:text-text-primary'}`}
                            >
                                Draft
                            </button>
                            <button
                                onClick={() => setMode('agentic')}
                                className={`px-2.5 py-1 rounded-md text-[10px] uppercase tracking-wider transition-all ${mode === 'agentic' ? 'bg-accent-primary/20 text-accent-primary' : 'text-text-secondary hover:text-text-primary'}`}
                            >
                                <MessageSquare size={11} className="inline mr-1" />
                                Chat
                            </button>
                        </div>
                    </div>
                )}

                {/* Messages */}
                {!isCollapsed && (
                    <div ref={scrollRef} className="flex-1 min-h-0 overflow-y-auto p-4 space-y-3 custom-scrollbar">
                        <AnimatePresence initial={false}>
                            {messages.map((message) => (
                                <motion.div
                                    key={message.id}
                                    variants={msgVariants}
                                    initial="hidden"
                                    animate="visible"
                                    transition={{ type: 'spring', stiffness: 400, damping: 30 }}
                                    className={`rounded-2xl px-3.5 py-2.5 border transition-colors ${getMessageStyle(message.role, message.failed)}`}
                                >
                                    {/* Role label + timestamp */}
                                    <div className="flex items-center justify-between mb-1">
                                        <span className={`text-[9px] uppercase tracking-wider font-bold flex items-center gap-1.5 ${getRoleTextStyle(message.role, message.failed)}`}>
                                            <span className="w-4 h-4 rounded-full bg-white/[0.06] flex items-center justify-center shrink-0">
                                                {getRoleAvatar(message.role)}
                                            </span>
                                            {getRoleLabel(message.role)}
                                        </span>
                                        <span className="text-[9px] text-text-tertiary">{formatTime(message.ts)}</span>
                                    </div>

                                    {/* Text */}
                                    <p className="text-xs text-text-primary leading-relaxed whitespace-pre-wrap">
                                        {message.text}
                                    </p>
                                    {message.approvalDraft && (
                                        <AgentActionApproval
                                            draft={message.approvalDraft}
                                            onResolved={(draftId, decision) => {
                                                appendMessage({
                                                    id: `m-approval-resolved-${draftId}-${Date.now()}`,
                                                    role: 'system',
                                                    text: `Accion ${draftId} ${decision === 'approve' ? 'aprobada' : 'rechazada'}.`,
                                                    ts: new Date().toISOString(),
                                                });
                                            }}
                                        />
                                    )}
                                    {onSendToTerminal && (
                                        <div className="mt-2">
                                            <button
                                                onClick={() => onSendToTerminal({ text: message.text, ts: new Date().toISOString(), source: 'chat' })}
                                                className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-[10px] bg-accent-primary/10 text-accent-primary border border-accent-primary/20 transition-colors hover:bg-accent-primary/15"
                                            >
                                                Enviar a terminal
                                            </button>
                                        </div>
                                    )}

                                    {/* Intent / Decision badges */}
                                    {(message.detectedIntent || message.decisionPath || message.executionDecision || typeof message.riskScore === 'number') && (
                                        <div className="mt-2 flex flex-wrap gap-1.5">
                                            {message.detectedIntent && (
                                                <span className="text-[9px] px-2 py-0.5 rounded-full border border-accent-primary/30 bg-accent-primary/8 text-accent-primary">
                                                    Intent: {message.detectedIntent}
                                                </span>
                                            )}
                                            {message.decisionPath && (
                                                <span className="text-[9px] px-2 py-0.5 rounded-full border border-white/[0.06] bg-surface-3/50 text-text-secondary">
                                                    Ruta: {message.decisionPath}
                                                </span>
                                            )}
                                            {message.executionDecision && (
                                                <span className="text-[9px] px-2 py-0.5 rounded-full border border-amber-400/30 bg-amber-500/10 text-amber-300">
                                                    Decision: {message.executionDecision}
                                                </span>
                                            )}
                                            {typeof message.riskScore === 'number' && (
                                                <span className="text-[9px] px-2 py-0.5 rounded-full border border-white/[0.06] bg-surface-3/50 text-text-secondary">
                                                    Risk: {message.riskScore}
                                                </span>
                                            )}
                                        </div>
                                    )}
                                    {message.decisionReason && (
                                        <div className="mt-1 text-[10px] text-text-tertiary">
                                            Razon: {message.decisionReason}
                                        </div>
                                    )}

                                    {/* Execution steps (collapsible) */}
                                    {message.executionSteps && message.executionSteps.length > 0 && (
                                        <div className="mt-2">
                                            <button
                                                onClick={() => toggleStepsCollapse(message.id)}
                                                className="text-[9px] text-text-tertiary hover:text-text-secondary flex items-center gap-1 mb-1 transition-colors"
                                            >
                                                <ChevronDown
                                                    size={10}
                                                    className={`transition-transform ${stepsCollapsed.has(message.id) ? '' : 'rotate-180'}`}
                                                />
                                                {stepsCollapsed.has(message.id) ? 'Ver pasos' : 'Ocultar pasos'}
                                            </button>
                                            <AnimatePresence>
                                                {!stepsCollapsed.has(message.id) && (
                                                    <motion.div
                                                        initial={{ height: 0, opacity: 0 }}
                                                        animate={{ height: 'auto', opacity: 1 }}
                                                        exit={{ height: 0, opacity: 0 }}
                                                        transition={{ duration: 0.2 }}
                                                        className="space-y-1 overflow-hidden"
                                                    >
                                                        {message.executionSteps.map((step) => (
                                                            <div
                                                                key={`${message.id}-${step.key}`}
                                                                className={`text-[10px] rounded-lg px-2 py-1 border ${getStepStyle(step.status)}`}
                                                            >
                                                                {step.label}: {step.detail || (step.status === 'pending' ? 'pendiente' : step.status)}
                                                            </div>
                                                        ))}
                                                    </motion.div>
                                                )}
                                            </AnimatePresence>
                                        </div>
                                    )}

                                    {/* Actionable error */}
                                    {message.errorActionable && (
                                        <div className="mt-2 text-[10px] rounded-lg border border-amber-500/20 bg-amber-500/5 text-amber-400 px-2.5 py-1.5 flex items-start gap-1.5">
                                            <AlertTriangle size={11} className="shrink-0 mt-0.5" />
                                            <span>{message.errorActionable}</span>
                                        </div>
                                    )}

                                    {/* Retry button for failed messages */}
                                    {message.failed && message.failedPrompt && (
                                        <button
                                            onClick={() => void handleSend(message.failedPrompt)}
                                            disabled={isSending}
                                            className="mt-2 inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[10px] bg-white/[0.04] border border-white/[0.06] text-text-secondary hover:text-text-primary hover:bg-white/[0.06] transition-colors disabled:opacity-50"
                                        >
                                            <RefreshCw size={10} />
                                            Reintentar
                                        </button>
                                    )}

                                    {/* Draft actions */}
                                    {message.draftId && drafts.some((d) => d.id === message.draftId && d.status === 'draft') && (
                                        <div className="mt-2 flex items-center gap-2">
                                            <button
                                                onClick={() => approveDraft(message.draftId!)}
                                                disabled={approvingId === message.draftId}
                                                className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-[10px] bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 disabled:opacity-50 transition-colors hover:bg-emerald-500/15"
                                            >
                                                <Check size={11} />
                                                {approvingId === message.draftId ? 'Aprobando...' : 'Aprobar'}
                                            </button>
                                            <button
                                                onClick={() => rejectDraft(message.draftId!)}
                                                className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-[10px] bg-red-500/10 text-red-400 border border-red-500/20 transition-colors hover:bg-red-500/15"
                                            >
                                                <X size={11} />
                                                Rechazar
                                            </button>
                                        </div>
                                    )}

                                    {/* Run from approved */}
                                    {message.approvedId && !message.runId && (
                                        <div className="mt-2">
                                            <button
                                                onClick={() => void createRunFromApproved(message.approvedId!, message.draftId)}
                                                className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-[10px] bg-accent-primary/10 text-accent-primary border border-accent-primary/20 transition-colors hover:bg-accent-primary/15"
                                            >
                                                <Sparkles size={11} />
                                                Ejecutar run
                                            </button>
                                            {onViewInFlow && (
                                                <button
                                                    onClick={() => onViewInFlow(message.approvedId)}
                                                    className="ml-2 inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-[10px] bg-white/[0.04] text-text-tertiary border border-white/[0.06] transition-colors hover:text-text-secondary hover:bg-white/[0.06]"
                                                    title="Investigar telemetría en el Flujo IDS"
                                                >
                                                    <Activity size={10} />
                                                    Flujo
                                                </button>
                                            )}
                                        </div>
                                    )}
                                </motion.div>
                            ))}
                        </AnimatePresence>

                        {/* P2: Mood Indicator */}
                        {mode === 'agentic' && currentMood !== 'neutral' && !isCollapsed && (
                            <div className="flex justify-end">
                                <MoodIndicator mood={currentMood} />
                            </div>
                        )}

                        {/* P2: Proposed Plan Review */}
                        {mode === 'agentic' && proposedPlan && !isCollapsed && (
                            <PlanReview
                                plan={proposedPlan}
                                onApprove={handleApprovePlan}
                                onReject={handleRejectPlan}
                                onModify={handleModifyPlan}
                                isProcessing={isSending}
                            />
                        )}

                        {/* P2: Pending User Question */}
                        {mode === 'agentic' && pendingQuestion && !isCollapsed && (
                            <UserQuestionPrompt
                                question={pendingQuestion}
                                onAnswer={handleAnswerQuestion}
                            />
                        )}

                        {/* Agentic tool calls in progress */}
                        {mode === 'agentic' && agenticToolCalls.length > 0 && (
                            <div className="rounded-xl border border-white/[0.06] bg-surface-2/40 px-3 py-2 space-y-1">
                                <div className="text-[9px] uppercase tracking-wider text-text-tertiary flex items-center gap-1">
                                    <Wrench size={10} /> Tool Calls
                                </div>
                                {agenticToolCalls.map((tc) => (
                                    <div key={tc.tool_call_id} className="flex items-center gap-2 text-[11px]">
                                        <span className={tc.status === 'success' ? 'text-emerald-400' : tc.status === 'error' || tc.status === 'denied' ? 'text-red-400' : 'text-amber-400'}>
                                            {tc.status === 'success' ? '✓' : tc.status === 'error' ? '✗' : tc.status === 'denied' ? '⊘' : '⋯'}
                                        </span>
                                        <span className="text-text-primary font-mono">{tc.tool_name}</span>
                                        <span className={`text-[9px] px-1.5 py-0.5 rounded-full border ${tc.risk === 'HIGH' ? 'border-red-500/30 text-red-400' : tc.risk === 'MEDIUM' ? 'border-amber-500/30 text-amber-400' : 'border-white/[0.06] text-text-tertiary'}`}>
                                            {tc.risk}
                                        </span>
                                        {tc.duration != null && (
                                            <span className="text-[9px] text-text-tertiary">{tc.duration.toFixed(1)}s</span>
                                        )}
                                    </div>
                                ))}
                            </div>
                        )}

                        {/* HITL approval required */}
                        {pendingApproval && (
                            <motion.div
                                initial={{ opacity: 0, y: 8 }}
                                animate={{ opacity: 1, y: 0 }}
                                className="rounded-xl border border-red-500/30 bg-red-500/5 px-3.5 py-3 space-y-2"
                            >
                                <div className="flex items-center gap-2 text-[11px] text-red-400 font-semibold">
                                    <ShieldAlert size={14} />
                                    Aprobacion requerida: {pendingApproval.tool_name}
                                </div>
                                <pre className="text-[10px] text-text-secondary bg-surface-2/60 rounded-lg p-2 max-h-24 overflow-auto">
                                    {JSON.stringify(pendingApproval.arguments, null, 2).slice(0, 300)}
                                </pre>
                                <div className="flex gap-2">
                                    <button
                                        onClick={() => void handleApproveHitl(pendingApproval.tool_call_id, true)}
                                        className="px-3 py-1.5 rounded-lg bg-emerald-500/15 border border-emerald-500/30 text-emerald-400 text-[10px] hover:bg-emerald-500/20 transition-colors"
                                    >
                                        <Check size={11} className="inline mr-1" /> Aprobar
                                    </button>
                                    <button
                                        onClick={() => void handleApproveHitl(pendingApproval.tool_call_id, false)}
                                        className="px-3 py-1.5 rounded-lg bg-red-500/15 border border-red-500/30 text-red-400 text-[10px] hover:bg-red-500/20 transition-colors"
                                    >
                                        <X size={11} className="inline mr-1" /> Rechazar
                                    </button>
                                </div>
                            </motion.div>
                        )}

                        {/* Thinking indicator */}
                        {isSending && (
                            <motion.div
                                initial={{ opacity: 0, y: 8 }}
                                animate={{ opacity: 1, y: 0 }}
                                className="flex items-center gap-2 px-3 py-2 text-[11px] text-text-tertiary"
                            >
                                <div className="flex gap-1">
                                    <div className="w-1.5 h-1.5 rounded-full bg-accent-primary/50 animate-bounce" style={{ animationDelay: '0ms' }} />
                                    <div className="w-1.5 h-1.5 rounded-full bg-accent-primary/50 animate-bounce" style={{ animationDelay: '150ms' }} />
                                    <div className="w-1.5 h-1.5 rounded-full bg-accent-primary/50 animate-bounce" style={{ animationDelay: '300ms' }} />
                                </div>
                                GIMO esta pensando...
                            </motion.div>
                        )}
                    </div>
                )}

                {/* Input */}
                <div className={`p-3 flex items-center gap-2 shrink-0 ${isCollapsed ? 'h-full items-center pl-16' : 'border-t border-white/[0.04]'}`}>
                    <div className="relative flex-1">
                        <textarea
                            ref={inputRef}
                            value={input}
                            onChange={(e) => setInput(e.target.value)}
                            onKeyDown={(e) => {
                                if (isSlashInput && slashSuggestions.length > 0) {
                                    const handled = handleSuggestionKeyDown(e, input, slashSuggestions, selectedSuggestionIdx, (val: string) => {
                                        setInput(val);
                                        if (val === '/') setInput('/'); // reset case
                                    });
                                    if (handled) return;
                                }

                                if (e.key === 'Enter' && !e.shiftKey) {
                                    e.preventDefault();
                                    void handleSend();
                                }
                            }}
                            rows={1}
                            placeholder={mode === 'agentic' ? 'Chat agentic con GIMO...' : mode === 'generate' ? 'Describe el workflow o usa /comando...' : 'Crear draft manual...'}
                            className="flex-1 w-full min-h-[40px] max-h-[120px] rounded-xl bg-surface-2/60 border border-white/[0.06] px-3 py-2.5 text-sm text-text-primary placeholder:text-text-tertiary outline-none focus:border-accent-primary/50 transition-colors duration-200 resize-none overflow-y-auto"
                        />
                        {isSlashInput && (
                            <div className="absolute left-0 right-0 bottom-11 rounded-xl border border-white/[0.08] bg-surface-1/95 backdrop-blur-lg shadow-xl shadow-black/40 p-1 z-20">
                                {skillsLoading && (
                                    <div className="px-2 py-2 text-[11px] text-text-tertiary">Cargando slash commands...</div>
                                )}
                                {!skillsLoading && slashSuggestions.length === 0 && (
                                    <div className="px-2 py-2 text-[11px] text-text-tertiary">No hay comandos que coincidan.</div>
                                )}
                                {!skillsLoading && slashSuggestions.length > 0 && (
                                    <div className="max-h-44 overflow-auto custom-scrollbar">
                                        {slashSuggestions.map((skill, idx) => (
                                            <button
                                                key={skill.id}
                                                type="button"
                                                onMouseDown={(e) => {
                                                    e.preventDefault();
                                                    setInput(`${skill.command} `);
                                                    inputRef.current?.focus();
                                                }}
                                                className={`w-full text-left rounded-lg px-2 py-1.5 transition-colors ${idx === selectedSuggestionIdx ? 'bg-accent-primary/15 text-accent-primary' : 'text-text-secondary hover:bg-white/[0.05] hover:text-text-primary'}`}
                                            >
                                                <div className="text-[11px] font-mono">{skill.command}</div>
                                                <div className="text-[10px] text-text-tertiary truncate">{skill.name}</div>
                                            </button>
                                        ))}
                                    </div>
                                )}
                            </div>
                        )}
                    </div>
                    <button
                        onClick={() => void handleSend()}
                        disabled={isSending || !input.trim()}
                        className="h-10 px-3 rounded-xl bg-accent-primary hover:bg-accent-primary/85 disabled:opacity-40 disabled:cursor-not-allowed text-white inline-flex items-center gap-2 active:scale-[0.97] transition-all"
                    >
                        {isSending ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
                        <span className="text-xs font-medium">{t('common.send')}</span>
                    </button>
                </div>
            </div>

            {/* Sidebar: Drafts or Thread History */}
            {!isCollapsed && (
                <aside className="w-72 min-w-[240px] max-w-[320px] bg-surface-0/60 backdrop-blur-lg flex flex-col min-h-0">
                    {/* Thread history (agentic mode) */}
                    {mode === 'agentic' && (
                        <div className="border-b border-white/[0.04]">
                            <div className="h-11 px-4 flex items-center justify-between shrink-0">
                                <span className="text-[10px] uppercase tracking-wider text-text-secondary font-bold">
                                    Conversaciones
                                </span>
                                <button
                                    onClick={() => { setAgenticThreadId(null); setMessages([{ id: 'm-welcome-new', role: 'system', text: 'Nueva sesion agentic. Escribe un mensaje para comenzar.', ts: new Date().toISOString() }]); }}
                                    className="text-[10px] text-accent-primary hover:text-accent-primary/80 transition-colors"
                                >
                                    + Nueva
                                </button>
                            </div>
                            <div className="max-h-48 overflow-y-auto px-3 pb-2 space-y-1 custom-scrollbar">
                                {threadHistory.length === 0 && (
                                    <p className="text-[10px] text-text-tertiary text-center py-2">Sin conversaciones previas.</p>
                                )}
                                {threadHistory.map(th => (
                                    <button
                                        key={th.id}
                                        onClick={() => { setAgenticThreadId(th.id); addToast(`Thread: ${th.id.slice(0, 8)}`, 'info'); }}
                                        className={`w-full text-left rounded-lg px-2 py-1.5 text-[10px] transition-colors ${agenticThreadId === th.id ? 'bg-accent-primary/15 text-accent-primary border border-accent-primary/20' : 'text-text-secondary hover:bg-white/[0.04] border border-transparent'}`}
                                    >
                                        <div className="truncate font-medium">{th.title || 'Sin titulo'}</div>
                                        <div className="text-[9px] text-text-tertiary">{th.id.slice(0, 8)} · {Array.isArray(th.turns) ? th.turns.length : 0} turnos</div>
                                    </button>
                                ))}
                            </div>
                        </div>
                    )}
                    <div className="h-11 px-4 border-b border-white/[0.04] flex items-center justify-between shrink-0">
                        <span className="text-[10px] uppercase tracking-wider text-text-secondary font-bold">
                            Drafts
                        </span>
                        <button
                            onClick={() => void fetchDrafts()}
                            className="text-[10px] text-accent-primary hover:text-accent-primary/80 transition-colors"
                        >
                            {isLoadingDrafts ? 'Cargando...' : 'Actualizar'}
                        </button>
                    </div>
                    <div className="flex-1 min-h-0 overflow-y-auto p-3 space-y-2 custom-scrollbar">
                        <div className="grid grid-cols-2 gap-1.5 mb-2">
                            <button
                                onClick={() => setDraftViewTab('pending')}
                                className={`text-[10px] px-2 py-1 rounded-md border transition-colors ${draftViewTab === 'pending' ? 'border-accent-primary/30 text-accent-primary bg-accent-primary/8' : 'border-white/[0.06] text-text-secondary hover:text-text-primary'}`}
                            >
                                Pendientes ({draftCounts.pending})
                            </button>
                            <button
                                onClick={() => setDraftViewTab('approved')}
                                className={`text-[10px] px-2 py-1 rounded-md border transition-colors ${draftViewTab === 'approved' ? 'border-accent-primary/30 text-accent-primary bg-accent-primary/8' : 'border-white/[0.06] text-text-secondary hover:text-text-primary'}`}
                            >
                                Aprobados ({draftCounts.approved})
                            </button>
                            <button
                                onClick={() => setDraftViewTab('rejected_error')}
                                className={`text-[10px] px-2 py-1 rounded-md border transition-colors ${draftViewTab === 'rejected_error' ? 'border-accent-primary/30 text-accent-primary bg-accent-primary/8' : 'border-white/[0.06] text-text-secondary hover:text-text-primary'}`}
                            >
                                Rech/Error ({draftCounts.rejectedError})
                            </button>
                            <button
                                onClick={() => setDraftViewTab('all')}
                                className={`text-[10px] px-2 py-1 rounded-md border transition-colors ${draftViewTab === 'all' ? 'border-accent-primary/30 text-accent-primary bg-accent-primary/8' : 'border-white/[0.06] text-text-secondary hover:text-text-primary'}`}
                            >
                                Todos ({draftCounts.all})
                            </button>
                        </div>
                        {visibleDrafts.length === 0 ? (
                            <p className="text-[11px] text-text-tertiary text-center py-8">
                                No hay drafts para este filtro.
                            </p>
                        ) : (
                            visibleDrafts.map((draft) => (
                                <div
                                    key={draft.id}
                                    className="rounded-xl border border-white/[0.04] bg-surface-2/50 p-2.5 space-y-2 hover:border-white/[0.08] transition-colors"
                                >
                                    <div>
                                        <div className="text-[9px] text-text-tertiary">{formatTime(draft.created_at)}</div>
                                        <div className="text-[11px] text-text-primary line-clamp-3 mt-0.5">{draft.prompt}</div>
                                    </div>
                                    <div className="text-[9px] text-text-tertiary uppercase tracking-wider">Estado: {draft.status}</div>
                                    {draft.status === 'draft' && (
                                        <div className="flex gap-1.5">
                                            <button
                                                onClick={() => void approveDraft(draft.id)}
                                                disabled={!!approvingId}
                                                className="flex-1 h-7 rounded-lg bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 text-[10px] disabled:opacity-50 hover:bg-emerald-500/15 transition-colors"
                                            >
                                                Aprobar
                                            </button>
                                            <button
                                                onClick={() => void rejectDraft(draft.id)}
                                                className="flex-1 h-7 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 text-[10px] hover:bg-red-500/15 transition-colors"
                                            >
                                                Rechazar
                                            </button>
                                        </div>
                                    )}
                                </div>
                            ))
                        )}
                    </div>
                </aside>
            )}
        </section>
    );
};
