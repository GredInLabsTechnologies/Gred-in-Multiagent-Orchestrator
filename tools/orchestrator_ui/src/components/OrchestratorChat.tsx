import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Check, Loader2, Send, Sparkles, X } from 'lucide-react';
import { API_BASE, ChatExecutionStep, OpsApproveResponse, OpsDraft } from '../types';
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
    errorActionable?: string;
    executionSteps?: ChatExecutionStep[];
}

const buildDraftSteps = (
    draft: OpsDraft,
    extras?: Partial<Pick<ChatMessage, 'approvedId' | 'runId'>>
): ChatExecutionStep[] => {
    const intentDetected = Boolean(draft.context?.detected_intent);
    const hasError = draft.status === 'error';
    const hasApproval = Boolean(extras?.approvedId);
    const hasRun = Boolean(extras?.runId);

    return [
        {
            key: 'intent_detected',
            label: 'Intención detectada',
            status: intentDetected ? 'done' : 'pending',
            detail: draft.context?.detected_intent,
        },
        {
            key: 'draft_created',
            label: 'Draft creado',
            status: hasError ? 'error' : 'done',
            detail: hasError ? (draft.error || 'No se pudo crear el draft') : draft.id,
        },
        {
            key: 'approved',
            label: 'Draft aprobado',
            status: hasApproval ? 'done' : 'pending',
            detail: extras?.approvedId,
        },
        {
            key: 'run_created',
            label: 'Run creado',
            status: hasRun ? 'done' : 'pending',
            detail: extras?.runId,
        },
        {
            key: 'run_status',
            label: 'Estado de run',
            status: hasError ? 'error' : (hasRun ? 'done' : 'pending'),
            detail: hasError ? (draft.error || draft.context?.error_actionable) : (hasRun ? 'pending' : undefined),
        },
    ];
};

