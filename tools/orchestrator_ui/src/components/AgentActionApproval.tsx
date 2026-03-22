import React, { useEffect, useMemo, useState } from 'react';
import { API_BASE } from '../types';
import { fetchWithRetry } from '../lib/fetchWithRetry';

export interface ActionDraftUi {
    id: string;
    agent_id: string;
    tool: string;
    params: Record<string, any>;
    risk_level: 'low' | 'medium' | 'high' | 'critical';
    status: 'pending' | 'approved' | 'rejected' | 'timeout';
    created_at: string;
}

interface Props {
    draft: ActionDraftUi;
    onResolved?: (draftId: string, decision: 'approve' | 'reject') => void;
}

const RISK_BADGE: Record<string, string> = {
    low: 'text-emerald-400 border-emerald-400/30 bg-emerald-500/10',
    medium: 'text-amber-300 border-amber-400/30 bg-amber-500/10',
    high: 'text-orange-300 border-orange-400/30 bg-orange-500/10',
    critical: 'text-red-300 border-red-400/30 bg-red-500/10',
};

function previewForDraft(draft: ActionDraftUi): string {
    if (draft.tool.includes('write') && typeof draft.params?.content === 'string') {
        return draft.params.content.slice(0, 240);
    }
    if (draft.tool.includes('command') || draft.tool.includes('shell')) {
        return String(draft.params?.cmd || draft.params?.command || '').slice(0, 240);
    }
    return JSON.stringify(draft.params || {}, null, 2).slice(0, 240);
}

export const AgentActionApproval: React.FC<Props> = ({ draft, onResolved }) => {
    const [nowMs, setNowMs] = useState(0);

    useEffect(() => {
        setNowMs(Date.now());
        const timer = setInterval(() => setNowMs(Date.now()), 1000);
        return () => clearInterval(timer);
    }, []);

    const msRemaining = useMemo(() => {
        const created = new Date(draft.created_at).getTime();
        const elapsed = nowMs - created;
        return Math.max(0, 5 * 60 * 1000 - elapsed);
    }, [draft.created_at, nowMs]);

    const timerText = `${Math.floor(msRemaining / 60000)}:${String(Math.floor((msRemaining % 60000) / 1000)).padStart(2, '0')}`;

    const decide = async (decision: 'approve' | 'reject') => {
        const url = `${API_BASE}/ops/action-drafts/${draft.id}/${decision}`;
        const res = await fetchWithRetry(url, { method: 'POST', credentials: 'include' });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        onResolved?.(draft.id, decision);
    };

    const approveBatch = async () => {
        const list = await fetchWithRetry(`${API_BASE}/ops/action-drafts?status=pending`, { credentials: 'include' });
        if (!list.ok) throw new Error(`HTTP ${list.status}`);
        const items: ActionDraftUi[] = await list.json();
        await Promise.all(items.map(async (item) => {
            const r = await fetchWithRetry(`${API_BASE}/ops/action-drafts/${item.id}/approve`, {
                method: 'POST',
                credentials: 'include',
            });
            if (r.ok) onResolved?.(item.id, 'approve');
        }));
    };

    return (
        <div className="mt-2 rounded-xl border border-white/[0.08] bg-surface-2/70 p-3">
            <div className="flex items-center justify-between gap-2">
                <div className="text-xs text-text-primary font-semibold">Action requires approval</div>
                <span className={`text-[10px] px-2 py-0.5 rounded-full border ${RISK_BADGE[draft.risk_level] || RISK_BADGE.medium}`}>
                    {draft.risk_level}
                </span>
            </div>
            <div className="mt-2 text-[11px] text-text-secondary">
                <strong>{draft.agent_id}</strong> wants to execute <strong>{draft.tool}</strong>
            </div>
            <pre className="mt-2 text-[10px] bg-surface-3/60 border border-white/[0.06] rounded-lg p-2 overflow-auto text-text-tertiary whitespace-pre-wrap">
                {previewForDraft(draft)}
            </pre>
            <div className="mt-2 flex items-center justify-between">
                <div className="text-[10px] text-amber-300">Auto-reject en {timerText}</div>
                <div className="flex items-center gap-2">
                    <button
                        onClick={() => void decide('approve')}
                        className="px-2.5 py-1 rounded-lg text-[10px] bg-emerald-500/12 border border-emerald-500/25 text-emerald-300"
                    >
                        Aprobar
                    </button>
                    <button
                        onClick={() => void decide('reject')}
                        className="px-2.5 py-1 rounded-lg text-[10px] bg-red-500/12 border border-red-500/25 text-red-300"
                    >
                        Rechazar
                    </button>
                    <button
                        onClick={() => void approveBatch()}
                        className="px-2.5 py-1 rounded-lg text-[10px] bg-accent-primary/12 border border-accent-primary/25 text-accent-primary"
                    >
                        Aprobar batch
                    </button>
                </div>
            </div>
        </div>
    );
};
