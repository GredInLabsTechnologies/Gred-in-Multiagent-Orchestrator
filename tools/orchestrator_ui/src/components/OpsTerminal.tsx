import React, { useEffect, useMemo, useState } from 'react';
import { API_BASE } from '../types';

interface TerminalEvent {
    id: string;
    ts: string;
    source: 'terminal' | 'chat';
    text: string;
}

interface OpsTerminalProps {
    inboundFromChat?: { text: string; ts: string; source: 'chat' } | null;
    onSendSummaryToChat?: (payload: { id: string; text: string; ts: string }) => void;
}

const formatTs = (ts: string) => {
    const d = new Date(ts);
    if (Number.isNaN(d.getTime())) return ts;
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
};

export const OpsTerminal: React.FC<OpsTerminalProps> = ({ inboundFromChat, onSendSummaryToChat }) => {
    const [events, setEvents] = useState<TerminalEvent[]>([]);

    useEffect(() => {
        const pullAudit = async () => {
            try {
                const response = await fetch(`${API_BASE}/ui/audit?limit=30`, { credentials: 'include' });
                if (!response.ok) return;
                const data = await response.json();
                const lines: string[] = Array.isArray(data?.lines) ? data.lines : [];
                const mapped = lines.slice(-10).map((line, idx) => ({
                    id: `audit-${idx}-${line.length}`,
                    ts: new Date().toISOString(),
                    source: 'terminal' as const,
                    text: line,
                }));
                setEvents((prev) => [...mapped, ...prev.filter((e) => e.source === 'chat')].slice(0, 120));
            } catch {
                // no-op en MVP
            }
        };

        void pullAudit();
        const id = window.setInterval(() => void pullAudit(), 5000);
        return () => window.clearInterval(id);
    }, []);

    useEffect(() => {
        if (!inboundFromChat) return;
        setEvents((prev): TerminalEvent[] => [
            {
                id: `chat-${Date.now()}`,
                ts: inboundFromChat.ts,
                source: 'chat' as const,
                text: inboundFromChat.text,
            },
            ...prev,
        ].slice(0, 120));
    }, [inboundFromChat]);

    const summary = useMemo(() => {
        const top = events.slice(0, 3).map((e) => `[${e.source}] ${e.text}`);
        return top.join('\n');
    }, [events]);

    return (
        <section className="h-full min-h-0 flex flex-col bg-surface-0/80 border-l border-white/[0.04]">
            <div className="h-11 px-3 border-b border-white/[0.04] flex items-center justify-between">
                <span className="text-[11px] uppercase tracking-wider text-text-secondary font-semibold">Terminal</span>
                <button
                    onClick={() => {
                        if (!onSendSummaryToChat || !summary) return;
                        onSendSummaryToChat({ id: `term-summary-${Date.now()}`, text: summary, ts: new Date().toISOString() });
                    }}
                    className="text-[10px] px-2 py-1 rounded-md border border-accent-primary/20 text-accent-primary hover:bg-accent-primary/10 transition-colors"
                >
                    Enviar resumen al chat
                </button>
            </div>
            <div className="flex-1 min-h-0 overflow-auto p-3 font-mono text-[11px] space-y-1">
                {events.length === 0 ? (
                    <div className="text-text-tertiary">Awaiting execution logs...</div>
                ) : (
                    events.map((e) => (
                        <div key={e.id} className="text-text-secondary">
                            <span className="text-text-tertiary">[{formatTs(e.ts)}]</span>{' '}
                            <span className={e.source === 'chat' ? 'text-accent-primary' : 'text-zinc-300'}>{e.source}</span>{' '}
                            <span>{e.text}</span>
                        </div>
                    ))
                )}
            </div>
        </section>
    );
};
