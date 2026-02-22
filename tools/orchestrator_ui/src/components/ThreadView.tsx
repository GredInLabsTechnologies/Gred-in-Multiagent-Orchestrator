import React, { useState, useEffect, useRef } from 'react';
import { MessageSquare, Plus, ChevronLeft, GitFork, Archive, MoreVertical, Send } from 'lucide-react';
import { TurnItem } from './TurnItem';

interface GimoThread {
    id: string;
    title: string;
    turns: any[];
    status: string;
    updated_at: string;
}

export const ThreadView: React.FC = () => {
    const [threads, setThreads] = useState<GimoThread[]>([]);
    const [selectedThread, setSelectedThread] = useState<GimoThread | null>(null);
    const [loading, setLoading] = useState(true);
    const [inputValue, setInputValue] = useState('');
    const [sending, setSending] = useState(false);
    const chatEndRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        // SSE Listener for real-time updates
        const eventSource = new EventSource('/ops/notifications/stream');
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
            const resp = await fetch('/ops/threads');
            const data = await resp.json();
            setThreads(data);
            if (data.length > 0 && !selectedThread) {
                fetchThreadDetail(data[0].id);
            }
        } catch (err) {
            console.error('Failed to fetch threads', err);
        } finally {
            setLoading(false);
        }
    };

    const fetchThreadDetail = async (id: string) => {
        try {
            const resp = await fetch(`/ops/threads/${id}`);
            const data = await resp.json();
            setSelectedThread(data);
        } catch (err) {
            console.error('Failed to fetch thread detail', err);
        }
    };

    const createNewThread = async () => {
        try {
            const resp = await fetch('/ops/threads?workspace_root=.', { method: 'POST' });
            const data = await resp.json();
            setThreads([data, ...threads]);
            setSelectedThread(data);
        } catch (err) {
            console.error('Failed to create thread', err);
        }
    };

    const handleSendMessage = async () => {
        if (!inputValue.trim() || !selectedThread || sending) return;

        setSending(true);
        try {
            const resp = await fetch(`/ops/threads/${selectedThread.id}/messages?content=${encodeURIComponent(inputValue)}`, {
                method: 'POST'
            });
            if (resp.ok) {
                setInputValue('');
                // SSE will update the selectedThread state
            }
        } catch (err) {
            console.error('Failed to send message', err);
        } finally {
            setSending(false);
        }
    };

    if (loading) return (
        <div className="flex-1 flex items-center justify-center bg-[#1c1c1e] text-[#86868b]">
            <div className="animate-pulse flex flex-col items-center gap-4">
                <MessageSquare size={48} />
                <span className="text-sm font-medium uppercase tracking-widest">Loading Conversation Protocol...</span>
            </div>
        </div>
    );

    return (
        <div className="flex-1 flex bg-[#000000] overflow-hidden">
            {/* Sidebar: Threads List */}
            <div className="w-80 border-r border-[#2c2c2e] flex flex-col">
                <div className="p-4 border-b border-[#2c2c2e] flex items-center justify-between">
                    <h2 className="text-sm font-bold text-[#f5f5f7] uppercase tracking-wider">Conversations</h2>
                    <button
                        onClick={createNewThread}
                        className="p-1.5 hover:bg-[#1c1c1e] rounded-lg text-[#0a84ff] transition-colors"
                    >
                        <Plus size={18} />
                    </button>
                </div>
                <div className="flex-1 overflow-y-auto">
                    {threads.map((t) => (
                        <button
                            key={t.id}
                            onClick={() => fetchThreadDetail(t.id)}
                            className={`w-full p-4 text-left border-b border-[#1c1c1e] transition-colors hover:bg-[#1c1c1e]/50 ${selectedThread?.id === t.id ? 'bg-[#1c1c1e]' : ''}`}
                        >
                            <div className="flex items-center justify-between mb-1">
                                <span className={`text-xs font-bold ${selectedThread?.id === t.id ? 'text-[#0a84ff]' : 'text-[#f5f5f7]'}`}>
                                    {t.title}
                                </span>
                                <span className="text-[10px] text-[#86868b]">
                                    {new Date(t.updated_at).toLocaleDateString()}
                                </span>
                            </div>
                            <p className="text-[11px] text-[#86868b] truncate">
                                {t.turns.at(-1)?.items[0]?.content || 'Empty conversation'}
                            </p>
                        </button>
                    ))}
                </div>
            </div>

            {/* Main Content: Thread Detail */}
            <div className="flex-1 flex flex-col bg-[#1c1c1e]/30 backdrop-blur-md relative">
                {selectedThread ? (
                    <>
                        {/* Header */}
                        <div className="px-6 py-4 border-b border-[#2c2c2e] flex items-center justify-between bg-[#1c1c1e]/50">
                            <div className="flex items-center gap-4">
                                <button onClick={() => setSelectedThread(null)} className="md:hidden">
                                    <ChevronLeft size={20} />
                                </button>
                                <div>
                                    <h3 className="text-sm font-bold text-[#f5f5f7]">{selectedThread.title}</h3>
                                    <span className="text-[10px] text-[#30d158] font-bold uppercase tracking-widest">{selectedThread.status}</span>
                                </div>
                            </div>
                            <div className="flex items-center gap-2">
                                <button className="p-2 hover:bg-[#2c2c2e] rounded-lg text-[#86868b] transition-colors" title="Fork Thread">
                                    <GitFork size={18} />
                                </button>
                                <button className="p-2 hover:bg-[#2c2c2e] rounded-lg text-[#86868b] transition-colors" title="Archive">
                                    <Archive size={18} />
                                </button>
                                <button className="p-2 hover:bg-[#2c2c2e] rounded-lg text-[#86868b] transition-colors">
                                    <MoreVertical size={18} />
                                </button>
                            </div>
                        </div>

                        {/* Message Area */}
                        <div className="flex-1 overflow-y-auto px-6 py-8">
                            {selectedThread.turns.map((turn) => (
                                <TurnItem key={turn.id} turn={turn} />
                            ))}
                            <div ref={chatEndRef} />
                        </div>

                        {/* Input Area */}
                        <div className="p-6 bg-gradient-to-t from-[#000000] to-transparent">
                            <div className="relative max-w-4xl mx-auto">
                                <input
                                    type="text"
                                    value={inputValue}
                                    onChange={(e) => setInputValue(e.target.value)}
                                    onKeyDown={(e) => e.key === 'Enter' && handleSendMessage()}
                                    placeholder="Execute the Agent-to-IDE protocol. Send a command..."
                                    className="w-full bg-[#2c2c2e] border border-[#3c3c3e] rounded-2xl px-6 py-4 text-sm text-[#f5f5f7] focus:outline-none focus:border-[#0a84ff] transition-all pr-14 shadow-2xl"
                                    disabled={sending}
                                />
                                <button
                                    onClick={handleSendMessage}
                                    disabled={sending || !inputValue.trim()}
                                    className="absolute right-4 top-1/2 -translate-y-1/2 p-2 bg-[#0a84ff] text-white rounded-xl shadow-lg hover:bg-[#0071e3] transition-colors disabled:opacity-50 disabled:grayscale"
                                >
                                    <Send size={18} />
                                </button>
                            </div>
                            <p className="text-center mt-3 text-[10px] text-[#86868b] uppercase tracking-widest font-bold">
                                GIMO Protocol v1.0 • SSE Real-time Active
                            </p>
                        </div>
                    </>
                ) : (
                    <div className="flex-1 flex items-center justify-center text-[#86868b]">
                        <div className="text-center max-w-sm">
                            <div className="w-16 h-16 bg-[#2c2c2e] rounded-3xl flex items-center justify-center mx-auto mb-6 text-[#0a84ff]">
                                <MessageSquare size={32} />
                            </div>
                            <h4 className="text-[#f5f5f7] font-bold mb-2">Select a Conversation</h4>
                            <p className="text-xs">Explore the structured interaction between your agents and the environment.</p>
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
};
