import React, { useState, useEffect, useRef } from 'react';
import { MessageSquare, Plus, ChevronLeft, GitFork, Archive, MoreVertical, Send } from 'lucide-react';
import { TurnItem } from './TurnItem';
import { API_BASE } from '../types';
import { useToast } from './Toast';

interface GimoThread {
    id: string;
    title: string;
    turns: any[];
    status: string;
    updated_at: string;
}
interface OpsDraft {
    id: string;
    prompt: string;
    status: 'draft' | 'approved' | 'rejected' | 'error';
    content?: string;
    error?: string;
    context?: Record<string, any>;
    created_at: string;
    updated_at: string;
}

interface OpsApproveResponse {
    approved: any;
    run?: any;
}

export const ThreadView: React.FC = () => {
    const { addToast } = useToast();
    const [threads, setThreads] = useState<GimoThread[]>([]);
    const [selectedThread, setSelectedThread] = useState<GimoThread | null>(null);
    const [loading, setLoading] = useState(true);
    const [inputValue, setInputValue] = useState('');
    const [sending, setSending] = useState(false);
    const [pendingDrafts, setPendingDrafts] = useState<Record<string, OpsDraft>>({});
    const chatEndRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        const eventSource = new EventSource(`${API_BASE}/ops/notifications/stream`, { withCredentials: true });
        eventSource.onmessage = (event) => {
            const { event: type, data } = JSON.parse(event.data);
            if (type === 'thread_updated' && data.id === selectedThread?.id) {
                setSelectedThread(data);
            } else if (type === 'thread_updated') {
                fetchThreads();
            }
        };
        return () => eventSource.close();
    }, [selectedThread?.id]);

    useEffect(() => {
        chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }, [selectedThread?.turns]);

    const fetchThreads = async () => {
        try {
            const resp = await fetch(`${API_BASE}/ops/threads`, { credentials: 'include' });
            const data = await resp.json();
            setThreads(data);
            if (data.length > 0 && !selectedThread) {
                fetchThreadDetail(data[0].id);
            }
        } catch (err) {
            addToast('No se pudieron cargar las conversaciones.', 'error');
        } finally {
            setLoading(false);
        }
    };

    const fetchThreadDetail = async (id: string) => {
        try {
            const resp = await fetch(`${API_BASE}/ops/threads/${id}`, { credentials: 'include' });
            const data = await resp.json();
            setSelectedThread(data);
        } catch (err) {
            addToast('No se pudo cargar el detalle de la conversación.', 'error');
        }
    };

    const createNewThread = async () => {
        try {
            const resp = await fetch(`${API_BASE}/ops/threads?workspace_root=.`, { method: 'POST', credentials: 'include' });
            const data = await resp.json();
            setThreads([data, ...threads]);
            setSelectedThread(data);
        } catch (err) {
            addToast('No se pudo crear una conversación nueva.', 'error');
        }
    };

    const handleSendMessage = async () => {
        if (!inputValue.trim() || !selectedThread || sending) return;

        const text = inputValue.trim();
        setInputValue('');
        setSending(true);

        try {
            // Optimistic User Turn
            const userTurn: any = {
                id: `temp-${Date.now()}`,
                agent_id: 'User',
                created_at: new Date().toISOString(),
                items: [{ id: `item-${Date.now()}`, type: 'text', content: text, status: 'completed' }]
            };
            setSelectedThread(prev => prev ? { ...prev, turns: [...prev.turns, userTurn] } : prev);

            // Generate Draft directly from the Chat
            const generateResponse = await fetch(`${API_BASE}/ops/generate?prompt=${encodeURIComponent(text)}`, {
                method: 'POST',
                credentials: 'include'
            });

            if (!generateResponse.ok) throw new Error(`HTTP ${generateResponse.status}`);
            const draft: OpsDraft = await generateResponse.json();

            // Agent Turn with Draft
            const agentTurn: any = {
                id: `agent-${Date.now()}`,
                agent_id: 'Orchestrator',
                created_at: new Date().toISOString(),
                items: [
                    {
                        id: draft.id,
                        type: draft.status === 'error' ? 'error' : 'text',
                        content: draft.content || draft.error || 'Draft generated successfully.',
                        status: 'completed',
                        metadata: { draftId: draft.id, status: draft.status }
                    }
                ]
            };
            setSelectedThread(prev => prev ? { ...prev, turns: [...prev.turns, agentTurn] } : prev);

            if (draft.status === 'draft') {
                setPendingDrafts(prev => ({ ...prev, [draft.id]: draft }));
            }

        } catch (err) {
            addToast('No se pudo generar el draft desde el chat.', 'error');
        } finally {
            setSending(false);
        }
    };

    const handleApproveDraft = async (draftId: string, turnId: string) => {
        try {
            const res = await fetch(`${API_BASE}/ops/drafts/${draftId}/approve`, { method: 'POST', credentials: 'include' });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const approvalData: OpsApproveResponse = await res.json();

            setPendingDrafts(prev => { const updated = { ...prev }; delete updated[draftId]; return updated; });
            setSelectedThread(prev => {
                if (!prev) return prev;
                return { ...prev, turns: prev.turns.map(t => t.id === turnId ? { ...t, items: [...t.items, { id: `exec-${Date.now()}`, type: 'tool_call', content: 'Executing approved plan...', status: 'started' }] } : t) };
            });

            if (approvalData.approved?.id && !approvalData.run?.id) {
                await fetch(`${API_BASE}/ops/runs`, {
                    method: 'POST',
                    credentials: 'include',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ approved_id: approvalData.approved.id }),
                });
            }
        } catch (err) { addToast('No se pudo aprobar/ejecutar el draft.', 'error'); }
    };

    const handleRejectDraft = async (draftId: string, turnId: string) => {
        try {
            const res = await fetch(`${API_BASE}/ops/drafts/${draftId}/reject`, { method: 'POST', credentials: 'include' });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            setPendingDrafts(prev => { const updated = { ...prev }; delete updated[draftId]; return updated; });
            setSelectedThread(prev => {
                if (!prev) return prev;
                return { ...prev, turns: prev.turns.map(t => t.id === turnId ? { ...t, items: [...t.items, { id: `reject-${Date.now()}`, type: 'text', content: 'Draft rejected.', status: 'completed' }] } : t) };
            });
        } catch (err) {
            addToast('No se pudo rechazar el draft.', 'error');
        }
    };

    if (loading) return (
        <div className="flex-1 flex items-center justify-center bg-surface-2 text-text-secondary">
            <div className="animate-pulse flex flex-col items-center gap-4">
                <MessageSquare size={48} />
                <span className="text-sm font-medium uppercase tracking-widest">Loading Conversation Protocol...</span>
            </div>
        </div>
    );

    return (
        <div className="flex-1 flex bg-surface-0 overflow-hidden">
            {/* Sidebar: Threads List */}
            <div className="w-80 border-r border-border-primary flex flex-col bg-surface-1">
                <div className="p-4 border-b border-border-primary flex items-center justify-between">
                    <h2 className="text-sm font-bold text-text-primary uppercase tracking-wider">Conversations</h2>
                    <button
                        onClick={createNewThread}
                        className="p-1.5 hover:bg-surface-3 rounded-lg text-accent-primary transition-colors"
                    >
                        <Plus size={18} />
                    </button>
                </div>
                <div className="flex-1 overflow-y-auto">
                    {threads.map((t) => (
                        <button
                            key={t.id}
                            onClick={() => fetchThreadDetail(t.id)}
                            className={`w-full p-4 text-left border-b border-border-subtle transition-colors hover:bg-surface-3/50 ${selectedThread?.id === t.id ? 'bg-surface-3/60' : ''}`}
                        >
                            <div className="flex items-center justify-between mb-1">
                                <span className={`text-xs font-bold ${selectedThread?.id === t.id ? 'text-accent-primary' : 'text-text-primary'}`}>
                                    {t.title}
                                </span>
                                <span className="text-[10px] text-text-secondary">
                                    {new Date(t.updated_at).toLocaleDateString()}
                                </span>
                            </div>
                            <p className="text-[11px] text-text-secondary truncate">
                                {t.turns.at(-1)?.items[0]?.content || 'Empty conversation'}
                            </p>
                        </button>
                    ))}
                </div>
            </div>

            {/* Main Content: Thread Detail */}
            <div className="flex-1 flex flex-col bg-surface-1/30 backdrop-blur-md relative">
                {selectedThread ? (
                    <>
                        {/* Header */}
                        <div className="px-6 py-4 border-b border-border-primary flex items-center justify-between bg-surface-2/60">
                            <div className="flex items-center gap-4">
                                <button onClick={() => setSelectedThread(null)} className="md:hidden">
                                    <ChevronLeft size={20} />
                                </button>
                                <div>
                                    <h3 className="text-sm font-bold text-text-primary">{selectedThread.title}</h3>
                                    <span className="text-[10px] text-accent-trust font-bold uppercase tracking-widest">{selectedThread.status}</span>
                                </div>
                            </div>
                            <div className="flex items-center gap-2">
                                <button className="p-2 hover:bg-surface-3 rounded-lg text-text-secondary transition-colors" title="Fork Thread">
                                    <GitFork size={18} />
                                </button>
                                <button className="p-2 hover:bg-surface-3 rounded-lg text-text-secondary transition-colors" title="Archive">
                                    <Archive size={18} />
                                </button>
                                <button className="p-2 hover:bg-surface-3 rounded-lg text-text-secondary transition-colors">
                                    <MoreVertical size={18} />
                                </button>
                            </div>
                        </div>

                        {/* Message Area */}
                        <div className="flex-1 overflow-y-auto px-6 py-8 scroll-smooth">
                            {selectedThread.turns.map((turn) => (
                                <div key={turn.id} className="relative group animate-in slide-in-from-bottom-2 fade-in duration-300">
                                    <TurnItem turn={turn} />
                                    {turn.items.map((item: any) => {
                                        if (item.metadata?.draftId && pendingDrafts[item.metadata.draftId]) {
                                            return (
                                                <div key={`actions-${item.id}`} className="absolute -bottom-2 left-12 flex items-center gap-2 bg-surface-2/90 backdrop-blur-md p-1.5 rounded-lg border border-border-primary shadow-2xl z-10 opacity-0 group-hover:opacity-100 transition-all duration-200 transform translate-y-2 group-hover:translate-y-0">
                                                    <button
                                                        onClick={() => handleApproveDraft(item.metadata.draftId, turn.id)}
                                                        className="px-3 py-1 bg-accent-approval/15 text-accent-approval hover:bg-accent-approval/30 border border-accent-approval/30 hover:border-accent-approval/50 rounded-md text-[11px] font-medium transition-all duration-200 active:scale-95"
                                                    >
                                                        Aprobar & Ejecutar
                                                    </button>
                                                    <button
                                                        onClick={() => handleRejectDraft(item.metadata.draftId, turn.id)}
                                                        className="px-3 py-1 bg-accent-alert/15 text-accent-alert hover:bg-accent-alert/30 border border-accent-alert/30 hover:border-accent-alert/50 rounded-md text-[11px] font-medium transition-all duration-200 active:scale-95"
                                                    >
                                                        Rechazar
                                                    </button>
                                                </div>
                                            );
                                        }
                                        return null;
                                    })}
                                </div>
                            ))}
                            {sending && (
                                <div className="flex items-center gap-3 ml-12 mb-6 animate-pulse opacity-70">
                                    <div className="flex gap-1 items-center">
                                        <div className="w-1.5 h-1.5 rounded-full bg-accent-primary animate-status-pulse" style={{ animationDelay: '0ms' }}></div>
                                        <div className="w-1.5 h-1.5 rounded-full bg-accent-primary animate-status-pulse" style={{ animationDelay: '150ms' }}></div>
                                        <div className="w-1.5 h-1.5 rounded-full bg-accent-primary animate-status-pulse" style={{ animationDelay: '300ms' }}></div>
                                    </div>
                                    <span className="text-[10px] text-text-secondary uppercase tracking-widest font-semibold">Generando draft...</span>
                                </div>
                            )}
                            <div ref={chatEndRef} />
                        </div>

                        {/* Input Area */}
                        <div className="p-6 bg-gradient-to-t from-surface-0 via-surface-0 to-transparent shrink-0">
                            <div className="relative max-w-4xl mx-auto group">
                                <div className={`absolute -inset-0.5 rounded-2xl bg-gradient-to-r from-accent-primary/0 via-accent-primary/30 to-accent-primary/0 opacity-0 blur-sm transition-opacity duration-500 ${sending ? 'opacity-100 animate-status-pulse' : 'group-hover:opacity-40'}`}></div>
                                <div className="relative flex items-center">
                                    <input
                                        type="text"
                                        value={inputValue}
                                        onChange={(e) => setInputValue(e.target.value)}
                                        onKeyDown={(e) => e.key === 'Enter' && handleSendMessage()}
                                        placeholder={sending ? "Analizando intención..." : "Describe el plan a ejecutar..."}
                                        className={`w-full bg-surface-2 border border-border-primary rounded-2xl pl-6 pr-14 py-4 text-sm text-text-primary focus:outline-none focus:border-accent-primary focus:bg-surface-3 transition-all duration-300 shadow-2xl ${sending ? 'opacity-60 cursor-not-allowed' : ''}`}
                                        disabled={sending}
                                    />
                                    <button
                                        onClick={handleSendMessage}
                                        disabled={sending || !inputValue.trim()}
                                        className={`absolute right-3 p-2.5 rounded-xl transition-all duration-300 ${sending || !inputValue.trim()
                                            ? 'bg-surface-3 text-text-secondary'
                                            : 'bg-accent-primary text-white hover:bg-accent-primary/90 hover:scale-105 active:scale-95 shadow-lg shadow-[0_0_12px_var(--glow-primary)]'
                                            }`}
                                    >
                                        <Send size={16} className={sending ? 'animate-pulse' : ''} />
                                    </button>
                                </div>
                            </div>
                            <p className="text-center mt-3 text-[10px] text-text-secondary uppercase tracking-widest font-bold">
                                GIMO Protocol v1.0 • SSE Real-time Active
                            </p>
                        </div>
                    </>
                ) : (
                    <div className="flex-1 flex items-center justify-center text-text-secondary">
                        <div className="text-center max-w-sm">
                            <div className="w-16 h-16 bg-surface-3 rounded-3xl flex items-center justify-center mx-auto mb-6 text-accent-primary">
                                <MessageSquare size={32} />
                            </div>
                            <h4 className="text-text-primary font-bold mb-2">Select a Conversation</h4>
                            <p className="text-xs">Explore the structured interaction between your agents and the environment.</p>
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
};
