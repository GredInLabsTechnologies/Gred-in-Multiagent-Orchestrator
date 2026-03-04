import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Check, Loader2, Send, Sparkles, X, RefreshCw, AlertTriangle, ChevronDown } from 'lucide-react';
import { API_BASE, ChatExecutionStep, ChatExecutionStepStatus, OpsApproveResponse, OpsDraft } from '../types';
import { useToast } from './Toast';

type ComposerMode = 'generate' | 'draft';

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

export const OrchestratorChat: React.FC<OrchestratorChatProps> = ({
    isCollapsed = false,
    providerConnected = true,
    onPlanGenerated,
    onNavigateToSettings,
}) => {
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
    const [approvingId, setApprovingId] = useState<string | null>(null);
    const [stepsCollapsed, setStepsCollapsed] = useState<Set<string>>(new Set());
    const { addToast } = useToast();
    const scrollRef = useRef<HTMLDivElement>(null);
    const inputRef = useRef<HTMLInputElement>(null);

    /* ── Auto-scroll ── */
    useEffect(() => {
        if (scrollRef.current) {
            scrollRef.current.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
        }
    }, [messages]);

    const pendingDrafts = useMemo(
        () => drafts.filter((d) => d.status === 'draft').sort((a, b) => +new Date(b.created_at) - +new Date(a.created_at)),
        [drafts],
    );

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
            const response = await fetch(`${API_BASE}/ops/drafts`, { credentials: 'include' });
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

    const approveDraft = async (draftId: string) => {
        if (approvingId) return;
        setApprovingId(draftId);
        try {
            const currentDraft = drafts.find((d) => d.id === draftId);
            const response = await fetch(`${API_BASE}/ops/drafts/${draftId}/approve`, { method: 'POST', credentials: 'include' });
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
            const response = await fetch(`${API_BASE}/ops/drafts/${draftId}/reject`, { method: 'POST', credentials: 'include' });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            setDrafts((prev) => prev.map((d) => (d.id === draftId ? { ...d, status: 'rejected' } : d)));
            appendMessage({ id: `m-reject-${Date.now()}`, role: 'system', text: `Draft ${draftId} rechazado.`, ts: new Date().toISOString(), draftId });
            addToast('Draft rechazado', 'info');
        } catch {
            addToast('No se pudo rechazar el draft', 'error');
        }
    };

    const createRunFromApproved = async (approvedId: string, sourceDraftId?: string) => {
        try {
            const response = await fetch(`${API_BASE}/ops/runs`, {
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
        const response = await fetch(`${API_BASE}/ops/generate?prompt=${encodeURIComponent(prompt)}`, { method: 'POST', credentials: 'include' });
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
        const response = await fetch(`${API_BASE}/ops/drafts`, {
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

    /* ── Send logic ── */
    const handleSend = async (retryPrompt?: string) => {
        const prompt = retryPrompt || input.trim();
        if (!prompt || isSending) return;

        if (mode === 'generate' && !providerConnected) {
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
            if (mode === 'generate') {
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
                                        <span className={`text-[9px] uppercase tracking-wider font-bold ${getRoleTextStyle(message.role, message.failed)}`}>
                                            {getRoleLabel(message.role)}
                                        </span>
                                        <span className="text-[9px] text-text-tertiary">{formatTime(message.ts)}</span>
                                    </div>

                                    {/* Text */}
                                    <p className="text-xs text-text-primary leading-relaxed whitespace-pre-wrap">
                                        {message.text}
                                    </p>

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
                                    {message.draftId && pendingDrafts.some((d) => d.id === message.draftId) && (
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
                                        </div>
                                    )}
                                </motion.div>
                            ))}
                        </AnimatePresence>

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
                    <input
                        ref={inputRef}
                        value={input}
                        onChange={(e) => setInput(e.target.value)}
                        onKeyDown={(e) => {
                            if (e.key === 'Enter' && !e.shiftKey) {
                                e.preventDefault();
                                void handleSend();
                            }
                        }}
                        placeholder={mode === 'generate' ? 'Describe el workflow...' : 'Crear draft manual...'}
                        className="flex-1 h-10 rounded-xl bg-surface-2/60 border border-white/[0.06] px-3 text-sm text-text-primary placeholder:text-text-tertiary outline-none focus:border-accent-primary/50 transition-colors duration-200"
                    />
                    <button
                        onClick={() => void handleSend()}
                        disabled={isSending || !input.trim()}
                        className="h-10 px-3 rounded-xl bg-accent-primary hover:bg-accent-primary/85 disabled:opacity-40 disabled:cursor-not-allowed text-white inline-flex items-center gap-2 active:scale-[0.97] transition-all"
                    >
                        {isSending ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
                        <span className="text-xs font-medium">Enviar</span>
                    </button>
                </div>
            </div>

            {/* Drafts sidebar */}
            {!isCollapsed && (
                <aside className="w-72 min-w-[240px] max-w-[320px] bg-surface-0/60 backdrop-blur-lg flex flex-col min-h-0">
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
                        {pendingDrafts.length === 0 ? (
                            <p className="text-[11px] text-text-tertiary text-center py-8">
                                No hay drafts pendientes.
                            </p>
                        ) : (
                            pendingDrafts.map((draft) => (
                                <div
                                    key={draft.id}
                                    className="rounded-xl border border-white/[0.04] bg-surface-2/50 p-2.5 space-y-2 hover:border-white/[0.08] transition-colors"
                                >
                                    <div>
                                        <div className="text-[9px] text-text-tertiary">{formatTime(draft.created_at)}</div>
                                        <div className="text-[11px] text-text-primary line-clamp-3 mt-0.5">{draft.prompt}</div>
                                    </div>
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
                                </div>
                            ))
                        )}
                    </div>
                </aside>
            )}
        </section>
    );
};
