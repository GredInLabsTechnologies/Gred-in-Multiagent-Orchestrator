import { useState, useCallback, useEffect, useRef } from 'react';
import {
    API_BASE,
    OpsPlan, OpsDraft, OpsApproved, OpsRun, OpsConfig,
    OpsApproveResponse, ProviderConfig,
    ACTIVE_RUN_STATUSES
} from '../types';
import { fetchWithRetry } from '../lib/fetchWithRetry';

const POLL_INTERVAL_MS = 3000;

export const useOpsService = (_token?: string) => {
    const [plan, setPlan] = useState<OpsPlan | null>(null);
    const [drafts, setDrafts] = useState<OpsDraft[]>([]);
    const [approved, setApproved] = useState<OpsApproved[]>([]);
    const [runs, setRuns] = useState<OpsRun[]>([]);
    const [config, setConfigState] = useState<OpsConfig | null>(null);
    const [provider] = useState<ProviderConfig | null>(null);
    const [isLoading, setIsLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

    const getHeaders = useCallback(() => {
        return { 'Content-Type': 'application/json' } as HeadersInit;
    }, []);

    const fetchAll = useCallback(async () => {
        setIsLoading(true);
        try {
            const h = getHeaders();
            const [pRes, dRes, aRes, rRes, cRes] = await Promise.all([
                fetchWithRetry(`${API_BASE}/ops/plan`, { headers: h, credentials: 'include' }),
                fetchWithRetry(`${API_BASE}/ops/drafts`, { headers: h, credentials: 'include' }),
                fetchWithRetry(`${API_BASE}/ops/approved`, { headers: h, credentials: 'include' }),
                fetchWithRetry(`${API_BASE}/ops/runs`, { headers: h, credentials: 'include' }),
                fetchWithRetry(`${API_BASE}/ops/config`, { headers: h, credentials: 'include' }),
            ]);

            if (pRes.ok) setPlan(await pRes.json());
            if (dRes.ok) setDrafts(await dRes.json());
            if (aRes.ok) setApproved(await aRes.json());
            if (rRes.ok) setRuns(await rRes.json());
            if (cRes.ok) setConfigState(await cRes.json());

            setError(null);
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Failed to fetch OPS data');
        } finally {
            setIsLoading(false);
        }
    }, [getHeaders]);

    // Poll runs when there are active (pending/running) runs
    const refreshRuns = useCallback(async () => {
        try {
            const res = await fetchWithRetry(`${API_BASE}/ops/runs`, { headers: getHeaders(), credentials: 'include' });
            if (res.ok) setRuns(await res.json());
        } catch (err) { console.warn('Runs polling failed:', err); }
    }, [getHeaders]);

    useEffect(() => {
        // F4 fix: poll while any run is in an active (non-terminal) status,
        // exhaustively derived from backend-generated OpsRunStatus. This list
        // is the single source of truth — adding a new backend status requires
        // an explicit decision here, caught at codegen time (F3).
        const hasActive = runs.some(r => ACTIVE_RUN_STATUSES.includes(r.status));
        if (hasActive && !pollRef.current) {
            pollRef.current = setInterval(refreshRuns, POLL_INTERVAL_MS);
        } else if (!hasActive && pollRef.current) {
            clearInterval(pollRef.current);
            pollRef.current = null;
        }
        return () => {
            if (pollRef.current) clearInterval(pollRef.current);
        };
    }, [runs, refreshRuns]);

    const updatePlan = async (newPlan: OpsPlan) => {
        try {
            const res = await fetchWithRetry(`${API_BASE}/ops/plan`, {
                method: 'PUT', headers: getHeaders(), credentials: 'include', body: JSON.stringify(newPlan)
            });
            if (!res.ok) throw new Error('Failed to update plan');
            setPlan(newPlan);
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Update failed');
        }
    };

    const generateDraft = async (prompt: string) => {
        setIsLoading(true);
        try {
            const res = await fetchWithRetry(`${API_BASE}/ops/generate?prompt=${encodeURIComponent(prompt)}`, {
                method: 'POST', headers: getHeaders(), credentials: 'include'
            });
            if (!res.ok) throw new Error('Generation failed');
            const newDraft = await res.json();
            setDrafts(prev => [newDraft, ...prev]);
            return newDraft;
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Generation failed');
        } finally {
            setIsLoading(false);
        }
    };

    const approveDraft = async (id: string, autoRun?: boolean) => {
        try {
            const params = autoRun !== undefined ? `?auto_run=${autoRun}` : '';
            const res = await fetchWithRetry(`${API_BASE}/ops/drafts/${id}/approve${params}`, {
                method: 'POST', headers: getHeaders(), credentials: 'include'
            });
            if (!res.ok) throw new Error('Approval failed');
            const data: OpsApproveResponse = await res.json();
            setApproved(prev => [data.approved, ...prev]);
            // F5 fix: reflect the draft status from the server's approved payload,
            // not a hardcoded client assertion. The draft is stamped with the
            // approval metadata server-side; we mirror it rather than assume it.
            setDrafts(prev => prev.map(d =>
                d.id === id
                    ? { ...d, status: 'approved', approved_at: data.approved.approved_at, approved_by: data.approved.approved_by ?? null }
                    : d
            ));
            if (data.run) setRuns(prev => [data.run!, ...prev]);
            return data;
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Approval failed');
        }
    };

    const rejectDraft = async (id: string) => {
        try {
            const res = await fetchWithRetry(`${API_BASE}/ops/drafts/${id}/reject`, {
                method: 'POST', headers: getHeaders(), credentials: 'include'
            });
            if (!res.ok) {
                if (res.status === 403) throw new Error('Permission denied: You need operator or admin role to reject drafts.');
                throw new Error('Rejection failed');
            }
            // F5 fix: trust the server-updated draft in the response rather than
            // asserting the new status locally. The server may enrich the draft
            // (rejected_by, rejected_at) — we must not invent those fields.
            const updatedDraft: OpsDraft = await res.json();
            setDrafts(prev => prev.map(d => d.id === id ? updatedDraft : d));
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Rejection failed');
        }
    };

    const startRun = async (approvedId: string) => {
        try {
            const res = await fetchWithRetry(`${API_BASE}/ops/runs`, {
                method: 'POST', headers: getHeaders(), credentials: 'include',
                body: JSON.stringify({ approved_id: approvedId })
            });
            if (!res.ok) throw new Error('Failed to start run');
            const newRun = await res.json();
            setRuns(prev => [newRun, ...prev]);
            return newRun;
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Run failed');
        }
    };

    const cancelRun = async (runId: string) => {
        try {
            const res = await fetchWithRetry(`${API_BASE}/ops/runs/${runId}/cancel`, {
                method: 'POST', headers: getHeaders(), credentials: 'include'
            });
            if (!res.ok) throw new Error('Cancel failed');
            const updated = await res.json();
            setRuns(prev => prev.map(r => r.id === runId ? updated : r));
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Cancel failed');
        }
    };

    const updateConfig = async (newConfig: OpsConfig) => {
        try {
            const res = await fetchWithRetry(`${API_BASE}/ops/config`, {
                method: 'PUT', headers: getHeaders(), credentials: 'include',
                body: JSON.stringify(newConfig)
            });
            if (!res.ok) throw new Error('Config update failed');
            setConfigState(await res.json());
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Config update failed');
        }
    };

    useEffect(() => { fetchAll(); }, [fetchAll]);

    return {
        plan, drafts, approved, runs, config, provider,
        isLoading, error,
        updatePlan, generateDraft, approveDraft, rejectDraft,
        startRun, cancelRun, updateConfig,
        refresh: fetchAll
    };
};
