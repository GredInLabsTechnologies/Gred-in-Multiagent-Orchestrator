import { useState, useCallback, useEffect, useRef } from 'react';
import { API_BASE, AgentMessage, MessageType } from '../types';

/**
 * Fetches conversation turns for an agent from /ops/threads and maps them
 * to the AgentMessage contract expected by AgentChat.
 *
 * When agentId is null the hook is inert (no fetches, empty messages).
 */
export function useAgentComms(agentId: string | null) {
    const [messages, setMessages] = useState<AgentMessage[]>([]);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const abortRef = useRef<AbortController | null>(null);

    const refresh = useCallback(async () => {
        if (!agentId) return;
        abortRef.current?.abort();
        const ctrl = new AbortController();
        abortRef.current = ctrl;

        setLoading(true);
        setError(null);
        try {
            const res = await fetch(`${API_BASE}/ops/threads?agent_id=${encodeURIComponent(agentId)}`, {
                credentials: 'include',
                signal: ctrl.signal,
            });
            if (!res.ok) {
                setError(`Failed to fetch messages (${res.status})`);
                return;
            }
            const threads = await res.json();
            // Flatten turns from all threads into AgentMessage[]
            const mapped: AgentMessage[] = [];
            for (const thread of Array.isArray(threads) ? threads : []) {
                for (const turn of thread.turns ?? []) {
                    for (const item of turn.items ?? []) {
                        mapped.push({
                            id: item.id ?? `${turn.turn_id ?? ''}-${mapped.length}`,
                            from: turn.agent_id === agentId ? 'agent' : 'orchestrator',
                            agentId: turn.agent_id ?? agentId,
                            type: 'report' as MessageType,
                            content: typeof item.content === 'string' ? item.content : JSON.stringify(item.content ?? ''),
                            timestamp: turn.created_at ?? new Date().toISOString(),
                        });
                    }
                }
            }
            setMessages(mapped);
        } catch (err) {
            if ((err as Error).name !== 'AbortError') {
                setError((err as Error).message);
            }
        } finally {
            setLoading(false);
        }
    }, [agentId]);

    const sendMessage = useCallback(async (content: string, _type: MessageType = 'instruction') => {
        if (!agentId) return null;
        try {
            const res = await fetch(`${API_BASE}/ops/threads`, {
                method: 'POST',
                credentials: 'include',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ workspace_root: '.', title: `Agent ${agentId}` }),
            });
            if (!res.ok) return null;
            const thread = await res.json();

            await fetch(`${API_BASE}/ops/threads/${thread.thread_id}/chat`, {
                method: 'POST',
                credentials: 'include',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ content }),
            });

            await refresh();
            return thread.thread_id;
        } catch {
            return null;
        }
    }, [agentId, refresh]);

    useEffect(() => {
        refresh();
        return () => abortRef.current?.abort();
    }, [refresh]);

    return { messages, loading, error, sendMessage, refresh };
}