export const OrchestratorChat: React.FC<{ isCollapsed?: boolean }> = ({ isCollapsed = false }) => {
    const [messages, setMessages] = useState<ChatMessage[]>([
        {
            id: 'm-welcome',
            role: 'system',
            text: 'Chat del orquestador listo. Puedes generar borradores con IA o crear drafts manuales para revisión.',
            ts: new Date().toISOString(),
        },
    ]);
    const [drafts, setDrafts] = useState<OpsDraft[]>([]);
    const [input, setInput] = useState('');
    const [mode, setMode] = useState<ComposerMode>('generate');
    const [isSending, setIsSending] = useState(false);
    const [isLoadingDrafts, setIsLoadingDrafts] = useState(false);
    const [approvingId, setApprovingId] = useState<string | null>(null);
    const { addToast } = useToast();

    const pendingDrafts = useMemo(
        () => drafts.filter(d => d.status === 'draft').sort((a, b) => +new Date(b.created_at) - +new Date(a.created_at)),
        [drafts]
    );

    const appendMessage = useCallback((message: ChatMessage) => {
        setMessages(prev => [...prev, message]);
    }, []);

    const upsertDraft = useCallback((draft: OpsDraft) => {
        setDrafts(prev => {
            const idx = prev.findIndex(d => d.id === draft.id);
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

    useEffect(() => {
        fetchDrafts();
    }, [fetchDrafts]);

    const approveDraft = async (draftId: string) => {
        if (approvingId) return;
        setApprovingId(draftId);
        try {
            const currentDraft = drafts.find(d => d.id === draftId);
            const response = await fetch(`${API_BASE}/ops/drafts/${draftId}/approve`, {
                method: 'POST',
                credentials: 'include',
            });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const data: OpsApproveResponse = await response.json();
            setDrafts(prev => prev.map(d => d.id === draftId ? { ...d, status: 'approved' } : d));
            appendMessage({
                id: `m-approve-${Date.now()}`,
                role: 'system',
                text: `Draft ${draftId} aprobado y listo para ejecución.`,
                ts: new Date().toISOString(),
                draftId,
                approvedId: data.approved.id,
                runId: data.run?.id,
                detectedIntent: currentDraft?.context?.detected_intent,
                decisionPath: currentDraft?.context?.decision_path,
                executionSteps: buildDraftSteps(
                    {
                        ...(currentDraft || {
                            id: draftId,
                            prompt: '',
                            status: 'approved',
                            created_at: new Date().toISOString(),
                        }),
                        status: 'approved',
                    },
                    { approvedId: data.approved.id, runId: data.run?.id }
                ),
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
            const response = await fetch(`${API_BASE}/ops/drafts/${draftId}/reject`, {
                method: 'POST',
                credentials: 'include',
            });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            setDrafts(prev => prev.map(d => d.id === draftId ? { ...d, status: 'rejected' } : d));
            appendMessage({
                id: `m-reject-${Date.now()}`,
                role: 'system',
                text: `Draft ${draftId} rechazado.`,
                ts: new Date().toISOString(),
                draftId,
            });
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
                    {
                        key: 'run_created',
                        label: 'Run creado',
                        status: 'done',
                        detail: run.id,
                    },
                    {
                        key: 'run_status',
                        label: 'Estado de run',
                        status: run.status === 'error' ? 'error' : 'done',
                        detail: run.status,
                    },
                ],
            });
            addToast('Run creado', 'success');
        } catch {
            addToast('No se pudo crear el run', 'error');
        }
    };

    const handleSend = async () => {
        const prompt = input.trim();
        if (!prompt || isSending) return;

        appendMessage({
            id: `m-user-${Date.now()}`,
            role: 'user',
            text: prompt,
            ts: new Date().toISOString(),
        });
        setInput('');
        setIsSending(true);

        try {
            if (mode === 'generate') {
                const response = await fetch(`${API_BASE}/ops/generate?prompt=${encodeURIComponent(prompt)}`, {
                    method: 'POST',
                    credentials: 'include',
                });
                if (!response.ok) throw new Error(`HTTP ${response.status}`);
                const generated: OpsDraft = await response.json();
                upsertDraft(generated);
                const intent = generated.context?.detected_intent;
                const decisionPath = generated.context?.decision_path;
                const actionable = generated.context?.error_actionable || generated.error || undefined;
                appendMessage({
                    id: `m-gen-${generated.id}`,
                    role: generated.status === 'error' ? 'system' : 'assistant',
                    text: generated.content || generated.error || 'Draft generado sin contenido.',
                    ts: generated.created_at,
                    draftId: generated.id,
                    detectedIntent: intent,
                    decisionPath,
                    errorActionable: actionable,
                    executionSteps: buildDraftSteps(generated),
                });
                addToast('Draft generado con IA', 'success');
            } else {
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
                    text: `Draft manual ${created.id} creado y pendiente de aprobación.`,
                    ts: created.created_at,
                    draftId: created.id,
                    executionSteps: buildDraftSteps(created),
                });
                addToast('Draft manual creado', 'success');
            }
        } catch {
            appendMessage({
                id: `m-error-${Date.now()}`,
                role: 'system',
                text: 'No se pudo procesar la solicitud del chat.',
                ts: new Date().toISOString(),
            });
            addToast('Error en la operación de chat', 'error');
        } finally {
            setIsSending(false);
        }
    };

    return (
        <section className="h-full bg-[#0a0a0a] flex min-h-0">
            <div className={`border-r border-[#2c2c2e] flex flex-col min-h-0 ${isCollapsed ? 'w-full border-r-0' : 'w-2/3'}`}>
                {!isCollapsed && (
                    <div className="h-11 px-4 border-b border-[#2c2c2e] flex items-center justify-between shrink-0">
                        <div className="text-xs uppercase tracking-wider font-semibold text-[#f5f5f7]">Orchestrator Chat</div>
                        <div className="flex items-center gap-1 rounded-lg border border-[#2c2c2e] bg-[#141414] p-1">
                            <button
                                onClick={() => setMode('generate')}
                                className={`px-2.5 py-1 rounded-md text-[10px] uppercase tracking-wider ${mode === 'generate' ? 'bg-[#0a84ff]/20 text-[#0a84ff]' : 'text-[#86868b]'}`}
                            >
                                <Sparkles size={12} className="inline mr-1" />IA
                            </button>
                            <button
                                onClick={() => setMode('draft')}
                                className={`px-2.5 py-1 rounded-md text-[10px] uppercase tracking-wider ${mode === 'draft' ? 'bg-[#0a84ff]/20 text-[#0a84ff]' : 'text-[#86868b]'}`}
                            >
                                Draft
                            </button>
                        </div>
                    </div>
                )}

                {!isCollapsed && (
                    <div className="flex-1 min-h-0 overflow-y-auto p-4 space-y-3 custom-scrollbar">
                        {messages.map(message => (
                            <div key={message.id} className={`rounded-xl px-3 py-2 border ${message.role === 'user'
                                ? 'bg-[#0a84ff]/10 border-[#0a84ff]/20 ml-14'
                                : message.role === 'assistant'
                                    ? 'bg-[#141414] border-[#2c2c2e] mr-14'
                                    : 'bg-[#ff9f0a]/10 border-[#ff9f0a]/20 text-[#ffb340]'
                                }`}>
                                <p className="text-xs text-[#f5f5f7] whitespace-pre-wrap">{message.text}</p>
                                {(message.detectedIntent || message.decisionPath) && (
                                    <div className="mt-2 flex flex-wrap gap-1.5">
                                        {message.detectedIntent && (
                                            <span className="text-[10px] px-2 py-0.5 rounded-full border border-[#0a84ff]/40 bg-[#0a84ff]/10 text-[#7fc1ff]">
                                                Intent: {message.detectedIntent}
                                            </span>
                                        )}
                                        {message.decisionPath && (
                                            <span className="text-[10px] px-2 py-0.5 rounded-full border border-[#2c2c2e] bg-[#1a1a1c] text-[#d0d0d4]">
                                                Ruta: {message.decisionPath}
                                            </span>
                                        )}
                                    </div>
                                )}
                                {message.executionSteps && message.executionSteps.length > 0 && (
                                    <div className="mt-2 space-y-1">
                                        {message.executionSteps.map(step => (
                                            <div
                                                key={`${message.id}-${step.key}`}
                                                className={`text-[10px] rounded-md px-2 py-1 border ${step.status === 'done'
                                                    ? 'border-[#32d74b]/30 bg-[#32d74b]/10 text-[#8ae89a]'
                                                    : step.status === 'error'
                                                        ? 'border-[#ff453a]/30 bg-[#ff453a]/10 text-[#ff8f88]'
                                                        : 'border-[#2c2c2e] bg-[#171718] text-[#b5b5bb]'
                                                    }`}
                                            >
                                                {step.label}: {step.detail || (step.status === 'pending' ? 'pendiente' : step.status)}
                                            </div>
                                        ))}
                                    </div>
                                )}
                                {message.errorActionable && (
                                    <div className="mt-2 text-[10px] rounded-md border border-[#ff9f0a]/30 bg-[#ff9f0a]/10 text-[#ffbe69] px-2 py-1">
                                        Acción sugerida: {message.errorActionable}
                                    </div>
                                )}
                                {message.draftId && pendingDrafts.some(d => d.id === message.draftId) && (
                                    <div className="mt-2 flex items-center gap-2">
                                        <button
                                            onClick={() => approveDraft(message.draftId!)}
                                            disabled={approvingId === message.draftId}
                                            className="inline-flex items-center gap-1 px-2 py-1 rounded-md text-[10px] bg-[#32d74b]/15 text-[#32d74b] border border-[#32d74b]/30 disabled:opacity-50"
                                        >
                                            <Check size={11} /> {approvingId === message.draftId ? 'Aprobando...' : 'Aprobar'}
                                        </button>
                                        <button
                                            onClick={() => rejectDraft(message.draftId!)}
                                            className="inline-flex items-center gap-1 px-2 py-1 rounded-md text-[10px] bg-[#ff453a]/15 text-[#ff453a] border border-[#ff453a]/30"
                                        >
                                            <X size={11} /> Rechazar
                                        </button>
                                    </div>
                                )}
                                {message.approvedId && !message.runId && (
                                    <div className="mt-2 flex items-center gap-2">
                                        <button
                                            onClick={() => void createRunFromApproved(message.approvedId!, message.draftId)}
                                            className="inline-flex items-center gap-1 px-2 py-1 rounded-md text-[10px] bg-[#0a84ff]/15 text-[#0a84ff] border border-[#0a84ff]/30"
                                        >
                                            <Sparkles size={11} /> Ejecutar run
                                        </button>
                                    </div>
                                )}
                            </div>
                        ))}
                    </div>
                )}

                <div className={`p-3 flex items-center gap-2 shrink-0 ${isCollapsed ? 'border-t-0 h-full items-center pl-16' : 'border-t border-[#2c2c2e]'}`}>
                    <input
                        value={input}
                        onChange={(e) => setInput(e.target.value)}
                        onKeyDown={(e) => {
                            if (e.key === 'Enter' && !e.shiftKey) {
                                e.preventDefault();
                                void handleSend();
                            }
                        }}
                        placeholder={mode === 'generate' ? 'Describe el workflow para generar un draft...' : 'Crear draft manual...'}
                        className="flex-1 h-10 rounded-xl bg-[#141414] border border-[#2c2c2e] px-3 text-sm text-[#f5f5f7] placeholder:text-[#86868b] outline-none focus:border-[#0a84ff]"
                    />
                    <button
                        onClick={() => void handleSend()}
                        disabled={isSending || !input.trim()}
                        className="h-10 px-3 rounded-xl bg-[#0a84ff] hover:bg-[#0071e3] disabled:opacity-50 disabled:cursor-not-allowed text-white inline-flex items-center gap-2"
                    >
                        {isSending ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
                        <span className="text-xs font-medium">Enviar</span>
                    </button>
                </div>
            </div>

            {!isCollapsed && (
                <aside className="w-1/3 min-w-[280px] max-w-[420px] bg-[#0d0d0e] flex flex-col min-h-0">
                    <div className="h-11 px-4 border-b border-[#2c2c2e] flex items-center justify-between shrink-0">
                        <span className="text-xs uppercase tracking-wider text-[#86868b]">Drafts pendientes</span>
                        <button onClick={() => void fetchDrafts()} className="text-[10px] text-[#0a84ff] hover:underline">
                            {isLoadingDrafts ? 'Actualizando…' : 'Actualizar'}
                        </button>
                    </div>
                    <div className="flex-1 min-h-0 overflow-y-auto p-3 space-y-2 custom-scrollbar">
                        {pendingDrafts.length === 0 ? (
                            <p className="text-xs text-[#86868b]">No hay drafts en estado draft.</p>
                        ) : pendingDrafts.map(draft => (
                            <div key={draft.id} className="rounded-xl border border-[#2c2c2e] bg-[#141414] p-2.5 space-y-2">
                                <div>
                                    <div className="text-[10px] text-[#86868b]">{new Date(draft.created_at).toLocaleString()}</div>
                                    <div className="text-xs text-[#f5f5f7] line-clamp-3">{draft.prompt}</div>
                                </div>
                                <div className="flex gap-1.5">
                                    <button onClick={() => void approveDraft(draft.id)} disabled={!!approvingId} className="flex-1 h-7 rounded-md bg-[#32d74b]/15 border border-[#32d74b]/30 text-[#32d74b] text-[10px] disabled:opacity-50">
                                        Aprobar
                                    </button>
                                    <button onClick={() => void rejectDraft(draft.id)} className="flex-1 h-7 rounded-md bg-[#ff453a]/15 border border-[#ff453a]/30 text-[#ff453a] text-[10px]">
                                        Rechazar
                                    </button>
                                </div>
                            </div>
                        ))}
                    </div>
                </aside>
            )}
        </section>
    );
};
